import gc
import sys
import uuid

import pygit2
import pytest

from harness.adapters.fake import FakeAdapter
from harness.event_store import Command, catalog_stream
from harness.models import ArtifactRef, CatalogEventType, EventType, ProjectEventType
from harness.proposals import delivery_turn, product_spec
from harness.providers.selection import ModelSelection
from harness.public_tree import CapturedFile, CapturedTree
from harness.release_check import ReleaseCheckReport, request_instance_upgrade
from harness.runtime import LoopSystem
from harness.tests.contract_checks import assert_payloads_follow_contract
from harness.tests.helpers import merge_scripts, quality_turns
from harness.tree_archive import artifact_run, load_tree
from harness.write_path import NewCatalogEvent

# 应用层合同中的事件载荷类型与控制核心实际写入的载荷一致。run 事件的各种路径由事件序列对照的全部场景核对
# （test_event_sequence.py），这里从系统整体运行一个项目：登记、配置、材料、归档与恢复、事项开始失败、
# 两个事项一个采纳一个保留为未采纳候选，再加一个事项走真实的采纳写回流程（#347 的五种写回事件全部产出），
# 目录流中的实例升级三个事件（#355、#462）也在这里产出，核对日志中的每条事件。
_PASS_COMMAND = f'"{sys.executable}" -c "import sys; sys.exit(0)"'


def _release_script(summary, files=None):
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    return {
        "product": [product_spec()],
        "engineering": [delivery_turn(summary=summary, files=files, checks={_PASS_COMMAND: 0})],
        # 质检在交付到达以前有一轮预测性探索，到达以后才核验（quality_turns 按这一轮开始时有没有交付决定做什么）
        "quality": quality_turns("release", f"ok {summary}"),
    }

def _release_report() -> ReleaseCheckReport:
    # 一次通过的发布检查结果：与 harness/release_check.py 写进决定请求的同一形状
    return ReleaseCheckReport(
        repository="D:/repo", pending_commit="0123456789abcdef", base_tag="v0.1.0",
        kernel_changes=("harness/bounds.py",), kernel_python_lines=5290, python_lines_max=5471,
        findings=(), text="发布检查：通过")


def _withdraw_instance_upgrade(system, decision_id: str, reason: str) -> None:
    # 目录流中的撤销（工单 #462）：没有生产写出方，按投影读取的字段直接写出
    def decide(transaction):
        transaction.append(NewCatalogEvent(CatalogEventType.INSTANCE_UPGRADE_WITHDRAWN,
                                           {"decision_id": decision_id, "reason": reason}, actor="system"))

    system.writes.transact(catalog_stream(), decide)

def _writeback_tree(repo, files):
    # 文件路径按 / 分层建树：采纳树与目标树的内容都经这条路径写入裸仓库
    nested: dict = {}
    for file in files:
        parts = file.path.split("/")
        node = nested
        for name in parts[:-1]:
            node = node.setdefault(name, {})
        node[parts[-1]] = file

    def insert(node):
        builder = repo.TreeBuilder()
        for name, value in node.items():
            if isinstance(value, dict):
                builder.insert(name, insert(value), pygit2.enums.FileMode.TREE)
            else:
                builder.insert(name, repo.create_blob(value.data), pygit2.enums.FileMode.BLOB)
        return builder.write()

    return insert(nested)

def _force_target_commit(bare_path, captured, message):
    # 目标分支的推进（前项合入、已含变更、冲突）由测试直接提交：写回只读它，不伪造写回事件
    repo = pygit2.Repository(str(bare_path))
    signature = pygit2.Signature("Yudao Test", "test@yudao.invalid")
    tree = _writeback_tree(repo, captured.files)
    parent = repo.references["refs/heads/main"].peel(pygit2.Commit).id
    commit = repo.create_commit("refs/heads/main", signature, signature, message, tree, [parent])
    del repo
    gc.collect()
    return commit

def _produce_writeback_events(system, projects, project_id, base_version, adoption_id, remote):
    # 真实的采纳写回流程（harness/writeback.py）：按事项基线查到的采纳树做三方合并，检查、推分支、
    # 目标分支推进都走产品代码；五种写回事件在这里全部自然产出
    project = projects.projection(project_id)
    adoption = next(item for item in project.adoptions if item.adoption_id == adoption_id)
    item = project.work_item(adoption.work_item_id)
    base = load_tree(system.artifacts, artifact_run(item.baseline["tree_ref"]["path"]),
                     ArtifactRef(**item.baseline["tree_ref"]))
    adopted = load_tree(system.artifacts, artifact_run(adoption.tree_ref["path"]),
                        ArtifactRef(**adoption.tree_ref))
    repo = pygit2.init_repository(str(remote), bare=True)
    signature = pygit2.Signature("Yudao Test", "test@yudao.invalid")
    tree = _writeback_tree(repo, base.files)
    repo.set_head("refs/heads/main")
    repo.create_commit("refs/heads/main", signature, signature, "seed", tree, [])
    del repo
    gc.collect()
    projects.configure_source_directory(
        project_id, "src", "C:/repo/src", base_version=base_version,
        writeback_enabled=True, remote=str(remote), target_branch="main", check_commands=[],
    )
    # 本事项的基线采纳还没有合入目标分支：等待前项
    held = projects.execute_writeback(project_id, adoption_id)
    assert held.type == ProjectEventType.WRITEBACK_HELD
    # 目标分支以 squash 合并的方式合入前项以后：合并通过、检查通过、推分支
    extra = CapturedTree(base.directories, tuple(
        sorted([*base.files, CapturedFile("target_note.txt", b"target advanced\n")],
               key=lambda file: file.path)))
    _force_target_commit(remote, extra, f"squash merge pr-{item.baseline['adoption_id']} "
                                        f"adoption {item.baseline['adoption_id']}")
    completed = projects.execute_writeback(project_id, adoption_id)
    assert completed.type == ProjectEventType.WRITEBACK_COMPLETED
    # 分支已在远端且树与父提交一致：核实已发生的写回动作（核实事件与完成事件写在同一次执行里）
    before_ids = {event.event_id for event in system.store.read(0, limit=100_000)}
    assert projects.execute_writeback(project_id, adoption_id).type == ProjectEventType.WRITEBACK_COMPLETED
    fresh = [event for event in system.store.read(0, limit=100_000) if event.event_id not in before_ids]
    assert ProjectEventType.WRITEBACK_VERIFIED in {event.type for event in fresh}
    # 目标分支已经包含本次变更：无需写回
    _force_target_commit(remote, adopted, "target already has the changes")
    not_needed = projects.execute_writeback(project_id, adoption_id)
    assert not_needed.type == ProjectEventType.WRITEBACK_NOT_NEEDED
    # 目标分支与采纳成果改了同一处：冲突停止
    conflict = CapturedTree(base.directories, tuple(
        CapturedFile(file.path, b"target conflict\n" if file.path == "src/echo.py" else file.data)
        for file in base.files))
    _force_target_commit(remote, conflict, "target conflicts")
    stopped = projects.execute_writeback(project_id, adoption_id)
    assert stopped.type == ProjectEventType.WRITEBACK_STOPPED

def test_every_event_of_a_project_follows_the_payload_contract(data_dir):
    system = LoopSystem.for_testing(data_dir, FakeAdapter(merge_scripts(
        _release_script("A"), _release_script("B", files={"src/echo.py": "print('B')\n"}),
        _release_script("C", files={"src/echo.py": "print('C')\n"}),
    )))
    projects = system.projects
    project_id = projects.register("载荷", "核对每种事件的载荷")
    projects.rename(project_id, "载荷核对")
    projects.set_goal(project_id, "核对修改以后的长期目标")
    projects.pin(project_id, True)
    projects.configure_department_settings(
        project_id, "engineering", ModelSelection(department_prompt="先写计划再写代码。"), 0)
    projects.record_material(project_id, "一段原文", department="product")
    projects.record_material(project_id, "不属于部门的原文")
    projects.configure_source_directory(project_id, "src", "C:/repo/src", base_version=0)
    projects.archive(project_id)
    projects.restore(project_id)
    projects.set_parameter(project_id, "check_timeout_sec", 300, reason="核对载荷", modified_by="user:test")
    with pytest.raises(ValueError, match="max_cycles"):
        projects.start_work_item(project_id, "开始失败的事项", max_cycles=0)
    _work_item_a, run_a = projects.start_work_item(project_id, "事项 A")
    _work_item_b, run_b = projects.start_work_item(project_id, "事项 B（在 A 采纳前创建）")
    assert system.run_until_stop(run_a).status == "done"
    assert projects.settle(run_a).type == ProjectEventType.DELIVERABLE_ADOPTED
    assert system.run_until_stop(run_b).status == "done"
    assert projects.settle(run_b).type == ProjectEventType.ADOPTION_HELD
    # 采纳写回（#347）：事项 C 的基线是事项 A 的采纳，写回的五种事件由真实流程产出
    _work_item_c, run_c = projects.start_work_item(project_id, "事项 C")
    assert system.run_until_stop(run_c).status == "done"
    assert projects.settle(run_c).type == ProjectEventType.DELIVERABLE_ADOPTED
    adoption_id = projects.projection(project_id).current_adoption.adoption_id
    _produce_writeback_events(system, projects, project_id, base_version=1,
                              adoption_id=adoption_id, remote=data_dir.parent / "writeback-target.git")
    # 实例升级的三个目录事件（工单 #462）：requested 由发布检查的真实入口写出，
    # answered 由 orchestrator 的目录流分支写出；withdrawn 没有生产写出方，按投影读的字段直接写
    decision_id = request_instance_upgrade(system, _release_report())
    system.orchestrator.answer_decision(
        decision_id, "approve", None, base_version=1,
        command=Command(str(uuid.uuid4()), "decision.answer", "sha256:approve:1", "user:local"))
    _withdraw_instance_upgrade(system, decision_id, "user_cancelled")

    events = system.store.read(0, limit=100_000)
    written = {event.type for event in events}
    onboarding = {ProjectEventType.INITIAL_PRD_PROPOSED, ProjectEventType.PROJECT_DECISION_REQUESTED,
                  ProjectEventType.PROJECT_DECISION_ANSWERED, ProjectEventType.PROJECT_DECISION_WITHDRAWN,
                  ProjectEventType.ONBOARDING_REVISION_STARTED, ProjectEventType.BASELINE_ADOPTED}
    assert ({value for key, value in vars(ProjectEventType).items() if not key.startswith("_")} - onboarding) <= written
    assert {EventType.RUN_CREATED, EventType.DELIVERY_ACCEPTED, EventType.QA_SUBMITTED, EventType.RUN_DONE} <= written
    assert {ProjectEventType.WRITEBACK_COMPLETED, ProjectEventType.WRITEBACK_HELD,
            ProjectEventType.WRITEBACK_NOT_NEEDED, ProjectEventType.WRITEBACK_STOPPED,
            ProjectEventType.WRITEBACK_VERIFIED} <= written
    assert_payloads_follow_contract(events)
