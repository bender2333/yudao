import argparse
import subprocess
import sys
import time
from pathlib import Path

from . import graph, index, scaffold
from .rulefacts import canon as rf_canon, scan as rf_scan, view as rf_view
from .scan import is_scaffold


def repo_root(arg):
    if arg:
        return Path(arg).resolve()
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, check=True).stdout
    return Path(out.decode("utf-8").strip())


def cmd_build(root, args):
    t = time.time()
    s = index.build(root)
    print(f"索引已更新：{s['files']} 个文件，{s['nodes']} 个节点，{s['edges']} 条边；写入 {s['written']} 个索引文件，删除 {s['removed']} 个；用时 {time.time() - t:.1f} 秒")


def cmd_status(root, args):
    rows = index.status(root)
    for kind, nid in rows:
        print(f"{kind}  {nid}")
    print(f"共 {len(rows)} 个节点和索引不一致" if rows else "工作区和索引一致")


def cmd_who(root, args):
    target, rows = index.who(root, args.target)
    for path, lines, e in rows:
        where = f"{path}:{','.join(map(str, lines))}" if lines else path
        print(f"{where}  [{e['kind']}]  {e['src']}  ->  {e['dst']}")
    print(f"{target} 被 {len(rows)} 处引用")


def cmd_view(root, args):
    out, data = graph.view(root)
    print(f"已生成 {out}（{len(data['nodes'])} 个节点，{len(data['edges'])} 条边）")


def cmd_nodes(root, args):
    ids = index.list_nodes(root, args.keyword)
    print("\n".join(ids))
    print(f"共 {len(ids)} 个节点包含 {args.keyword!r}")


def cmd_refresh(root, args):
    names = scaffold.refresh(root)
    print(f"已保存 {len(names)} 个 GitHub 标签到 .doc-index/labels.json")


def cmd_check(root, args):
    lines, total = scaffold.check(root)
    print("\n".join(lines))


def cmd_pending(root, args):
    _, items = index.pending(root)
    for path, e, up in items:
        print(f"{path}  {e['src']}  [{e['kind']}]  引用的 {e['dst']} 变了")
    scope = "范围：上下游都不是记录文档，只算指向小节、表格行、总图的节或缝的引用"
    print(f"共 {len(items)} 条待核对（{scope}）" if items else f"没有待核对的引用（{scope}）")


def cmd_confirm(root, args):
    done = index.confirm(root, args.downstream, args.upstream)
    for e, up in done:
        print(f"已确认  {e['src']}  引用的 {e['dst']}")
    print(f"共确认 {len(done)} 条，记录追加在 .doc-index/confirmed.jsonl" if done else "没有符合的待核对项")


def cmd_scope(root, args):
    model, facts, rows = scaffold.scope(root)
    for role, must, link_only, chars_must, chars_reach in rows:
        print(f"【{role}】必读 {len(must)} 个文件 {chars_must} 字符；只是可达的另有 {len(link_only)} 个，合计可达 {chars_reach} 字符")
        for f in must:
            print(f"  必读  {f}  ({facts.sizes[f]} 字符)")
        if args.reach:
            for f in link_only:
                print(f"  可达  {f}")


def cmd_impact(root, args):
    model, facts, target, hits, must, link, unseen = scaffold.impact(root, args.target)

    def show(node):
        lines = scaffold.hit_lines(model, facts, node, hits[node])
        why = "、".join(sorted({("引用" if w == "ref" else "提到") + (f" {x}" if w != "ref" else "") for w, x in hits[node]}))
        where = f"{node.split('#', 1)[0]}:{','.join(map(str, lines))}" if lines else node.split("#", 1)[0]
        return f"{where}  {node}  [{why}]"

    print(f"目标：{target}；引用或提到它的节点共 {len(hits)} 个")
    for role, _ in facts.roles:
        if role in must or role in link:
            print(f"【{role}】必读范围里 {len(must.get(role, []))} 个，只是可达的 {len(link.get(role, []))} 个")
            for n in sorted(must.get(role, [])):
                print("  必读  " + show(n))
            for n in sorted(link.get(role, [])):
                print("  可达  " + show(n))
    if unseen:
        print(f"【没有角色读到】{len(unseen)} 个")
        for n in sorted(unseen):
            print("  " + show(n))


def cmd_rules(root, args):
    if args.rules_cmd == "canon":
        print("\n".join(rf_canon.format_canon(rf_canon.read_canon(root))))
    elif args.rules_cmd == "scan":
        print("\n".join(rf_scan.format_scan(root, args.sample)))
    else:
        out, data = rf_view.view(root)
        g = data["graph"]
        print(f"已生成 {out}（矩阵 {len(data['matrix'])} 行，规则图 {len(g['nodes'])} 个节点、{len(g['edges'])} 条边）")


COMMANDS = {
    "build": cmd_build,
    "status": cmd_status,
    "who": cmd_who,
    "view": cmd_view,
    "nodes": cmd_nodes,
    "refresh": cmd_refresh,
    "check": cmd_check,
    "pending": cmd_pending,
    "confirm": cmd_confirm,
    "scope": cmd_scope,
    "impact": cmd_impact,
    "rules": cmd_rules,
}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="doc-consistency", description="文档索引与脚手架线的一致性检查")
    ap.add_argument("--root", help="仓库根目录，默认取当前所在的 git 仓库")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", help="重建索引")
    sub.add_parser("status", help="工作区和索引比，哪些节点变了")
    p = sub.add_parser("who", help="谁引用了某个文件或小节")
    p.add_argument("target")
    p = sub.add_parser("nodes", help="按关键词列出节点名（who、impact、confirm 要写完整的节点名）")
    p.add_argument("keyword")
    sub.add_parser("view", help="生成离线图谱页面到 .tmp/doc-index/graph.html")
    sub.add_parser("refresh", help="用 gh label list 保存 GitHub 标签快照（其余命令都离线）")
    sub.add_parser("check", help="脚手架线检查，汇总提醒，永远以 0 退出；程序或规则出错才报错退出")
    sub.add_parser("pending", help="列出待核对：上游变了、下游没改也没确认")
    p = sub.add_parser("confirm", help="记录确认：下游看过上游的新版本，不用改")
    p.add_argument("downstream", help="下游文件或小节")
    p.add_argument("upstream", nargs="?", help="只确认指向这个上游的引用，不写则确认下游所有待核对项")
    p = sub.add_parser("scope", help="每个角色从入口出发的阅读范围")
    p.add_argument("--reach", action="store_true", help="同时列出只是可达的文件")
    p = sub.add_parser("impact", help="改了某个文件或小节，哪些节点引用或提到它，按角色分组")
    p.add_argument("target")
    p = sub.add_parser("rules", help="规则事实线（到第 2 步：读正本表格、粗筛盘点）")
    rs = p.add_subparsers(dest="rules_cmd", required=True)
    rs.add_parser("canon", help="把正本表格读成事实，列出附注、读不出的格子、一条事实两处正本、读不到正本的角色；永远以 0 退出")
    rs.add_parser("view", help="生成离线页面到 .tmp/doc-index/rulefacts.html：角色 × 规则矩阵与规则图")
    p = rs.add_parser("scan", help="粗筛与盘点：列出脚手架文件里像在复述规则的句子，分已是引用、能改成句式、不是规则事实三类；永远以 0 退出")
    p.add_argument("--sample", type=int, metavar="N", help="按固定种子随机抽 N 条候选（用来人工核对噪音率），格式相同")
    args = ap.parse_args(argv)
    root = repo_root(args.root)
    COMMANDS[args.cmd](root, args)


if __name__ == "__main__":
    sys.exit(main())
