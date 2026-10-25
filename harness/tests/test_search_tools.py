from harness.environment import LocalEnvironment
from harness.tests.helpers import perform
from harness.workspace import Workspace


def _environment(root):
    workspace = Workspace(root)
    return workspace, LocalEnvironment(workspace)


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


def test_search_never_exposes_private_tree_content(tmp_path):
    workspace, environment = _environment(tmp_path)
    (workspace.root / ".checks" / "notes.txt").write_text("s3cr3t 私有回执\n", encoding="utf-8")
    result = perform(environment, "search", {"pattern": "s3cr3t"})
    assert result.ok, result.error
    assert result.output["matches"] == []
    assert result.output["total_matches"] == 0


