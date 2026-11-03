# 压缩以后的失败清单（工单 #1405，设计说明「压缩以后保留失败的尝试」）：这一段是事件上的纯函数，
# 不读临时目录、不起进程、不连网络，结论只依赖交给它的事件与两个上限，登记为单元层。
#
# 测试按三环留（docs/design/test-pyramid.md 第 13 节）：
# - R2（合同）：两个上限读规则登记的现值，规则版本随 Rules 的取值变化；
# - R3（路线图已走到）：压缩保留失败的尝试——失败的工具调用、被拒绝的提案与没有通过的检查各列一条，
#   用事件编号取回的原文与事件里的相同；后来做成的标「后来已解决」；超出上限时按设计说明的顺序合并，
#   最新的未解决失败留在清单里；只给这个角色自己。

import json

from harness.definitions import DEFINITIONS
from harness.failure_list import (FAILURE_LIST, MERGED_EARLIER, MERGED_RESOLVED, failure_list, tool_result)
from harness.models import Event, EventType, json_dumps

ENGINEERING = "engineering"
QUALITY = "quality"


def _event(position, type_, *, department=ENGINEERING, payload=None):
    # 一条事件的完整信封：失败清单只读种类、部门、事件编号、位置与载荷
    return Event(
        event_id=f"evt_{position:016x}", run_id="run_1", type=type_, role=None, parent_event_id=None,
        state_before="running", state_after="running", payload=payload or {}, artifact_hashes=[],
        session_id="ses_engineering", provider=None, model=None, context_digest=None, stop_reason=None,
        error=None, created_at="2026-11-03T00:00:00+00:00", position=position, stream="run_1",
        stream_version=position, project_id=None, work_item_id=None, department=department,
    )


def _tool_event(position, *, name, args, ok, output=None, error=None, department=ENGINEERING, type_=None):
    # 工具结果事件：部门历史里的那一条（input_item）带着 ok、output、error 三项
    result = {"ok": ok, "output": output, "error": error}
    return _event(position, type_ or EventType.TOOL_CALLED, department=department, payload={
        "name": name, "args": args, "ok": ok, "error": error,
        "input_item": {"type": "function_call_output", "call_id": f"call-{position}",
                       "output": json_dumps(result)},
    })


def _receipt(name, exit_code, *, summary="host-executed command=uv run pytest exit=1\n2 failed, 3 passed",
             snapshot="sha256:" + "a" * 64, tree_changed=False):
    return {"name": name, "exit_code": exit_code, "summary": summary, "snapshot_hash": snapshot,
            "executor": "host", "tree_changed": tree_changed}


def _failed_read(position, *, path="missing.txt", error=None):
    return _tool_event(position, name="read_file", args={"path": path}, ok=False,
                       error=error or f"no such file: {path}")


def _rejected(position, *, kind="delivery_spec", message="check_names must name receipts from this activation"):
    return _event(position, EventType.PROPOSAL_REJECTED, payload={
        "kind": kind, "errors": [{"field": "check_names", "message": message}]})


def _failed_check(position, *, name="smoke", exit_code=1, snapshot="sha256:" + "a" * 64,
                  department=ENGINEERING):
    return _tool_event(position, name="run_check", args={"name": name, "command": "uv run pytest"},
                       ok=True, output=_receipt(name, exit_code, snapshot=snapshot), department=department)


def _received(event):
    # 事件载荷里 tool_result 那一段（ok、output、error），清单里的原文从它来
    return json.loads(event.payload["input_item"]["output"])


def _listing(events, *, boundary=None, department=ENGINEERING, limit_tokens=4000, entry_chars=400):
    return failure_list(events, department=department,
                        boundary_event_id=(events[-1].event_id if boundary is None else boundary),
                        limit_tokens=limit_tokens, entry_chars=entry_chars)


def _payload_of(listing):
    return json.loads(listing.item["content"].split("\n", 1)[1])


def test_a_failed_tool_call_a_rejected_proposal_and_a_failed_check_are_listed_with_their_events():
    """一次失败的工具调用、一次被拒绝的提案、一次没有通过的检查：逐条列出做法、失败原因与事件编号。"""
    failed_read = _failed_read(2)
    rejected = _rejected(3)
    failed_check = _failed_check(4)
    events = [_event(1, EventType.DEPARTMENT_INPUT), failed_read, rejected, failed_check]

    listing = _listing(events)

    assert [failure.event_id for failure in listing.failures] == [
        failed_read.event_id, rejected.event_id, failed_check.event_id,
    ]
    assert [failure.kind for failure in listing.failures] == ["tool", "proposal", "check"]
    assert [failure.resolved for failure in listing.failures] == [False, False, False]
    # 做了什么：工具与参数、提案种类、检查名称
    assert listing.failures[0].did == 'read_file {"path":"missing.txt"}'
    assert listing.failures[1].did == "提案 delivery_spec"
    assert listing.failures[2].did == "检查 smoke"
    # 怎么失败的：错误原文、拒绝原因、失败输出的开头
    assert listing.failures[0].failure == "no such file: missing.txt"
    assert listing.failures[1].failure == "check_names must name receipts from this activation"
    assert listing.failures[2].failure.startswith("退出码 1：host-executed command=uv run pytest")
    # 用事件编号取回的原文与事件里的相同
    assert tool_result(failed_read)["error"] == listing.failures[0].failure
    assert _received(failed_read)["error"] == listing.failures[0].failure
    assert rejected.payload["errors"][0]["message"] == listing.failures[1].failure
    assert _received(failed_check)["output"]["summary"] == listing.failures[2].failure.split("：", 1)[1]


def test_the_section_is_one_history_item_after_the_summary_slot_and_names_the_listed_events():
    failed_read = _failed_read(2)
    listing = _listing([_event(1, EventType.DEPARTMENT_INPUT), failed_read])

    assert listing.item["role"] == "user"
    assert listing.item["content"].startswith(f"[{FAILURE_LIST}]\n")
    assert _payload_of(listing)["failures"] == [{
        "did": 'read_file {"path":"missing.txt"}', "event_id": failed_read.event_id,
        "failure": "no such file: missing.txt", "resolved": False,
    }]
    # 这一段逐条列了哪些事件由清单记进 context_assembled
    assert listing.event_ids == (failed_read.event_id,)


def test_failures_after_the_boundary_stay_in_recent_rounds_and_are_not_listed():
    """分界之后的失败留在近期回合里，这里不重复列；还没有分界时（没有检查点）不生成这一段。"""
    before = _failed_read(2)
    after = _failed_read(3, path="later.txt")
    events = [_event(1, EventType.DEPARTMENT_INPUT), before, after]

    listing = _listing(events, boundary=before.event_id)
    assert [failure.event_id for failure in listing.failures] == [before.event_id]
    assert failure_list(events, department=ENGINEERING, boundary_event_id=None,
                        limit_tokens=4000, entry_chars=400) is None
    # 分界指到不在这份事件里的事件：宁可不列，也不把不该列的事件列一遍
    assert failure_list(events, department=ENGINEERING, boundary_event_id="evt_elsewhere",
                        limit_tokens=4000, entry_chars=400) is None


def test_no_failure_means_no_section_at_all():
    """没有失败的会话压缩以后不生成这一段：清单为 None，历史里只有摘要与近期回合。"""
    events = [_event(1, EventType.DEPARTMENT_INPUT),
              _tool_event(2, name="read_file", args={"path": "README.md"}, ok=True, output="text")]
    assert _listing(events) is None


def test_a_second_compaction_still_lists_the_failures_before_the_first_boundary():
    """同一会话连续压缩两次：第一次分界之前的失败在第二次压缩以后的清单里仍按原文出现。"""
    first = _failed_read(2)
    events = [_event(1, EventType.DEPARTMENT_INPUT), first, _event(3, EventType.DEPARTMENT_INPUT),
              _failed_check(4)]
    first_boundary = events[2].event_id
    second_boundary = events[-1].event_id

    one = _listing(events, boundary=first_boundary)
    two = _listing(events, boundary=second_boundary)
    assert [failure.event_id for failure in one.failures] == [first.event_id]
    assert [failure.event_id for failure in two.failures] == [first.event_id, events[-1].event_id]
    assert two.failures[0] == one.failures[0]
    assert tool_result(first)["error"] == two.failures[0].failure


def test_a_failure_is_marked_resolved_when_the_same_thing_later_succeeds():
    """后来做成的失败标「后来已解决」：同名的检查在较新的快照上通过、同一种提案后来被接纳、
    同一工具以同样的参数后来成功。"""
    failed_check = _failed_check(2, name="smoke", snapshot="sha256:" + "a" * 64)
    passed_check = _failed_check(3, name="smoke", exit_code=0, snapshot="sha256:" + "b" * 64)
    rejected = _rejected(4)
    accepted = _event(5, EventType.DELIVERY_ACCEPTED, payload={"kind": "delivery_spec", "id": "d-1"})
    failed_read = _failed_read(6)
    successful_read = _tool_event(7, name="read_file", args={"path": "missing.txt"}, ok=True, output="text")

    listing = _listing([_event(1, EventType.DEPARTMENT_INPUT), failed_check, passed_check, rejected, accepted,
                        failed_read, successful_read])
    assert [failure.kind for failure in listing.failures] == ["check", "proposal", "tool"]
    assert [failure.resolved for failure in listing.failures] == [True, True, True]
    assert [item["resolved"] for item in _payload_of(listing)["failures"]] == [True, True, True]


def test_a_check_that_passes_on_the_same_snapshot_or_another_check_does_not_resolve_it():
    """同名的检查在同一个快照上再跑一次通过，或者别的检查名通过，都不算「后来做成」。"""
    failed_check = _failed_check(2, name="smoke", snapshot="sha256:" + "a" * 64)
    same_snapshot = _failed_check(3, name="smoke", exit_code=0, snapshot="sha256:" + "a" * 64)
    other_name = _failed_check(4, name="lint", exit_code=0, snapshot="sha256:" + "b" * 64)

    listing = _listing([_event(1, EventType.DEPARTMENT_INPUT), failed_check, same_snapshot, other_name])
    assert [failure.resolved for failure in listing.failures] == [False]


def test_a_different_proposal_kind_or_a_different_tool_call_does_not_resolve_the_failure():
    rejected = _rejected(2, kind="delivery_spec")
    other_kind = _event(3, EventType.SPEC_ACCEPTED, payload={"kind": "product_spec"})
    failed_read = _failed_read(4, path="missing.txt")
    other_args = _tool_event(5, name="read_file", args={"path": "README.md"}, ok=True, output="text")
    same_call_still_failing = _tool_event(6, name="read_file", args={"path": "missing.txt"}, ok=False,
                                          error="no such file: missing.txt")

    listing = _listing([_event(1, EventType.DEPARTMENT_INPUT), rejected, other_kind, failed_read, other_args,
                        same_call_still_failing])
    # 三种失败都在：被拒绝的提案、第一次失败的读取、后来又失败一次的同参数读取；前两条都没有做成
    assert [failure.event_id for failure in listing.failures] == [
        rejected.event_id, failed_read.event_id, same_call_still_failing.event_id,
    ]
    assert [failure.resolved for failure in listing.failures] == [False, False, False]


def test_only_this_role_sees_its_own_failures():
    """只给这个角色自己：核验角色的清单里没有被核验方的失败。"""
    engineering_failure = _failed_read(2)
    quality_failure = _failed_check(3, name="acceptance", department=QUALITY)
    events = [_event(1, EventType.DEPARTMENT_INPUT), engineering_failure,
              _event(2, EventType.DEPARTMENT_INPUT, department=QUALITY), quality_failure]

    quality = _listing(events, department=QUALITY)
    assert [failure.event_id for failure in quality.failures] == [quality_failure.event_id]
    engineering = _listing(events)
    assert [failure.event_id for failure in engineering.failures] == [engineering_failure.event_id]
    assert quality_failure.event_id not in engineering.event_ids


def test_one_failure_entry_is_truncated_to_the_entry_limit():
    """单条失败原文按单条上限截断：开头保留，超出的部分按事件编号取回。"""
    long_error = "BEGIN-" + "z" * 900 + "-END"
    failed = _failed_read(2, error=long_error)
    events = [_event(1, EventType.DEPARTMENT_INPUT), failed]

    listing = _listing(events, entry_chars=400)
    assert len(listing.failures[0].failure) == 400
    assert listing.failures[0].failure.startswith("BEGIN-") and "-END" not in listing.failures[0].failure
    # 改参数以后清单随之变化：上限放到 2000 字符时整段原文都在清单里
    wide = _listing(events, entry_chars=2000)
    assert wide.failures[0].failure == long_error
    # 原文本身仍在事件里，事件编号指向它
    assert tool_result(failed)["error"] == long_error


def _many_failures(count, *, resolved_every=None):
    events = [_event(1, EventType.DEPARTMENT_INPUT)]
    position = 1
    for index in range(count):
        position += 1
        path = f"missing-{index}.txt"
        events.append(_failed_read(position, path=path))
        if resolved_every and index % resolved_every == 0:
            position += 1
            events.append(_tool_event(position, name="read_file", args={"path": path}, ok=True, output="text"))
    return events


def _failed_ids(events):
    return [event.event_id for event in events
            if event.type == EventType.TOOL_CALLED and (event.payload or {}).get("ok") is False]


def test_below_the_limit_every_failure_is_listed_and_nothing_is_merged():
    listing = _listing(_many_failures(3), limit_tokens=4000)
    assert len(listing.failures) == 3
    assert (listing.merged_resolved, listing.merged_earlier) == (0, 0)
    assert "merged" not in _payload_of(listing)


def test_over_the_limit_the_resolved_failures_merge_first_then_the_earliest_unresolved():
    """超出清单上限：先把「后来已解决」的合并成一行，再从最早的未解决失败开始合并，
    最新的未解决失败留在清单里。"""
    events = _many_failures(6, resolved_every=2)
    failed = _failed_ids(events)

    listing = _listing(events, limit_tokens=90)

    # 三个偶数序号的失败后面跟着同参数的成功：它们标「后来已解决」，超限时最先被合并
    assert listing.merged_resolved == 3
    assert listing.merged_earlier > 0
    assert all(not failure.resolved for failure in listing.failures)
    # 最新的未解决失败留在清单里：最早的先被合并掉，条数守恒
    assert listing.failures[-1].event_id == failed[-1]
    assert failed[0] not in {failure.event_id for failure in listing.failures}
    assert len(listing.failures) + listing.merged_resolved + listing.merged_earlier == len(failed)
    assert _payload_of(listing)["merged"] == [
        MERGED_RESOLVED.format(count=3), MERGED_EARLIER.format(count=listing.merged_earlier),
    ]


def test_the_newest_unresolved_failure_survives_even_when_the_list_still_exceeds_the_limit():
    """最新的未解决失败总留在清单里：只剩它一条时不再合并，即使仍然超过上限。"""
    events = _many_failures(4)
    listing = _listing(events, limit_tokens=10)
    assert len(listing.failures) == 1
    assert listing.merged_earlier == 3
    assert listing.failures[0].event_id == events[-1].event_id


def test_the_same_events_and_the_same_limits_give_the_same_bytes():
    """同一份事件与同一版规则装配两次，失败清单逐字节相同，重放不发出模型请求（这里是纯函数）。"""
    events = _many_failures(5, resolved_every=2)
    first = _listing(events)
    second = _listing(events)
    assert json_dumps(first.item) == json_dumps(second.item)
    assert first == second
    # 打乱交给它的顺序不影响结果：清单按事件位置排
    assert json_dumps(_listing(list(reversed(events)), boundary=events[-1].event_id).item) \
        == json_dumps(first.item)


def test_the_two_limits_are_read_from_the_rule_registry():
    """两个上限读规则登记（context-assembly.md「压缩以后保留失败的尝试」），随 Rules 的取值记录版本。"""
    from harness.context import Rules

    rules = Rules()
    assert rules.failure_list_tokens == DEFINITIONS.rule_value("context.failure_list_tokens") == 4000
    assert rules.failure_entry_chars == DEFINITIONS.rule_value("context.failure_entry_chars") == 400
    list_rule = DEFINITIONS.rule("context.failure_list_tokens")
    entry_rule = DEFINITIONS.rule("context.failure_entry_chars")
    assert list(list_rule.bounds) == [1000, 13107] and list(entry_rule.bounds) == [100, 2000]
    assert "context-assembly.md" in list_rule.origin and "压缩以后保留失败的尝试" in list_rule.origin
    assert "context-assembly.md" in entry_rule.origin and "400 字符" in entry_rule.origin
    # 两个上限进规则版本：取值变了就是新的一版
    assert Rules(failure_list_tokens=2000).version() != rules.version()
    assert Rules(failure_entry_chars=800).version() != rules.version()


def test_a_failure_result_without_error_text_still_records_the_failure_output():
    """没有错误文字的失败：写输出本身的开头（被拒绝的工具许可只带原因与输出）。"""
    refused = _tool_event(2, name="write_file", args={"path": "src/a.py"}, ok=False,
                          output={"refused": True, "reason": "the public tree changed"})
    listing = _listing([_event(1, EventType.DEPARTMENT_INPUT), refused])
    assert listing.failures[0].failure == json_dumps(
        {"refused": True, "reason": "the public tree changed"})


def test_a_skipped_tool_call_is_a_failed_tool_result_and_names_its_reason():
    skipped = _tool_event(2, name="read_file", args={"path": "a.txt"}, ok=False,
                          error="Not executed because this activation ended", type_=EventType.TOOL_SKIPPED)
    listing = _listing([_event(1, EventType.DEPARTMENT_INPUT), skipped])
    assert [(failure.kind, failure.failure) for failure in listing.failures] == [
        ("tool", "Not executed because this activation ended")]


def test_two_failures_of_the_same_kind_keep_their_own_event_ids():
    """事件编号是清单与事件之间的凭据：同一种失败出现两次，两条各自带自己的编号。"""
    first = _failed_check(2, name="smoke")
    second = _failed_check(3, name="smoke")
    listing = _listing([_event(1, EventType.DEPARTMENT_INPUT), first, second])
    assert [failure.event_id for failure in listing.failures] == [first.event_id, second.event_id]
    assert len(set(listing.event_ids)) == 2
