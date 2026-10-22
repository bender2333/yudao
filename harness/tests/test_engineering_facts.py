# 工程与质检之间问答的事实与解释（工单 #554，验证的独立性设计说明第 4 节）：
# 质检请求里可以放入的工程内容由一个纯函数算出来——事实部分总在，解释部分只在质检对当前交付
# 提交结论以后进入它之后的请求；新的交付到达后按新交付重新计算。
#
# 单元层：只用内存里的事件与交付说明，不起目录、不起进程、不连网络。

from harness.context import engineering_facts_text, quality_engineering_content
from harness.models import ArtifactRef, DeliverySpec, Event, EventType


def _event(position: int, type: str, payload: dict, *, session_id: str | None = None,
           department: str | None = None) -> Event:
    return Event(
        event_id=f"evt_{position}", run_id="run_1", type=type, role=None, parent_event_id=None,
        state_before="QUALITY", state_after="QUALITY", payload=payload, artifact_hashes=[],
        session_id=session_id, provider=None, model=None, context_digest=None, stop_reason=None,
        error=None, created_at="2026-10-24T00:00:00Z", position=position, stream="run_1",
        stream_version=position, project_id=None, work_item_id=None, department=department,
    )


def _delivery(content_hash: str = "sha256:delivery-1") -> DeliverySpec:
    return DeliverySpec(
        id="del_1", run_id="run_1", revision=1, parent_hash=None, content_hash=content_hash,
        issuer="engineering", status="active", created_event_id="evt_1",
        product_spec_hash="sha256:spec-1", effective_contract_hash="sha256:contract-1",
        summary="大写输出", files=["src/echo.py"], check_names=["smoke"], checks=[],
        known_risks=["没有空行结尾"], code_tree_digest="sha256:tree-1",
        tree_ref=ArtifactRef(kind="tree", content_hash=content_hash, path="run_1/tree"),
    )


def _asked_event(position: int = 1) -> Event:
    # 工程询问质检：问题与背景分成事实与解释两部分（工单 #554）
    return _event(position, EventType.ASK_STARTED, {
        "requester": "engineering",
        "recipient": "quality",
        "question": "",
        "background": "",
        "expected": "结论",
        "facts": "接口：echo <文本>，大写输出",
        "explanation": "这样实现是因为历史用例要求大写",
        "branch_session_id": "ses_ask_qua_1",
    }, session_id="ses_eng_1", department="engineering")


def _quality_asked_event(position: int = 2) -> Event:
    # 质检询问工程：问题不带事实与解释的拆分（那是工程给出的内容才拆）
    return _event(position, EventType.ASK_STARTED, {
        "requester": "quality",
        "recipient": "engineering",
        "question": "检查项覆盖了换行吗？",
        "background": "缺陷记录之前核对",
        "expected": "结论",
        "branch_session_id": "ses_ask_eng_1",
    }, session_id="ses_qua_1", department="quality")


def _answered_event(position: int = 3) -> Event:
    # 工程在分支里回答质检：回答分成事实与解释两部分
    return _event(position, EventType.ASK_ANSWERED, {
        "requester": "quality",
        "recipient": "engineering",
        "status": "answered",
        "answer": "",
        "facts": "检查脚本不用改",
        "explanation": "改动风险低，评审时已确认",
    }, session_id="ses_ask_eng_1", department="engineering")


def _judgement_event(position: int = 3, delivery_hash: str = "sha256:delivery-1") -> Event:
    # 质检对当前交付提交结论：缺陷记录或放行都算
    return _event(position, EventType.QA_SUBMITTED, {
        "delivery_spec_hash": delivery_hash,
        "verdict": "rework_engineering",
    }, session_id="ses_qua_1", department="quality")


def test_the_delivery_explanation_is_hidden_until_the_quality_concludes():
    # 通道一：交付说明。事实部分总在，解释部分（summary、known_risks）等质检的结论
    delivery = _delivery()
    events = [_event(1, EventType.DELIVERY_ACCEPTED, {"content_hash": delivery.content_hash})]
    before = quality_engineering_content(events, delivery=delivery)
    assert before["explanation_visible"] is False
    assert "summary" not in before["delivery"]
    assert "known_risks" not in before["delivery"]
    assert before["delivery"]["files"] == ["src/echo.py"]
    assert before["delivery"]["check_names"] == ["smoke"]

    after = quality_engineering_content(events + [_judgement_event()], delivery=delivery)
    assert after["explanation_visible"] is True
    assert after["delivery"]["summary"] == "大写输出"
    assert after["delivery"]["known_risks"] == ["没有空行结尾"]


def test_the_answer_and_the_question_carry_only_facts_before_the_conclusion():
    # 通道二与通道三：质检收到的工程回答、质检分支看到的工程的问题，
    # 解释部分在质检对当前交付下结论以前不给
    delivery = _delivery()
    events = [_event(1, EventType.DELIVERY_ACCEPTED, {"content_hash": delivery.content_hash}),
              _asked_event(2), _quality_asked_event(3), _answered_event(4)]
    content = quality_engineering_content(events, delivery=delivery)
    assert content["explanation_visible"] is False
    assert len(content["answers"]) == 1
    answer = content["answers"][0]
    assert engineering_facts_text(answer, part="answer", explanation_visible=False) == "检查脚本不用改"
    # 提交结论以后：解释部分进入
    content = quality_engineering_content(events + [_judgement_event(5)], delivery=delivery)
    answer = content["answers"][0]
    assert "改动风险低" in engineering_facts_text(answer, part="answer", explanation_visible=True)
    assert content["explanations"], content


def test_a_new_delivery_hides_the_explanation_again():
    # 新的交付到达后按新交付重新计算：此前全部工程内容的解释部分重新藏起来
    first = _delivery("sha256:delivery-1")
    events = [_event(1, EventType.DELIVERY_ACCEPTED, {"content_hash": first.content_hash}),
              _asked_event(2), _quality_asked_event(3), _answered_event(4), _judgement_event(5)]
    assert quality_engineering_content(events, delivery=first)["explanation_visible"] is True

    second = _delivery("sha256:delivery-2")
    events = events + [_event(6, EventType.DELIVERY_ACCEPTED, {"content_hash": second.content_hash})]
    content = quality_engineering_content(events, delivery=second)
    assert content["explanation_visible"] is False
    assert "summary" not in content["delivery"]
    assert content["explanations"] == []
    answer = content["answers"][0]
    assert engineering_facts_text(answer, part="answer", explanation_visible=False) == "检查脚本不用改"


def test_without_a_delivery_the_explanation_never_shows():
    # 还没有交付（预测性探索）：质检只看到事实部分
    events = [_asked_event(1), _quality_asked_event(2), _answered_event(3)]
    content = quality_engineering_content(events)
    assert content["explanation_visible"] is False
    assert content["delivery"] is None
