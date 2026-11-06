# 基础规则第三条的后半：每个工具开始事件之前有一条允许的许可记录。
#
# 工具许可（adjudication.tool_permission）本身不写入，只在内存里判断；它允许以后才开始执行，
# 许可留下的痕迹就是同一次调用里写在工具开始事件之前的那条记录。因此可断言的命题是：
# 每次工具开始都能在同一调用上找到允许它的许可判断——执行环境工具的记录是 tool_started，
# 主机提交类工具的记录在同一次调用里有提交类提案事件；被拒绝的调用没有工具开始事件，
# 只有带拒绝原因的调用结果或跳过记录。
#
# 对全部事件序列基准执行：基准是真实运行录下来的事件序列（44 个场景），
# 读静态文件，不重跑运行，属于单元层。
#
# 试用工具的启动方式核对（工单 #1497）：`tool_permission` 直接拒绝五种调用——`trial_start` 的启动方式
# 形状不对、`trial_open` 的名称不在当前交付说明里、交付说明没有写启动方式、执行位置的系统没有对应命令、
# 桌面种类；原因文字与执行侧执行之前的再核对相同，两侧用的是 `launch_rules.py` 里的同一份规则。

import json
from pathlib import Path

import pytest

from harness.actions import WorkspaceFacts
from harness.adjudication import WorkBasis, tool_permission
from harness.definitions import DEFINITIONS
from harness.launch_rules import current_system, normalize_launch, resolve_trial_launch, select_command
from harness.minimal_projection import MinimalProjection
from harness.models import ArtifactRef, DeliverySpec, RunProjection
from harness.tightening import WATCHED_OUTPUTS
from harness.validation import AdjudicationView

BASELINE_DIR = Path(__file__).resolve().parents[1] / "event_sequences"
# 计费用的 provider_usage 不是一次工具调用，没有许可判断，也没有工具开始事件
_ACCOUNTING = "provider_usage"
# 被拒绝的调用留下的痕迹：调用结果带原因，或调用被跳过
_STARTED = "tool_started"
_CALLED = "tool_called"
_SKIPPED = "tool_skipped"


def _baselines():
    files = sorted(BASELINE_DIR.glob("*.json"))
    assert files, f"{BASELINE_DIR} 里没有事件序列基准"
    return files


def _payload(event: dict) -> dict:
    return event.get("payload") or {}


def _call_key(payload: dict) -> tuple:
    # 同一次逻辑调用：部门激活、步骤与调用编号（工单 #307 的逻辑调用编号跨重试不变）
    return (payload.get("activation_id"), payload.get("step_id"), payload.get("id"))


def test_every_baseline_recorded_tool_calls():
    # 有些场景在第一次工具调用以前就结束（上下文超限、模型服务故障），没有工具开始事件是正常的；
    # 这里核对全部基线都录到事件，并且至少有一个场景确实被允许过工具调用
    started_any = False
    for path in _baselines():
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document["events"], f"{path.name} 没有录到事件"
        started_any = started_any or _STARTED in {event["type"] for event in document["events"]}
    assert started_any, f"{BASELINE_DIR} 里没有一次被允许的工具调用"


def test_no_tool_call_outside_the_current_work_starts_without_a_permission():
    # 逐个事件顺序核对：任何没有工具开始事件的调用结果都必须是被拒绝（有原因）或被跳过，
    # 不存在「执行了却没有许可」的调用
    for path in _baselines():
        document = json.loads(path.read_text(encoding="utf-8"))
        started: set[tuple] = set()
        for event in document["events"]:
            payload = _payload(event)
            if event["type"] == _STARTED:
                started.add(_call_key(payload))
                continue
            if event["type"] == _SKIPPED:
                assert _call_key(payload) not in started, \
                    f"{path.name} 的 {_SKIPPED} {payload.get('name')!r} 之前已经有工具开始事件"
                continue
            if event["type"] != _CALLED or payload.get("name") == _ACCOUNTING:
                continue
            if _call_key(payload) in started:
                continue
            # 没有许可记录：只能是拒绝并说明原因，或者调用结果本身没有成功
            assert payload.get("error"), (
                f"{path.name} 的调用 {payload.get('name')!r}（调用编号 {payload.get('id')!r}）"
                f"之前没有工具开始事件，也没有拒绝原因；ok={payload.get('ok')!r}"
            )
            assert payload.get("ok") is False, \
                f"{path.name} 的调用 {payload.get('name')!r} 没有许可记录却报告成功"


def test_every_started_tool_call_reports_its_result():
    # 反向核对：每个工具开始都有对应的调用结果；执行中途被取消时是跳过记录
    for path in _baselines():
        document = json.loads(path.read_text(encoding="utf-8"))
        started: list[tuple] = []
        settled: set[tuple] = set()
        for event in document["events"]:
            payload = _payload(event)
            if event["type"] == _STARTED:
                started.append(_call_key(payload))
            elif event["type"] in (_CALLED, _SKIPPED) and payload.get("name") != _ACCOUNTING:
                key = _call_key(payload)
                if key in started:
                    settled.add(key)
        unsettled = [key for key in started if key not in settled]
        assert not unsettled, f"{path.name} 的工具开始没有对应的调用结果或跳过记录：{unsettled}"


# ---- 试用工具的启动方式核对（工单 #1497）----

def _launch(*, name: str = "web", kind: str = "web", systems: tuple[str, ...] | None = None,
            ready_url: str | None = "http://127.0.0.1:{port}/") -> dict:
    # 一个形状正确的启动方式；systems 只用其中这些系统的命令
    system = current_system()
    covered = systems or ((system,) if system else ("windows", "linux"))
    commands = {item: {"windows": ["cmd", "/c", "npm start"], "linux": ["npm", "start"]}[item]
                for item in covered}
    return {"name": name, "kind": kind, "commands": commands, "ready_url": ready_url}


def _delivery(launch: list[dict]) -> DeliverySpec:
    # 当前交付说明：只有启动方式这一项与这次核对有关
    return DeliverySpec(
        id="delivery_1", run_id="run_trial", revision=1, parent_hash=None,
        content_hash="sha256:" + "1" * 64, issuer="engineering", status="active",
        created_event_id="evt_delivery", product_spec_hash="sha256:" + "2" * 64,
        effective_contract_hash="sha256:" + "3" * 64, summary="delivered the trial app",
        files=["src/app.py"], check_names=["smoke"], checks=[], known_risks=[],
        code_tree_digest="sha256:" + "4" * 64,
        tree_ref=ArtifactRef(kind="tree", content_hash="sha256:" + "1" * 64, path="tree"),
        launch=launch)


def _permission(name: str, args: dict, delivery: DeliverySpec | None, department: str):
    # 工具许可直接判断一次试用工具调用：不跑模型、不起运行
    view = AdjudicationView(minimal=MinimalProjection(), state=RunProjection(delivery_spec=delivery))
    return tool_permission(
        view, {"id": "call-trial", "name": name, "args": args}, department=department,
        basis=WorkBasis(effective_contract_hash=None, input_version=0, guidance_version=0),
        aborted=False, facts=WorkspaceFacts(), tightening=WATCHED_OUTPUTS)


def _other_system() -> str:
    system = current_system()
    assert system in {"windows", "linux"}, "启动命令只按 windows 与 linux 给出"
    return "linux" if system == "windows" else "windows"


def test_the_tool_permission_refuses_a_launch_method_of_the_wrong_shape():
    # `trial_start` 给出的启动方式形状不对：工具许可拒绝，原因写明形状的哪一处不对
    refused = _permission("trial_start", {"launch": {"name": "web", "kind": "web", "commands": {}}},
                          None, "engineering")
    assert not refused.allowed and not refused.stopped
    assert refused.reason == "commands must map at least one system to an argv list"


@pytest.mark.parametrize("launch, reason", [
    ("web", "trial_start requires a launch method object"),
    ({}, "kind must be web or desktop"),
    ({"kind": "web", "name": " ", "commands": {"windows": ["npm", "start"]}},
     "name must be a non-empty string"),
    ({"kind": "web", "name": "web", "commands": {"macos": ["npm", "start"]}},
     "commands keys must be windows or linux, not 'macos'"),
    ({"kind": "web", "name": "web", "commands": {"windows": []}},
     "commands.windows must be a non-empty list of non-empty strings"),
    ({"kind": "web", "name": "web", "commands": {"windows": ["npm", "start"]}},
     "a web app requires a ready_url containing {port}"),
])
def test_the_tool_permission_refuses_every_other_wrong_shape_of_a_launch(launch, reason):
    # 形状核对的每一支都在工具许可里给出自己的原因，调用不交给执行环境
    refused = _permission("trial_start", {"launch": launch}, None, "engineering")
    assert not refused.allowed and not refused.stopped
    assert refused.reason == reason


def test_the_launch_rule_only_starts_the_two_trial_tools():
    # 共用规则只处理建立会话的两个工具：别的工具名不建立会话（`TRIAL_TOOLS` 之外的调用不会被工具许可送到这里）
    launch, reason = resolve_trial_launch("trial_stop", {}, [])
    assert launch is None and reason == "trial_stop does not start a trial session"


def test_normalize_launch_fills_the_default_timeout_and_strips_the_name():
    # 执行侧建立会话之前按共用规则再规范化一次：名称去掉首尾空白，没有就绪时限时取规则登记的默认值
    normalized = normalize_launch({"name": " web ", "kind": "web", "commands": {"linux": ["npm", "start"]},
                                   "ready_url": "http://127.0.0.1:{port}/"})
    assert normalized["name"] == "web"
    assert normalized["ready_timeout_sec"] == DEFINITIONS.rule_value("execution.readiness_timeout_sec")


def test_normalize_launch_refuses_the_shapes_the_shared_rule_refuses():
    # 形状与就绪时限的界限只有一份：执行侧再规范化时用的是同一份核对，拒绝的原因与工具许可相同
    cases = [
        ("web", "a launch method must be an object"),
        ({"kind": "web"}, "name must be a non-empty string"),
        ({"kind": "desktop", "name": "app", "commands": {"linux": ["run"]},
          "ready_url": "http://127.0.0.1:{port}/"}, "a desktop program has no ready_url"),
        ({"kind": "web", "name": "web", "commands": {"linux": ["npm", "start"]},
          "ready_url": "http://127.0.0.1:{port}/", "ready_timeout_sec": 1801},
         "ready_timeout_sec must be an integer between 10 and 1800"),
        ({"kind": "web", "name": "web", "commands": {"linux": ["npm", "start"]},
          "ready_url": "http://127.0.0.1:{port}/", "ready_timeout_sec": "300"},
         "ready_timeout_sec must be an integer between 10 and 1800"),
    ]
    for raw, reason in cases:
        with pytest.raises(ValueError) as refused:
            normalize_launch(raw)
        assert str(refused.value) == reason, raw


def test_select_command_picks_the_argv_of_this_system_and_refuses_the_others():
    # 选命令的规则也在这份共用规则里：没有系统、没有这个系统的命令时给出原因
    launch = {"commands": {"windows": ["cmd", "/c", "npm start"], "linux": ["npm", "start"]}}
    assert select_command(launch, "linux") == ["npm", "start"]
    with pytest.raises(ValueError) as no_system:
        select_command(launch, None)
    assert str(no_system.value) == "this execution location has no system from which to choose a launch command"
    with pytest.raises(ValueError) as no_command:
        select_command(launch, "macos")
    assert str(no_command.value) == ("the launch method has no command for macos; "
                                     "commands cover: linux, windows")


def test_the_tool_permission_refuses_a_trial_open_name_the_delivery_spec_does_not_carry():
    # `trial_open` 的名称不在当前交付说明里：原因写明交付说明中已有的名称
    refused = _permission("trial_open", {"launch_name": "missing"}, _delivery([_launch(name="web")]),
                          "quality")
    assert not refused.allowed and not refused.stopped
    assert refused.reason == ("the DeliverySpec has no launch method named 'missing'; it carries: web")


def test_the_tool_permission_refuses_a_trial_open_without_a_delivery_launch_method():
    # 当前交付说明没有写启动方式（没有交付，或者交付的 launch 为空）：按同一个原因拒绝
    for delivery in (None, _delivery([])):
        refused = _permission("trial_open", {"launch_name": "web"}, delivery, "quality")
        assert not refused.allowed and not refused.stopped
        assert refused.reason == "the DeliverySpec has no launch method"


def test_the_tool_permission_refuses_a_launch_without_a_command_for_this_system():
    # 执行位置的系统没有对应的命令：原因写明缺哪个系统、现有命令覆盖哪些系统
    other = _other_system()
    refused = _permission("trial_start", {"launch": _launch(systems=(other,))}, None, "engineering")
    assert not refused.allowed and not refused.stopped
    assert refused.reason == (f"the launch method has no command for {current_system()}; "
                              f"commands cover: {other}")


def test_the_tool_permission_refuses_a_desktop_trial_launch():
    # 桌面种类的试用会话在本机版还没有接上：形状与命令都合格时仍拒绝
    refused = _permission("trial_start", {"launch": _launch(kind="desktop", ready_url=None)}, None,
                          "engineering")
    assert not refused.allowed and not refused.stopped
    assert refused.reason == "desktop trial sessions are not available in this build"


def test_the_tool_permission_and_the_execution_side_check_the_launch_the_same_way():
    # 验收第 3 条：同一组输入，U 的核对与执行侧执行之前的再核对给出同样的启动方式或同样的原因。
    # 执行侧（environment 的 `_trial_start`、`_trial_open`）在动作执行之前用同一个 `resolve_trial_launch`
    # 按当前交付说明的启动方式再核对一次；两侧是同一份规则，任何一侧另写一份核对，这条用例就失败
    good = _launch()
    delivery = _delivery([good])
    cases = [
        ("engineering", "trial_start", {"launch": good}, None),
        ("engineering", "trial_start", {"launch": {"name": "web", "kind": "web", "commands": {}}}, None),
        ("engineering", "trial_start", {"launch": {"name": "web", "kind": "web"}}, None),
        ("engineering", "trial_start", {"launch": _launch(systems=(_other_system(),))}, None),
        ("engineering", "trial_start", {"launch": _launch(kind="desktop", ready_url=None)}, None),
        ("quality", "trial_open", {"launch_name": "web"}, delivery),
        ("quality", "trial_open", {"launch_name": "missing"}, delivery),
        ("quality", "trial_open", {"launch_name": "web"}, _delivery([])),
        ("quality", "trial_open", {"launch_name": "web"}, None),
    ]
    for department, name, args, spec in cases:
        permission = _permission(name, args, spec, department)
        launch, reason = resolve_trial_launch(name, args, spec.launch if spec is not None else [])
        assert permission.reason == reason, (name, args)
        assert permission.allowed == (launch is not None), (name, args)