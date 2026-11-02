from harness.definitions import DEFINITIONS
from harness.environment import LocalEnvironment
from harness.models import json_dumps
from harness.tests.helpers import perform
from harness.workspace import Workspace


def _environment(root):
    workspace = Workspace(root)
    return workspace, LocalEnvironment(workspace)


def _page_size(page):
    # 一页占的字符数：命中与截断标记，与执行环境决定一页放几条时量的是同一份内容
    return len(json_dumps({"matches": page, "truncated": True}))


def test_search_returns_path_line_and_locatable_snippet(tmp_path):
    workspace, environment = _environment(tmp_path)
    workspace.write_file("src/main.py", "第一行\nneedle 在这里\n最后一行\n")
    result = perform(environment, "search", {"pattern": "needle"})
    assert result.ok, result.error
    assert result.output["total_matches"] == 1
    match = result.output["matches"][0]
    assert match["path"] == "src/main.py"
    assert match["line"] == 2
    # 片段必须能定位到原文件对应行
    assert workspace.read_file("src/main.py").splitlines()[match["line"] - 1] == match["snippet"]
    assert result.output["digest"] == workspace.digest()
    assert result.output["truncated"] is False
    assert result.output["next_cursor"] is None


def test_a_page_over_the_output_limit_keeps_the_matches_that_fit_and_says_it_truncated(tmp_path):
    # 工单 #1299：一页超过输出上限时按这一页的真实大小定页，挤出去的命中留给下一页
    limit = DEFINITIONS.rule_value("tool_output_limit")
    workspace, environment = _environment(tmp_path)
    lines = [f"needle {index:03d} " + "x" * 90 for index in range(60)]
    workspace.write_file("big.txt", "\n".join(lines) + "\n")
    expected = [{"path": "big.txt", "line": number, "snippet": line} for number, line in enumerate(lines, 1)]

    result = perform(environment, "search", {"pattern": "needle", "max_results": 50})
    assert result.ok, result.error
    output = result.output
    page = output["matches"]
    assert output["total_matches"] == len(expected)
    # 截断有说明：页被截短，并给出继续取回的游标
    assert output["truncated"] is True and output["next_cursor"]
    # 要的这一页（50 条）装不下：返回装得下的那些，再加一条就超过上限
    assert 1 < len(page) < 50
    assert page == expected[:len(page)]
    assert _page_size(page) <= limit < _page_size(expected[:len(page) + 1])

    # 挤出去的命中在下一页：连续取回，每一条恰好返回一次
    seen = [item["line"] for item in page]
    cursor = output["next_cursor"]
    while cursor:
        result = perform(environment, "search", {"pattern": "needle", "max_results": 50, "cursor": cursor})
        assert result.ok, result.error
        seen.extend(item["line"] for item in result.output["matches"])
        cursor = result.output["next_cursor"]
    assert seen == [item["line"] for item in expected]


def test_search_never_exposes_private_tree_content(tmp_path):
    workspace, environment = _environment(tmp_path)
    (workspace.root / ".checks" / "notes.txt").write_text("s3cr3t 私有回执\n", encoding="utf-8")
    result = perform(environment, "search", {"pattern": "s3cr3t"})
    assert result.ok, result.error
    assert result.output["matches"] == []
    assert result.output["total_matches"] == 0


