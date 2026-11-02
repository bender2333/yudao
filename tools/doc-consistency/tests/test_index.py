from doc_consistency import index

from conftest import Repo


def nodes_of(root, path):
    return index.load_index(root)[path]["nodes"]


def test_crlf_and_lf_have_same_hash(tmp_path):
    text = "# 标题\n\n第一段。\n\n## 小节\n\n内容 `docs/x.md`。\n"
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a, b = Repo(tmp_path / "a"), Repo(tmp_path / "b")
    a.write("docs/t.md", text, newline="\n")
    b.write("docs/t.md", text, newline="\r\n")
    a.commit()
    b.commit()
    index.build(a.path)
    index.build(b.path)
    na = [(n["id"], n["hash"]) for n in nodes_of(a.path, "docs/t.md")]
    nb = [(n["id"], n["hash"]) for n in nodes_of(b.path, "docs/t.md")]
    assert na == nb


def test_same_title_sections_get_distinct_ids(docs_repo):
    index.build(docs_repo.path)
    ids = [n["id"] for n in nodes_of(docs_repo.path, "docs/design/other.md")]
    assert "docs/design/other.md#另一份 > 细节" in ids
    assert "docs/design/other.md#另一份 > 细节 (2)" in ids


def test_architecture_seams_and_position_line(docs_repo):
    index.build(docs_repo.path)
    nodes = nodes_of(docs_repo.path, "docs/architecture.html")
    assert sum(1 for n in nodes if n["kind"] == "section") == 6
    assert sum(1 for n in nodes if n["kind"] == "seam") == 13
    assert {n["id"] for n in nodes if n["kind"] == "section"} == {f"docs/architecture.html#s{i}" for i in range(1, 7)}
    edges = index.load_index(docs_repo.path)["docs/design/context.md"]["edges"]
    dsts = {(e["dst"], e["kind"]) for e in edges}
    assert ("docs/architecture.html#s4 > 装配", "map-position") in dsts
    # markdown 链接指向小节，反引号路径指向文件
    assert ("docs/design/other.md#另一份 > 细节", "link") in dsts
    assert ("docs/design/other.md", "code-path") in dsts


def test_build_is_deterministic(docs_repo):
    index.build(docs_repo.path)
    first = docs_repo.index_snapshot()
    stats = index.build(docs_repo.path)
    assert stats["written"] == 0
    assert docs_repo.index_snapshot() == first


def test_adding_first_line_changes_only_that_files_index(docs_repo):
    index.build(docs_repo.path)
    before = docs_repo.index_snapshot()
    old = {n["id"]: n["hash"] for n in nodes_of(docs_repo.path, "docs/design/other.md")}
    text = docs_repo.read("docs/design/other.md")
    docs_repo.write("docs/design/other.md", "开头加的一行\n" + text)
    assert index.status(docs_repo.path) == [("新增", "docs/design/other.md#(开头)")]
    index.build(docs_repo.path)
    after = docs_repo.index_snapshot()
    changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
    assert changed == {"files/docs/design/other.md.json"}
    new = {n["id"]: n["hash"] for n in nodes_of(docs_repo.path, "docs/design/other.md")}
    # 只多出开头一节（文件自己的 hash 当然变了），原有的小节 hash 一个也没变
    assert set(new) - set(old) == {"docs/design/other.md#(开头)"}
    assert all(new[k] == v for k, v in old.items() if k != "docs/design/other.md")


def test_who_gives_lines(docs_repo):
    index.build(docs_repo.path)
    target, rows = index.who(docs_repo.path, "docs/architecture.html#s4 > 装配")
    assert [(r[0], r[1]) for r in rows] == [("docs/design/context.md", [3])]
    _, rows = index.who(docs_repo.path, "docs/design/other.md#另一份 > 细节")
    assert [(r[0], r[1]) for r in rows] == [("docs/design/context.md", [7])]
    _, rows = index.who(docs_repo.path, "docs/design/other.md")
    assert len(rows) == 2


def test_pending_after_upstream_change_then_downstream_edit(docs_repo):
    index.build(docs_repo.path)
    assert index.pending(docs_repo.path)[1] == []
    docs_repo.write("docs/design/other.md", docs_repo.read("docs/design/other.md").replace("第一处细节", "改过的细节"))
    items = index.pending(docs_repo.path)[1]
    assert {e["src"] for _, e, _ in items} == {"docs/design/context.md#上下文设计 > 方案"}
    # 改下游：处理完
    docs_repo.write("docs/design/context.md", docs_repo.read("docs/design/context.md") + "补了一句。\n")
    assert index.pending(docs_repo.path)[1] == []


def test_pending_after_upstream_change_then_confirm(docs_repo):
    index.build(docs_repo.path)
    docs_repo.write("docs/design/other.md", docs_repo.read("docs/design/other.md").replace("第一处细节", "改过的细节"))
    rc, out = docs_repo.cli("pending")
    assert "共 2 条待核对" in out
    rc, out = docs_repo.cli("confirm", "docs/design/context.md")
    assert "共确认 2 条" in out
    assert "没有待核对" in docs_repo.cli("pending")[1]
    lines = docs_repo.read(".doc-index/confirmed.jsonl").strip().split("\n")
    assert len(lines) == 2
    # 重建以后仍然没有待核对，确认记录只追加
    docs_repo.cli("build")
    assert "没有待核对" in docs_repo.cli("pending")[1]
    assert docs_repo.read(".doc-index/confirmed.jsonl").strip().split("\n") == lines
    # 上游再改一次，又出现
    docs_repo.write("docs/design/other.md", docs_repo.read("docs/design/other.md").replace("改过的细节", "又改了"))
    assert "共 2 条待核对" in docs_repo.cli("pending")[1]


def test_new_edge_gets_baseline_not_pending(docs_repo):
    index.build(docs_repo.path)
    docs_repo.write("docs/design/other.md", docs_repo.read("docs/design/other.md").replace("第一处细节", "改过的细节"))
    docs_repo.write("docs/design/new.md", "# 新\n\n见 `docs/design/other.md`。\n")
    index.build(docs_repo.path)
    # 新文档的边以建索引时的上游为基线；老的边仍然待核对
    srcs = {e["src"] for _, e, _ in index.pending(docs_repo.path)[1]}
    assert srcs == {"docs/design/context.md#上下文设计 > 方案"}
