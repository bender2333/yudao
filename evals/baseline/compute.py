import argparse
import json
import re
import statistics
from datetime import datetime, timezone

# 审查轮数：review-failed 的次数加一（工单 #345 的口径）
REVIEW_FAILED_LABEL = "review-failed"

# 集成层评论的首行是判定与提交号，两种写法：带计数（竖线分隔）与不带计数
INTEGRATION_HEADER = re.compile(
    r"^INTEGRATION:\s+(PASS|FAIL)\s+([0-9a-f]{7,40})"
    r"(?:\s*\|\s*(.*))?$")

# 集成层失败评论里点名的工单（#123）；「PR #251」写的是合并请求编号，不作数
ISSUE_REFERENCE = re.compile(r"(?<!PR )#(\d{2,4})\b")
COMMIT_REFERENCE = re.compile(r"\b([0-9a-f]{7,40})\b")

# 阶段父工单自身的编号不作为归因对象
STAGE_PARENT = 9

# 分句里出现这些说法时，该分句点名的工单或提交是修复方，不是引入失败的一方。
# 集成层评论的常见写法：「修复工单 #285，已派发」「#285 修复以后……全部消失」
# 「#136 合并以前」「#269 第 2 轮的交付已经改正这一处」「由 #219 修正」。
FIX_SIDE_MARKERS = ("修复", "改正", "修正", "重写了", "已生效", "没有再出现",
                    "在审查", "按用户指示", "先等待", "等待合并", "暂停合并",
                    "重新运行通过", "连续 4 次通过", "并入", "排在最前",
                    "上一批", "合并以后", "合并以前", "起点")

# 只是列举这一批合并了哪些工单（不写原因），不是引入失败的一方
BATCH_MARKERS = ("本批合并", "本批包括", "下一批", "这一批", "这批")

# 集成层评论的句子边界与分句边界
SENTENCE_BREAK = r"[。\n]"
CLAUSE_BREAK = r"[；，：:,]"

# 括号里的内容是补充说明或与别的工单比较，不作归因
PARENTHETICAL = re.compile(r"（[^）]*）|\([^)]*\)")


def parse_integration(comment):
    """一条阶段父工单评论解析成集成层记录；不是集成层评论时返回 None。"""
    lines = [line.strip() for line in comment.get("body", "").splitlines()]
    lines = [line for line in lines if line and line != "@"]
    if not lines:
        return None
    matched = INTEGRATION_HEADER.match(lines[0])
    if not matched:
        return None
    return {"created_at": comment.get("created_at"),
            "verdict": matched.group(1),
            "commit": matched.group(2),
            "counts": (matched.group(3) or "").strip(),
            "body": comment.get("body", "")}


def integration_runs(stage_comments):
    """阶段父工单评论里的集成层记录，按时间排序。"""
    records = [parse_integration(comment) for comment in stage_comments]
    return sorted([record for record in records if record],
                  key=lambda record: record["created_at"])


def attribution_clauses(record):
    """集成层评论拆成句子与分句，标出每句点名的是引入方还是修复方。

    整句只列举这一批合并了哪些工单时不作数（「本批合并的 4 个：#295、#242…」）。
    剩下的句子按分句判定：分句里有修复类说法（「修复工单 #285」）时，这一分句点名的
    工单或提交都算修复方；没有则算引入失败的一方。括号里的补充说明与比较不算点名，
    判定与提交号本身也不算。
    """
    clauses = []
    for sentence in re.split(SENTENCE_BREAK, record.get("body", "")):
        if any(marker in sentence for marker in BATCH_MARKERS):
            continue
        # 先去掉括号里的补充说明，否则括号内的逗号会把括号拆成两半
        for piece in re.split(CLAUSE_BREAK, PARENTHETICAL.sub(" ", sentence)):
            piece = piece.strip()
            if not piece or piece == "@" or piece.startswith("INTEGRATION:"):
                continue
            issues = ISSUE_REFERENCE.findall(piece)
            commits = COMMIT_REFERENCE.findall(piece)
            if not issues and not commits:
                continue
            culprits = not any(marker in piece for marker in FIX_SIDE_MARKERS)
            clauses.append({"text": piece, "side": "引入方" if culprits else "修复方",
                            "issues": [int(number) for number in issues],
                            "commits": [commit for commit in commits
                                        if commit != record.get("commit")]})
    return clauses


def label_events(issue, label):
    """工单上某个标签被加上与去掉的时间点。"""
    added, removed = [], []
    for event in issue.get("timeline", []):
        if event.get("label") != label:
            continue
        if event["event"] == "labeled":
            added.append(event["created_at"])
        elif event["event"] == "unlabeled":
            removed.append(event["created_at"])
    return sorted(added), sorted(removed)


def review_rounds(issue):
    """审查轮数：review-failed 的次数加一。"""
    added, _removed = label_events(issue, REVIEW_FAILED_LABEL)
    return len(added) + 1


def delivery_rounds(issue):
    """交付评论里写明的轮数（DELIVERY: 第 k 轮），作为交叉核对。"""
    rounds = []
    for comment in issue.get("comments", []):
        lines = comment.get("body", "").lstrip().splitlines()
        if not lines:
            continue
        matched = re.match(r"^DELIVERY:\s*第\s*(\d+)\s*轮", lines[0].strip())
        if matched:
            rounds.append(int(matched.group(1)))
    return rounds


def stalled_reason(issue):
    """搁置的原因：工单标 ready-for-human 时紧随其后的评论。"""
    added, _removed = label_events(issue, "ready-for-human")
    if not added:
        return None
    since = added[0]
    for comment in issue.get("comments", []):
        if comment.get("created_at", "") >= since:
            return {"since": since,
                    "comments": [{"at": comment.get("created_at"),
                                  "text": comment.get("body", "").strip()}]}
    return {"since": since, "comments": []}


def first_in_progress(issue):
    """第一次进入 in-progress 的时刻；没有时返回 None。"""
    added, _removed = label_events(issue, "in-progress")
    return added[0] if added else None


def merged_pull_requests(issue_number, pull_requests):
    """对应这个工单的合并请求。"""
    result = []
    for pull in pull_requests:
        closed = [ref.get("number")
                  for ref in (pull.get("closingIssuesReferences") or [])]
        if issue_number in closed:
            result.append(pull)
    return result


def merged_at(issue_number, pull_requests):
    """工单对应的合并请求里最早的一次合并时间。"""
    times = [pull["mergedAt"] for pull in merged_pull_requests(issue_number,
                                                               pull_requests)]
    return min(times) if times else None


def issue_usage(issue_number, runs):
    """工单关联的执行者与审查者运行的用量汇总。"""
    mine = [run for run in runs if run["issue"] == issue_number]
    usage = {"executor_runs": 0, "reviewer_runs": 0, "requests": 0,
             "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
             "cache_write_tokens": 0, "total_tokens": 0, "cost": 0.0,
             "models": {}, "runs": []}
    for run in sorted(mine, key=lambda item: item["file"]):
        usage["runs"].append({"file": run["file"], "role": run["role"],
                              "round": run["round"], "requests": run["requests"],
                              "total_tokens": run["total_tokens"],
                              "exit_code": run.get("exit_code")})
        if run["role"] == "omp":
            usage["executor_runs"] += 1
        else:
            usage["reviewer_runs"] += 1
        usage["requests"] += run["requests"]
        for key in ("input_tokens", "output_tokens", "cache_read_tokens",
                    "cache_write_tokens", "total_tokens"):
            usage[key] += run[key]
        usage["cost"] += run["cost"]
        for model, entry in run["models"].items():
            target = usage["models"].setdefault(model, {"requests": 0,
                                                         "total_tokens": 0,
                                                         "cost": 0.0})
            target["requests"] += entry["requests"]
            target["total_tokens"] += entry["total_tokens"]
            target["cost"] += entry["cost"]
    return usage


def _issues_of_commit(short_commit, pull_requests):
    """短提交号对应的合并请求关闭的工单。"""
    for pull in pull_requests:
        oid = (pull.get("mergeCommit") or {}).get("oid", "")
        if oid.startswith(short_commit):
            return [ref.get("number")
                    for ref in (pull.get("closingIssuesReferences") or [])]
    return []


def failure_attribution(integration, pull_requests, issue_numbers):
    """每条集成层失败归因到哪些工单。

    引入失败的一侧：评论里以引入方写法点名的工单，以及能对上合并请求合并提交的
    提交号（这条评论自身的集成提交不算）。评论把点名全部写在修复一侧或只写处理办法
    时定位不到引入方，这条失败记为未归因，不摊到同批的其它工单。
    """
    attribution = {}
    for record in integration:
        if record["verdict"] != "FAIL":
            continue
        clauses = attribution_clauses(record)
        culprits = [clause for clause in clauses if clause["side"] == "引入方"]
        named = sorted({number for clause in culprits for number in clause["issues"]
                        if number in issue_numbers and number != STAGE_PARENT})
        by_commit = sorted({number for clause in culprits
                            for commit in clause["commits"]
                            for number in _issues_of_commit(commit, pull_requests)
                            if number in issue_numbers and number != STAGE_PARENT})
        targets = sorted(set(named) | set(by_commit))
        attribution[record["commit"]] = {
            "commit": record["commit"], "created_at": record["created_at"],
            "attribution": "评论点名" if targets else "未归因",
            "issues": targets,
            "evidence": " ".join(clause["text"] for clause in culprits)
                        or attribution_text(record)}
    return attribution


def compute_issue(issue, pull_requests, attribution, runs):
    """一个工单的全部基线数字。"""
    number = issue["number"]
    record = {"number": number, "title": issue["title"],
              "milestone": issue["milestone"], "state": issue["state"],
              "review_rounds": review_rounds(issue),
              "review_failed_times": review_rounds(issue) - 1,
              "delivery_rounds": delivery_rounds(issue),
              "first_in_progress": first_in_progress(issue),
              "merged_at": merged_at(number, pull_requests),
              "pull_requests": [pull["number"] for pull in
                               merged_pull_requests(number, pull_requests)],
              "integration_failures": [],
              "stalled": stalled_reason(issue),
              "usage": issue_usage(number, runs)}
    for entry in attribution.values():
        if number in entry["issues"]:
            record["integration_failures"].append(
                {"commit": entry["commit"], "created_at": entry["created_at"],
                 "attribution": entry["attribution"],
                 "evidence": entry["evidence"][:400]})
    started, finished = record["first_in_progress"], record["merged_at"]
    record["elapsed_minutes"] = (
        round((_parse(finished) - _parse(started)).total_seconds() / 60)
        if started and finished else None)
    return record


def _parse(stamp):
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def summarize(records):
    """汇总：计数、中位数与分布。"""
    merged = [record for record in records if record["merged_at"]]
    rounds = [record["review_rounds"] for record in merged]
    elapsed = [record["elapsed_minutes"] for record in merged
               if record["elapsed_minutes"] is not None]
    failures = [len(record["integration_failures"]) for record in merged]
    requests = [record["usage"]["requests"] for record in merged]
    totals = [record["usage"]["total_tokens"] for record in merged]
    costs = [record["usage"]["cost"] for record in merged]
    return {
        "issues": len(records),
        "merged": len(merged),
        "review_rounds": _stats(rounds),
        "integration_failures": _stats(failures),
        "elapsed_minutes": _stats(elapsed),
        "requests": _stats(requests),
        "total_tokens": _stats(totals),
        "cost": _stats(costs),
        "stalled": sum(1 for record in records if record["stalled"]),
        "with_usage": sum(1 for record in merged if record["usage"]["requests"]),
    }


def failure_counts(records):
    """集成层失败的计数：归因到工单的条数与未归因的条数。"""
    attributed = [record for record in records
                  if record["attribution"] == "评论点名"]
    return {"failures": len(records),
            "attributed_failures": len(attributed),
            "unattributed_failures": len(records) - len(attributed),
            "failure_pairs": sum(len(record["issues"]) for record in attributed)}


def _stats(values):
    if not values:
        return {"count": 0, "median": None, "min": None, "max": None,
                "mean": None, "distribution": {}}
    return {"count": len(values), "median": statistics.median(values),
            "min": min(values), "max": max(values),
            "mean": round(statistics.fmean(values), 1),
            "distribution": _distribution(values)}


def _distribution(values):
    distribution = {}
    for value in values:
        distribution[value] = distribution.get(value, 0) + 1
    return dict(sorted(distribution.items()))


def compute(data):
    """只读数据文件，算出每个工单的数字与汇总。"""
    issues = data.get("issues", [])
    pull_requests = data.get("pull_requests", [])
    runs = data.get("runs", [])
    integration = integration_runs(data.get("stage_comments", []))
    issue_numbers = {issue["number"] for issue in issues}
    attribution = failure_attribution(integration, pull_requests, issue_numbers)
    ordered = []
    for record in integration:
        if record["verdict"] != "FAIL":
            continue
        entry = dict(attribution[record["commit"]])
        entry["counts"] = record["counts"]
        ordered.append(entry)
    records = [compute_issue(issue, pull_requests, attribution, runs)
               for issue in issues]
    records.sort(key=lambda record: record["number"])
    return {"collected_at": data.get("collected_at"),
            "stage_parent_issue": data.get("stage_parent_issue"),
            "integration": integration, "attribution": ordered,
            "failures": failure_counts(ordered),
            "issues": records, "summary": summarize(records)}


def build_report(result):
    """中文报告（Markdown 表格）。"""
    summary = result["summary"]
    lines = ["# Stage 3 基线数字：omp 流程开发 Yudao",
             "",
             "抓取时间：%s；数据文件：`docs/evaluation/baseline-omp-stage3.json`。" % result["collected_at"],
             "",
             "这份报告给出 omp 流程（执行者与审查者都由 omp 运行）在 Stage 3 里程碑下的基线数字，"
             "供自举第一层的配对验收对照使用（[总体路线图](../program-roadmap.md)第 6.1 节）。"
             "计算只读取数据文件，不访问 GitHub 与运行目录。",
             "",
             "## 一、口径",
             "",
             "- 工单范围：里程碑标题以 `Stage 3` 开头的工单，共 %d 个。" % summary["issues"],
             "- 审查轮数：`review-failed` 标签被加上的次数加一。",
             "- 集成层失败归因：阶段父工单 #%s 上 `INTEGRATION: FAIL` 评论里以引入方写法点名的"
             "工单，以及能对上合并请求合并提交的提交号；评论把点名全部写成修复方或只写处理办法"
             "时定位不到引入方，这条失败记为未归因。" % result["stage_parent_issue"],
             "- 搁置的原因：工单标 `ready-for-human` 时紧随其后的评论。",
             "- 耗时：第一次 `in-progress` 到合并请求的合并时间。",
             "- 用量：运行目录里 `omp-` 与 `rv-` 开头输出中的模型请求数与 token 用量；"
             "自主推进开始以前的工单没有运行输出，用量为 0。",
             "- 费用：运行输出里的 cost 字段全是 0，omp 在这些运行上没有记费用；费用按用量乘以"
             "单价计算，单价由用户填写（[D09](../requirements/execution-limits.md)）。",
             "",
             "## 二、覆盖",
             "",
             "| 项目 | 数量 |", "| --- | --- |",
             "| 工单 | %d |" % summary["issues"],
             "| 已合并 | %d |" % summary["merged"],
             "| 有运行记录 | %d |" % summary["with_usage"],
             "| 集成层记录 | %d |" % len(result["integration"]),
             "| 集成层失败 | %d |" % len(result["attribution"]),
             "| 归因到工单的失败 | %d |" % result["failures"]["attributed_failures"],
             "| 未归因的失败 | %d |" % result["failures"]["unattributed_failures"],
             "| 失败归因到的工单 | %d |" % result["failures"]["failure_pairs"],
             "| 搁置过 | %d |" % summary["stalled"],
             "",
             "## 三、汇总",
             "",
             "| 指标 | 条数 | 中位数 | 最小 | 最大 | 平均 |",
             "| --- | --- | --- | --- | --- | --- |"]
    for label, key, unit in (("审查轮数", "review_rounds", "轮"),
                             ("合并后的集成层失败", "integration_failures", "次"),
                             ("耗时", "elapsed_minutes", "分钟"),
                             ("模型请求数", "requests", "次"),
                             ("token 用量", "total_tokens", "token"),
                             ("费用", "cost", "美元")):
        stats = summary[key]
        lines.append("| %s（%s） | %s | %s | %s | %s | %s |"
                     % (label, unit, stats["count"], _number(stats["median"]),
                        _number(stats["min"]), _number(stats["max"]),
                        _number(stats["mean"])))
    lines += ["", "分布：", ""]
    for label, key in (("审查轮数", "review_rounds"),
                       ("合并后的集成层失败", "integration_failures")):
        lines.append("- %s：%s"
                     % (label, _distribution_text(summary[key]["distribution"])))
    lines += ["", "## 四、逐个工单", "",
              "| 工单 | 里程碑 | 状态 | 审查轮数 | 交付轮数 | 集成层失败 | 首次 in-progress "
              "| 合并时间 | 耗时（分钟） | 请求数 | token | 费用 |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for record in result["issues"]:
        lines.append("| #%d | %s | %s | %d | %s | %d | %s | %s | %s | %d | %d | %s |"
                     % (record["number"],
                        record["milestone"].split("·")[-1].strip(),
                        record["state"], record["review_rounds"],
                        _rounds(record["delivery_rounds"]),
                        len(record["integration_failures"]),
                        record["first_in_progress"] or "",
                        record["merged_at"] or "",
                        _number(record["elapsed_minutes"]),
                        record["usage"]["requests"],
                        record["usage"]["total_tokens"],
                        _number(record["usage"]["cost"])))
    lines += ["", "## 五、搁置的原因", ""]
    stalled = [record for record in result["issues"] if record["stalled"]]
    if not stalled:
        lines.append("Stage 3 里程碑下没有工单标过 `ready-for-human`。")
    for record in stalled:
        lines += ["### #%d %s" % (record["number"], record["title"]), "",
                  "标 `ready-for-human` 起始于 %s。原因：" % record["stalled"]["since"]]
        for comment in record["stalled"]["comments"]:
            lines += ["", comment["text"][:600]]
        lines.append("")
    failures = [record for record in result["attribution"]]
    lines += ["## 六、集成层失败与归因", "",
              "共 %d 条失败，其中归因到工单 %d 条、未归因 %d 条；归因到的工单共 %d 个。"
              % (len(failures), result["failures"]["attributed_failures"],
                 result["failures"]["unattributed_failures"],
                 result["failures"]["failure_pairs"]), "",
              "| 集成提交 | 时间 | 计数 | 归因到的工单 | 归因依据 |",
              "| --- | --- | --- | --- | --- |"]
    for record in failures:
        lines.append("| %s | %s | %s | %s | %s |"
                     % (record["commit"], record["created_at"],
                        record["counts"] or "",
                        ", ".join("#%d" % number for number in record["issues"])
                        or "未归因",
                        record["evidence"][:200] or "评论未写明引入方"))
    lines.append("")
    return "\n".join(lines)


def _distribution_text(distribution):
    if not distribution:
        return "无"
    return "，".join("%s 次出现 %d 次" % (value, count)
                     for value, count in distribution.items())


def _rounds(rounds):
    return "/".join(str(value) for value in rounds) if rounds else ""


def _number(value):
    if value is None:
        return ""
    number = float(value)
    if number == int(number):
        return str(int(number))
    return ("%.4f" % number).rstrip("0").rstrip(".")


def main():
    parser = argparse.ArgumentParser(
        description="只读数据文件，算出 Stage 3 的 omp 基线数字")
    parser.add_argument("--data", required=True, help="抓取得到的数据文件")
    parser.add_argument("--result", help="机器可读结果文件")
    parser.add_argument("--report", help="中文报告文件")
    args = parser.parse_args()
    with open(args.data, encoding="utf-8") as handle:
        data = json.load(handle)
    result = compute(data)
    if args.result:
        with open(args.result, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    if args.report:
        with open(args.report, "w", encoding="utf-8") as handle:
            handle.write(build_report(result))
    print("工单 %d 个（已合并 %d 个），审查轮数中位数 %s，耗时中位数 %s 分钟"
          % (result["summary"]["issues"], result["summary"]["merged"],
             _number(result["summary"]["review_rounds"]["median"]),
             _number(result["summary"]["elapsed_minutes"]["median"])))


if __name__ == "__main__":
    main()