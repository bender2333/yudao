# 发布检查（可信内核设计说明第 4.4 节，工单 #355）：在临时 git 仓库里植入四类问题，
# 每类都被报成对应的不通过项；干净的仓库通过；改待发布提交里的清单与内核测试不改变结果。
# 目录流中的决定请求「实例升级」带着检查结果。

import json
from pathlib import Path

import pygit2
import pytest

from harness.release_check import (
    MANIFEST_PATH, Finding, check_repository, decision_request_payload, load_manifest, request_instance_upgrade,
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
    # 改动内核清单里的路径：报成内核差异，位置是改动的路径
    repository.write(KERNEL_MODULE, KERNEL_SOURCE + "\nEXTRA = 2\n")
    repository.commit("change the kernel")
    report = check_repository(repository.path)
    assert KERNEL_MODULE in report.kernel_changes
    assert KERNEL_MODULE in [item.where for item in _findings(report).get("内核差异", [])]


def test_kernel_python_lines_over_the_cap_are_reported(repository, tmp_path):
    # 行数超过上限：报成行数不通过。上限取自实例自带的清单，把行数抬到它以上
    cap = load_manifest().python_lines_max
    repository.write(KERNEL_MODULE, KERNEL_SOURCE + "".join(f"LINE_{index} = {index}\n" for index in range(cap)))
    repository.commit("grow the kernel")
    report = check_repository(repository.path)
    assert report.kernel_python_lines > report.python_lines_max
    assert any(item.check == "行数" for item in report.findings)


def test_an_import_outside_the_allowed_direction_is_reported(repository):
    # 导入方向：内核模块导入清单以外的第三方包时报成导入方向不通过，位置带行号
    repository.write(KERNEL_MODULE, "import pygit2\n")
    repository.commit("import a third-party package")
    report = check_repository(repository.path)
    assert any(item.check == "导入方向" and item.where.startswith(f"{KERNEL_MODULE}:")
               for item in report.findings)


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
    # 把待发布提交里的行数上限改成 1，结果仍然只有内核差异这两项，行数上限仍按实例自带的算
    repository.write("harness/definitions/kernel-manifest.json", _manifest_payload(python_lines_max=1))
    repository.write("harness/tests/kernel/test_manifest.py",
                     "def test_manifest():\n    assert True  # 待发布提交里改成一律通过\n")
    repository.commit("rewrite the manifest in the pending commit")
    report = check_repository(repository.path)
    assert [item.check for item in report.findings] == ["内核差异", "内核差异"]
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


def test_the_report_is_carried_by_the_instance_upgrade_decision_request(repository, tmp_path):
    # 决定请求「实例升级」带着检查结果：写进目录流以后读回来，材料是同一份报告，
    # 选项是批准升级与拒绝
    report = check_repository(repository.path)
    system = LoopSystem(tmp_path / "data")
    try:
        decision_id = request_instance_upgrade(system, report)
        saved = system.store.decision(decision_id)
    finally:
        system.close()
    assert saved is not None
    assert saved.kind == "instance_upgrade"
    assert saved.status == "open"
    payload = decision_request_payload(report)
    assert payload["kind"] == "instance_upgrade"
    assert [option["id"] for option in payload["options"]] == ["approve", "reject"]
    assert payload["report"]["passed"] == report.passed
    assert report.text in payload["facts"]
    assert json.loads(saved.state)["request"]["report"]["pending_commit"] == report.pending_commit


def test_answering_the_instance_upgrade_decision_records_the_choice(repository, tmp_path):
    # 决定请求「实例升级」可以回答：用户批准以后状态是已回答，选项是批准升级
    import uuid

    from harness.event_store import Command
    from harness.projection import saved_decision

    report = check_repository(repository.path)
    system = LoopSystem(tmp_path / "data")
    try:
        decision_id = request_instance_upgrade(system, report)
        saved = saved_decision(system.store, decision_id)
        assert saved is not None and saved.version == 1
        answered = system.orchestrator.answer_decision(
            decision_id, "approve", None, base_version=1,
            command=Command(str(uuid.uuid4()), "decision.answer", "sha256:approve:1", "user:local"))
        assert answered is None
        closed = saved_decision(system.store, decision_id)
        assert closed is not None and closed.status == "answered"
        assert closed.answer is not None and closed.answer["option"] == "approve"
    finally:
        system.close()


def test_the_manifest_lists_the_release_check_as_added_later():
    # 发布检查不在内核路径里（它导入 pygit2，不满足内核的导入方向），登记在 added_later
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    paths = [entry["path"] for entry in manifest["paths"]]
    assert "harness/release_check.py" not in paths
    assert "harness/release_check.py" in [entry["path"] for entry in manifest["added_later"]]
