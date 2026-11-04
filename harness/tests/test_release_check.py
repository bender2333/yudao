# 发布检查（可信内核设计说明第 4.4 节，工单 #355）：在临时 git 仓库里植入两类问题（导入方向、
# 评测专有内容），每类都被报成对应的不通过项；干净的仓库通过；改待发布提交里的清单与内核测试不改变结果。
# 目录流中的决定请求「实例升级」带着检查结果，旧事件里的行数上限仍能读（工单 #1473）。

import json
from pathlib import Path

import pygit2
import pytest

from harness.app.application import Application
from harness.app.decision_queries import DecisionsList
from harness.event_store import catalog_stream
from harness.models import CatalogEventType, ProjectEventType
from harness.release_check import (
    MANIFEST_PATH,
    Finding,
    check_repository,
    decision_request_payload,
    load_manifest,
    request_instance_upgrade,
)
from harness.runtime import LoopSystem
from harness.write_path import NewCatalogEvent

# 内核清单里的一个模块，改动它用来制造内核差异
KERNEL_MODULE = "harness/bounds.py"
# 内核清单里的模块在临时仓库里的内容：只导入标准库，不含任何评测材料
KERNEL_SOURCE = "from __future__ import annotations\n\nLIMIT = 1\n"
# 评测场景的材料清单：它给出的标题与提交号是评测专有内容
EVAL_MANIFEST = json.dumps({
    "scenario": "scenario-2",
    "title": "FeatBench 842 model settings extra_args",
    "source": {"record": "openai__openai-agents-python-842", "upstream_repository": "openai/openai-agents-python",
               "base_commit": "8dfd6ff35c1b73bc5d2e6a14c0246b03aa2f9f98", "version": "v0.0.18"},
})
# 待发布提交里被检索的部门 Prompt 与工具说明
ROLES = json.dumps({"roles": [{"id": "engineering", "prompt": "按合同实现。"}]})
TOOLS = json.dumps({"tools": [{"name": "write_file", "description": "写入一个文件。"}]})


class Repository:
    # 一个临时 git 仓库：提交文件、打发布标签，供检查读取待发布提交
    def __init__(self, path: Path) -> None:
        self.path = path
        self.repository = pygit2.init_repository(path)
        self.signature = pygit2.Signature("release-check", "release-check@yudao.local")

    def write(self, relative: str, content: str) -> None:
        target = self.path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def commit(self, message: str) -> str:
        self.repository.index.add_all()
        self.repository.index.write()
        tree = self.repository.index.write_tree()
        parent = [] if self.repository.head_is_unborn else [self.repository.head.target]
        oid = self.repository.create_commit("HEAD", self.signature, self.signature, message, tree, parent)
        return str(oid)

    def tag(self, name: str) -> None:
        self.repository.create_reference(f"refs/tags/{name}", self.repository.head.target)


def _manifest_payload(*, module_paths: tuple[str, ...] = (KERNEL_MODULE,)) -> str:
    # 待发布提交里的内核清单：它与实例自带的清单无关，改它不改变检查结果。
    # 工单 #1473 起清单里没有行数上限，module_paths 让「待发布提交里改清单」的用例换一个字段
    return json.dumps({
        "owner": "user", "updated": "2026-10-10",
        "kinds": {"module": "控制核心的裁决模块", "material": "评价材料与守卫自身"},
        "paths": [{"path": path, "kind": "module", "why": "边界的核对"} for path in module_paths],
        "allowed_imports": ["内核文件", "标准库", "pydantic"],
    })


@pytest.fixture
def repository(tmp_path) -> Repository:
    # 一个干净的待发布仓库：实例清单里的内核模块、定义与评测材料都在，内核没有改动
    repo = Repository(tmp_path / "repo")
    for path in load_manifest().modules:
        repo.write(path, KERNEL_SOURCE if path == KERNEL_MODULE else "import pydantic\n")
    for path in load_manifest().material_globs:
        if path.endswith("**"):
            continue
        repo.write(path, "{}")
    repo.write("harness/tests/kernel/test_manifest.py", "def test_manifest():\n    assert True\n")
    repo.write("harness/definitions/kernel-manifest.json", _manifest_payload())
    repo.write("harness/definitions/roles.json", ROLES)
    repo.write("harness/definitions/tools.json", TOOLS)
    repo.write("evals/scenarios/scenario-2/materials/manifest.json", EVAL_MANIFEST)
    repo.commit("base")
    repo.tag("v0.1.0")
    repo.write("client/index.html", "<html></html>")
    repo.commit("pending")
    return repo


def _findings(report) -> dict[str, list[Finding]]:
    grouped: dict[str, list[Finding]] = {}
    for item in report.findings:
        grouped.setdefault(item.check, []).append(item)
    return grouped


def test_a_clean_pending_commit_passes(repository):
    # 干净的仓库通过：内核没有改动，导入方向正确，四处表面没有评测专有内容
    report = check_repository(repository.path)
    assert report.passed, report.text
    assert report.base_tag == "v0.1.0"
    assert report.kernel_changes == ()


def test_the_report_has_two_checks_and_no_line_cap(repository):
    # 工单 #1473：取消内核行数上限以后，发布检查只剩导入方向与评测专有内容两项，
    # 内核 Python 总行数仍写进报告，只作读数、不写上限，也不判通过
    repository.write(KERNEL_MODULE, "import pygit2\n")
    repository.commit("import a third-party package")
    report = check_repository(repository.path)
    assert {item.check for item in report.findings} == {"导入方向"}
    assert "上限" not in report.text
    assert f"内核 Python 行数：{report.kernel_python_lines}" in report.text
    assert "python_lines_max" not in decision_request_payload(report)["report"]


def test_a_changed_kernel_path_is_reported(repository):
    # 改动内核清单里的路径：列进报告的内核路径改动，不算不通过（改内核路径不事前批准，守它的是内核测试）
    repository.write(KERNEL_MODULE, KERNEL_SOURCE + "\nEXTRA = 2\n")
    repository.commit("change the kernel")
    report = check_repository(repository.path)
    assert KERNEL_MODULE in report.kernel_changes
    assert report.passed, report.text
    assert KERNEL_MODULE in report.text


def test_an_import_outside_the_allowed_direction_is_reported(repository):
    # 导入方向：内核模块导入清单以外的第三方包时报成导入方向不通过，位置带行号
    repository.write(KERNEL_MODULE, "import pygit2\n")
    repository.commit("import a third-party package")
    report = check_repository(repository.path)
    assert any(item.check == "导入方向" and item.where.startswith(f"{KERNEL_MODULE}:")
               for item in report.findings)


def test_a_kernel_module_missing_from_the_pending_commit_is_reported(repository):
    # 内核清单里的模块在待发布提交里被删掉：依赖它位置的检查都没法做，报成导入方向不通过。
    # 工单 #1473 去掉行数检查以后这条仍守着，位置写模块的路径
    (repository.path / KERNEL_MODULE).unlink()
    repository.repository.index.remove(KERNEL_MODULE)
    repository.commit("delete a kernel module")
    report = check_repository(repository.path)
    assert any(item.check == "导入方向" and item.where == KERNEL_MODULE for item in report.findings), report.text


def test_eval_proprietary_content_in_a_department_prompt_is_reported(repository):
    # 部门 Prompt 里出现评测场景专有内容：报成评测专有内容不通过
    repository.write("harness/definitions/roles.json", json.dumps(
        {"roles": [{"id": "engineering", "prompt": "参考 FeatBench 842 model settings extra_args 的做法。"}]}))
    repository.commit("leak the scenario into a prompt")
    report = check_repository(repository.path)
    proprietary = _findings(report).get("评测专有内容", [])
    assert any(item.where.startswith("harness/definitions/roles.json") for item in proprietary)


def test_eval_proprietary_content_in_a_skill_is_reported(repository):
    # 技能里出现评测场景专有内容：报成评测专有内容不通过，位置是技能目录下的文件
    repository.write("skills/deploy/SKILL.md", "部署前核对 openai__openai-agents-python-842 的记录。")
    repository.commit("leak the scenario into a skill")
    report = check_repository(repository.path)
    proprietary = _findings(report).get("评测专有内容", [])
    assert any(item.where.startswith("skills/") for item in proprietary)


def test_eval_proprietary_content_in_a_tool_description_is_reported(repository):
    # 工具说明里出现评测材料提交号：报成评测专有内容不通过，位置是工具说明。提交号不出现在
    # 部门 Prompt 与技能里（这个用例的仓库只改了工具说明），命中只在工具说明
    repository.write("harness/definitions/tools.json", json.dumps(
        {"tools": [{"name": "write_file",
                    "description": "按 8dfd6ff35c1b73bc5d2e6a14c0246b03aa2f9f98 校验。"}]}))
    repository.commit("leak the scenario into a tool description")
    report = check_repository(repository.path)
    proprietary = _findings(report).get("评测专有内容", [])
    assert proprietary, report.text
    assert any("工具 write_file" in item.where for item in proprietary)


def test_eval_proprietary_content_in_a_definition_is_reported(repository):
    # 定义里出现评测材料的提交号：同样报成评测专有内容不通过
    repository.write("harness/definitions/tools.json", json.dumps(
        {"tools": [{"name": "write_file",
                    "description": "基线提交 8dfd6ff35c1b73bc5d2e6a14c0246b03aa2f9f98 上的写法。"}]}))
    repository.commit("leak the scenario into a definition")
    report = check_repository(repository.path)
    proprietary = _findings(report).get("评测专有内容", [])
    assert any("harness/definitions/tools.json" in item.where for item in proprietary)


def test_editing_the_pending_manifest_does_not_change_the_result(repository):
    # 待发布提交里的清单与内核测试改不动结果：检查用的是实例自带的清单与检查。
    # 待发布提交里把清单改成一条模块都不列（照它自己的清单，那个内核模块的导入不会被核对），
    # 内核模块又导入了清单以外的 pygit2：导入方向仍按实例自带的清单报出来，
    # 清单与内核测试列进内核路径改动
    repository.write(KERNEL_MODULE, "import pygit2\n")
    repository.write("harness/definitions/kernel-manifest.json", _manifest_payload(module_paths=()))
    repository.write("harness/tests/kernel/test_manifest.py",
                     "def test_manifest():\n    assert True  # 待发布提交里改成一律通过\n")
    repository.commit("rewrite the manifest in the pending commit")
    report = check_repository(repository.path)
    assert any(item.check == "导入方向" and item.where.startswith(f"{KERNEL_MODULE}:")
               for item in report.findings), report.text
    assert "harness/definitions/kernel-manifest.json" in report.kernel_changes
    assert "harness/tests/kernel/test_manifest.py" in report.kernel_changes


def test_editing_the_pending_check_code_does_not_change_the_result(repository):
    # 待发布提交里的检查代码改不动结果：发布检查只用实例自带的检查。删掉待发布提交里的一处
    # 工具说明检索，检查仍然按实例自带的检索报出评测专有内容
    repository.write("harness/definitions/tools.json", json.dumps(
        {"tools": [{"name": "write_file",
                    "description": "按 8dfd6ff35c1b73bc5d2e6a14c0246b03aa2f9f98 校验。"}]}))
    repository.write("harness/release_check.py", "# 待发布提交里改写检查：实例不运行它\n")
    repository.commit("rewrite the check in the pending commit")
    report = check_repository(repository.path)
    assert any(item.check == "评测专有内容" for item in report.findings)


def test_the_query_lists_the_instance_upgrade_request_with_its_report(repository, tmp_path):
    # 工单 #564：决定请求「实例升级」经 decisions.list 返回，请求载荷通过应用层合同，
    # 项目、事项与 run 都为空，阻塞范围是实例
    report = check_repository(repository.path)
    system = LoopSystem(tmp_path / "data")
    try:
        decision_id = request_instance_upgrade(system, report)
        application = Application(system)
        listed = application.query("decisions.list", DecisionsList())
        [view] = [item for item in listed.data.decisions if item.decision_id == decision_id]
        assert view.kind == "instance_upgrade"
        assert view.blocks == "instance"
        assert view.status == "open"
        assert (view.project_id, view.work_item_id, view.run_id) == (None, None, None)
        assert view.request.kind == "instance_upgrade"
        assert view.request.blocks == "instance"
        assert [option.id for option in view.request.options] == ["approve", "reject"]
        assert report.text in view.request.facts
        assert view.request.report.pending_commit == report.pending_commit
        assert view.request.report.passed == report.passed
        # 工单 #1473：新生成的报告里没有行数上限这一项，写进目录流的载荷也不带这个字段
        assert view.request.report.python_lines_max is None
        [written] = [event for event in system.store.read(0, limit=1000)
                     if event.type == CatalogEventType.INSTANCE_UPGRADE_REQUESTED]
        assert "python_lines_max" not in written.payload["report"]
    finally:
        system.close()


def test_an_old_instance_upgrade_event_with_the_line_cap_still_reads(tmp_path):
    # 工单 #1473：目录流里已有的「实例升级」旧事件带着取消以前的行数上限。载荷合同把字段改成可选，
    # 这些事件仍能读取并经决定请求的投影返回，读到的上限就是当时记下的值
    system = LoopSystem(tmp_path / "data")
    try:
        old_report = {"repository": "D:/repo", "pending_commit": "0123456789abcdef", "base_tag": "v0.1.0",
                      "kernel_changes": [], "kernel_python_lines": 4093, "python_lines_max": 4096,
                      "passed": True, "findings": []}
        payload = {"kind": "instance_upgrade", "blocks": "instance",
                   "options": [{"id": "approve", "label": "批准升级"}, {"id": "reject", "label": "拒绝"}],
                   "description": "发布检查通过：是否把这台电脑上安装的那一份升级？",
                   "facts": ["发布检查：通过"], "report": old_report}

        def decide(transaction):
            return transaction.append(NewCatalogEvent(CatalogEventType.INSTANCE_UPGRADE_REQUESTED, payload,
                                                      actor="system"))

        [event] = system.writes.transact(catalog_stream(), decide)
        listed = Application(system).query("decisions.list", DecisionsList(kind="instance_upgrade"))
        [view] = [item for item in listed.data.decisions if item.decision_id == event.event_id]
        assert view.request.report.kernel_python_lines == 4093
        assert view.request.report.python_lines_max == 4096
    finally:
        system.close()

def test_the_kind_filter_returns_only_instance_upgrade_requests(repository, tmp_path):
    # 工单 #564：按 kind=instance_upgrade 筛选只返回实例升级决定，run 流的决定不在其中
    report = check_repository(repository.path)
    system = LoopSystem(tmp_path / "data")
    try:
        request_instance_upgrade(system, report)
        application = Application(system)
        listed = application.query("decisions.list", DecisionsList(kind="instance_upgrade"))
        assert [item.kind for item in listed.data.decisions] == ["instance_upgrade"]
        every = application.query("decisions.list", DecisionsList())
        assert {item.decision_id for item in every.data.decisions} == {
            item.decision_id for item in listed.data.decisions}
    finally:
        system.close()

def test_answering_an_instance_upgrade_request_shows_in_the_query(repository, tmp_path):
    # 工单 #564：回答以后经 decisions.list 读到的状态是已回答，回答记录所选选项
    import uuid

    from harness.event_store import Command

    report = check_repository(repository.path)
    system = LoopSystem(tmp_path / "data")
    try:
        decision_id = request_instance_upgrade(system, report)
        application = Application(system)
        answered = system.orchestrator.answer_decision(
            decision_id, "approve", None, base_version=1,
            command=Command(str(uuid.uuid4()), "decision.answer", "sha256:approve:1", "user:local"))
        assert answered is None
        listed = application.query("decisions.list", DecisionsList())
        [view] = [item for item in listed.data.decisions if item.decision_id == decision_id]
        assert view.status == "answered"
        assert view.answer is not None and view.answer.option == "approve"
    finally:
        system.close()

def test_the_catalog_stream_decisions_mark_the_list_for_resubscription(repository, tmp_path):
    # 工单 #564：目录流三个实例升级事件在 decisions.list 的 changed_by 里，客户端收到它们重新查询
    system = LoopSystem(tmp_path / "data")
    try:
        capabilities = Application(system).capabilities("", access="local")
        listed = next(item for item in capabilities.queries if item.name == "decisions.list")
        assert {CatalogEventType.INSTANCE_UPGRADE_REQUESTED, CatalogEventType.INSTANCE_UPGRADE_ANSWERED,
                CatalogEventType.INSTANCE_UPGRADE_WITHDRAWN} <= set(listed.changed_by)
        # 工单 #701：项目流里的决定（接入已有项目的初始 PRD）同样在清单里，
        # 客户端按这份清单重查顶栏的待决数量
        assert {ProjectEventType.PROJECT_DECISION_REQUESTED, ProjectEventType.PROJECT_DECISION_ANSWERED,
                ProjectEventType.PROJECT_DECISION_WITHDRAWN} <= set(listed.changed_by)
    finally:
        system.close()

def test_the_manifest_lists_the_release_check_as_added_later():
    # 发布检查不在内核路径里（它导入 pygit2，不满足内核的导入方向），登记在 added_later
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    paths = [entry["path"] for entry in manifest["paths"]]
    assert "harness/release_check.py" not in paths
    assert "harness/release_check.py" in [entry["path"] for entry in manifest["added_later"]]
