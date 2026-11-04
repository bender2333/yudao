"""本体检查的入口：python -m doc_consistency.ontology <命令>（在仓库根目录用 uv run --project tools/doc-consistency）。

命令：
  check     本体自检：M3 符合它自己，canon.json、roles.json 编译出的种类、关系、实例、别名自洽
  layering  分层：内核模块点名部门或脚手架实例的地方，基线里的只计数，新出现的逐条列出；--all 全列
  facts     打印编译出的本体事实（给人看，也给以后的规则用）
  baseline  把现在的分层命中记进 data/ontology/layering-baseline.json（只追加）

永远以 0 退出；程序或规则自己出错才报错退出。只读，不改任何文档或代码。
"""

import argparse
import json
import subprocess
from pathlib import Path

from ..scaffold import DATA, pick, solve
from .compile import compile_repo
from .layering import layering_facts

BASELINE = DATA / "ontology" / "layering-baseline.json"
ALLOW = DATA / "ontology" / "layering-allow.json"
SELF_RULES = ["ontology/layers.lp", "ontology/meta.lp", "ontology/selfcheck.lp"]

CHECKS = [
    ("m3_bad_owner", "M3：字段的主人不是登记过的元种类"),
    ("m3_bad_card", "M3：单多值不是登记过的取值"),
    ("kind_bad_layer", "种类的层没有登记"),
    ("kind_two_layers", "种类在两层里"),
    ("rel_bad_domain", "关系的起点种类不存在"),
    ("rel_bad_range", "关系的终点种类不存在"),
    ("rel_bad_card", "关系的单多值不是登记过的取值"),
    ("rel_card_mismatch", "同名关系在两张表里单多值不一致"),
    ("rel_range_mismatch", "同名关系的终点种类不一致"),
    ("inst_bad_kind", "实例的种类没有登记"),
    ("name_two_kinds", "同一个名字是两个种类的实例"),
    ("alias_clash", "一个别名指两个东西"),
    ("alias_shadows", "别名和另一个种类的实例同名（一个词指两样东西；可能有意，比如载体和事实同名，要人看）"),
    ("alias_dangling", "别名指向的东西不是任何种类的实例"),
    ("group_bad_member", "合称的成员不是角色"),
]
GAPS = [("rel_no_domain", "待补：关系所在的表没有声明 node，起点种类空着")]


def repo_root(arg):
    if arg:
        return Path(arg).resolve()
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, check=True).stdout
    return Path(out.decode("utf-8").strip())


def selfcheck(facts):
    atoms = solve(facts.symbols, SELF_RULES)
    return {name: pick(atoms, name) for name, _ in CHECKS + GAPS}


def format_selfcheck(facts, found):
    kinds = sorted(facts.kinds)
    lines = [
        f"本体第一块：{len(kinds)} 个种类，{len(facts.rels)} 条关系声明（来自 canon.json、roles.json，层都是脚手架）",
        "种类：" + "、".join(kinds),
    ]
    n = 0
    for name, title in CHECKS:
        rows = found[name]
        n += len(rows)
        if rows:
            lines.append(f"\n{title}（{len(rows)}）")
            lines += ["  " + " | ".join(str(x) for x in r) for r in rows]
    lines.append(f"\n自检问题共 {n} 条")
    for name, title in GAPS:
        rows = found[name]
        if rows:
            lines.append(f"\n{title}（{len(rows)}）")
            lines += ["  " + " | ".join(str(x) for x in r) for r in rows]
    return "\n".join(lines)


def load_list(path):
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))["items"]


def key(row):
    path, _line, inst, _kind, scope = row
    return (path, scope, inst)


def layering(root):
    facts = compile_repo(root)
    scaffold_names = {str(a.arguments[0].string) for a in facts.symbols if a.name == "instance_of"}
    syms = set(facts.symbols) | layering_facts(root, scaffold_names)
    atoms = solve(syms, SELF_RULES + ["ontology/layering.lp"])
    return pick(atoms, "layer_violation"), pick(atoms, "scaffold_leak")


def format_layering(viol, leak, show_all):
    base = {(b["path"], b["scope"], b["instance"]) for b in load_list(BASELINE)}
    allow = {(a["path"], a["scope"], a["instance"]): a["why"] for a in load_list(ALLOW)}
    lines = []
    for title, rows in (("内核模块点名下层实例", viol), ("内核模块点名脚手架的实例", leak)):
        new = [r for r in rows if key(r) not in base and key(r) not in allow]
        lines.append(f"{title}：共 {len(rows)} 处，白名单 {sum(key(r) in allow for r in rows)}，基线 {sum(key(r) in base for r in rows)}，新 {len(new)}")
        for r in rows if show_all else new:
            tag = "白名单：" + allow[key(r)] if key(r) in allow else ("基线" if key(r) in base else "新")
            path, line, inst, kind, scope = r
            lines.append(f"  {path}:{line}  {scope}  「{inst}」是{kind}的实例  [{tag}]")
    return "\n".join(lines)


def write_baseline(viol, leak):
    old = load_list(BASELINE)
    have = {(b["path"], b["scope"], b["instance"]) for b in old}
    add = []
    for r in viol + leak:
        k = key(r)
        if k not in have:
            have.add(k)
            add.append({"path": k[0], "scope": k[1], "instance": k[2]})
    data = {
        "说明": "分层命中的基线：只追加，用 baseline 命令写。键是文件、所在函数、实例名，不记行号（行号会挪）。有理由的例外不放这里，放 layering-allow.json 并写理由。",
        "items": old + add,
    }
    BASELINE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(old), len(add)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m doc_consistency.ontology")
    ap.add_argument("--root")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    lp = sub.add_parser("layering")
    lp.add_argument("--all", action="store_true")
    sub.add_parser("facts")
    sub.add_parser("baseline")
    args = ap.parse_args(argv)
    root = repo_root(args.root)
    if args.cmd == "check":
        facts = compile_repo(root)
        print(format_selfcheck(facts, selfcheck(facts)))
    elif args.cmd == "facts":
        for s in sorted(compile_repo(root).symbols, key=str):
            print(f"{s}.")
    elif args.cmd == "layering":
        print(format_layering(*layering(root), args.all))
    elif args.cmd == "baseline":
        o, a = write_baseline(*layering(root))
        print(f"基线原有 {o} 条，新增 {a} 条")


if __name__ == "__main__":
    main()
