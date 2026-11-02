from browser_check import open_graph


def test_graph_page_opens_offline_in_a_real_browser(docs_repo, tmp_path):
    docs_repo.write("docs/design/alone.md", "# 无关的文档\n\n没有引用任何东西。\n")
    docs_repo.write("docs/design/alone2.md", "# 另一份无关的\n\n见 `docs/design/alone.md`。\n")
    docs_repo.commit("无关的文档")
    docs_repo.cli("build")
    docs_repo.cli("view")
    page = docs_repo.path / ".tmp" / "doc-index" / "graph.html"
    res = open_graph(page, tmp_path / "shots", pick="docs/design/context.md")
    assert res["errors"] == []
    assert res["external"] == []
    # 展开总图：6 个节、13 道缝
    assert res["arch_children"] == {"sections": 6, "seams": 13}
    # 点一份文档：它引用的和引用它的被高亮，其余变淡
    assert res["highlight"]["up"] >= 1
    assert res["highlight"]["dim"] > 0
    assert (tmp_path / "shots" / "graph.png").stat().st_size > 1000
