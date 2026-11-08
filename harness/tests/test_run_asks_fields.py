# 工单 #1637：run.asks 带回答的事实与解释、询问的背景与期望（应用层与接口层设计说明「项目页四层读哪个查询」
# 第 3 项；循环结构设计说明「询问的记录与查询」「工程与质检之间的问答：事实与解释」；总图第四节「接口」缝）。
# 这四样都已经在询问的开始与回答事件里，这张单只把它读出来给页面：四项与事件里的原文一致，事实与解释是分开的两个
# 字段；旧事件没有这些字段时为空，不报错。
#
# 模块层：在真实的事件库里经写入口写入这两条事件（SQLite 事件库，不调用模型、不起目录、不连网络），经应用层的查询读出。
# 守 R2（查询交换的字段：只增、旧事件读得懂）与 R3（询问与回答经查询看得见）。

from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.app.project_queries import RunAsks
from harness.event_store import run_stream
from harness.models import EventType
from harness.runtime import LoopSystem
from harness.write_path import NewEvent

# 质检问工程：询问带背景与期望（#554 起，询问的开始事件写这两个字段）
ASK = {
    "requester": "quality",
    "recipient": "engineering",
    "question": "执行入口在哪里？",
    "background": "质检核对交付之前",
    "expected": "指出入口与运行方式",
    "branch_session_id": "ses_ask_eng_1",
}
# 工程的回答分事实与解释两段（#554）
ANSWER = {
    "requester": "quality",
    "recipient": "engineering",
    "status": "answered",
    "answer": "入口是 python -m echo。",
    "reason": "",
    "with_spec_revision": False,
    "revision": None,
    "facts": "入口：python -m echo；文件：src/echo.py",
    "explanation": "这样实现是因为产品要求单文件命令行。",
}


def _system(data_dir):
    # 一个有事项与 run 的测试系统（与 run.steps 的夹具同一个做法），事件由用例自己写
    system = LoopSystem.for_testing(data_dir, FakeAdapter([]))
    project_id = system.projects.register("询问的字段", "核对 run.asks 的字段")
    _work_item_id, run_id = system.projects.start_work_item(project_id, "读一次询问")
    return system, run_id


def _append(system, run_id, event_type, *, session_id, department, payload):
    return system.writes.append(run_stream(run_id), NewEvent(
        event_type, actor=f"department:{department}", department=department,
        state_before="running", state_after="running", session_id=session_id, payload=payload))[0]


def _asks(system, run_id):
    return Application(system).query("run.asks", RunAsks(run_id=run_id)).data.asks


def _events(system, run_id, event_type):
    return [event for event in system.store.list_events(run_id) if event.type == event_type]


def test_the_answer_facts_and_explanation_are_two_fields_matching_the_events(data_dir):
    # 验收一：工程回答质检的询问，run.asks 里事实与解释是分开的两个字段，内容和事件一致。
    # 验收二前半：询问带背景与期望时读得到——还包括一次还没有回答的询问（循环图上开着的那条虚线）
    system, run_id = _system(data_dir)
    _append(system, run_id, EventType.ASK_STARTED, session_id="ses_qua_2", department="quality",
            payload={**ASK, "question": "参数错误怎么处理？", "branch_session_id": "ses_ask_eng_2"})
    _append(system, run_id, EventType.ASK_STARTED, session_id="ses_qua_1", department="quality",
            payload=dict(ASK))
    _append(system, run_id, EventType.ASK_ANSWERED, session_id="ses_ask_eng_1", department="engineering",
            payload=dict(ANSWER))

    by_question = {ask.question: ask for ask in _asks(system, run_id)}
    answered_ask = by_question[ASK["question"]]
    open_ask = by_question["参数错误怎么处理？"]
    started_events = _events(system, run_id, EventType.ASK_STARTED)
    [answered_event] = _events(system, run_id, EventType.ASK_ANSWERED)
    answered_started = next(event for event in started_events
                            if event.payload["branch_session_id"] == answered_ask.id)

    assert answered_ask.status == "已回答"
    # 回答的正文照旧，事实与解释各在事件的原文里，没有拼成一段
    assert answered_ask.answer == answered_event.payload["answer"]
    assert answered_ask.answer_facts == answered_event.payload["facts"] == ANSWER["facts"]
    assert answered_ask.answer_explanation == answered_event.payload["explanation"] == ANSWER["explanation"]
    assert ANSWER["explanation"] not in answered_ask.answer_facts
    assert ANSWER["facts"] not in answered_ask.answer_explanation
    # 询问的背景与期望来自询问开始事件
    assert answered_ask.background == answered_started.payload["background"] == ASK["background"]
    assert answered_ask.expected == answered_started.payload["expected"] == ASK["expected"]

    # 还没回答的询问：背景与期望已在，回答的两段为空
    assert open_ask.status == "进行中"
    assert open_ask.background == "质检核对交付之前"
    assert open_ask.expected == "指出入口与运行方式"
    assert open_ask.answer is None
    assert open_ask.answer_facts is None
    assert open_ask.answer_explanation is None


def test_old_events_without_these_fields_read_as_empty(data_dir):
    # 验收二后半：老事件没有这些字段时为空，不报错——询问的开始事件早于 #554（没有背景与期望），
    # 回答事件也早于 #554（没有事实与解释），其余字段照旧读出
    system, run_id = _system(data_dir)
    _append(system, run_id, EventType.ASK_STARTED, session_id="ses_qua_1", department="quality",
            payload={"requester": "quality", "recipient": "engineering", "question": "执行入口在哪里？",
                     "branch_session_id": "ses_ask_eng_1"})
    _append(system, run_id, EventType.ASK_ANSWERED, session_id="ses_ask_eng_1", department="engineering",
            payload={"requester": "quality", "recipient": "engineering", "status": "answered",
                     "answer": "入口是 python -m echo。", "reason": "", "with_spec_revision": False,
                     "revision": None})

    [ask] = _asks(system, run_id)
    assert ask.status == "已回答"
    assert ask.answer == "入口是 python -m echo。"
    assert ask.background is None
    assert ask.expected is None
    assert ask.answer_facts is None
    assert ask.answer_explanation is None
