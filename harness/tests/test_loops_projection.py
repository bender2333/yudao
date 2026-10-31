# 循环与收敛状态的纯函数投影（工单 #397 的验收）：五层树与步骤归组、四类被接纳事实与三类不计、
# 步骤层的四种判定、三项冻结参数与方法常量、限额只由停止原因判定、不设上限时保留数值。
# 这些结论只读事件与冻结参数，不写事件、不调用模型，登记为单元层。

from harness import loops
from harness.models import Event, EventType
from harness.parameters import FROZEN_PARAMETERS, initial_values


def frozen(**overrides):
    # 建 run 时冻结的参数字典（工单 #1189）：三项收敛判定参数按用例覆盖，其余按定义初值
    values = {name: initial_values()[name] for name in FROZEN_PARAMETERS}
    values.update(overrides)
    return {"values": values}


def event(kind: str, position: int, *, department: str | None = "product", payload: dict | None = None,
          stop_reason: str | None = None) -> Event:
    # 一条 run 事件：测试只关心种类、位置、部门与载荷，其余字段给固定的值
    return Event(
        event_id=f"evt-{position}", run_id="run-1", type=kind, role=None, parent_event_id=None,
        state_before="running", state_after="running", payload=payload or {}, artifact_hashes=[],
        session_id=department, provider=None, model=None, context_digest=None, stop_reason=stop_reason,
        error=None, created_at="2026-10-31T00:00:00+00:00", position=position, stream="run:run-1",
        stream_version=position, project_id="proj-1", work_item_id="wi-1", department=department,
    )


def created(**parameter_overrides) -> Event:
    return event(EventType.RUN_CREATED, 1, department=None, payload={
        "project_id": "proj-1", "work_item_id": "wi-1", "kind": "change",
        "max_cycles": 999999, "run_time_limit_sec": 7200,
        "sessions": {"product": "product", "engineering": "engineering", "quality": "quality"},
        "parameters": frozen(**parameter_overrides),
    })


def activated(position: int, department: str = "product", *, cycle: int | None = None) -> Event:
    payload: dict = {"activation_id": f"act-{position}", "activated_at": "2026-10-31T00:00:00+00:00"}
    if cycle is not None:
        payload["cycle"] = cycle
    return event(EventType.DEPARTMENT_ACTIVATED, position, department=department, payload=payload)


def finished(position: int, department: str = "product", activation_id: str = "act-2") -> Event:
    return event(EventType.ACTIVATION_FINISHED, position, department=department,
                 payload={"activation_id": activation_id, "elapsed_ms": 1000})


def requested(position: int, *, activation_id: str = "act-2", root: int = 1, purpose: str = "work",
              step: int = 1) -> Event:
    return event(EventType.MODEL_REQUESTED, position, payload={
        "activation_id": activation_id, "step_id": step, "root_step_id": root, "attempt": 1,
        "purpose": purpose, "started_at": "2026-10-31T00:00:00+00:00",
    })


def called(position: int, name: str, args: dict, *, ok: bool = True, refused: bool = False) -> Event:
    payload = {"name": name, "args": args, "ok": ok}
    if refused:
        payload["refused"] = True
        payload["refused_reason"] = "许可拒绝"
    return event(EventType.TOOL_CALLED, position, payload=payload)


def done(position: int, stop_reason: str) -> Event:
    return event(EventType.RUN_DONE, position, stop_reason=stop_reason,
                 payload={"stop_reason": stop_reason})


def base_events() -> list[Event]:
    # 一次激活里的两步：step 1 的重试（同一 root_step_id）算一步，step 2 是另一步
    return [created(), activated(2, cycle=1), requested(3, root=1), requested(4, root=1, step=2)]


def test_tree_has_five_layers_and_steps_group_by_one_model_request():
    # 守 R3（五层循环树与步骤归组）：五层按项目循环、事项、run、激活、步骤排；重试与它重试的那一步算一步
    events = base_events()
    events.append(finished(5, activation_id="act-2"))
    tree = loops.build_loop_tree(events)
    assert [layer.name for layer in tree.layers] == ["project_loop", "work_item", "run", "activation", "step"]
    assert [activation.activation_id for activation in tree.activations] == ["act-2"]
    [step] = tree.activations[0].steps
    assert step.step_id == 1 and step.attempts == 2
    assert tree.run_id == "run-1" and tree.project_id == "proj-1" and tree.work_item_id == "wi-1"


def test_four_kinds_of_accepted_facts_count_and_the_rest_do_not():
    # 守 R3（被接纳的主机事实）：成果接纳、检查回执、改变工作区树的写入、询问获答算；失败的写入、
    # 被拒绝的调用、读取、压缩步与失败的模型调用都不算
    events = base_events()
    events += [
        called(5, "run_check", {"command": "pytest"}, ok=True),
        called(6, "write_file", {"path": "a.py"}, ok=True),
        called(7, "write_file", {"path": "b.py"}, ok=False),
        called(8, "read_file", {"path": "a.py"}, ok=True),
        called(9, "run_check", {"command": "pytest"}, ok=False, refused=True),
        event(EventType.ASK_ANSWERED, 10, payload={"requester": "engineering", "recipient": "product"}),
        event(EventType.ARTIFACT_ACCEPTED, 11, payload={"artifact_kind": "delivery_spec"}),
        requested(12, activation_id="act-2", root=3, purpose="compaction", step=3),
    ]
    tree = loops.build_loop_tree(events)
    [first, compaction] = tree.activations[0].steps
    assert [fact.kind for fact in first.facts] == [loops.FACT_CHECK, loops.FACT_WRITE,
                                                  loops.FACT_ANSWER, loops.FACT_ARTIFACT]
    assert first.accepted is True
    # 压缩步不是工作步，也不改变被接纳的事实
    assert compaction.purpose == "compaction" and compaction.accepted is False


def step_events(facts: int, *, repeat: int = 0, stop_reason: str | None = None) -> list[Event]:
    # 一个窗口（默认 8 步）之内的若干步：facts 是末尾几步里有被接纳事实的步数，
    # repeat 是第一步里同一个调用重复的次数
    events: list[Event] = [created(), activated(2, cycle=1)]
    position = 3
    for index in range(8):
        events.append(requested(position, activation_id="act-2", root=index + 1, step=index + 1))
        position += 1
        if index >= 8 - facts:
            events.append(called(position, "write_file", {"path": f"{index}.py"}, ok=True))
            position += 1
        for _ in range(repeat if index == 0 else 0):
            events.append(called(position, "read_file", {"path": "same.py"}, ok=True))
            position += 1
    if stop_reason is not None:
        events.append(done(position, stop_reason))
    return events


def test_step_layer_state_converging_and_stalled():
    # 守 R3（步骤层判定）：窗口（默认 8 步）内有被接纳的记录为收敛中；窗口满了都没有为停滞
    converging = loops.build_loop_tree(step_events(facts=2))
    stalled = loops.build_loop_tree(step_events(facts=0))
    step_layer = {layer.name: layer for layer in converging.layers}["step"]
    assert step_layer.state == loops.CONVERGING and step_layer.missing is None
    assert {layer.name: layer for layer in stalled.layers}["step"].state == loops.STALLED


def test_step_layer_state_oscillating_and_boundary():
    # 守 R3：窗口内同一个调用（名称与参数摘要相同）达到重复次数（默认 3）为震荡；
    # 停止原因属于限额类为达到边界，只看停止原因、不比较数值
    oscillating = step_events(facts=1, repeat=3)
    tree = loops.build_loop_tree(oscillating)
    assert {layer.name: layer for layer in tree.layers}["step"].state == loops.OSCILLATING
    boundary = loops.build_loop_tree(step_events(facts=8, stop_reason="model_steps_exhausted"))
    assert {layer.name: layer for layer in boundary.layers}["step"].state == loops.BOUNDARY


def test_step_layer_is_undetermined_until_a_full_window():
    # 守 R3：步数还没满一个窗口时不判定，写明缺少的事实
    tree = loops.build_loop_tree(base_events())
    step_layer = {layer.name: layer for layer in tree.layers}["step"]
    assert step_layer.state == loops.UNDETERMINED
    assert "窗口" in step_layer.missing


def test_activation_project_and_run_layers_are_undetermined_with_missing_facts():
    # 守 R3：本工单只判步骤层；run 层在 #1194 接入逐条核验数据以后判，激活层与项目层写明缺少的事实
    tree = loops.build_loop_tree(base_events())
    layers = {layer.name: layer for layer in tree.layers}
    # #1194 以后 run 层仍不判定（这份事件流没有逐条核验结论），说明的文字改成「核验角色提交…以后判定」
    assert layers["run"].state == loops.UNDETERMINED and layers["run"].missing == loops.MISSING_RUN
    assert layers["activation"].state == loops.UNDETERMINED and layers["activation"].missing
    assert layers["project_loop"].state == loops.UNDETERMINED and "故障记录" in layers["project_loop"].missing
    assert layers["work_item"].state == loops.UNDETERMINED


def test_frozen_parameters_drive_the_judgement_and_method_constants_stay_fixed():
    # 守 R3（三项参数在实例创建时冻结）：判定用 run_created 里冻结的取值，运行中改全局值不改变已有实例；
    # 方法常量固定为 8 与 2
    events = step_events(facts=2)
    events[0] = created(**{"convergence.step_window": 3})
    tree = loops.build_loop_tree(events)
    assert tree.parameters == {"convergence.rounds": 3, "convergence.step_window": 3,
                               "convergence.step_repeat": 3}
    assert tree.method == {"trend_switch_rounds": 8, "flip_threshold": 2}
    # 冻结窗口为 3：三步之内有被接纳的记录即为收敛中（全局默认窗口是 8，这里证明用的是冻结值）
    assert {layer.name: layer for layer in tree.layers}["step"].state == loops.CONVERGING


def test_amounts_carry_numbers_and_an_unlimited_flag():
    # 守 R3（限额）：上限达到登记界限的上沿、登记说明它拦截不到失败时标为不设上限，同时仍带数值；
    # 运行时间上限没有这一条，保持有限
    events = step_events(facts=1)
    events.append(finished(90, activation_id="act-2"))
    tree = loops.build_loop_tree(events)
    layers = {layer.name: layer for layer in tree.layers}
    model_steps = layers["run"].amounts["model_steps"]
    assert model_steps.unlimited is True and model_steps.limit == 999999 and model_steps.used > 0
    elapsed = layers["run"].amounts["elapsed_ms"]
    assert elapsed.unlimited is False and elapsed.limit == 7200 * 1000 and elapsed.used == 1000
    activations = layers["activation"].amounts["activations"]
    assert activations.unlimited is True and activations.used >= 1


def test_trend_explanation_appears_from_eight_rounds_and_rank_trend_is_the_method():
    # 守 R3：轮数达到 8 改用秩相关的趋势检验；这一格说明的是步骤层的秩相关（run 层的逐条核验结论
    # 由 #1194 的 run_state 判定，不再写进这一格）
    events = [created()]
    position = 2
    for index in range(8):
        events.append(activated(position, cycle=index + 1))
        position += 1
    tree = loops.build_loop_tree(events)
    assert tree.rounds == 8
    assert tree.trend is not None
    assert tree.trend["method"] == "spearman" and tree.trend["switch_rounds"] == 8
    assert tree.trend["flip_threshold"] == 2 and "步骤层" in tree.trend["note"]
    # 严格下降为负、上升为正、并列无趋势
    assert loops.rank_trend([3, 2, 1]) < 0
    assert loops.rank_trend([1, 2, 3]) > 0
    assert loops.rank_trend([2, 2, 2]) == 0
