"""里程碑的工单记录：抓取一个里程碑每张工单的数据，算出每张一行的记录与汇总。

两步分开（沿用 B6 的做法）：
- `collect`：按里程碑标题从 GitHub 取工单、标签时间线、对应的 PR，写成数据文件；
- `report`：只读数据文件，算出记录，写中文报告；给出上一个里程碑的数据文件时，逐项比较。

不导入 `harness`，不读取 omp 的运行目录，不解析执行者的模型。
"""

import argparse
import json
import os
import re
import statistics
import sys
from datetime import datetime, timezone

# 抓取沿用 B6 的 gh 调用封装（失败就地抛出）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DELIVERY_PREFIX = "DELIVERY:"
BUG_LABEL = "bug"
IN_PROGRESS_LABEL = "in-progress"
ARCHITECT_LABEL = "needs-architect"
CLOSING_REFERENCE = re.compile(r"\b(?:closes|fixes|resolves)\s+#(\d+)", re.IGNORECASE)

# 不算手写的文件（运行配置第 7 节「工单大小的上限」）：生成的客户端类型、接口快照、
# 事件序列基准与日记
GENERATED_PREFIXES = ("client/src/renderer/src/api/generated/",
                      "harness/tests/event_sequences/",
                      "agents_jour/")
GENERATED_FILES = ("harness/tests/openapi/openapi.json",
                   "harness/tests/prompt_snapshot.json")
# 基准变化数：事件序列基准目录下的文件，加上提示词快照
BASELINE_PREFIXES = ("harness/tests/event_sequences/",)
BASELINE_FILES = ("harness/tests/prompt_snapshot.json",)


# ---------------------------------------------------------------- 抓取

def closing_issues(body):
    """PR 正文里 `Closes #<编号>` 点名的工单编号。"""
    return sorted({int(number) for number in CLOSING_REFERENCE.findall(body or "")})


def collect(milestone, data_path):
    """抓取一个里程碑的全部工单与它们的 PR，写出数据文件。"""
    import collect as b6  # B6 的 gh 封装，与本文件同目录
    import subprocess
    import time

    class gh:
        # gh 偶尔网络失败：每次调用最多重试 3 次，仍失败就抛出
        @staticmethod
        def _retry(function, args):
            for attempt in range(3):
                try:
                    return function(args)
                except subprocess.CalledProcessError:
                    if attempt == 2:
                        raise
                    time.sleep(2)

        @staticmethod
        def _gh(args):
            return gh._retry(b6._gh, args)

        @staticmethod
        def _gh_items(args):
            return gh._retry(b6._gh_items, args)

    issues = gh._gh(["issue", "list", "--state", "all", "--limit", "1000", "--json",
                     "number,title,milestone,state,stateReason,createdAt,closedAt,"
                     "labels,url"])
    issues = sorted([issue for issue in issues
                     if (issue.get("milestone") or {}).get("title") == milestone],
                    key=lambda issue: issue["number"])
    if not issues:
        raise RuntimeError("没有标题为「%s」的里程碑，或者里程碑里没有工单" % milestone)
    numbers = {issue["number"] for issue in issues}
    stored_issues = []
    for issue in issues:
        timeline = gh._gh_items([
            "api", "repos/{owner}/{repo}/issues/%d/timeline" % issue["number"],
            "--paginate", "-q",
            '.[] | select(.event == "labeled" or .event == "unlabeled" '
            'or .event == "closed" or .event == "reopened") '
            "| {event: .event, created_at: .created_at, actor: .actor.login, "
            "label: .label.name} | tojson"])
        stored_issues.append({
            "number": issue["number"], "title": issue["title"],
            "state": issue["state"], "state_reason": issue.get("stateReason"),
            "created_at": issue["createdAt"], "closed_at": issue.get("closedAt"),
            "labels": [label["name"] for label in issue.get("labels") or []],
            "url": issue["url"], "timeline": timeline})
    pulls = gh._gh(["pr", "list", "--state", "all", "--limit", "2000", "--json",
                    "number,body,state,createdAt,mergedAt,headRefName"])
    stored_pulls = []
    for pull in sorted(pulls, key=lambda item: item["number"]):
        closes = [number for number in closing_issues(pull.get("body")) if number in numbers]
        if not closes:
            continue
        detail = gh._gh(["pr", "view", str(pull["number"]), "--json",
                         "files,reviews,comments"])
        stored_pulls.append({
            "number": pull["number"], "closes": closes, "state": pull["state"],
            "created_at": pull["createdAt"], "merged_at": pull.get("mergedAt"),
            "branch": pull["headRefName"],
            "files": [item["path"] for item in detail.get("files") or []],
            # 评论只留首行：轮数只看首行是否为 DELIVERY:
            "comments": [{"created_at": item["createdAt"],
                          "author": (item.get("author") or {}).get("login"),
                          "first_line": _first_line(item.get("body"))}
                         for item in detail.get("comments") or []],
            "reviews": [{"author": (item.get("author") or {}).get("login"),
                         "state": item["state"],
                         "submitted_at": item.get("submittedAt")}
                        for item in detail.get("reviews") or []]})
    data = {"milestone": milestone, "collected_at": _now(),
            "issues": stored_issues, "pull_requests": stored_pulls}
    os.makedirs(os.path.dirname(os.path.abspath(data_path)), exist_ok=True)
    with open(data_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return data


def _first_line(body):
    lines = (body or "").strip().splitlines()
    return lines[0].strip() if lines else ""


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- 计算（只读数据文件）

def _parse(stamp):
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def is_generated(path):
    return path in GENERATED_FILES or path.startswith(GENERATED_PREFIXES)


def is_baseline(path):
    return path in BASELINE_FILES or path.startswith(BASELINE_PREFIXES)


def compute_issue(issue, pulls):
    """一张工单的一行记录。pulls 是数据文件里点名关闭这张工单的全部 PR。"""
    pulls = sorted(pulls, key=lambda pull: pull["number"])
    labels = issue["labels"]
    timeline = issue["timeline"]
    delivery_per_pr = {
        pull["number"]: sum(1 for comment in pull["comments"]
                            if comment["first_line"].startswith(DELIVERY_PREFIX))
        for pull in pulls}
    reviews = [review for pull in pulls for review in pull["reviews"]
               if review["state"] in ("APPROVED", "CHANGES_REQUESTED")]
    reviews.sort(key=lambda review: review.get("submitted_at") or "")
    changes_requested = sum(1 for review in reviews if review["state"] == "CHANGES_REQUESTED")
    final_review = ("无审查" if not reviews else
                    "批准" if reviews[-1]["state"] == "APPROVED" else "要求修改")
    merged_times = [pull["merged_at"] for pull in pulls if pull.get("merged_at")]
    first_merge = min(merged_times) if merged_times else None
    last_merge = max(merged_times) if merged_times else None
    started = [event["created_at"] for event in timeline
               if event["event"] == "labeled" and event["label"] == IN_PROGRESS_LABEL]
    elapsed = None
    if started and last_merge:
        elapsed = round((_parse(last_merge) - _parse(min(started))).total_seconds() / 60)
    files = sorted({path for pull in pulls for path in pull["files"]})
    reopened = sum(1 for event in timeline
                   if event["event"] == "reopened" and first_merge
                   and event["created_at"] >= first_merge)
    return {
        "number": issue["number"], "title": issue["title"],
        "state": issue["state"],
        "kind": "修复类" if BUG_LABEL in labels else "实现类",
        "pull_requests": [pull["number"] for pull in pulls],
        "merged_pull_requests": [pull["number"] for pull in pulls if pull.get("merged_at")],
        "rounds": sum(delivery_per_pr.values()),
        "rounds_per_pr": delivery_per_pr,
        "changes_requested": changes_requested,
        "final_review": final_review,
        "elapsed_minutes": elapsed,
        "files_total": len(files),
        "files_handwritten": sum(1 for path in files if not is_generated(path)),
        "baseline_changes": sum(1 for path in files if is_baseline(path)),
        "architect_interventions": sum(1 for event in timeline
                                       if event["event"] == "labeled"
                                       and event["label"] == ARCHITECT_LABEL),
        "reopened_after_merge": reopened,
        "closed_without_pr": issue["state"] == "CLOSED" and not pulls,
    }


def _distribution(values):
    if not values:
        return {"count": 0}
    return {"count": len(values), "min": min(values), "median": statistics.median(values),
            "max": max(values)}


def summarize(records):
    total = len(records)
    open_count = sum(1 for record in records if record["state"] != "CLOSED")
    with_rounds = [record["rounds"] for record in records if record["rounds"] > 0]
    elapsed = [record["elapsed_minutes"] for record in records
               if record["elapsed_minutes"] is not None]
    histogram = {}
    for rounds in with_rounds:
        histogram[str(rounds)] = histogram.get(str(rounds), 0) + 1
    interventions = sum(record["architect_interventions"] for record in records)
    return {
        "issues": total, "open": open_count, "closed": total - open_count,
        "with_delivery": len(with_rounds),
        "average_rounds": round(sum(with_rounds) / len(with_rounds), 2) if with_rounds else None,
        "rounds": _distribution(with_rounds),
        "rounds_histogram": dict(sorted(histogram.items(), key=lambda pair: int(pair[0]))),
        "elapsed_minutes": _distribution(elapsed),
        "architect_interventions": interventions,
        "architect_interventions_per_issue": round(interventions / total, 2) if total else None,
        "issues_with_architect": sum(1 for r in records if r["architect_interventions"]),
        "fix_issues": sum(1 for record in records if record["kind"] == "修复类"),
        "fix_ratio": (round(sum(1 for r in records if r["kind"] == "修复类") / total, 3)
                      if total else None),
        "changes_requested": sum(record["changes_requested"] for record in records),
        "reopened_after_merge": sum(record["reopened_after_merge"] for record in records),
        "closed_without_pr": sum(1 for record in records if record["closed_without_pr"]),
        "baseline_changes": sum(record["baseline_changes"] for record in records),
        "files_handwritten_median": (statistics.median(
            [r["files_handwritten"] for r in records if r["pull_requests"]])
            if any(r["pull_requests"] for r in records) else None),
    }


def compute(data):
    """数据文件 → 每张工单一行与汇总。"""
    pulls_by_issue = {}
    for pull in data["pull_requests"]:
        for number in pull["closes"]:
            pulls_by_issue.setdefault(number, []).append(pull)
    records = [compute_issue(issue, pulls_by_issue.get(issue["number"], []))
               for issue in data["issues"]]
    return {"milestone": data["milestone"], "collected_at": data["collected_at"],
            "issues": records, "summary": summarize(records)}


# 比较表的行：(名称, 汇总里的取值函数)
COMPARE_ROWS = (
    ("工单数", lambda s: s["issues"]),
    ("其中未关闭", lambda s: s["open"]),
    ("有交付的工单数", lambda s: s["with_delivery"]),
    ("平均轮数", lambda s: s["average_rounds"]),
    ("轮数中位数", lambda s: s["rounds"].get("median")),
    ("轮数最大值", lambda s: s["rounds"].get("max")),
    ("耗时中位数（分钟）", lambda s: s["elapsed_minutes"].get("median")),
    ("耗时最大值（分钟）", lambda s: s["elapsed_minutes"].get("max")),
    ("要求修改的合计次数", lambda s: s["changes_requested"]),
    ("架构师介入合计次数", lambda s: s["architect_interventions"]),
    ("架构师介入，平均每张工单", lambda s: s["architect_interventions_per_issue"]),
    ("修复类比例", lambda s: s["fix_ratio"]),
    ("手写文件数中位数", lambda s: s["files_handwritten_median"]),
    ("基准变化数合计", lambda s: s["baseline_changes"]),
    ("合并以后重新打开合计次数", lambda s: s["reopened_after_merge"]),
    ("关闭时没有 PR 的工单数", lambda s: s["closed_without_pr"]),
)


def compare(current, previous):
    """两个里程碑的汇总逐项并列：[(名称, 上一个, 这一个)]。"""
    return [(name, getter(previous["summary"]), getter(current["summary"]))
            for name, getter in COMPARE_ROWS]


# ---------------------------------------------------------------- 报告

def _text(value):
    return "无" if value is None else str(value)


def build_report(result, previous=None):
    summary = result["summary"]
    lines = ["# 里程碑工单记录：%s" % result["milestone"], "",
             "截止时间：%s（UTC）。里程碑内共 %d 张工单，其中 %d 张还没有关闭，%d 张已关闭。"
             % (result["collected_at"], summary["issues"], summary["open"], summary["closed"]),
             "数据来自 GitHub 的工单时间线与 PR，由 `evals/baseline/milestone.py` 计算；"
             "字段口径见工单 #602。", ""]
    if summary["open"]:
        lines += ["里程碑还没有关闭，下面的数字只覆盖截止时间之前已经出现的记录；"
                  "没有交付的工单不计入平均轮数和耗时。", ""]
    lines += ["## 汇总", "",
              "| 项目 | 数值 |", "| --- | --- |",
              "| 有交付（至少一条 DELIVERY）的工单 | %d |" % summary["with_delivery"],
              "| 平均轮数 | %s |" % _text(summary["average_rounds"]),
              "| 轮数分布（轮数：工单数） | %s |" % (
                  "、".join("%s 轮：%d" % pair for pair in summary["rounds_histogram"].items())
                  or "无"),
              "| 轮数 最小 / 中位 / 最大 | %s |" % _spread(summary["rounds"]),
              "| 耗时（分钟）最小 / 中位 / 最大 | %s |" % _spread(summary["elapsed_minutes"]),
              "| 架构师介入合计 | %d 次，涉及 %d 张工单 |" % (
                  summary["architect_interventions"], summary["issues_with_architect"]),
              "| 架构师介入，平均每张工单 | %s |" % _text(summary["architect_interventions_per_issue"]),
              "| 修复类工单 | %d 张，占 %s |" % (summary["fix_issues"], _percent(summary["fix_ratio"])),
              "| 要求修改合计 | %d 次 |" % summary["changes_requested"],
              "| 基准变化数合计 | %d |" % summary["baseline_changes"],
              "| 合并以后重新打开合计 | %d 次 |" % summary["reopened_after_merge"],
              "| 关闭时没有 PR 的工单 | %d 张 |" % summary["closed_without_pr"], ""]
    if previous is not None:
        lines += ["## 与上一个里程碑比较", "",
                  "上一个：%s（截止 %s）。" % (previous["milestone"], previous["collected_at"]), "",
                  "| 项目 | 上一个 | 这一个 |", "| --- | --- | --- |"]
        for name, before, after in compare(result, previous):
            lines.append("| %s | %s | %s |" % (name, _text(before), _text(after)))
        lines.append("")
    lines += ["## 每张工单", "",
              "| 工单 | 类型 | 状态 | PR | 轮数 | 要求修改 | 最后审查 | 耗时（分钟） | "
              "文件（全部/手写） | 基准变化 | 架构师介入 | 合并后重开 |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for record in result["issues"]:
        pulls = "、".join("#%d" % number for number in record["pull_requests"]) or "无"
        state = "关闭（无 PR）" if record["closed_without_pr"] else (
            "已关闭" if record["state"] == "CLOSED" else "未关闭")
        lines.append("| #%d %s | %s | %s | %s | %d | %d | %s | %s | %d/%d | %d | %d | %d |" % (
            record["number"], record["title"].replace("|", "/"), record["kind"], state, pulls,
            record["rounds"], record["changes_requested"], record["final_review"],
            _text(record["elapsed_minutes"]), record["files_total"],
            record["files_handwritten"], record["baseline_changes"],
            record["architect_interventions"], record["reopened_after_merge"]))
    lines += ["", "## 口径", "",
              "- 类型：带 `bug` 标签为修复类，其余为实现类。",
              "- 轮数：点名关闭这张工单的全部 PR 上，首行为 `DELIVERY:` 的评论数。",
              "- 要求修改：这些 PR 上 CHANGES_REQUESTED 审查的次数；最后审查取时间最晚的批准或要求修改。",
              "- 耗时：第一次加 `in-progress` 到最后一个 PR 合并，没有合并的不计。",
              "- 手写文件：不算生成的客户端类型、接口快照、事件序列基准、提示词快照与日记。",
              "- 基准变化：`harness/tests/event_sequences/` 下的文件加 `harness/tests/prompt_snapshot.json`。",
              "- 架构师介入：加 `needs-architect` 标签的次数。",
              "- 合并后重开：在第一个 PR 合并之后出现的 reopened 事件数。", ""]
    return "\n".join(lines)


def _spread(distribution):
    if not distribution.get("count"):
        return "无"
    return "%s / %s / %s" % (distribution["min"], distribution["median"], distribution["max"])


def _percent(ratio):
    return "无" if ratio is None else "%.1f%%" % (ratio * 100)


# ---------------------------------------------------------------- 命令行

def _load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def report(data_path, report_path, previous_path=None):
    result = compute(_load(data_path))
    previous = compute(_load(previous_path)) if previous_path else None
    text = build_report(result, previous)
    os.makedirs(os.path.dirname(os.path.abspath(report_path)), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return result


def main():
    parser = argparse.ArgumentParser(description="里程碑的工单记录")
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("collect", help="按里程碑标题抓取数据文件")
    fetch.add_argument("--milestone", required=True, help="GitHub 里程碑的完整标题")
    fetch.add_argument("--data", required=True, help="数据文件（.json）的输出位置")
    calc = sub.add_parser("report", help="只读数据文件，写中文报告")
    calc.add_argument("--data", required=True, help="数据文件（.json）")
    calc.add_argument("--report", required=True, help="中文报告（.md）的输出位置")
    calc.add_argument("--previous", help="上一个里程碑的数据文件；给出时报告逐项比较")
    args = parser.parse_args()
    if args.command == "collect":
        data = collect(args.milestone, args.data)
        print("抓取工单 %d 张，PR %d 个：%s"
              % (len(data["issues"]), len(data["pull_requests"]), args.data))
    else:
        result = report(args.data, args.report, args.previous)
        print("工单 %d 张，未关闭 %d 张：%s"
              % (result["summary"]["issues"], result["summary"]["open"], args.report))


if __name__ == "__main__":
    main()
