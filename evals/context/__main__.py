"""命令行入口：

    python -m evals.context measure --db <events.sqlite> [--artifacts <目录>] --out <报告前缀>
    python -m evals.context replay  --db <events.sqlite> --rules <规则文件> --out <报告前缀>
    python -m evals.context verify  --db <events.sqlite>
    python -m evals.context counterfactual --db <events.sqlite> --sample 24 --out <结果文件>

`measure` 不需要模型与凭据；`counterfactual` 需要 YUDAO_EVAL_BASE_URL、YUDAO_EVAL_API_KEY、
YUDAO_EVAL_MODEL 三个环境变量，凭据只从环境变量读，不写进任何文件。
"""

from __future__ import annotations

import argparse
import os
import sys

DEFAULT_DB = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Yudao", "events.sqlite")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.context", description="上下文装配的离线回放与测量")
    sub = parser.add_subparsers(dest="command", required=True)

    measure = sub.add_parser("measure", help="测现状：每一步的召回与浪费")
    measure.add_argument("--db", default=DEFAULT_DB)
    measure.add_argument("--artifacts", default=None)
    measure.add_argument("--out", default="docs/evaluation/context-assembly-2026-10-29")

    replay = sub.add_parser("replay", help="用新视图重放，比较与记录的差异")
    replay.add_argument("--db", default=DEFAULT_DB)
    replay.add_argument("--artifacts", default=None)
    replay.add_argument("--rules", default="evals/context/rule-set.json")
    replay.add_argument("--out", default="docs/evaluation/context-assembly-replay-2026-10-29")

    verify = sub.add_parser("verify", help="核对每一步的视图能从事件与工件一字不差地重建")
    verify.add_argument("--db", default=DEFAULT_DB)
    verify.add_argument("--artifacts", default=None)

    counter = sub.add_parser("counterfactual", help="抽样若干步，旧视图与新视图各问一次模型")
    counter.add_argument("--db", default=DEFAULT_DB)
    counter.add_argument("--artifacts", default=None)
    counter.add_argument("--rules", default="evals/context/rule-set.json")
    counter.add_argument("--sample", type=int, default=24)
    counter.add_argument("--temperature", type=float, default=0.0)
    counter.add_argument("--out", default="docs/evaluation/context-assembly-counterfactual-2026-10-29.json")
    counter.add_argument("--seed", type=int, default=912)

    cost = sub.add_parser("cost", help="按前缀缓存计价，折算每套规则的费用")
    cost.add_argument("--db", default=DEFAULT_DB)
    cost.add_argument("--artifacts", default=None)
    cost.add_argument("--rules", default="evals/context/rule-set.json")
    cost.add_argument("--title", default="")
    cost.add_argument("--out", default=None)

    sweep = sub.add_parser("sweep", help="扫描一个参数的取值，看省量与召回")
    sweep.add_argument("--db", default=DEFAULT_DB)
    sweep.add_argument("--artifacts", default=None)
    sweep.add_argument("--rules", default="evals/context/rule-set.json")
    sweep.add_argument("--param", default="tool_result_keep_tokens")
    sweep.add_argument("--values", default="40000,24000,16000,8000,4000,2000")
    sweep.add_argument("--out", default=None)

    args = parser.parse_args(argv)
    if args.command == "measure":
        from . import measure as module
        data = module.run_measure(args.db, args.artifacts)
        module.write_report(data, args.out + ".json", args.out + ".md")
        print(module.to_markdown(data))
        return 0
    if args.command == "replay":
        from . import replay as module
        report = module.run_replay(args.db, args.artifacts, args.rules)
        module.write_report(report, args.out + ".json", args.out + ".md")
        print(module.to_markdown(report))
        return 0
    if args.command == "verify":
        from . import verify as module
        return module.main(args.db, args.artifacts)
    if args.command == "counterfactual":
        from . import counterfactual as module
        return module.main(args.db, args.artifacts, args.rules, args.sample,
                           args.temperature, args.out, args.seed)
    if args.command == "cost":
        from . import cost as module
        data = module.run_cost(args.db, args.artifacts, args.rules)
        print(module.to_markdown(data, args.title))
        if args.out:
            module.write_report(data, args.out + ".json", args.out + ".md", args.title)
        return 0
    if args.command == "sweep":
        from . import sweep as module
        values = []
        for part in args.values.split(","):
            part = part.strip()
            values.append(int(part) if part.isdigit() else part)
        data = module.sweep(args.db, args.artifacts, args.rules, args.param, values)
        print(module.to_markdown(data))
        if args.out:
            import json
            os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
            with open(args.out + ".json", "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=1, sort_keys=True)
            with open(args.out + ".md", "w", encoding="utf-8") as handle:
                handle.write(module.to_markdown(data))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
