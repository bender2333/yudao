import asyncio
import json
import os
import shutil
import sys
import threading
import time
import uuid

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness.actions import Action, ActionReceipt, Preconditions
from harness.adapters.fake import FakeAdapter, FakeTurn, prompt_part
from harness.assembly import ContextAssembly
from harness.context import ContextAssembler, ContextPart
from harness.definitions import DEFINITIONS
from harness.department_prompts import save_department_prompt
from harness.engine import StepLimits
from harness.models import ArtifactRef, ContextManifest, DepartmentPrompt, Event, json_dumps
from harness.proposals import (delivery_turn, product_spec, review,
                        review_turn)
from harness.environment import LocalEnvironment, QA_TESTS_DIR
from harness.providers.call import ModelCall, ModelResponse
from harness.runtime import LoopSystem
from harness.tools import tool_action
from harness.tightening import WATCHED_OUTPUTS

# 测试中的重试间隔缩短到毫秒级，其余参数与正式运行相同
FAST_RETRIES = StepLimits(retry_initial_delay_sec=0.01, retry_max_delay_sec=0.02)

# 连续只回复文字、没有调用工具时最多追加说明的次数，取规则登记中的现值
TOOL_CALL_REQUIRED_LIMIT = DEFINITIONS.rule_value("tool_call_required_limit")


def guidance_reply(text: str = "已按新的要求处理。"):
    """部门对待处理指导的收尾：以指导独占的一轮用文字回答结束。

    这一轮开始时关注的成果里只有指导，模型不调用工具的文字回复就是对用户的回答，
    一轮工作就此正常结束（部门指导设计说明第 3 节，工单 #1037）；主机在一轮正常结束时
    写已回答事件（工单 #1039）。"""
    def factory(request: ModelCall) -> FakeTurn:
        return FakeTurn(transcript=text)
    return factory


def calls_during(function, operation) -> int:
    # 用 sys.setprofile 记录 function 在 operation 期间（当前线程中）被调用的次数；只观察，不替换
    code, calls = function.__code__, []

    def profile(frame, event, _arg):
        if event == "call" and frame.f_code is code:
            calls.append(1)

    previous = sys.getprofile()
    sys.setprofile(profile)
    try:
        operation()
    finally:
        sys.setprofile(previous)
    return len(calls)


def action(name: str, args: dict[str, Any], *, department: str = "engineering",
           preconditions: Preconditions = Preconditions()) -> Action:
    # 一个环境工具调用的动作合同，动作身份每次不同
    return Action(action_id=f"test:{uuid.uuid4().hex}", kind=tool_action(name), tool=name,
                  department=department, input=args, preconditions=preconditions)


def perform(environment: LocalEnvironment, name: str, args: dict[str, Any], *,
            department: str = "engineering") -> ActionReceipt:
    # 直接调用执行环境的公开接口执行一个动作。在另一个线程的事件循环中执行，假模型的脚本（已在事件循环中）也能调用
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, environment.perform(action(name, args, department=department))).result()


# 长时间运行的进程（argv 的一项）：启动一个同样长时间运行的子进程并输出它的进程号，在第一个参数给出的位置写下
# 标记文件以后等待；用来检查运行中的超时与取消是否结束整个进程树
LONG_RUNNING_TREE = (
    "import pathlib, subprocess, sys, time; "
    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
    "print(f'started child={child.pid}', flush=True); "
    "pathlib.Path(sys.argv[1]).write_text('running'); "
    "time.sleep(60)"
)


def run_tree_command(marker) -> str:
    # 把长时间运行的程序连同标记文件的位置包成一条检查命令：程序只用单引号，
    # 整段用双引号包给 bash，Windows 上的解释器路径用正斜杠
    return f'"{sys.executable.replace(chr(92), "/")}" -c "{LONG_RUNNING_TREE}" "{Path(marker).as_posix()}"'


# 等待放行的进程（argv 的一项）：在第一个参数给出的目录中写下 started 与自己的进程号，
# 然后等待同一目录中出现 release（至多 30 秒）。父进程先终止 Yudao 进程、等它退出，
# 再按记录的进程号收掉这个子进程（工单 #338）：它与 Yudao 进程不同组，进程树终止到不了它
WAIT_FOR_RELEASE = (
    "import os, pathlib, sys, time; signals = pathlib.Path(sys.argv[1]); "
    "(signals / 'started').write_text('running'); "
    "(signals / 'child.pid').write_text(str(os.getpid())); "
    "[time.sleep(0.05) for _ in range(600) if not (signals / 'release').exists()]"
)


def run_wait_command(signals) -> str:
    # 等待放行的程序连同信号目录的位置包成一条命令字符串
    return f'"{sys.executable.replace(chr(92), "/")}" -c "{WAIT_FOR_RELEASE}" "{Path(signals).as_posix()}"'


def wait_for_file(path: Path) -> None:
    for _ in range(300):
        if path.exists():
            return
        time.sleep(0.05)
    raise AssertionError(f"{path} was not created")


def pid_alive(pid: int) -> bool:
    # 跨平台的进程存活检查：只读探测，不改变进程状态
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def delete_watched_file(path: Path, *, timeout_sec: float = 5.0, interval_sec: float = 0.05) -> None:
    # 删除应用正在监视的配置文件（目录文件、准入文件、.env）：应用每约 1 秒读一次这些文件，
    # Windows 上文件正被读取时删除会报 PermissionError（WinError 32，文件被占用）。
    # 短时间重试到删除成功；超时仍失败时照常抛出原来的错误，调用方的断言不因此放宽（工单 #1091）
    deadline = time.monotonic() + timeout_sec
    while True:
        try:
            path.unlink()
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(interval_sec)


def wait_until_stopped(pid: int) -> bool:
    for _ in range(100):
        if not pid_alive(pid):
            return True
        time.sleep(0.1)
    return False


def system_with(data_dir: Path, script) -> LoopSystem:
    return LoopSystem.for_testing(data_dir, FakeAdapter(script))


def run_scripted(data_dir: Path, script, task: str = "build echo", **kwargs):
    system = system_with(data_dir, script)
    run_id = system.create_run(task, **kwargs)
    return system, system.run_until_stop(run_id)


def copy_data_dir(source: Path, destination: Path) -> Path:
    # 保存的数据目录的一份副本。夹具建完循环以后已经关闭系统（事件库连接关闭时把预写日志收回主文件），
    # 目录中的工件库、工作区与 Git 版本齐全，整目录复制即是一份新的数据目录
    shutil.copytree(source, destination)
    return destination


def system_on_copy(source: Path, destination: Path, script=()) -> LoopSystem:
    # 在保存的数据目录的一份副本上打开系统。保存的 run 可能还没有结束，重新打开不自动继续它，
    # 激活由测试自己驱动（harness.runtime.LoopSystem.for_testing 的 resume_on_startup 参数）
    return LoopSystem.for_testing(copy_data_dir(source, destination), FakeAdapter(list(script)),
                                  resume_on_startup=False)


def explore_turn() -> FakeTurn:
    # 质检的预测性探索：按 PRD 起草测试用例，写进质检自己的测试材料；
    # 这一轮没有交付可以核验，提交的结论被拒绝，这一轮到这里结束（工单 #557）
    return FakeTurn(
        writes={f"{QA_TESTS_DIR}/test_echo.py":
                "import subprocess, sys\nr = subprocess.run([sys.executable, 'src/echo.py', 'hello'],"
                "capture_output=True, text=True)\nassert r.returncode == 0 and r.stdout.strip() == 'hello'\n"},
        proposal=review("release", "按 PRD 起草了测试用例；还没有交付可以核验"),
    )


def quality_turns(verdict: str = "release", rationale: str = "checks passed on the current snapshot",
                  *, defects: list[dict[str, str]] | None = None, checks: dict[str, Any] | None = None,
                  times: int = 10) -> list[Any]:
    # 质检的脚本（工单 #557）：质检关注「PRD 被接纳」，PRD 的每一个新版本与每一份新交付都让它开始一轮工作，
    # 轮数随这些成果到达的时机变化，因此每一轮按这一轮开始时有没有交付决定做什么：
    # 没有交付的一轮是预测性探索（提交的结论被拒绝），有交付的一轮是核验（缺陷记录或放行）。
    # 脚本项给足几轮，实际用掉几轮由运行决定（PRD 每修订一次就多一轮预测性探索）。
    state = {"concluded": False}

    def turn(call: ModelCall) -> FakeTurn:
        if not prompt_part(call, "current_delivery_spec"):
            return explore_turn()
        if verdict == "rework_engineering" and not state["concluded"]:
            state["concluded"] = True
            return review_turn(verdict, rationale, defects=defects, checks=checks)(call)
        return review_turn("release", rationale, checks=checks)(call)

    return [turn] * times


def happy_script():
    # 按部门给出的脚本（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    return {
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": [explore_turn(), review_turn("release", "checks passed on the current snapshot")],
    }


def repeat_script(script: dict[str, list[Any]], times: int) -> dict[str, list[Any]]:
    # 同一个适配器跑多次运行（例如两个项目各完成一个事项）：每个部门的脚本重复若干遍
    return {department: list(turns) * times for department, turns in script.items()}


def merge_scripts(*scripts: dict[str, list[Any]]) -> dict[str, list[Any]]:
    # 把几个按部门给出的脚本接在一起（一个适配器跑几个事项，每个事项一份脚本）
    merged: dict[str, list[Any]] = {}
    for script in scripts:
        for department, turns in script.items():
            merged.setdefault(department, []).extend(turns)
    return merged


def list_files_turn(call: ModelCall) -> ModelResponse:
    # 三个部门都能调用的只读工具，用来构造不提交提案的工作步骤
    identity = f"list-{call.activation_id}-{call.step_id}"
    return ModelResponse(output=[{"id": identity, "call_id": identity, "type": "function_call",
                                  "name": "list_files", "arguments": json_dumps({})}])


@dataclass(frozen=True)
class RecordedContext:
    manifest: ContextManifest
    parts: list[ContextPart]


def recorded_context(system: LoopSystem, call: ModelCall) -> RecordedContext:
    # 一次模型调用的上下文清单与各段材料，取自主机的记录（投影中的清单与它引用的 context_parts 工件）
    manifest = next(item for item in system.project(call.run_id).manifests
                    if item.activation_id == call.activation_id and item.step_id == call.step_id)
    raw = json.loads(system.artifacts.get_for_run(call.run_id, ArtifactRef(**manifest.parts_ref)))
    return RecordedContext(manifest, [ContextPart(item["source"], item["version"], item["text"]) for item in raw])


def developer_text(call: ModelCall) -> str:
    # 工作请求的第一条消息：本步装配的全部部门材料
    return call.input_items[0]["content"]


def department_history(system: LoopSystem, run_id: str, department: str) -> list[dict]:
    # 部门历史，按事件由上下文装配（P）重建
    return ContextAssembly(system.artifacts, system.store, tightening=WATCHED_OUTPUTS).department_history(system.store.list_events(run_id), department)


def after_event(system: LoopSystem, event_type: str, action: Callable[[Event], None]) -> None:
    # 某种事件提交以后，在提交它的线程中执行 action（订阅事件日志的提交通知）：在这个时点插入用户操作（新输入、取消），
    # 或者通知测试线程。通知时不持有任何锁，action 中的操作在写入方之后的任何写入之前提交；
    # 同一事务中这条事件之后追加的事件已经一起提交
    def notify(events: list[Event]) -> None:
        for event in events:
            if event.type == event_type:
                action(event)

    system.store.subscribe(notify)


class OtherThreadOperation:
    # 在另一个线程中完成的一个操作（取消、新输入、指导等）；errors 是它抛出的异常
    def __init__(self, operation: Callable[[], Any]) -> None:
        self.errors: list[Exception] = []

        def run() -> None:
            try:
                operation()
            except Exception as exc:
                self.errors.append(exc)

        thread = threading.Thread(target=run)
        thread.start()
        thread.join(10)
        assert not thread.is_alive()


def from_another_thread(operation: Callable[[], Any]) -> OtherThreadOperation:
    # 在 after_event 的 action 中调用：操作在另一个线程中完成以后，写入方才继续
    return OtherThreadOperation(operation)


def summary_message(request, text="Product memory: prior evidence was read; keep the original requirements."):
    # 一次压缩请求的输出项：文字形式的记忆摘要
    return {"id": f"summary-{request.activation_id}-{request.step_id}", "type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": text}]}


def read_file_call(request, path) -> ModelResponse:
    # 只读工具 read_file 的调用结果（ModelResponse），用来构造触发压缩的工作步骤
    identity = f"read-{request.activation_id}-{request.step_id}"
    return ModelResponse(output=[{"id": identity, "call_id": identity, "type": "function_call", "name": "read_file",
                                  "arguments": json_dumps({"path": path})}])


def compacted_runner(tmp_path, *, cancelled_summary=None, reject_first_spec=False, step_limits=StepLimits()):
    # 一个上下文窗口只有 6000、工作区里放着大文件的运行：按请求目的与部门给出剧本，第一次读取以后压缩
    work_counts = {}
    rejected_spec = False

    def respond(request):
        nonlocal rejected_spec
        if request.purpose == "compaction":
            if cancelled_summary is not None:
                return cancelled_summary(request)
            return ModelResponse(output=[summary_message(request)])
        count = work_counts.get(request.activation_id, 0)
        work_counts[request.activation_id] = count + 1
        if request.department == "engineering":
            if count == 0:
                call_id = f"ask-{request.activation_id}-{request.step_id}"
                return ModelResponse(output=[{
                    "id": call_id,
                    "call_id": call_id,
                    "type": "function_call",
                    "name": "ask",
                    "arguments": json_dumps({
                        "recipient": "product",
                        "question": "Clarify requirements",
                        "background": "Engineering question",
                        "expected": "Confirmation",
                    }),
                }])
            return delivery_turn()(request)
        if request.department == "quality":
            return review_turn("release", "host checks passed")(request)
        if count == 0:
            return read_file_call(request, "large.txt")
        if request.session_id.startswith("ses_ask_"):
            call_id = f"ans-{request.activation_id}-{request.step_id}"
            return ModelResponse(output=[{
                "id": call_id,
                "call_id": call_id,
                "type": "function_call",
                "name": "answer",
                "arguments": json_dumps({
                    "answer": "The original requirements remain applicable.",
                }),
            }])
        if reject_first_spec and not rejected_spec:
            rejected_spec = True
            return product_spec() | {"acceptance_criteria": []}
        return product_spec()

    # 脚本按部门给出（工单 #557、#888）：PRD 被接纳以后工程与质检同时开始一轮工作，
    # 一条按先后排队的列表脚本被两个部门取用时谁拿到哪一项随调度变化。
    # 同一个回答函数按请求里的部门与轮次决定做什么，各部门各取自己的一份
    adapter = FakeAdapter({department: [respond] * 100
                           for department in ("product", "engineering", "quality")})
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=step_limits)
    original = "  Original intent\r\nDo not rewrite this. \n"
    run_id = system.create_run(original, context_window=6000)
    system.workspace(run_id).write_file("large.txt", "FIRST_TOOL_ORIGINAL " * 2200)
    return system, adapter, run_id, original

def pinned_input_tokens(system: LoopSystem, run_id: str, department: str = "product") -> int:
    # 固定材料（部门提示、规则、提案合同、工具清单）的实测 token 估算；依赖总长度的测试由它推出窗口。
    # 窗口取足够大的值，避免装配本身因窗口失败；历史为空，只测不带历史时一次工作请求的输入
    text = DEFINITIONS.role(department).prompt
    prompt_ref = save_department_prompt(system.artifacts, run_id, department, text)
    prompt = DepartmentPrompt(department, 0, text, prompt_ref, "")
    projection = system.project(run_id)
    session = projection.sessions[department]
    assembled = ContextAssembler(system.artifacts, tightening=WATCHED_OUTPUTS).assemble(
        projection, department=department, session_id=session.session_id, activation_id="pinned",
        prompt=prompt, context_window=1_000_000, max_output_tokens=1_000_000)
    return assembled.manifest.input_token_estimate
