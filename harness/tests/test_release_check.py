# 发布检查：内核差异列入报告，三类技术失败阻止发布；
# 干净的仓库通过；改待发布提交里的清单与内核测试不改变结果。
# 目录流中的决定请求「实例升级」带着检查结果。

import json
from pathlib import Path

import pygit2
import pytest

from harness.app.application import Application
from harness.app.decision_queries import DecisionsList
from harness.models import CatalogEventType, ProjectEventType
from harness.release_check import (
    MANIFEST_PATH,
    Finding,
    check_repository,
    load_manifest,
    request_instance_upgrade,
)
from harness.runtime import LoopSystem

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


def _manifest_payload(*, python_lines_max: int = 100000) -> str:
    # 待发布提交里的内核清单：它与实例自带的清单无关，改它不改变检查结果
    return json.dumps({
        "owner": "user", "updated": "2026-10-10",
        "kinds": {"module": "控制核心的裁决模块", "material": "评价材料与守卫自身"},
        "paths": [{"path": KERNEL_MODULE, "kind": "module", "why": "边界的核对"}],
        "python_lines_max": python_lines_max,
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
    # 干净的仓库通过：内核没有改动，行数在上限内，导入方向正确，四处表面没有评测专有内容
    report = check_repository(repository.path)
    assert report.passed, report.text
    assert report.base_tag == "v0.1.0"
    assert report.kernel_changes == ()


def test_a_changed_kernel_path_is_reported(repository):
    # R2：内核差异列入发布报告，符合其余检查的提交可以发布。
    repository.write(KERNEL_MODULE, KERNEL_SOURCE + "\nEXTRA = 2\n")
    repository.commit("change the kernel")
    report = check_repository(repository.path)
    assert KERNEL_MODULE in report.kernel_changes
    assert KERNEL_MODULE in report.text
    assert report.passed, report.text


def test_kernel_python_lines_over_the_cap_are_reported(repository, tmp_path):
    # 行数超过上限：报成行数不通过。上限取自实例自带的清单，把行数抬到它以上
    cap = load_manifest().python_lines_max
    repository.write(KERNEL_MODULE, KERNEL_SOURCE + "".join(f"LINE_{index} = {index}\n" for index in range(cap)))
    repository.commit("grow the kernel")
    report = check_repository(repository.path)
    assert report.kernel_python_lines > report.python_lines_max
    assert any(item.check == "行数" for item in report.findings)
    assert not report.passed


def test_an_import_outside_the_allowed_direction_is_reported(repository):
    # 导入方向：内核模块导入清单以外的第三方包时报成导入方向不通过，位置带行号
    repository.write(KERNEL_MODULE, "import pygit2\n")
    repository.commit("import a third-party package")
    report = check_repository(repository.path)
    assert any(item.check == "导入方向" and item.where.startswith(f"{KERNEL_MODULE}:")
               for item in report.findings)
    assert not report.passed


def test_eval_proprietary_content_in_a_department_prompt_is_reported(repository):
    # 部门 Prompt 里出现评测场景专有内容：报成评测专有内容不通过
    repository.write("harness/definitions/roles.json", json.dumps(
        {"roles": [{"id": "engineering", "prompt": "参考 FeatBench 842 model settings extra_args 的做法。"}]}))
    repository.commit("leak the scenario into a prompt")
    report = check_repository(repository.path)
    proprietary = _findings(report).get("评测专有内容", [])
    assert any(item.where.startswith("harness/definitions/roles.json") for item in proprietary)
    assert not report.passed


@pytest.mark.parametrize("invalid_import", [False, True])
def test_release_check_cli_is_readonly_and_returns_the_check_status(repository, tmp_path, capsys, invalid_import):
    # R2：重复发布检查返回实际检查结果，使用中的实例目录不受检查命令影响。
    from harness.__main__ import main

    repository.write(KERNEL_MODULE, "import pygit2\n" if invalid_import else KERNEL_SOURCE + "EXTRA = 2\n")
    repository.commit("change kernel for release")
    data_dir = tmp_path / "live-instance"
    system = LoopSystem(data_dir)
    try:
        before = {path.relative_to(data_dir): path.read_bytes()
                  for path in data_dir.rglob("*") if path.is_file()}
        for _ in range(2):
            assert main(["release-check", str(repository.path), "--data-dir", str(data_dir)]) == (
                1 if invalid_import else 0)
            output = capsys.readouterr().out
            assert KERNEL_MODULE in output
            assert "决定请求" not in output
            after = {path.relative_to(data_dir): path.read_bytes()
                     for path in data_dir.rglob("*") if path.is_file()}
            assert after == before
    finally:
        system.close()


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
    # 把待发布提交里的行数上限改成 1，行数上限仍按实例自带的算，差异记录在报告中。
    repository.write("harness/definitions/kernel-manifest.json", _manifest_payload(python_lines_max=1))
    repository.write("harness/tests/kernel/test_manifest.py",
                     "def test_manifest():\n    assert True  # 待发布提交里改成一律通过\n")
    repository.commit("rewrite the manifest in the pending commit")
    report = check_repository(repository.path)
    assert report.passed, report.text
    assert set(report.kernel_changes) == {
        "harness/definitions/kernel-manifest.json", "harness/tests/kernel/test_manifest.py"}
    assert report.python_lines_max == load_manifest().python_lines_max
    assert report.kernel_python_lines > 1


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
