# 工具定义本身的规则：工具种类与动作类别、工具说明写明的证据要求、回执的显示方式、唯一的可重复判断入口，
# 以及按输入方式提供工具的机制。这些结论只读取仓库内的定义与纯函数，登记为单元层。

import pytest

from harness.definitions import DEFINITIONS
from harness.tools import offers_with_input, tool_action, tool_kind, tools_for

TOOLS = DEFINITIONS.tools


def test_tools_are_host_tools_or_environment_actions():
    # 主机工具只有提交类工具；其余工具是环境工具，各有动作类别
    assert {name for name, tool in TOOLS.items() if tool.kind == "host"} == {
        name for name in TOOLS if name.startswith("submit_")}
    assert {name: tool.action for name, tool in TOOLS.items() if tool.kind == "environment"} == {
        "read_file": "read", "list_files": "read", "search": "read", "read_range": "read",
        "write_file": "write", "edit_range": "write", "delete_file": "write", "move_file": "write",
        "run_check": "check", "bash": "command", "read_output": "command", "stop_job": "command",
    }


def test_submit_review_description_rejects_engineering_receipts_as_quality_evidence():
    review = TOOLS["submit_review"]
    assert "Engineering receipts are not accepted as QA evidence." in review.description
    assert review.parameters["properties"]["checks"]["description"] == "Quality check names run via run_check"


def test_submit_delivery_description_states_that_check_receipts_come_from_run_check():
    delivery = TOOLS["submit_delivery"]
    text = delivery.description
    assert "Every name in check_names must be a name you passed to run_check in this activation on the current workspace" in text
    assert "if any file changes after a check, call run_check again before submitting" in text
    assert "bash results are action receipts and are not accepted as delivery check receipts" in text
    names = delivery.parameters["properties"]["check_names"]["description"]
    assert "Names passed to run_check in this activation on the current workspace" in names
    assert "bash results do not count" in names


def test_bash_description_separates_action_receipts_from_delivery_check_receipts():
    text = TOOLS["bash"].description
    assert "host-observed exit status" in text
    assert "A bash result is an action receipt, not a check receipt" in text
    assert "it cannot be listed in submit_delivery check_names" in text
    assert "run the checks a delivery needs with run_check" in text
    assert "inherits the Yudao process's full environment" in text
    assert "replaces the value of any known secret with its name" in text
    assert "the whole process tree is stopped" in text
    assert "Output exceeding the limit is truncated with a job_id; use read_output to retrieve the remaining output" in text
    assert "Background commands (background=true) return immediately with a job_id" in text
    assert "cursor" not in TOOLS["bash"].parameters["properties"]
    assert "background" in TOOLS["bash"].parameters["properties"]
    assert "job_id" in TOOLS["read_output"].parameters["properties"]
    assert "job_id" in TOOLS["stop_job"].parameters["properties"]


def test_write_tool_descriptions_state_engineering_only():
    write = TOOLS["write_file"].description
    assert "replace its entire content" in write and "missing parent directories are created" in write
    assert "Use edit_range to change part of an existing file." in write
    for name in ("write_file", "edit_range"):
        text = TOOLS[name].description
        assert "Engineering only" in text
        assert "plan" not in text.lower()


def test_run_check_requires_a_command_string():
    # 工单 #480：检查的调用是命令字符串，不再是 argv 向量；超时缺省、超限截断
    check = TOOLS["run_check"]
    assert set(check.parameters["required"]) == {"name", "command"}
    assert "command" in check.parameters["properties"]
    assert "argv" not in check.parameters["properties"]
    assert "The command string runs with bash at the copy root" in check.description
    assert "Only run_check receipts count as check evidence" in check.description


def test_smoke_exit_code_does_not_accept_fake_or_missing_evidence():
    from harness.smoke import smoke_exit_code

    assert smoke_exit_code({"available": False}) == 2
    done = {
        "phase": "DONE",
        "stop_reason": "released",
        "replay_consistent": True,
        "context_isolated": True,
        "model_input_audit": {"status": "verified"},
        "check_receipts": [{"name": "smoke"}],
        "check_receipts_verified": True,
        "delivery_archive": {"status": "verified"},
        "git_audit": {"status": "verified"},
        "fake_used": False,
        "request_count": 2,
        "collaboration_audit": {"status": "verified", "pre_spec_consultation": True, "requirements_action": True},
    }
    assert smoke_exit_code({"available": True, "scenarios": {"happy": done, "collaboration": done}}) == 0
    fake = dict(done, fake_used=True)
    assert smoke_exit_code({"available": True, "scenarios": {"happy": fake}}) == 2
    no_receipts = dict(done, check_receipts=[])
    assert smoke_exit_code({"available": True, "scenarios": {"happy": no_receipts}}) == 1
    no_git_audit = {key: value for key, value in done.items() if key != "git_audit"}
    assert smoke_exit_code({"available": True, "scenarios": {"happy": no_git_audit}}) == 1
    unverified_git = dict(done, git_audit={"status": "unverified"})
    assert smoke_exit_code({"available": True, "scenarios": {"happy": unverified_git}}) == 1


def test_edit_range_is_an_engineering_only_write_tool():
    assert tool_kind("edit_range") == "environment" and tool_action("edit_range") == "write"
    assert "edit_range" in tools_for("engineering")
    assert "edit_range" not in tools_for("product")
    assert "edit_range" not in tools_for("quality")

def test_read_output_and_stop_job_are_offered_to_all_departments():
    for department in ("product", "engineering", "quality"):
        tools = tools_for(department)
        assert "read_output" in tools
        assert "stop_job" in tools



def test_guidance_tool_contract_lists_explained_and_requires_host_results_for_completed():
    tool = DEFINITIONS.tools["submit_guidance_response"]
    status = list(tool.parameters["properties"]["status"]["enum"])
    assert status == ["explained", "completed", "declined", "needs_work"]
    assert "empty is allowed" not in tool.description
    contract = DEFINITIONS.proposal_contract("product")["kinds"]["department_guidance_response"]
    assert contract["status"] == ["explained", "completed", "declined", "needs_work"]


def test_offers_with_input_filters_tools_that_need_images():
    # 声明需要图像输入的工具在调用目标不含图像时不提供（机制本身；3.2D 的屏幕工具使用这一声明）
    names = ["read_file", "list_files"]
    assert offers_with_input(names, ("text",)) == names
    assert offers_with_input(names, ("text", "image")) == names
    assert offers_with_input(names, ()) == names


@pytest.mark.parametrize("path", ["../src/", "/src/", "C:/src/", "src/../other/", ".checks/", ".CHECKS/",
                                  "src:file", "src/ ", ".checks /", "src./", "NUL", "src/COM1.py"])
def test_normalize_scope_rejects_paths_outside_public_workspace(path):
    from harness.contracts import normalize_scope

    with pytest.raises(ValueError):
        normalize_scope(path)


def test_scope_matches_files_and_directory_boundaries():
    from harness.contracts import normalize_scope, path_in_scope

    assert normalize_scope(" src/") == " src/"
    assert path_in_scope(" src/main.py", [" src/"])
    assert path_in_scope("src/main.py", ["src/"])
    assert path_in_scope("src/main.py", ["src/main.py"])
    assert not path_in_scope("src-other/main.py", ["src/"])
    assert not path_in_scope("src/other.py", ["src/main.py"])
    assert not path_in_scope("../materials/run/PRD.md", ["."])
    assert not path_in_scope(".checks/receipts.jsonl", ["."])
    assert not path_in_scope(" src/main.py", ["src/"])
    assert not path_in_scope("src/main.py ", ["src/"])


def test_quality_prompt_mentions_qa_tests_dir():
    from harness.public_tree import QA_TESTS_DIR

    assert QA_TESTS_DIR in DEFINITIONS.roles["quality"].prompt
