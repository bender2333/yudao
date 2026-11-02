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


def test_code_html_is_outside_the_index(docs_repo):
    for rel in (
        "tools/doc-consistency/doc_consistency/assets/graph.html",
        "evals/scenarios/s1/reference/index.html",
        "evals/scenarios/s1/sub/page.html",
        "docs/prototypes/v1/index.html",
    ):
        docs_repo.write(rel, "<html><body><a href='../docs/design/other.md'>x</a></body></html>\n")
    docs_repo.write("docs/page.html", "<html><body>文档页面</body></html>\n")
    docs_repo.commit("代码里的 HTML")
    index.build(docs_repo.path)
    files = set(index.load_index(docs_repo.path))
    assert "docs/page.html" in files and "docs/architecture.html" in files
    assert not [f for f in files if f.startswith(("evals/", "docs/prototypes/")) or f.endswith("assets/graph.html")]


def test_link_target_is_not_in_hash_but_display_text_is(docs_repo):
    docs_repo.write("docs/design/c.md", "# 丙\n\n内容。\n")
    docs_repo.write("docs/design/user.md", "# 引用者\n\n## 做法\n\n见 [另一份的细节](other.md)。\n\n也见 <a href=\"other.md\">网页写法</a>。\n")
    docs_repo.commit("链接")
    index.build(docs_repo.path)
    uid = "docs/design/user.md#引用者 > 做法"

    def snap():
        d = index.load_index(docs_repo.path)["docs/design/user.md"]
        return (
            {n["id"]: n["hash"] for n in d["nodes"]},
            {(e["dst"], e["kind"]) for e in d["edges"] if e["src"] == uid},
        )

    h0, e0 = snap()
    assert ("docs/design/other.md", "link") in e0
    # 只改链接地址：hash 不变，边的目标跟着变
    docs_repo.write("docs/design/user.md", docs_repo.read("docs/design/user.md").replace("(other.md)", "(c.md)").replace('href="other.md"', 'href="c.md"'))
    assert index.status(docs_repo.path) == []
    index.build(docs_repo.path)
    h1, e1 = snap()
    assert h1 == h0
    assert ("docs/design/c.md", "link") in e1 and ("docs/design/other.md", "link") not in e1
    # 改显示文字：hash 变
    docs_repo.write("docs/design/user.md", docs_repo.read("docs/design/user.md").replace("另一份的细节", "改了的文字"))
    assert index.status(docs_repo.path) == [("改动", uid)]


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
    assert "共 1 条待核对" in out
    rc, out = docs_repo.cli("confirm", "docs/design/context.md")
    assert "共确认 1 条" in out
    assert "没有待核对" in docs_repo.cli("pending")[1]
    lines = docs_repo.read(".doc-index/confirmed.jsonl").strip().split("\n")
    assert len(lines) == 1
    # 重建以后仍然没有待核对，确认记录只追加
    docs_repo.cli("build")
    assert "没有待核对" in docs_repo.cli("pending")[1]
    assert docs_repo.read(".doc-index/confirmed.jsonl").strip().split("\n") == lines
    # 上游再改一次，又出现
    docs_repo.write("docs/design/other.md", docs_repo.read("docs/design/other.md").replace("改过的细节", "又改了"))
    assert "共 1 条待核对" in docs_repo.cli("pending")[1]


def test_record_docs_never_take_part_in_pending(docs_repo):
    docs_repo.write("docs/decision.md", "# 决策\n\n## 某一条\n\n内容。\n")
    docs_repo.write("claude_jour.md", "# 日记\n\n## 今天\n\n内容。\n")
    docs_repo.write("docs/adr/0001-x.md", "# ADR\n\n## 决定\n\n内容。\n")
    # 普通文档引用记录文档的小节（记录文档作上游）；记录文档引用普通文档的小节（记录文档作下游）
    docs_repo.write(
        "docs/design/user.md",
        "# 引用者\n\n## 做法\n\n见 `docs/decision.md`「某一条」与 `docs/adr/0001-x.md`「决定」。\n",
    )
    docs_repo.write("docs/adr/0002-y.md", "# ADR 2\n\n## 决定\n\n依据 `docs/design/other.md`「细节」与 `claude_jour.md`「今天」。\n")
    docs_repo.commit("记录文档")
    docs_repo.cli("build")
    for rel in ("docs/decision.md", "docs/adr/0001-x.md", "claude_jour.md"):
        docs_repo.write(rel, docs_repo.read(rel) + "新追加的一行。\n")
    docs_repo.write("docs/design/other.md", docs_repo.read("docs/design/other.md").replace("第一处细节", "改过的细节"))
    items = index.pending(docs_repo.path)[1]
    # 记录文档作上游的、作下游的都不算；剩下的只有普通文档之间那一条
    assert {(e["src"], e["dst"]) for _, e, _ in items} == {
        ("docs/design/context.md#上下文设计 > 方案", "docs/design/other.md#另一份 > 细节")
    }
    # 边仍在图谱里，who 照常能查
    _, rows = index.who(docs_repo.path, "docs/decision.md#决策 > 某一条")
    assert [r[0] for r in rows] == ["docs/design/user.md"]
    _, rows = index.who(docs_repo.path, "docs/design/other.md#另一份 > 细节")
    assert "docs/adr/0002-y.md" in [r[0] for r in rows]


def test_references_to_a_whole_file_do_not_take_part_in_pending(docs_repo):
    docs_repo.write("docs/design/whole.md", "# 整份引用\n\n## 做法\n\n见 [另一份](other.md)，也见 `docs/architecture.html`。\n")
    docs_repo.commit("整份文件的引用")
    docs_repo.cli("build")
    docs_repo.write("docs/design/other.md", docs_repo.read("docs/design/other.md").replace("第一处细节", "改过的细节"))
    arch = docs_repo.read("docs/architecture.html")
    assert "同样的事件重放出同样的请求" in arch
    docs_repo.write("docs/architecture.html", arch.replace("同样的事件重放出同样的请求", "同样的事件重放出同样的请求（改）"))
    items = index.pending(docs_repo.path)[1]
    # whole.md 只有指向整份文件的引用，不出现；context.md 指向小节的引用（other.md 的小节、总图的缝）出现
    assert {e["src"].split("#", 1)[0] for _, e, _ in items} == {"docs/design/context.md"}
    assert {e["dst"] for _, e, _ in items} == {"docs/design/other.md#另一份 > 细节", "docs/architecture.html#s4 > 装配"}
    # 但整份文件的引用仍在索引里
    _, rows = index.who(docs_repo.path, "docs/design/other.md")
    assert "docs/design/whole.md" in [r[0] for r in rows]


def test_new_edge_gets_baseline_not_pending(docs_repo):
    index.build(docs_repo.path)
    docs_repo.write("docs/design/other.md", docs_repo.read("docs/design/other.md").replace("第一处细节", "改过的细节"))
    docs_repo.write("docs/design/new.md", "# 新\n\n见 `docs/design/other.md`。\n")
    index.build(docs_repo.path)
    # 新文档的边以建索引时的上游为基线；老的边仍然待核对
    srcs = {e["src"] for _, e, _ in index.pending(docs_repo.path)[1]}
    assert srcs == {"docs/design/context.md#上下文设计 > 方案"}
