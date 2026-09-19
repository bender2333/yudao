"""A4 prompt comparison: two projects, frozen tasks. FakeAdapter by default."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .adapters.fake import FakeAdapter, FakeTurn
from .department_prompts import DEFAULT_PROMPTS
from .models import EventType
from .projects import ProjectEventType
from .proposals import delivery_turn, engineering_plan, product_spec, review_turn
from .public_tree import materialize_tree
from .providers import ProviderFacade
from .runtime import LoopSystem
from .smoke import summarize_run
from .tree_archive import load_tree

APPLICATION = "4c5cde4"
PROTOCOL = "docs/stage-2-a4-protocol.md"
BASELINE_NAME = "a4-baseline"
CANDIDATE_NAME = "a4-candidate"
COMPARISON_GOAL = "完成四个独立的公开确认任务，验证工程计划顺序与合同绑定。"
CONTEXT_WINDOW = 32_000
MAX_CYCLES = 8
SIDE_EFFECT_TOOLS = frozenset({"write_file", "delete_file", "move_file", "run_check"})

CANDIDATE_PARAGRAPHS = (
    "写入、删除、移动文件或 run_check、submit_delivery 之前，必须已有被主机接纳的当前计划。计划被拒后先根据回执改正，不得继续改代码。",
    "本 run 已有计划时，新计划必须说明相对上一份计划改了什么以及为什么，即使上一份已被拒收或已失效。",
    "计划绑定的合同身份必须使用当次输入提供的当前有效合同，不得引用记忆中的旧合同标识。",
)

ECHO_PY = "import sys\nfor line in sys.stdin:\n    sys.stdout.write(line)\n"
CSV_PY = """import sys
from pathlib import Path

if len(sys.argv) < 2:
    sys.stderr.write("missing file\\n")
    raise SystemExit(1)
path = Path(sys.argv[1])
if not path.is_file():
    sys.stderr.write(f"file not found: {path}\\n")
    raise SystemExit(1)
sys.stdout.write(path.read_text(encoding="utf-8"))
"""

TASKS = (
    {
        "key": "task-1",
        "title": "方向变更的文本处理",
        "text": (
            "做命令行工具，从标准输入逐行输出；空输入不崩溃且无输出。"
            "本任务只要求 stdin 逐行原样输出。"
            "公开检查：printf 'a\\nb\\n' | python src/echo.py 输出两行 a / b，空输入退出码 0。"
            "同一项目不在 A4 做第二次变更（第二次变更属于 B4）。"
        ),
    },
    {
        "key": "task-2",
        "title": "结构化数据",
        "text": (
            "读 CSV id,name,status，输出相同表头的 CSV，保留输入行顺序。"
            "公开检查用固定三行输入，期望三行输出。"
            "缺文件时非零退出并写错误到 stderr。"
        ),
    },
    {
        "key": "task-3",
        "title": "需澄清的要求",
        "text": (
            "任务原文同时说「按字母排序」和「保持原序」。"
            "产品必须先形成单一有效合同（提问或自行取舍并写进合同）；"
            "工程不得在合同未决时写代码。"
            "公开检查按最终合同执行，评价看协作是否发生、合同是否单一。"
        ),
    },
    {
        "key": "task-4",
        "title": "带公开回归的修复",
        "text": (
            "事项原文描述当前错误行为是丢掉空行（不预置代码）。"
            "工程实现正确行为：保留空行。"
            "公开检查包含空行样例。"
        ),
    },
)


def candidate_engineering_prompt() -> str:
    return DEFAULT_PROMPTS["engineering"] + "\n" + "\n".join(CANDIDATE_PARAGRAPHS)


def comparison_script() -> list:
    """Fake turns: baseline writes before the plan; candidate plans first."""

    def turn(request):
        if request.purpose == "compaction":
            return FakeTurn(transcript="Keep the current contract, plan, and files.")
        if request.department == "product":
            return product_spec()
        if request.department == "quality":
            return review_turn("release", "checks passed on the current snapshot")
        if request.department != "engineering":
            return product_spec()
        prompt = _developer_text(request)
        files = _delivery_files(_task_key_from_text(prompt))
        if request.engineering_plan_hash is None:
            plan = engineering_plan()
            if all(paragraph in prompt for paragraph in CANDIDATE_PARAGRAPHS):
                return plan
            return FakeTurn(writes={"src/echo.py": ECHO_PY}, proposal=plan)
        return delivery_turn(files=files)

    return [turn] * 128


def build_fake_comparison_system(data_dir: str | Path) -> LoopSystem:
    return LoopSystem.for_testing(data_dir, FakeAdapter(comparison_script()))


def run_a4_comparison(system: LoopSystem, out_dir: str | Path) -> dict[str, Any]:
    """Register two projects, alternate four frozen tasks, write JSON+Markdown."""

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    baseline_id = system.projects.register(BASELINE_NAME, COMPARISON_GOAL)
    candidate_id = system.projects.register(CANDIDATE_NAME, COMPARISON_GOAL)
    system.projects.configure_prompt(candidate_id, "engineering", candidate_engineering_prompt(), 0)
    project_ids = {"baseline": baseline_id, "candidate": candidate_id}
    trials: list[dict[str, Any]] = []
    task_rows: list[dict[str, Any]] = []
    for index, task in enumerate(TASKS):
        order = ("baseline", "candidate") if index % 2 == 0 else ("candidate", "baseline")
        pair: dict[str, Any] = {}
        for group in order:
            record = _run_work_item(system, project_ids[group], group, task)
            trials.append(record)
            pair[group] = record
        task_rows.append({
            "key": task["key"],
            "title": task["title"],
            "text": task["text"],
            "order": list(order),
            "baseline": pair["baseline"],
            "candidate": pair["candidate"],
        })
    report = {
        "protocol": PROTOCOL,
        "application": APPLICATION,
        "goal": COMPARISON_GOAL,
        "conclusion": "undecided",
        "projects": {
            "baseline": _project_facts(system, baseline_id, BASELINE_NAME),
            "candidate": _project_facts(system, candidate_id, CANDIDATE_NAME),
        },
        "tasks": task_rows,
        "trials": trials,
    }
    _write_report(out, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A4 prompt comparison")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--provider-config", help="real catalog; omit for FakeAdapter")
    args = parser.parse_args(argv)
    if args.provider_config:
        facade = ProviderFacade()
        facade.configure_paths(args.provider_config, None)
        facade.reload()
        system = LoopSystem(args.data_dir, facade=facade)
        status = system.provider_status()
        if not status["available"]:
            raise SystemExit(f"provider unavailable: {status.get('reason') or status.get('message')}")
    else:
        system = build_fake_comparison_system(args.data_dir)
    run_a4_comparison(system, args.out)
    return 0


def _run_work_item(system: LoopSystem, project_id: str, group: str, task: dict[str, str]) -> dict[str, Any]:
    work_item_id, run_id = system.projects.start_work_item(
        project_id, task["text"], title=task["title"],
        max_cycles=MAX_CYCLES, context_window=CONTEXT_WINDOW,
    )
    run_error = None
    try:
        projection = system.run_until_stop(run_id)
    except Exception as exc:  # noqa: BLE001 - comparison must keep failed items
        run_error = str(exc) or type(exc).__name__
        try:
            projection = system.project(run_id)
        except Exception:  # noqa: BLE001
            projection = None
    settle_error = None
    settle_event = None
    try:
        settle_event = system.projects.settle(run_id)
    except Exception as exc:  # noqa: BLE001
        settle_error = str(exc) or type(exc).__name__
    plan_record = _plan_compliance(system, run_id)
    summary = None
    if projection is not None:
        summary = summarize_run(system, run_id, scenario=f"{group}:{task['key']}")
    engineering_text = ""
    if projection is not None and "engineering" in projection.department_prompts:
        engineering_text = projection.department_prompts["engineering"].text
    return {
        "group": group,
        "task_key": task["key"],
        "task_title": task["title"],
        "project_id": project_id,
        "work_item_id": work_item_id,
        "run_id": run_id,
        "prompt_config_versions": {} if projection is None else dict(projection.prompt_config_versions),
        "engineering_prompt_has_candidate_addendum": all(
            paragraph in engineering_text for paragraph in CANDIDATE_PARAGRAPHS
        ),
        "phase": None if projection is None else projection.phase,
        "outcome": None if projection is None else projection.outcome,
        "stop_reason": None if projection is None else projection.stop_reason,
        "error": run_error if run_error is not None else (None if projection is None else projection.error),
        "settle_outcome": _settle_outcome(settle_event),
        "settle_error": settle_error,
        "qa_verdict": None if projection is None or projection.last_review is None else projection.last_review.verdict,
        "public_check": _public_check(system, run_id, task, projection),
        "summary": summary,
        **plan_record,
    }


def _plan_compliance(system: LoopSystem, run_id: str) -> dict[str, Any]:
    events = system.store.list_events(run_id)
    accepted = [event for event in events if event.type == EventType.PLAN_ACCEPTED]
    rejected = [
        event for event in events
        if event.type == EventType.PROPOSAL_REJECTED and event.payload.get("kind") == "engineering_plan"
    ]
    first_accepted = None if not accepted else accepted[0].seq
    before = []
    for event in events:
        if event.type not in {EventType.TOOL_STARTED, EventType.TOOL_CALLED, EventType.TOOL_SKIPPED}:
            continue
        name = (event.payload or {}).get("name")
        if name not in SIDE_EFFECT_TOOLS:
            continue
        if first_accepted is None or event.seq < first_accepted:
            before.append({
                "seq": event.seq,
                "type": event.type,
                "name": name,
                "ok": (event.payload or {}).get("ok"),
            })
    return {
        "plan_accepted_count": len(accepted),
        "plan_rejected_count": len(rejected),
        "writes_before_plan_accepted": bool(before),
        "writes_before_plan": before,
    }


def _public_check(system: LoopSystem, run_id: str, task: dict[str, str], projection) -> dict[str, Any]:
    if projection is None or projection.delivery_spec is None:
        return {"status": "not_run", "reason": "no accepted delivery"}
    delivery = projection.delivery_spec
    try:
        tree = load_tree(system.artifacts, run_id, delivery.tree_ref)
        if tree.digest != delivery.code_tree_digest:
            return {"status": "not_run", "reason": "archived tree does not match its accepted delivery"}
        with tempfile.TemporaryDirectory(prefix="yudao-a4-check-") as folder:
            restored = materialize_tree(tree, Path(folder) / "workspace")
            return _run_task_check(restored, task, projection)
    except (KeyError, TypeError, ValueError, OSError) as exc:
        return {"status": "not_run", "reason": str(exc)}


def _run_task_check(root: Path, task: dict[str, str], projection) -> dict[str, Any]:
    key = task["key"]
    if key == "task-1":
        return _check_echo(root, b"a\nb\n", [b"a", b"b"], empty=True)
    if key == "task-2":
        return _check_csv(root)
    if key == "task-3":
        return _check_contract(projection)
    if key == "task-4":
        return _check_echo(root, b"a\n\nb\n", [b"a", b"", b"b"], empty=False)
    return {"status": "not_run", "reason": f"unknown task {key}"}


def _check_echo(root: Path, payload: bytes, expected_lines: list[bytes], *, empty: bool) -> dict[str, Any]:
    script = root / "src" / "echo.py"
    if not script.is_file():
        return {"status": "not_run", "reason": "src/echo.py missing"}
    lined = _run_python(script, cwd=root, stdin=payload)
    lines = lined["stdout"].splitlines()
    notes = []
    ok = lined["returncode"] == 0 and lines == expected_lines
    if not ok:
        notes.append(f"stdin lines: expected {expected_lines!r} got {lines!r} exit={lined['returncode']}")
    empty_run = None
    if empty:
        empty_run = _run_python(script, cwd=root, stdin=b"")
        if empty_run["returncode"] != 0 or empty_run["stdout"] != b"":
            ok = False
            notes.append(f"empty stdin: exit={empty_run['returncode']} stdout={empty_run['stdout']!r}")
    return {
        "status": "pass" if ok else "fail",
        "notes": notes,
        "stdout_lines": [line.decode("utf-8", errors="replace") for line in lines],
        "empty_exit": None if empty_run is None else empty_run["returncode"],
    }


def _check_csv(root: Path) -> dict[str, Any]:
    script = root / "src" / "csv_tool.py"
    if not script.is_file():
        return {"status": "not_run", "reason": "src/csv_tool.py missing"}
    sample_lines = ["id,name,status", "1,a,open", "2,b,closed"]
    sample_path = root / "sample.csv"
    sample_path.write_text("\n".join(sample_lines) + "\n", encoding="utf-8")
    present = _run_python(script, cwd=root, args=[str(sample_path)])
    missing = _run_python(script, cwd=root, args=[str(root / "missing.csv")])
    notes = []
    got = present["stdout"].splitlines()
    expected = [line.encode("utf-8") for line in sample_lines]
    ok = present["returncode"] == 0 and got == expected
    if not ok:
        notes.append(f"three-line csv: exit={present['returncode']} stdout={present['stdout']!r}")
    if missing["returncode"] == 0 or not missing["stderr"]:
        ok = False
        notes.append(f"missing file: exit={missing['returncode']} stderr={missing['stderr']!r}")
    return {
        "status": "pass" if ok else "fail",
        "notes": notes,
        "missing_exit": missing["returncode"],
    }


def _check_contract(projection) -> dict[str, Any]:
    contract = projection.effective_contract
    if contract is None:
        return {
            "status": "合同未决",
            "contract_count": len(projection.effective_contracts),
            "collaboration": bool(projection.requests),
            "collaboration_count": len(projection.requests),
        }
    return {
        "status": "pass",
        "contract_count": len(projection.effective_contracts),
        "single_effective_contract": True,
        "collaboration": bool(projection.requests),
        "collaboration_count": len(projection.requests),
    }


def _run_python(script: Path, *, cwd: Path, stdin: bytes | None = None, args: list[str] | None = None) -> dict[str, Any]:
    argv = [sys.executable, str(script), *(args or [])]
    completed = subprocess.run(argv, cwd=cwd, input=stdin, capture_output=True, timeout=10, check=False)
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _project_facts(system: LoopSystem, project_id: str, name: str) -> dict[str, Any]:
    project = system.projects.projection(project_id)
    return {
        "project_id": project_id,
        "name": name,
        "prompt_configs": {
            department: {
                "version": config.version,
                "source": config.source,
                "has_candidate_addendum": all(paragraph in config.text for paragraph in CANDIDATE_PARAGRAPHS),
            }
            for department, config in project.prompt_configs.items()
        },
    }


def _settle_outcome(event) -> str:
    if event is None:
        return "none"
    if event.type == ProjectEventType.DELIVERABLE_ADOPTED:
        return "adopted"
    if event.type == ProjectEventType.ADOPTION_HELD:
        return "held"
    return event.type


def _developer_text(request) -> str:
    if not request.input_items:
        return ""
    content = request.input_items[0].get("content")
    return content if isinstance(content, str) else ""


def _task_key_from_text(text: str) -> str:
    if "id,name,status" in text:
        return "task-2"
    if "按字母排序" in text:
        return "task-3"
    if "丢掉空行" in text:
        return "task-4"
    return "task-1"


def _delivery_files(task_key: str) -> dict[str, str]:
    files = {"src/echo.py": ECHO_PY}
    if task_key == "task-2":
        files["src/csv_tool.py"] = CSV_PY
    return files


def _write_report(out_dir: Path, report: dict[str, Any]) -> None:
    payload = json.loads(json.dumps(report, ensure_ascii=False, default=str))
    (out_dir / "a4-compare.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    (out_dir / "a4-compare.md").write_text(_markdown(payload), encoding="utf-8")


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# A4 Prompt 固定任务比较",
        "",
        f"- 协议：`{report.get('protocol')}`",
        f"- 应用：`{report.get('application')}`",
        f"- 长期目标：{report.get('goal')}",
        f"- 结论：`{report.get('conclusion')}`（由主代理在真实验收后填写；本包不预填）",
        "",
    ]
    projects = report.get("projects") or {}
    for group in ("baseline", "candidate"):
        facts = projects.get(group) or {}
        lines.append(f"## 项目 {group}")
        lines.append("")
        lines.append(f"- project_id：`{facts.get('project_id')}`")
        lines.append(f"- 名称：`{facts.get('name')}`")
        for department, config in (facts.get("prompt_configs") or {}).items():
            lines.append(
                f"- {department} 配置 version={config.get('version')} source={config.get('source')} "
                f"候选段落={config.get('has_candidate_addendum')}"
            )
        lines.append("")
    for task in report.get("tasks") or []:
        lines.append(f"## {task.get('key')} {task.get('title')}")
        lines.append("")
        lines.append(f"- 交替顺序：{' → '.join(task.get('order') or [])}")
        lines.append("")
        lines.append("| 组 | run | phase | 结算 | 计划接纳/拒收 | 计划前写文件 | QA | 公开检查 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for group in ("baseline", "candidate"):
            trial = task.get(group) or {}
            check = (trial.get("public_check") or {}).get("status")
            lines.append(
                "| {group} | `{run}` | `{phase}` | `{settle}` | {accepted}/{rejected} | `{before}` | `{qa}` | `{check}` |".format(
                    group=group,
                    run=trial.get("run_id"),
                    phase=trial.get("phase"),
                    settle=trial.get("settle_outcome"),
                    accepted=trial.get("plan_accepted_count"),
                    rejected=trial.get("plan_rejected_count"),
                    before=trial.get("writes_before_plan_accepted"),
                    qa=trial.get("qa_verdict"),
                    check=check,
                )
            )
        lines.append("")
        for group in ("baseline", "candidate"):
            trial = task.get(group) or {}
            summary = trial.get("summary") or {}
            lines.append(f"### {group} 事实")
            lines.append("")
            lines.append(f"- project_id：`{trial.get('project_id')}`")
            lines.append(f"- work_item_id：`{trial.get('work_item_id')}`")
            lines.append(f"- run_id：`{trial.get('run_id')}`")
            lines.append(f"- prompt_config_versions：`{json.dumps(trial.get('prompt_config_versions') or {}, ensure_ascii=False, sort_keys=True)}`")
            lines.append(f"- 候选段落写入工程初始 Prompt：`{trial.get('engineering_prompt_has_candidate_addendum')}`")
            lines.append(f"- outcome / stop_reason：`{trial.get('outcome')}` / `{trial.get('stop_reason')}`")
            if trial.get("error"):
                lines.append(f"- error：{trial['error']}")
            lines.append(f"- 请求数：`{summary.get('request_count')}` token：`{summary.get('token_used')}`")
            lines.append(f"- 模型：`{summary.get('actual_provider')}` / `{summary.get('actual_model')}`")
            lines.append("")
    lines.append("失败事项均保留在 `trials` 中，未删除。")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
