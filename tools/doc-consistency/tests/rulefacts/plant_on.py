"""规则事实线第 4 步：植入矛盾验收的共用代码，也是一次性脚本。

把 planted.json 的 20 条植入某个提交的临时副本（git worktree），跑 rules check，打印找回表。
test_planted.py（当前 HEAD，pytest）和本文件（任意提交）共用这里的函数。

  uv run --project tools/doc-consistency python tools/doc-consistency/tests/rulefacts/plant_on.py <提交>

提交里没有锚点的句子记「锚点不在」，不算找回也不算失败，单独列。副本用完 git worktree remove --force 删掉，仓库本身不动。
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

TOOL = Path(__file__).resolve().parents[2]
REPO = TOOL.parent.parent
PLANTED = Path(__file__).with_name("planted.json")
TIERS = ("A", "B", "C")
ENV = {**os.environ, "PYTHONUTF8": "1"}

sys.path.insert(0, str(TOOL))
from doc_consistency.rulefacts import compare  # noqa: E402

KIND_OF_LABEL = {label: kind for kind, label in compare.KINDS}


def load():
    return json.loads(PLANTED.read_text(encoding="utf-8"))["条目"]


def git(*args, cwd=REPO):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, env=ENV)
    if r.returncode:
        raise RuntimeError(f"git {' '.join(args)} 失败：{r.stderr.decode('utf-8', 'replace')}")
    return r.stdout.decode("utf-8")


def add_worktree(commit, dest):
    git("worktree", "add", "--detach", str(dest), commit)


def remove_worktree(dest):
    try:
        git("worktree", "remove", "--force", str(dest))
    finally:
        git("worktree", "prune")


# ---------- 植入 ----------


def sentence_of(ins):
    """这一处插入的句子：「行」里第一个非空行。"""
    return next(t for t in ins["行"] if t.strip())


def plant(root, entries, strict=True):
    """按清单植入。返回 {id: {"状态": "植入" | "锚点不在" | "锚点不唯一", "位置": [(文件, 行号, 句子, 本处插入的各行号)]}}。

    锚点是含该文本的那一行，插在它后面。找不到（或不止一行含它）：strict 时报错，不猜；否则这一条整条不植入
    （一条有两处插入的，缺一处就整条不植入，免得只植一半）。
    """
    files, state = {}, {}

    def lines_of(rel):
        if rel not in files:
            raw = (Path(root) / rel).read_bytes().decode("utf-8")
            eol = "\r\n" if "\r\n" in raw else "\n"
            files[rel] = (raw.split(eol), eol)
        return files[rel][0]

    todo = defaultdict(list)  # 文件 -> [(锚点所在行下标, 先后, 条目 id, 第几处, 行)]
    order = 0
    for e in entries:
        found, status = [], "植入"
        for k, ins in enumerate(e["插入"]):
            try:
                text = lines_of(ins["文件"])
            except FileNotFoundError:
                hits = []
            else:
                hits = [i for i, t in enumerate(text) if ins["锚点"] in t]
            if len(hits) != 1:
                status = "锚点不在" if not hits else "锚点不唯一"
                if strict:
                    raise AssertionError(f"{e['id']}：{ins['文件']} 里含锚点「{ins['锚点']}」的行有 {len(hits)} 行，要恰好 1 行")
                break
            found.append((ins["文件"], hits[0], k, ins))
        state[e["id"]] = {"状态": status, "位置": []}
        if status != "植入":
            continue
        for rel, idx, k, ins in found:
            order += 1
            todo[rel].append((idx, order, e["id"], k, ins["行"]))
    placed = defaultdict(dict)  # id -> {第几处: (文件, 各行号, 句子)}
    for rel, items in todo.items():
        text, eol = files[rel]
        out, last = [], 0
        for idx, _, eid, k, block in sorted(items):
            out += text[last : idx + 1]
            last = idx + 1
            start = len(out) + 1  # 块的第一行在新文件里的行号
            out += block
            nums = [start + j for j, t in enumerate(block) if t.strip()]
            placed[eid][k] = (rel, nums, next(t for t in block if t.strip()))
        out += text[last:]
        (Path(root) / rel).write_bytes(eol.join(out).encode("utf-8"))
    for eid, d in placed.items():
        state[eid]["位置"] = [(rel, nums[0], sent, nums) for _, (rel, nums, sent) in sorted(d.items())]
    return state


# ---------- 跑 rules check 与读输出 ----------


def run_check(root, *extra):
    r = subprocess.run(
        [sys.executable, "-m", "doc_consistency", "--root", str(root), "rules", "check", *extra],
        cwd=TOOL,
        capture_output=True,
        env=ENV,
    )
    assert r.returncode == 0, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")
    return r.stdout


HEAD_RX = re.compile(r"^== (.+?)：(\d+) 条 ==$")
RESTATE_RX = re.compile(r"^复述 (\S+?):(\d+)  (.*)$")
HIT_RX = re.compile(r"^(\S+?):(\d+)  \[(.*?)\]  (.*)$")
ITEM_RX = re.compile(r"^    (\d+): (.*)$")


def parse_output(raw):
    """rules check 的输出 -> {"conflicts": [{kind, nodes: [(文件, 行, 原句)], canon: [正本行], why}], "unparsed": [(文件, 行, 标签, 原句)], "items": {(文件, 条目行): 引导句那一行}}。
    提醒里引导句带的条目缩进列在它下面，条目那几行也算在提醒里（挂在引导句下）。"""
    conflicts, unparsed, items, kind, cur, in_un = [], [], {}, None, None, False
    for line in raw.decode("utf-8").splitlines():
        m = HEAD_RX.match(line)
        if m:
            kind = KIND_OF_LABEL.get(m.group(1))
            in_un = False
            continue
        if line.startswith("== 像在说规则但解析不了"):
            in_un, kind = True, None
            continue
        if in_un:
            m = HIT_RX.match(line)
            if m:
                unparsed.append((m.group(1), int(m.group(2)), m.group(3), m.group(4)))
            else:
                m = ITEM_RX.match(line)
                if m and unparsed:
                    items[(unparsed[-1][0], int(m.group(1)))] = unparsed[-1][1]
            continue
        if not kind:
            continue
        m = RESTATE_RX.match(line)
        if m:
            if cur is None:
                cur = {"kind": kind, "nodes": [], "canon": [], "why": ""}
            cur["nodes"].append((m.group(1), int(m.group(2)), m.group(3)))
        elif line.startswith("  正本 ") and cur is not None:
            cur["canon"].append(line.strip())
        elif line.startswith("  差在哪：") and cur is not None:
            cur["why"] = line.strip()
            conflicts.append(cur)
            cur = None
    return {"conflicts": conflicts, "unparsed": unparsed, "items": items}


def run_all_tiers(root):
    """三档的提醒清单各跑一遍（--all）。返回 ({档: 原始输出}, {档: 解析结果})。"""
    raws = {t: run_check(root, "--all", "--tier", t) for t in TIERS}
    return raws, {t: parse_output(r) for t, r in raws.items()}


# ---------- 核对 ----------


def judge(entries, state, parsed, canon_text=None):
    """每条的找回与否。parsed 是 run_all_tiers 的第二项；canon_text 是这个提交上 rules canon 的输出：照句式写的期望对着的正本事实不在里面，
    就记「正本不在」（句子对着的那条规则在这个提交里还没有，不算找回也不算失败）。返回 [{id, 批次, 状态, 找回(True/False/None), 位置, 报成, 档}]。"""
    rows = []
    cp = parsed["A"]
    for e in entries:
        st = state[e["id"]]
        row = {"e": e, "状态": st["状态"], "位置": st["位置"], "找回": None, "报成": "", "档": {}}
        rows.append(row)
        if st["状态"] != "植入":
            continue
        sent = {(f, ln) for f, ln, _, _ in st["位置"]}
        everywhere = {(f, n) for f, _, _, nums in st["位置"] for n in nums}
        seen = [c for c in cp["conflicts"] if sent & {(f, ln) for f, ln, _ in c["nodes"]}]
        as_kinds = sorted({c["kind"] for c in seen})
        if e["批次"] == "照句式写":
            want = e["期望"]
            ok = [
                c
                for c in seen
                if c["kind"] == want["类别"]
                and sent <= {(f, ln) for f, ln, _ in c["nodes"]}
                and (not want.get("正本") or any(want["正本"] in x for x in c["canon"]))
            ]
            row["找回"] = bool(ok)
            row["报成"] = "、".join(compare.LABEL[k] for k in as_kinds) if as_kinds else "没报矛盾"
            if not ok and canon_text is not None and want.get("正本") and want["正本"] not in canon_text:
                row["状态"], row["找回"] = "正本不在", None
                row["报成"] = f"这个提交的正本里没有「{want['正本']}」，复述对不上任何一行"
            if not seen:
                tags = [t for f, ln, t, _ in cp["unparsed"] if (f, ln) in everywhere]
                row["报成"] += "；" + (f"在提醒里 [{tags[0]}]" if tags else "也不在提醒里（句子没成候选）")
        else:
            for t in TIERS:
                inn = {(f, ln) for f, ln, _, _ in parsed[t]["unparsed"]}
                inn_items = set(parsed[t]["items"])
                # 每一处插入的各行里，有一行在提醒里就算这一处在提醒里（引导句带条目时，提醒挂在引导句那一行）；
                # 只是挂在别的引导句下面的条目也算，但记下来（row["挂"]）
                row["档"][t] = all(any((f, n) in inn or (f, n) in inn_items for n in nums) for f, _, _, nums in st["位置"])
                if t == "A":
                    row["挂"] = row["档"]["A"] and not all(any((f, n) in inn for n in nums) for f, _, _, nums in st["位置"])
            row["找回"] = row["档"]["A"]
            if seen:
                row["报成"] = "解析成功，报成矛盾：" + "、".join(compare.LABEL[k] for k in as_kinds)
            elif row["档"]["A"]:
                tags = [t for f, ln, t, _ in cp["unparsed"] if (f, ln) in everywhere]
                if row.get("挂"):
                    leads = sorted({f"{f}:{cp['items'][(f, n)]}" for f, _, _, nums in st["位置"] for n in nums if (f, n) in cp["items"]})
                    tags = ["挂在引导句下，引导句 " + "、".join(leads)] + tags
                row["报成"] = "提醒 [" + "；".join(tags) + "]"
            else:
                row["报成"] = "不在提醒里（粗筛没选上，或解析成功没报矛盾）"
    return rows


def render(rows):
    """找回表（文本）。"""
    out = []
    for batch in ("照句式写", "随手写"):
        mine = [r for r in rows if r["e"]["批次"] == batch]
        planted = [r for r in mine if r["状态"] == "植入"]
        got = sum(1 for r in planted if r["找回"])
        miss = [r for r in mine if r["状态"] != "植入"]
        why = "、".join(sorted({r["状态"] for r in miss}))
        head = f"== {batch}：找回 {got}/{len(planted)}" + (f"（另有 {len(miss)} 条{why}，不计）" if miss else "")
        nested = sum(1 for r in planted if r.get("挂"))
        if nested:
            head += f"，其中 {nested} 条只是挂在别的引导句的提醒下面（自己单独成候选的 {got - nested} 条）"
        if batch == "随手写" and planted:
            head += "；按档：" + "，".join(f"{t} {sum(1 for r in planted if r['档'].get(t))}/{len(planted)}" for t in TIERS)
        out.append(head + " ==")
        for r in mine:
            e = r["e"]
            if r["状态"] == "锚点不在" or r["状态"] == "锚点不唯一":
                where = "；".join(f"{i['文件']}（锚点「{i['锚点'][:20]}」）" for i in e["插入"])
                out.append(f"{e['id']}  {r['状态']}  {where}")
                continue
            if r["状态"] == "正本不在":
                out.append(f"{e['id']}  正本不在  " + "；".join(f"{f}:{ln}" for f, ln, _, _ in r["位置"]) + f"  {r['报成']}")
                out.append(f"      {r['位置'][0][2]}")
                continue
            pos = "；".join(f"{f}:{ln}" for f, ln, _, _ in r["位置"])
            tiers = ""
            if batch == "随手写":
                tiers = "  档 " + "".join(t if r["档"][t] else "-" for t in TIERS)
            out.append(f"{e['id']}  {'找回' if r['找回'] else '没找回'}  {pos}  报成：{r['报成']}{tiers}")
            for _, _, sent, _ in r["位置"]:
                out.append(f"      {sent}")
    return out


def baseline_conflicts(parsed):
    """干净检出里本来就有的矛盾（类别, 原句们），植入前后对比用。"""
    return sorted((c["kind"], tuple(t for _, _, t in c["nodes"])) for c in parsed["conflicts"])


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        raise SystemExit("用法：plant_on.py <提交>")
    commit = git("rev-parse", "--verify", argv[0] + "^{commit}").strip()
    subject = git("log", "-1", "--format=%h %ad %s", "--date=short", commit).strip()
    entries = load()
    with tempfile.TemporaryDirectory(prefix="plant-on-") as tmp:
        clean, planted = Path(tmp) / "clean", Path(tmp) / "planted"
        add_worktree(commit, clean)
        add_worktree(commit, planted)
        try:
            state = plant(planted, entries, strict=False)
            try:
                raws, parsed = run_all_tiers(planted)
            except AssertionError as err:  # 这个提交上没有正本表（比如 workflow.md 收拢之前的提交），rules check 本身跑不了
                lines = str(err).strip().splitlines()
                raise SystemExit(f"提交 {subject}：rules check 在这个提交上跑不了，换一个提交：{lines[-1] if lines else err}")
            again = run_check(planted, "--all", "--tier", "A")
            canon_text = subprocess.run(
                [sys.executable, "-m", "doc_consistency", "--root", str(planted), "rules", "canon"], cwd=TOOL, capture_output=True, env=ENV
            ).stdout.decode("utf-8")
            _, parsed_clean = run_all_tiers(clean)
            rows = judge(entries, state, parsed, canon_text)
        finally:
            remove_worktree(planted)
            remove_worktree(clean)
    print(f"提交 {subject}")
    first = raws["A"].decode("utf-8").splitlines()[0]
    print(first)
    print("\n".join(render(rows)))
    print(f"两次输出逐字节相同：{'是' if again == raws['A'] else '否'}")
    # 干净副本里这些句子一条也不该出现
    cl = parsed_clean["A"]
    gone = [
        s
        for r in rows
        if r["状态"] == "植入"
        for _, _, s, _ in r["位置"]
        if any(s == t for c in cl["conflicts"] for _, _, t in c["nodes"]) or any(s == t for _, _, _, t in cl["unparsed"])
    ]
    print(f"干净副本里出现植入句：{len(gone)} 条")
    print(f"矛盾条数：干净副本 {len(cl['conflicts'])}，植入后 {len(parsed['A']['conflicts'])}（多 {len(parsed['A']['conflicts']) - len(cl['conflicts'])}）")


if __name__ == "__main__":
    main()
