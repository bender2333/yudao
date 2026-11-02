import json

import pytest

from doc_consistency import index, scaffold
from doc_consistency.scan import scan_repo

WORKFLOW = "docs/agents/workflow.md"


def dead(root):
    model = scan_repo(root)
    atoms = scaffold.solve(scaffold.scaffold_facts(model, scaffold.load_labels(root), root).symbols, ["deadrefs.lp"])
    return {
        "skill": {t[1] for t in scaffold.pick(atoms, "dead_skill")},
        "label": {t[1] for t in scaffold.pick(atoms, "dead_label")},
        "path": {t[1] for t in scaffold.pick(atoms, "dead_path")},
    }


def test_dead_references(scaffold_repo):
    d = dead(scaffold_repo.path)
    assert d["skill"] == {"ghost", "ghost-skill"}
    assert d["label"] == {"no-such-label"}
    assert d["path"] == {"docs/agents/missing.md", "harness/tests/test_nope.py"}


def test_known_non_problems_are_not_reported(scaffold_repo):
    d = dead(scaffold_repo.path)
    everything = d["skill"] | d["label"] | d["path"]
    assert "loop" not in everything  # 内置技能
    assert "integration-results" not in everything  # 不是标签
    assert "scripts/vision.mjs" not in everything  # 相对所在技能目录
    assert ".tmp/out.json" not in everything  # gitignore 管着的位置
    assert "solo-worker" not in everything


def test_check_exits_zero_with_reminders_and_fails_on_broken_setup(scaffold_repo):
    rc, out = scaffold_repo.cli("check", check=False)
    assert rc == 0
    assert "docs/agents/missing.md" in out and "提醒共" in out
    # 缺标签快照：程序自身的问题，报错退出
    (scaffold_repo.path / ".doc-index" / "labels.json").unlink()
    rc, out = scaffold_repo.cli("check", check=False)
    assert rc != 0 and "refresh" in out


def test_role_table_must_match_data_file(scaffold_repo):
    text = scaffold_repo.read(WORKFLOW).replace("| 审查者 | 审查 | 不推送 |\n", "")
    scaffold_repo.write(WORKFLOW, text)
    rc, out = scaffold_repo.cli("scope", check=False)
    assert rc != 0 and "审查者" in out


def test_reading_scope_separates_must_read_from_reachable(scaffold_repo):
    _, facts, rows = scaffold.scope(scaffold_repo.path)
    by_role = {r[0]: r for r in rows}
    solo = by_role["solo 执行者"]
    assert ".claude/skills/solo-worker/SKILL.md" in solo[1]
    assert "docs/agents/shared-rules.md" in solo[1]
    # 「审查者读 reviewer」只对审查者说：链接可达，但不是 solo 执行者的必读
    assert ".claude/skills/reviewer/SKILL.md" not in solo[1] and ".claude/skills/reviewer/SKILL.md" in solo[2]
    # 「命令见」只是查阅，可达但不必读
    assert "docs/agents/other.md" not in solo[1] and "docs/agents/other.md" in solo[2]
    reviewer = by_role["审查者"]
    assert ".claude/skills/reviewer/SKILL.md" in reviewer[1]
    assert ".claude/skills/solo-worker/SKILL.md" not in reviewer[1]
    assert solo[3] < solo[4]


def row_id(model, title):
    return next(n.id for n in model.nodes.values() if n.kind == "row" and n.title == title and n.file == WORKFLOW)


def test_impact_of_one_table_row_only_touches_nodes_that_mention_it(scaffold_repo):
    root = scaffold_repo.path
    model = scan_repo(root)
    _, _, target, hits, must, link, unseen = scaffold.impact(root, row_id(model, "needs-triage"))
    files = {n.split("#", 1)[0] for n in hits}
    assert "docs/agents/mentions-waiting.md" not in files
    assert ".claude/skills/solo-worker/SKILL.md" in files and "CLAUDE.md" in files
    # 表里的另一行（waiting）和 needs-triage 这一行自己都不在内
    assert row_id(model, "waiting") not in hits and target not in hits
    # 按角色分组：solo 执行者读到 solo-worker 技能，所以那里的提到算必读
    assert any(n.startswith(".claude/skills/solo-worker/SKILL.md") for n in must["solo 执行者"])
    # 反过来：改 waiting 这一行，只牵动提到 waiting 的节点
    _, _, _, hits_w, *_ = scaffold.impact(root, row_id(model, "waiting"))
    assert {n.split("#", 1)[0] for n in hits_w} == {"docs/agents/mentions-waiting.md"}


def test_impact_of_whole_file_includes_references_to_it(scaffold_repo):
    _, _, _, hits, *_ = scaffold.impact(scaffold_repo.path, WORKFLOW)
    files = {n.split("#", 1)[0] for n in hits}
    assert ".claude/skills/solo-worker/SKILL.md" in files  # 链接引用
    assert "docs/agents/mentions-waiting.md" in files  # 提到 waiting
    assert not any(f == WORKFLOW for f in files)


def test_refresh_writes_snapshot_in_stable_form(scaffold_repo):
    names = ["b", "a"]
    scaffold_repo.write_labels(names)
    assert scaffold.load_labels(scaffold_repo.path) == {"a", "b"}
    data = json.loads(scaffold_repo.read(".doc-index/labels.json"))
    assert data["labels"] == ["a", "b"]


def test_check_reports_pending_from_scaffold_files(scaffold_repo):
    index.build(scaffold_repo.path)
    scaffold_repo.write("docs/agents/shared-rules.md", "# 共同规则\n\n改过的内容。\n")
    rc, out = scaffold_repo.cli("check")
    assert "待核对" in out and "CLAUDE.md" in out
    scaffold_repo.cli("confirm", "CLAUDE.md")
    scaffold_repo.cli("confirm", "AGENTS.md")
    rc, out = scaffold_repo.cli("check")
    assert "待核对（下游在脚手架文件里，上游变了）：0 条" in out
