# 工单 #1657：动作标记与动作标题（工作过程的任务与动作标题设计说明「动作标记」「动作标题」）。
# 一个纯函数：工具定义 + 动作的参数 + 回执 → 动作标记（五种种类加系统量到的事实）、一行标题（上限 60 字符，
# 超出截断并加省略号）与标题来源。这一份守的是 R3（工作过程读得懂：每个动作一行标记加标题）与 R2
# （接口合同只增：事件流里工具事件的文字与 run.steps 的标题由同一个函数算，两处逐字相同）。
# 工单 #1659：运行命令的那一句话（设计说明「动作标题」表里的运行命令一行与「接口」的定义的缝）——
# 有它时标题是它、来源记作者，空白算缺失、缺失写「运行命令：<命令开头>」，标记只来自工具定义与回执。

import json

import pytest

from harness.app.action_titles import (SOURCE_AUTHOR, SOURCE_SYSTEM, TITLE_LIMIT, TIMEOUT_EXIT_CODE,
                                       ReceiptFacts, action_line, action_title, limit_title, mcp_tool_parts,
                                       text_title, tool_definition)
from harness.definitions import DEFINITIONS_DIR
from harness.environment import TIMEOUT_EXIT_CODE as EXECUTION_TIMEOUT_EXIT_CODE

# 工具定义的查找第一次会读发布的各份定义（默认与 forms/ 下每个形态）：在这里先做好，
# 单元层每条用例 5 秒的上限不受这一次读取影响
tool_definition("submit_completion")

# 设计说明「动作标题」那张表的每一行（本工单验收的第 1 条）
TITLES = [
    ("read_file", {"path": "src/a.py"}, "读取 src/a.py"),
    ("read_range", {"path": "src/a.py", "start_line": 3, "end_line": 5}, "读取 src/a.py 第 3–5 行"),
    ("read_range", {"path": "src/a.py", "start_line": 3}, "读取 src/a.py 第 3 行起"),
    ("list_files", {"prefix": "harness/"}, "列出 harness/ 下的文件"),
    ("search", {"pattern": "def add"}, "搜索「def add」"),
    ("fetch_url", {"url": "https://example.com/"}, "取回 https://example.com/"),
    ("write_file", {"path": "a.txt", "content": "新的内容"}, "写入 a.txt"),
    ("edit_range", {"path": "a.txt", "expected_text": "a", "new_text": "b"}, "修改 a.txt"),
    ("delete_file", {"path": "a.txt", "reason": "过期"}, "删除 a.txt：过期"),
    ("move_file", {"source": "a.txt", "destination": "b.txt", "reason": "整理"}, "移动 a.txt 到 b.txt：整理"),
    ("bash", {"command": "uv run pytest -q"}, "运行命令：uv run pytest -q"),
    ("run_check", {"name": "smoke", "command": "uv run pytest"}, "运行检查 smoke"),
    ("run_baseline_check", {"name": "smoke"}, "在基线上运行检查 smoke"),
    ("ask", {"recipient": "product", "question": "参数错误怎么处理？"}, "问产品部门：参数错误怎么处理？"),
    ("answer", {"answer": "按事实回答"}, "回答询问"),
    ("submit_delivery", {"summary": "交付"}, "提交交付"),
    ("submit_review", {"verdict": "release"}, "提交质检结论"),
    ("submit_completion", {"summary": "做完了"}, "提交交完成"),
    ("trial_start", {"launch": {"name": "web"}}, "开始试用 web"),
    ("trial_stop", {}, "结束试用"),
    ("trial_case_begin", {"title": "没有订单时"}, "开始用例：没有订单时"),
    ("trial_case_end", {"result": "passed"}, "结束用例：passed"),
    # 表里没有列的已知工具：按同类工具的写法写一句，对象取参数里的那一项（写进交付说明的「自定的边界」）
    ("read_external_source", {"source": "sha256:ab", "start_line": 2, "end_line": 4},
     "读取外部来源 sha256:ab 第 2–4 行"),
    ("read_output", {"job_id": "job-1"}, "读取后台命令的输出"),
    ("stop_job", {"job_id": "job-1"}, "停止后台命令"),
]


@pytest.mark.parametrize("name, args, title", TITLES)
def test_every_kind_of_tool_writes_the_title_from_the_table(name, args, title):
    # R3：读、写、搜索、检查、询问、提交各类工具的标题写明对象，与设计说明的表一致
    line = action_line(tool_definition(name), name, args)
    assert line.title == title
    assert line.source == SOURCE_SYSTEM


KIND_MARKS = [
    ("read_file", "读"), ("list_files", "读"), ("search", "读"), ("fetch_url", "读"),
    ("write_file", "写"), ("edit_range", "写"), ("delete_file", "写"), ("move_file", "写"),
    ("bash", "运行"), ("run_check", "运行"), ("run_baseline_check", "运行"), ("trial_start", "运行"),
    ("browser_click", "运行"), ("read_output", "运行"),
    ("ask", "询问"), ("answer", "询问"),
    ("submit_delivery", "提交"), ("submit_review", "提交"), ("submit_structure", "提交"),
]


@pytest.mark.parametrize("name, mark", KIND_MARKS)
def test_the_kind_mark_comes_from_the_tool_definition(name, mark):
    # R2：五种种类只由工具定义得出（kind、action、proposal），定义不加新栏
    assert action_line(tool_definition(name), name, {}).mark == mark


def test_every_submit_tool_of_every_form_is_a_submission():
    # R3：直做形态的提交工具只在形态自己的工具定义里（harness/definitions/forms/<形态>/ 各是一份完整的定义），
    # 查询与事件流用同一份查找，都认得它们
    from harness.definitions import DEFINITIONS, DEFINITIONS_DIR, load_definitions

    releases = [DEFINITIONS] + [
        load_definitions(path) for path in sorted((DEFINITIONS_DIR / "forms").iterdir())
        if (path / "tools.json").is_file()]
    submit_tools = [name for release in releases for name, tool in release.tools.items()
                    if tool.proposal is not None]
    assert submit_tools
    for name in submit_tools:
        found = tool_definition(name)
        assert found is not None, name
        assert action_line(found, name, {}).mark == "提交", name
        assert action_line(found, name, {}).title.startswith("提交"), name


def test_an_mcp_tool_is_named_by_its_server_and_tool():
    # R3：MCP 工具名是 mcp__服务器__工具，标题写「调用 <服务器> 的 <工具>」，种类算运行
    assert mcp_tool_parts("mcp__time__now") == ("time", "now")
    assert mcp_tool_parts("read_file") is None
    line = action_line(None, "mcp__time__now", {"tool": "now"})
    assert (line.mark, line.title) == ("运行", "调用 time 的 now")


def test_an_unknown_tool_or_invalid_arguments_writes_the_tool_name():
    # R3：参数不是合法 JSON（invalid_arguments）或工具已不存在时写工具名，不报错
    assert action_line(None, "no_such_tool", {}).title == "no_such_tool"
    assert action_line(None, "no_such_tool", {}).mark is None
    assert action_line(tool_definition("read_file"), "read_file",
                       {"invalid_arguments": '{"path": '}).title == "read_file"
    assert action_line(tool_definition("read_file"), "read_file", {}).title == "read_file"
    # 任意输入都不抛异常
    assert action_line(None, None, None).title == ""


def test_a_title_over_the_limit_is_cut_with_an_ellipsis():
    # R3：标题的显示上限 60 字符，超出截断并加省略号，上限含省略号本身
    assert limit_title("字" * TITLE_LIMIT) == "字" * TITLE_LIMIT
    cut = limit_title("字" * (TITLE_LIMIT + 10))
    assert len(cut) == TITLE_LIMIT and cut.endswith("…")
    title = action_line(tool_definition("read_file"), "read_file", {"path": "a" * (TITLE_LIMIT + 10)}).title
    assert len(title) == TITLE_LIMIT and title.endswith("…")
    # 原文在原始数据里：标题只是截断，不改参数
    long_command = "echo " + "x" * 200
    assert action_line(tool_definition("bash"), "bash",
                       {"command": long_command}).title.startswith("运行命令：echo xxx")


def test_the_one_sentence_of_a_run_command_is_the_title_from_its_author():
    # R3（工单 #1659）：运行命令带一句话时，标题就是这句话、来源记作者；换行合成空格，
    # 空白的算缺失、缺失时写「运行命令：<命令开头>」
    line = action_line(tool_definition("bash"), "bash",
                       {"command": "uv run pytest -q", "intent": "跑一次单元测试"})
    assert (line.title, line.source) == ("跑一次单元测试", SOURCE_AUTHOR)
    wrapped = action_line(tool_definition("bash"), "bash",
                          {"command": "ls", "intent": "先看目录，\n再决定跑哪一条"})
    assert (wrapped.title, wrapped.source) == ("先看目录， 再决定跑哪一条", SOURCE_AUTHOR)
    for blank in ("", "   ", "\n\t "):
        missing = action_line(tool_definition("bash"), "bash", {"command": "ls", "intent": blank})
        assert (missing.title, missing.source) == ("运行命令：ls", SOURCE_SYSTEM)
    # 没有这一项时与 #1657 的写法相同，来源记系统
    assert action_line(tool_definition("bash"), "bash", {"command": "ls"}).source == SOURCE_SYSTEM
    # 显示上限对角色写的与系统算的是同一个
    cut = action_line(tool_definition("bash"), "bash",
                      {"command": "ls", "intent": "字" * (TITLE_LIMIT + 10)}).title
    assert len(cut) == TITLE_LIMIT and cut.endswith("…")


def test_the_one_sentence_does_not_change_the_mark_or_the_facts():
    # R3（工单 #1659 验收第 4 条）：角色写「查看配置」而动作改了公开树时仍标「改了文件」；
    # 失败、超时、结果未知、被拒绝同样，一句话改变不了标记
    changed = action_line(tool_definition("bash"), "bash",
                          {"command": "sed -i s/a/b/ .env", "intent": "查看配置"},
                          ReceiptFacts(before_hash="sha256:" + "a" * 64,
                                       after_hash="sha256:" + "b" * 64))
    assert (changed.mark, changed.facts) == ("运行", ("改了文件",))
    assert changed.title == "查看配置"
    assert action_line(tool_definition("bash"), "bash", {"command": "false", "intent": "查看配置"},
                       ReceiptFacts(ok=True, exit_code=2)).facts == ("失败",)
    assert action_line(tool_definition("bash"), "bash", {"command": "sleep 9", "intent": "查看配置"},
                       ReceiptFacts(ok=False, status="timeout", exit_code=124)).facts == ("超时", "失败")
    assert action_line(tool_definition("bash"), "bash", {"command": "ls", "intent": "查看配置"},
                       ReceiptFacts(unknown=True)).facts == ("结果未知",)
    assert action_line(tool_definition("bash"), "bash", {"command": "ls", "intent": "查看配置"},
                       ReceiptFacts(refused=True)).facts == ("被拒绝",)


def test_only_the_run_command_takes_a_sentence_from_its_author():
    # 自定的边界（工单 #1659）：设计说明只给运行命令这一项，别的工具带了同名的一项也不算作者写的标题，
    # 标题照旧由系统算、来源记系统
    line = action_line(tool_definition("read_file"), "read_file", {"path": "a.py", "intent": "看看配置"})
    assert (line.title, line.source) == ("读取 a.py", SOURCE_SYSTEM)


def test_the_three_tool_definitions_carry_the_same_run_command():
    # R2（工单 #1659 验收第 6 条）：默认与两份形态的 bash 完全相同，这一项三处一样
    forms = ("several_roles_direct", "single_role_direct")
    paths = [DEFINITIONS_DIR / "tools.json"] + [DEFINITIONS_DIR / "forms" / form / "tools.json"
                                               for form in forms]
    runs = [json.loads(path.read_text(encoding="utf-8"))["bash"] for path in paths]
    assert runs[0] == runs[1] == runs[2]
    assert "intent" in runs[0]["parameters"]["properties"]


def test_a_text_only_row_is_one_line_with_the_opening_of_the_text():
    # R3：只有文字、没有动作的一步，这段文字的开头作一行（换行合成空格，同样受 60 字符上限）
    assert text_title("先看代码，\n再动手。") == "先看代码， 再动手。"
    assert text_title("   ") == ""
    assert len(text_title("字" * (TITLE_LIMIT + 5))) == TITLE_LIMIT


def test_a_failure_comes_from_the_exit_status_not_from_ok():
    # R3：失败由退出状态非零或工具报错得出——退出状态非零时 ok 仍为真，这一条用 ok 判不出来
    assert action_line(tool_definition("bash"), "bash", {"command": "false"},
                       ReceiptFacts(ok=True, exit_code=3, status="failed")).facts == ("失败",)
    assert action_line(tool_definition("bash"), "bash", {"command": "true"},
                       ReceiptFacts(ok=True, exit_code=0, status="ok")).facts == ()
    assert action_line(tool_definition("write_file"), "write_file", {"path": "a.txt"},
                       ReceiptFacts(ok=False, error="路径无法表示")).facts == ("失败",)
    # 标题只由工具与参数得出，回执改变不了它
    assert action_line(tool_definition("bash"), "bash", {"command": "false"},
                       ReceiptFacts(ok=False, exit_code=3)).title == "运行命令：false"


def test_a_timeout_comes_from_the_status_or_the_exit_code():
    # R3：超时由事实得出：命令的回执带 status，检查类工具的回执只有退出状态
    assert action_line(tool_definition("bash"), "bash", {"command": "sleep 9"},
                       ReceiptFacts(ok=False, status="timeout", exit_code=124)).facts == ("超时", "失败")
    assert action_line(tool_definition("run_check"), "run_check", {"name": "smoke"},
                       ReceiptFacts(ok=True, exit_code=TIMEOUT_EXIT_CODE)).facts == ("超时", "失败")


def test_the_timeout_exit_code_matches_the_execution_layer():
    # R2：两处取值相同——执行层写这个退出状态，这里按它认出超时
    assert TIMEOUT_EXIT_CODE == EXECUTION_TIMEOUT_EXIT_CODE


def test_unknown_refused_and_changed_files_come_from_the_receipt():
    # R3：结果未知、被拒绝、改了文件都由事实得出
    assert action_line(tool_definition("read_file"), "read_file", {"path": "a.txt"},
                       ReceiptFacts(unknown=True)).facts == ("结果未知",)
    assert action_line(tool_definition("write_file"), "write_file", {"path": "a.txt"},
                       ReceiptFacts(refused=True)).facts == ("被拒绝",)
    changed = action_line(tool_definition("write_file"), "write_file", {"path": "a.txt"},
                          ReceiptFacts(before_hash="sha256:" + "a" * 64, after_hash="sha256:" + "b" * 64))
    assert changed.facts == ("改了文件",)


def test_files_changed_compares_the_content_hash_not_the_whole_reference():
    # R3：比较动作前后快照引用的 content_hash，不比较整个引用（两个引用的 kind 不同）；缺一个快照时不标
    same = action_line(tool_definition("read_file"), "read_file", {"path": "a.txt"},
                       ReceiptFacts(before_hash="sha256:" + "a" * 64, after_hash="sha256:" + "a" * 64))
    assert same.facts == ()
    missing = action_line(tool_definition("read_file"), "read_file", {"path": "a.txt"},
                          ReceiptFacts(before_hash="sha256:" + "a" * 64))
    assert missing.facts == ()
    assert action_line(tool_definition("read_file"), "read_file", {"path": "a.txt"}).facts == ()


def test_a_known_credential_in_the_command_shows_its_name(monkeypatch):
    # R3：命令原文带已知凭据时，标题里显示凭据的名称，不出现原文
    monkeypatch.setenv("TOKEN_X", "secret-value-13579")
    title = action_line(tool_definition("bash"), "bash",
                        {"command": "curl -H 'Authorization: secret-value-13579'"}).title
    assert "secret-value-13579" not in title
    assert "${TOKEN_X}" in title
    # 角色写的那一句话和命令原文是同一条规则（工单 #1659）
    sentence = action_line(tool_definition("bash"), "bash",
                           {"command": "curl -s https://example.com/",
                            "intent": "用 secret-value-13579 取回数据"}).title
    assert "secret-value-13579" not in sentence
    assert "${TOKEN_X}" in sentence


def test_the_event_text_and_the_action_title_are_the_same_function():
    # R2：事件流里工具开始与工具结果的文字与 run.steps 的动作行同一个函数算，两处逐字相同
    args = {"path": "src/a.py"}
    assert action_title("read_file", args) == action_line(tool_definition("read_file"), "read_file", args).title
    assert action_title("bash", {"command": "ls"}) == "运行命令：ls"
    # 带一句话的运行命令：两处都写那一句（工单 #1659）
    assert action_title("bash", {"command": "ls", "intent": "看目录"}) == "看目录"
