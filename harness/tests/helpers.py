import asyncio
import json
import os
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness.actions import Action, ActionReceipt, Preconditions
from harness.adapters.fake import FakeAdapter
from harness.assembly import ContextAssembly
from harness.context import ContextPart
from harness.engine import StepLimits
from harness.event_store import NewEvent
from harness.models import ArtifactRef, ContextManifest, Event, json_dumps
from harness.proposals import delivery_turn, plan_turn, product_spec, review_turn
from harness.environment import LocalEnvironment
from harness.providers.call import ModelCall, ModelResponse
from harness.runtime import LoopSystem
from harness.tools import TOOL_DEFS

# 测试中的重试间隔缩短到毫秒级，其余参数与正式运行相同
FAST_RETRIES = StepLimits(retry_initial_delay_sec=0.01, retry_max_delay_sec=0.02)


def action(name: str, args: dict[str, Any], *, department: str = "engineering",
           preconditions: Preconditions = Preconditions()) -> Action:
    # 一个环境工具调用的动作合同，动作身份每次不同
    return Action(action_id=f"test:{uuid.uuid4().hex}", kind=TOOL_DEFS[name]["action"], tool=name,
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


# 等待放行的进程（argv 的一项）：在第一个参数给出的目录中写下 started，然后等待同一目录中出现 release（至多 30 秒）
WAIT_FOR_RELEASE = (
    "import pathlib, sys, time; signals = pathlib.Path(sys.argv[1]); "
    "(signals / 'started').write_text('running'); "
    "[time.sleep(0.05) for _ in range(600) if not (signals / 'release').exists()]"
)


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


def happy_script():
    return [
        product_spec(),
        plan_turn(),
        delivery_turn(),
        review_turn("release", "checks passed on the current snapshot"),
    ]


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
    return ContextAssembly(system.artifacts).department_history(system.store.list_events(run_id), department)


def after_event(monkeypatch, system: LoopSystem, event_type: str, action: Callable[[Event], None]) -> None:
    # 某种事件写入以后，在写入它的线程中执行 action：在这个时点插入用户操作（新输入、取消），或者通知测试线程。
    # action 在写入方的线程中执行，此时写入锁仍由写入方持有：同一临界区中这条事件之后的写入都在 action 之后发生，
    # 所以 action 只能挂在所在临界区最后一次写入的事件上；需要等待写入锁的操作不能在 action 中等待它完成，
    # 要表示「来自其他线程、在这个临界区结束时到达」的操作，用 start_waiting_for_writes
    writes = system.orchestrator.writes
    append = writes.append

    def append_then_act(run_id: str, *events: NewEvent) -> list[Event]:
        written = append(run_id, *events)
        for event in written:
            if event.type == event_type:
                action(event)
        return written

    monkeypatch.setattr(writes, "append", append_then_act)


class WaitingOperation:
    # 另一个线程中的一个操作（取消、新输入、指导等），在写入锁上等待；join 以后 errors 是它抛出的异常
    def __init__(self, operation: Callable[[], Any]) -> None:
        self.errors: list[Exception] = []
        started = threading.Event()

        def run() -> None:
            started.set()
            try:
                operation()
            except Exception as exc:
                self.errors.append(exc)

        self.thread = threading.Thread(target=run)
        self.thread.start()
        assert started.wait(5)

    def join(self) -> None:
        self.thread.join(10)
        assert not self.thread.is_alive()


def start_waiting_for_writes(operation: Callable[[], Any]) -> WaitingOperation:
    # 在 after_event 的 action 中调用（写入锁由写入方持有）：操作在另一个线程开始并在写入锁上等待，
    # 写入方的临界区结束时写入锁交给它，先于写入方之后再次取得写入锁的操作。
    # 依赖 CPython 3.13 起的锁：等待超过 1 毫秒的线程在锁释放时直接得到锁
    waiting = WaitingOperation(operation)
    time.sleep(0.1)
    return waiting
