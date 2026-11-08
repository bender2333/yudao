# 接入清单上的每个条目都要有读它的消费者（工单 #1582，接替 #1483 删掉的
# test_every_registered_rule_has_a_wiring_conclusion；规则登记与参数 docs/design/rules-and-parameters.md
# 「规则登记」「参数怎样成为带版本的数据」；总图第二节「定义」、第四节「定义」缝）。
#
# 这个文件查三件事：
# 1. 已接入的条目与读它的位置一一对应：清单外多一条或少一条都失败；parameter 条目不能只列「读定义初值」的
#    位置——这正是 #1582 的缺陷：browser.call_timeout_sec 标为已接入，实际只读定义文件里的初值，参数事件
#    改不了它；
# 2. browser.call_timeout_sec 并入建 run 时冻结的参数字典（选 (a)）：改全局值以后新建 run 的浏览器会话用
#    新值、已建 run 用原值，浏览器会话按冻结值起 ServerLaunch；
# 3. tool_output_limit 的两个读取方（harness/browser.py 的 STRUCTURE_LIMIT、harness/trial_sessions.py 的
#    DEFAULT_OUTPUT_LIMIT）的调用方传入本 run 的冻结值，模块里的初值只是没有冻结值时的回退。
#
# 层：功能与模块层（LoopSystem 与 SQLite 事件库、工作区文件；浏览器与试用会话的启动换成假的 MCP 客户与假的
# 会话表，不启动进程、不连网络）。守 R1（建 run 时冻结、参数事件不影响已建 run）与 R3（阶段二：参数能改且生效）。

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

from harness import fetch
from harness.adapters.fake import FakeAdapter
from harness.artifacts import ArtifactStore
from harness.browser import BrowserProgram, BrowserSessions
from harness.definitions import DEFINITIONS
from harness.environment import LocalEnvironment
from harness.mcp_client import McpClient, ServerLaunch
from harness.parameters import FROZEN_PARAMETERS, NOT_WIRED_REASONS, frozen_run_parameters, wired
from harness.projection import project_run
from harness.runtime import LoopSystem

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Reader:
    """读一个已接入取值的位置：取值从哪里来、在哪个文件里被读。"""

    # frozen：建 run 时冻结的参数字典；current：参数事件折叠出的现值（含 system.parameters()）；
    # definition：定义文件里的取值（structure 条目按它判断）
    kind: Literal["frozen", "current", "definition"]
    location: str


# 接入清单（harness/parameters.py 的 NOT_WIRED_REASONS）里标为已接入的条目，逐条写读它的位置。
# 加一条接入就加一行；清单与本表不一致时 test_every_wired_entry_names_the_code_that_reads_it 失败。
WIRED_READERS: dict[str, tuple[Reader, ...]] = {
    # ---- 建 run 时冻结的取值（harness/parameters.py 的 FROZEN_PARAMETERS）----
    "tool_call_required_limit": (
        Reader("frozen", "harness/orchestrator.py 的 _run_step_limits 读冻结值，交给 harness/engine.py "
                         "的 StepLimits 判定连续几次只回复文字时提醒"),),
    "max_model_steps": (
        Reader("frozen", "harness/orchestrator.py 的 _run_step_limits 读冻结值，作为 harness/engine.py "
                         "这一轮的模型步数上限"),),
    "max_provider_attempts": (
        Reader("frozen", "harness/orchestrator.py 的 _run_step_limits 读冻结值，作为 harness/engine.py "
                         "的重试次数上限"),),
    "retry_initial_delay_sec": (
        Reader("frozen", "harness/orchestrator.py 的 _run_step_limits 读冻结值，作为 harness/engine.py "
                         "的首次重试等待"),),
    "retry_max_delay_sec": (
        Reader("frozen", "harness/orchestrator.py 的 _run_step_limits 读冻结值，作为 harness/engine.py "
                         "的重试等待上限"),),
    "tool_output_limit": (
        Reader("frozen", "harness/environment.py 的 _output_limit 读冻结值（读输出、检查与命令的回执、"
                         "浏览器结构与试用会话的输出上限都从这里取）"),),
    "bash_timeout_default_sec": (
        Reader("frozen", "harness/environment.py 的 bash 命令默认时限（_limit 读冻结值）"),),
    "bash_timeout_max_sec": (
        Reader("frozen", "harness/environment.py 的 bash 命令时限上限（_limit 读冻结值）"),),
    "check_timeout_max_sec": (
        Reader("frozen", "harness/environment.py 的检查时限上限（_limit 读冻结值）"),),
    "compaction.stalled_limit": (
        Reader("frozen", "harness/orchestrator.py 的 _run_step_limits 读冻结值，交给 harness/engine.py "
                         "判定整理连续几次没有推进"),),
    "convergence.rounds": (
        Reader("frozen", "harness/loops.py 的 frozen_convergence_parameters 读冻结值，判定 run 的收敛"),),
    "convergence.step_window": (
        Reader("frozen", "harness/loops.py 的 frozen_convergence_parameters 读冻结值，判定步骤的震荡"),),
    "convergence.step_repeat": (
        Reader("frozen", "harness/loops.py 的 frozen_convergence_parameters 读冻结值，判定步骤的重复"),),
    "browser.call_timeout_sec": (
        Reader("frozen", "harness/environment.py 的 _open_browser 读这个 run 的冻结值，交给 "
                         "harness/browser.py 的 BrowserSessions.start 起 ServerLaunch"),),
    "roles.product.visibility": (
        Reader("frozen", "harness/context.py 的 frozen_visibility 按角色读冻结值，装配只放这个角色看得见的材料"),),
    "roles.engineering.visibility": (
        Reader("frozen", "harness/context.py 的 frozen_visibility 按角色读冻结值，装配只放这个角色看得见的材料"),),
    "roles.quality.visibility": (
        Reader("frozen", "harness/context.py 的 frozen_visibility 按角色读冻结值，装配只放这个角色看得见的材料"),),
    # ---- 用参数现值的地方（参数事件折叠的结果）----
    "run_time_limit_sec": (
        Reader("current", "harness/projects.py 的 ProjectService._limit_values 取参数现值写进事项限额，"
                          "run 按事项记录的限额运行"),),
    "max_cycles": (
        Reader("current", "harness/projects.py 的 ProjectService._limit_values 取参数现值写进事项限额，"
                          "run 按事项记录的轮次上限停止"),),
    "check_timeout_sec": (
        Reader("current", "harness/orchestrator.py 的 create_run 取参数现值（先看项目覆盖）写进 "
                          "run_created 的 check_timeout_sec；harness/parameters.py 的 frozen_check_timeout "
                          "按它读这个 run 的检查时限"),),
    "onboarding.round_time_limit_sec": (
        Reader("current", "harness/projects.py 的 onboarding_round_limit 取参数现值（先看项目覆盖）"),),
    "provider.model_test_max_concurrent": (
        Reader("current", "harness/app/catalog_commands.py 按 system.parameters() 读参数现值，作为模型测试的并发上限"),),
    # ---- 读定义里取值的 structure 条目 ----
    "organization.ask_chain_max_depth": (
        Reader("definition", "harness/adjudication.py 的 ask_chain_max_depth 读定义里的取值，判定询问链的层数"),),
}


def test_every_wired_entry_names_the_code_that_reads_it():
    # 接入清单的已接入集合与读取位置表一一对应（#1582：清单标为已接入、代码没有消费者时在这里失败）
    wired_names = {name for name, reason in NOT_WIRED_REASONS.items() if not reason}
    assert set(WIRED_READERS) == wired_names, (
        f"接入清单与读取位置表不一致：表里多 {sorted(set(WIRED_READERS) - wired_names)}，"
        f"表里少 {sorted(wired_names - set(WIRED_READERS))}")
    for name, readers in WIRED_READERS.items():
        assert readers, f"{name} 标为已接入，但没有列出读它的位置"
        for reader in readers:
            assert reader.location and reader.location.strip() == reader.location, name
            paths = re.findall(r"harness/[\w./-]+\.py", reader.location)
            assert paths, f"{name} 的读取位置没有写明文件：{reader.location}"
            for relative in paths:
                assert (ROOT / relative).is_file(), f"{name} 的读取位置写了不存在的文件：{relative}"


def test_the_wiring_list_decides_every_registered_rule():
    # 接入清单覆盖登记里的全部条目，结论只能是「已接入」或一段可以直接显示的原因（工单 #643 的清单判据）
    assert set(NOT_WIRED_REASONS) == set(DEFINITIONS.rules)
    assert all(reason == reason.strip() for reason in NOT_WIRED_REASONS.values())
    assert all(NOT_WIRED_REASONS[name] for name in NOT_WIRED_REASONS if not wired(name))


def test_a_parameter_is_not_wired_by_reading_the_definition_initial_value():
    # #1582 的缺陷形状：parameter 标为已接入，读它的位置却只有定义文件里的初值，参数事件改不了它
    for name, readers in WIRED_READERS.items():
        rule = DEFINITIONS.rules[name]
        kinds = {reader.kind for reader in readers}
        if rule.kind == "parameter":
            assert kinds & {"frozen", "current"}, (
                f"{name} 标为已接入，但读它的位置里没有现值或冻结值，只有 {sorted(kinds)}")
        else:
            assert "definition" in kinds, f"{name} 是 structure 条目，接入要读定义里的取值：{sorted(kinds)}"


def test_a_frozen_reader_is_a_parameter_of_the_frozen_dictionary():
    # 标为 frozen 的读取位置要求这个条目真的在建 run 时冻结（FROZEN_PARAMETERS）；#1582 之前
    # browser.call_timeout_sec 不在里面，所以这一条先失败
    for name, readers in WIRED_READERS.items():
        if any(reader.kind == "frozen" for reader in readers):
            assert name in FROZEN_PARAMETERS, (
                f"{name} 的读取位置写着冻结值，但它不在建 run 时冻结的参数字典里")


def _system(tmp_path: Path) -> LoopSystem:
    return LoopSystem.for_testing(tmp_path / "loop", FakeAdapter({}))


class _FakeMcpClient:
    # 假的 MCP 客户：记下启动参数，call_tool 交回一段文本（浏览器会话打开就绪地址用到）
    def __init__(self, launch: ServerLaunch) -> None:
        self.launch = launch
        self.info = None
        self.pid = None
        self.process_create_time = None

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        return SimpleNamespace(text=f"{name} result", is_error=False, content=(), cancelled=False)

    async def close(self) -> None:
        pass


def _browser_environment(system: LoopSystem, run_id: str, artifacts: ArtifactStore) -> LocalEnvironment:
    # 这个 run 的执行环境（参数是 run_created 里冻结的那一份）；浏览器会话表换成不用找程序的假表
    environment = system.orchestrator._workspaces.run_environment(run_id)
    environment.browsers = BrowserSessions(
        artifacts, program=BrowserProgram(node="node", cli="playwright-mcp.js"))
    return environment


def _open_browser(environment: LocalEnvironment, copy_root: Path) -> dict[str, Any]:
    # 按试用会话交给浏览器会话的几项起一次会话：不起交付软件、不启动真实 MCP 进程
    copy_root.mkdir(parents=True, exist_ok=True)
    session = {"copy": str(copy_root), "tree_digest": "sha256:" + "0" * 64,
               "ready_url": "http://127.0.0.1:9/", "session_id": "trial-test"}
    return asyncio.run(environment._open_browser(SimpleNamespace(department="engineering"), session))


def test_the_browser_call_timeout_is_the_runs_frozen_value(tmp_path, monkeypatch):
    # 验收第 1 条（选 (a)）：改全局值以后新建 run 的浏览器会话用新值，已建 run 保持原值
    monkeypatch.setattr(fetch, "SERVICE", None)
    launches: list[ServerLaunch] = []

    async def start(launch: ServerLaunch) -> _FakeMcpClient:
        launches.append(launch)
        return _FakeMcpClient(launch)

    monkeypatch.setattr(McpClient, "start", start)
    system = _system(tmp_path)
    try:
        system.set_parameter("browser.call_timeout_sec", 33, reason="冻结核对", modified_by="user:test")
        first = system.create_run("first")
        system.set_parameter("browser.call_timeout_sec", 77, reason="冻结核对", modified_by="user:test")
        second = system.create_run("second")
        artifacts = ArtifactStore(tmp_path / "artifacts")
        first_environment = _browser_environment(system, first, artifacts)
        _open_browser(first_environment, tmp_path / "copy-first")
        second_environment = _browser_environment(system, second, artifacts)
        _open_browser(second_environment, tmp_path / "copy-second")
        # 建 run 之后改全局值：已有 run 的浏览器会话仍按自己的冻结值起 ServerLaunch
        system.set_parameter("browser.call_timeout_sec", 120, reason="冻结核对", modified_by="user:test")
        _open_browser(first_environment, tmp_path / "copy-first-again")

        assert [launch.call_timeout_sec for launch in launches] == [33, 77, 33]
        assert frozen_run_parameters(project_run(system.store, first))["browser.call_timeout_sec"] == 33
    finally:
        system.close()


def test_the_browser_structure_limit_is_the_runs_frozen_output_limit(tmp_path, monkeypatch):
    # 验收第 2 条：tool_output_limit 的读取方 harness/browser.py 的 STRUCTURE_LIMIT 由调用方传入冻结值
    system = _system(tmp_path)
    try:
        system.set_parameter("tool_output_limit", 321, reason="冻结核对", modified_by="user:test")
        run_id = system.create_run("work")
        environment = _browser_environment(system, run_id, ArtifactStore(tmp_path / "artifacts"))
        seen: dict[str, Any] = {}

        async def call(**kwargs: Any) -> dict[str, Any]:
            seen.update(kwargs)
            return {"session": None}

        monkeypatch.setattr(environment.browsers, "call", call)
        action = SimpleNamespace(tool="browser_navigate", department="engineering",
                                 input={"url": "http://example.com/"})
        asyncio.run(environment._browser(action, None))
        assert seen["structure_limit"] == 321
    finally:
        system.close()


def test_the_trial_session_output_limit_is_the_runs_frozen_output_limit(tmp_path, monkeypatch):
    # 验收第 2 条：tool_output_limit 的读取方 harness/trial_sessions.py 的 DEFAULT_OUTPUT_LIMIT 由调用方传入冻结值
    system = _system(tmp_path)
    try:
        system.set_parameter("tool_output_limit", 432, reason="冻结核对", modified_by="user:test")
        run_id = system.create_run("work")
        environment = system.orchestrator._workspaces.run_environment(run_id)
        seen: dict[str, Any] = {}

        async def start(**kwargs: Any) -> dict[str, Any]:
            seen.update(kwargs)
            return {"session": {"kind": "cli"}}

        monkeypatch.setattr(environment._trials, "start", start)
        launch = {"name": "web", "kind": "cli", "commands": {}, "ready_url": "http://127.0.0.1:9/",
                  "ready_timeout_sec": 1}
        asyncio.run(environment._start_trial(SimpleNamespace(department="engineering"), launch, None))
        assert seen["output_limit"] == 432
    finally:
        system.close()
