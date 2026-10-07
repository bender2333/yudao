import argparse
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone

# 阶段范围：GitHub 里程碑标题以 STAGE_MILESTONE_PREFIX 开头的工单
STAGE_MILESTONE_PREFIX = "Stage 3"

# 标签与状态变化的时间线事件（评论、提交、引用事件不进数据文件）
TIMELINE_FILTER = ('select(.event == "labeled" or .event == "unlabeled" '
                   'or .event == "milestoned" or .event == "demilestoned" '
                   'or .event == "closed" or .event == "reopened")')

# 自主推进运行目录里的输出文件名：omp-<工单><轮次> 与 rv-<工单><轮次>
RUN_FILE = re.compile(r"^(omp|rv)-(\d+)([a-z]*)\.jsonl$")


def _gh_path():
    path = shutil.which("gh")
    if path is None:
        raise RuntimeError("找不到 gh，请先安装并放进 PATH")
    return path


def _gh(args):
    # 调 gh 取一个 JSON 值，失败就地抛出（fast-fail）。按 UTF-8 解码，非法字节替换
    result = subprocess.run([_gh_path()] + args, check=True, capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    return json.loads(result.stdout or "null")


def _gh_items(args):
    # --paginate 与 --jq 同时使用时每个分页各输出一段，且 --slurp 不能与 --jq 并用。
    # 这里让 jq 每项产出一行 tojson 文本，按 JSON 值的序列依次解码，分页之间顺序不乱
    result = subprocess.run([_gh_path()] + args, check=True, capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    text = result.stdout
    decoder = json.JSONDecoder()
    items, position = [], 0
    while position < len(text):
        while position < len(text) and text[position] in " \t\r\n":
            position += 1
        if position >= len(text):
            break
        value, position = decoder.raw_decode(text, position)
        if isinstance(value, list):
            items.extend(value)
        elif isinstance(value, str):
            items.append(json.loads(value))
        else:
            items.append(value)
    return items


def stage_issues():
    """Stage 3 的全部工单：编号、标题、里程碑、标签与关闭时间。"""
    issues = _gh(["issue", "list", "--state", "all", "--limit", "500", "--json",
                  "number,title,milestone,state,stateReason,createdAt,closedAt,"
                  "labels,author,url"])
    stage = [issue for issue in issues
             if (issue.get("milestone") or {}).get("title", "")
             .startswith(STAGE_MILESTONE_PREFIX)]
    return sorted(stage, key=lambda issue: issue["number"])


def issue_detail(number):
    """一个工单的标签变化时间线与评论。"""
    timeline = _gh_items(["api", "repos/{owner}/{repo}/issues/%d/timeline" % number,
                          "--paginate", "-q",
                          ".[] | %s | {event: .event, created_at: .created_at, "
                          "actor: .actor.login, label: .label.name, milestone: "
                          ".milestone.title} | tojson" % TIMELINE_FILTER])
    comments = _gh_items(["api", "repos/{owner}/{repo}/issues/%d/comments" % number,
                          "--paginate", "-q",
                          ".[] | {created_at: .created_at, author: .user.login, "
                          "body: .body} | tojson"])
    return timeline, comments


def pull_requests():
    """合并请求：合并时间、合并提交与它对应的工单。"""
    return _gh(["pr", "list", "--state", "merged", "--limit", "500", "--json",
                "number,title,mergedAt,mergeCommit,headRefOid,"
                "closingIssuesReferences"])


def integration_comments(stage_parent):
    """阶段父工单上的全部评论（集成层记录在其中）。"""
    return _gh(["issue", "view", str(stage_parent), "--json", "comments",
                "--jq", "[.comments[] | {created_at: .createdAt, author: "
                ".author.login, body: .body}]"])


def run_usage(runs_root):
    """自主推进运行目录里的执行者与审查者运行输出（含用量）。"""
    runs = []
    if not os.path.isdir(runs_root):
        return runs
    for name in sorted(os.listdir(runs_root)):
        matched = RUN_FILE.match(name)
        if not matched:
            continue
        role, number, round_suffix = matched.group(1), int(matched.group(2)), matched.group(3)
        runs.append(_run_summary(os.path.join(runs_root, name), name, role, number,
                                 round_suffix, runs_root))
    return runs


def _run_summary(path, name, role, number, round_suffix, runs_root):
    """一个运行输出的用量汇总：请求数、用量、费用、模型与起止时刻。"""
    summary = {"file": name, "role": role, "issue": number,
               "round": round_suffix or "a", "requests": 0,
               "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
               "cache_write_tokens": 0, "total_tokens": 0, "cost": 0.0,
               "models": {}, "started_ms": None, "finished_ms": None,
               "exit_code": None, "finished_local": None}
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if '"message_end"' not in line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "message_end":
                continue
            message = event.get("message") or {}
            if message.get("role") != "assistant":
                continue
            _add_usage(summary, message)
    _read_done_file(summary, os.path.join(runs_root, name[:-len(".jsonl")] + ".done"))
    return summary


def _add_usage(summary, message):
    # 一条助手消息就是一次模型请求；用量与费用按消息累计，模型分列
    usage = message.get("usage") or {}
    cost = usage.get("cost") or {}
    summary["requests"] += 1
    for key, name in (("input", "input_tokens"), ("output", "output_tokens"),
                      ("cacheRead", "cache_read_tokens"),
                      ("cacheWrite", "cache_write_tokens"),
                      ("totalTokens", "total_tokens")):
        summary[name] += int(usage.get(key) or 0)
    summary["cost"] += float(cost.get("total") or 0)
    model = "%s/%s" % (message.get("provider"), message.get("model"))
    entry = summary["models"].setdefault(model, {"requests": 0, "total_tokens": 0,
                                                  "cost": 0.0})
    entry["requests"] += 1
    entry["total_tokens"] += int(usage.get("totalTokens") or 0)
    entry["cost"] += float(cost.get("total") or 0)
    started = message.get("timestamp")
    finished = message.get("completedAt")
    if isinstance(started, int):
        if summary["started_ms"] is None or started < summary["started_ms"]:
            summary["started_ms"] = started
    if isinstance(finished, int):
        if summary["finished_ms"] is None or finished > summary["finished_ms"]:
            summary["finished_ms"] = finished


def _read_done_file(summary, path):
    # .done 写的是退出码与完成时刻，格式为 "exit <码> <时:分>"
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8", errors="replace") as handle:
        fields = handle.read().split()
    if len(fields) >= 3 and fields[0] == "exit":
        summary["exit_code"] = int(fields[1])
        summary["finished_local"] = fields[2]


def collect(stage_parent, runs_root, data_path):
    """抓取一次真实数据，写出数据文件。中断以后重跑按编号续抓。"""
    data = _read_partial(data_path)
    data.update({"collected_at": _now(), "stage_parent_issue": stage_parent,
                 "runs_root": runs_root,
                 "scope": {"milestone_prefix": STAGE_MILESTONE_PREFIX}})
    issues = data.setdefault("issues", [])
    known = {issue["number"] for issue in issues}
    for issue in stage_issues():
        if issue["number"] in known:
            continue
        timeline, comments = issue_detail(issue["number"])
        issues.append({"number": issue["number"], "title": issue["title"],
                       "milestone": (issue.get("milestone") or {}).get("title", ""),
                       "state": issue.get("state"),
                       "state_reason": issue.get("stateReason"),
                       "created_at": issue.get("createdAt"),
                       "closed_at": issue.get("closedAt"),
                       "author": (issue.get("author") or {}).get("login"),
                       "url": issue.get("url"),
                       "current_labels": [label["name"] for label in issue.get("labels") or []],
                       "timeline": timeline, "comments": comments})
        issues.sort(key=lambda item: item["number"])
        _write(data, data_path)
    data["pull_requests"] = pull_requests()
    data["stage_comments"] = integration_comments(stage_parent)
    data["runs"] = run_usage(runs_root)
    _write(data, data_path)
    return data


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_partial(data_path):
    # 续抓：已有数据文件就接着填，抓过的工单不再请求 GitHub
    if not os.path.exists(data_path):
        return {}
    with open(data_path, encoding="utf-8") as handle:
        return json.load(handle)


def _write(data, data_path):
    parent = os.path.dirname(os.path.abspath(data_path))
    os.makedirs(parent, exist_ok=True)
    with open(data_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def main():
    parser = argparse.ArgumentParser(description="抓取 Stage 3 工单的 omp 基线数据")
    parser.add_argument("--stage-parent", type=int, default=9,
                        help="阶段父工单号，集成层评论在其中（默认 9）")
    parser.add_argument("--runs-root", required=True,
                        help="自主推进运行目录，含 omp- 与 rv- 开头的运行输出")
    parser.add_argument("--data", required=True, help="数据文件路径")
    args = parser.parse_args()
    data = collect(args.stage_parent, args.runs_root, args.data)
    print("抓取工单 %d 个，合并请求 %d 个，运行输出 %d 个，阶段评论 %d 条：%s"
          % (len(data["issues"]), len(data["pull_requests"]),
             len(data["runs"]), len(data["stage_comments"]), args.data))


if __name__ == "__main__":
    main()
