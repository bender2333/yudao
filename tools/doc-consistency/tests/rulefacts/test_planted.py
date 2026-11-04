"""规则事实线第 4 步：植入矛盾验收（方案第 5 节）。

在当前 HEAD 的临时副本（git worktree）里按 planted.json 植入 20 条，再在副本上用真实命令行跑 rules check：
  照句式写 10 条：至少 8 条被报成期望的那类矛盾，且报的位置是植入处（文件:行），对着期望的那条正本事实；
  随手写 10 条：至少 8 条出现在「像在说规则但解析不了」里（rules check --all 把提醒全部打印）；
  同样的输入跑两次，输出逐字节相同；
  不植入的干净副本里，这些植入句一条也不出现。
每条的找回与否会打印（pytest -s 能看到）。别的提交上同一张表用 plant_on.py <提交>。
"""

import pytest
from plant_on import add_worktree, judge, load, plant, remove_worktree, render, run_all_tiers, run_check, baseline_conflicts


@pytest.fixture
def copies(tmp_path):
    """干净副本与植入副本，都检出当前 HEAD；用完删掉。"""
    clean, planted = tmp_path / "clean", tmp_path / "planted"
    add_worktree("HEAD", clean)
    try:
        add_worktree("HEAD", planted)
    except BaseException:
        remove_worktree(clean)
        raise
    try:
        yield clean, planted
    finally:
        remove_worktree(planted)
        remove_worktree(clean)


def test_planted_contradictions_are_found(copies):
    clean, planted = copies
    entries = load()
    assert len(entries) == 20 and sum(1 for e in entries if e["批次"] == "照句式写") == 10

    state = plant(planted, entries, strict=True)  # 锚点找不到就在这里报错，不猜
    assert all(s["状态"] == "植入" for s in state.values())

    raws, parsed = run_all_tiers(planted)
    again = run_check(planted, "--all", "--tier", "A")
    _, parsed_clean = run_all_tiers(clean)
    rows = judge(entries, state, parsed)
    print()
    print("\n".join(render(rows)))

    by = lambda batch: [r for r in rows if r["e"]["批次"] == batch]
    got_s = [r["e"]["id"] for r in by("照句式写") if r["找回"]]
    got_r = [r["e"]["id"] for r in by("随手写") if r["找回"]]
    print(f"照句式写找回 {len(got_s)}/10 {got_s}；随手写提醒找回 {len(got_r)}/10 {got_r}")
    assert len(got_s) >= 8, f"照句式写只找回 {len(got_s)}/10：{got_s}"
    assert len(got_r) >= 8, f"随手写只在提醒里找回 {len(got_r)}/10：{got_r}"

    # 同样的输入跑两次，输出逐字节相同
    assert again == raws["A"]

    # 干净副本里，植入句一条也不出现，期望的矛盾和提醒也就都不出现
    cl = parsed_clean["A"]
    sentences = {s for r in rows for _, _, s, _ in r["位置"]}
    in_conflict = {t for c in cl["conflicts"] for _, _, t in c["nodes"]}
    in_reminder = {t for _, _, _, t in cl["unparsed"]}
    assert not sentences & in_conflict and not sentences & in_reminder
    # 植入以后多出来的矛盾，就是植入引起的：干净副本里本来就有的，植入后还在
    before, after = baseline_conflicts(cl), baseline_conflicts(parsed["A"])
    assert not set(before) - set(after)
    assert len(after) > len(before)
