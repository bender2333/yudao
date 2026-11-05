"""Yudao 对单个 agent 的对照入口（`docs/design/evaluation-scenarios.md` 「Yudao 对单个 agent」）。

读同一场景的两份结果文件——Yudao 一侧与 OpenCode 一侧——按 D38 的 N-G1 给出「高于」
「没有达到」「受阻」之一，写出机器可读的对照结果（JSON）与中文报告。判定与逐次并排
的表在 `yudao_compare.compare_sides`，报告由 `yudao_report.write_side_report` 写出。
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yudao_compare
import yudao_report


def load_result(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Yudao 对 OpenCode 的对照（评测场景设计「Yudao 对单个 agent」）")
    parser.add_argument("--yudao", required=True, help="Yudao 一侧的结果文件（JSON）")
    parser.add_argument("--opencode", required=True, help="OpenCode 一侧的结果文件（JSON）")
    parser.add_argument("--result", help="对照结果（JSON）的路径")
    parser.add_argument("--report", help="中文报告的路径")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    comparison = yudao_compare.compare_sides(load_result(args.yudao),
                                             load_result(args.opencode))
    if args.result:
        yudao_report.write_result(comparison, args.result)
    if args.report:
        yudao_report.write_side_report(comparison, args.report)
    print(comparison["verdict_label"]
          + ("：" + comparison["block_reason"] if comparison.get("block_reason") else ""),
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
