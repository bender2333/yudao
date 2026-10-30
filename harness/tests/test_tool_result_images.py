# 工具结果带图像：装配里的减法与三个协议各自的图像输入写法。
# 依据：浏览器与 computer use 设计说明第 6.2 节「请求中的图像」、第 7.1 节「保存与绑定」；
# 模型管理设计说明第 5.6 节「按模型输入方式提供工具」与第 8.2 节「用量」。
# 守 R2（第二环的合同：装配缝交给模型的工具结果、三个协议各自的交换形状）与
# R3（阶段二：模型看到最近 3 张截图，更早的带证据编号，只有文本的模型不收到图像）。

import base64
import json

import pytest

from harness.adapters.base import ProviderError
from harness.adapters.fake import received_images
from harness.artifacts import ArtifactStore
from harness.compaction import (IMAGE_TOKEN_ESTIMATE, finish_compaction, plan_compaction,
                                request_input_tokens, visible_history)
from harness.context import evidence_placeholder, request_history
from harness.engine import tool_input_modalities, tool_result_item
from harness.models import canonical_hash
from harness.providers.chat import _chat_messages
from harness.providers.errors import ProviderError as ProtocolError
from harness.providers.invoke import (ToolImage, ToolResult, provider_input_for, split_tool_output,
                                      to_provider_input, tool_image_from_url)
from harness.providers.messages import _messages_input
from harness.providers.responses import _responses_input_items
from harness.tests.protocol_helpers import model_call

RUN_ID = "run-images"
IMAGE_MODALITIES = ("text", "image")
IMAGE_REF_FIELDS = ("kind", "content_hash", "path", "media_type")


def _screenshots(directory, count):
    # 每张截图的字节不同：请求里保留的是哪几张按字节核对
    artifacts = ArtifactStore(directory / "artifacts")
    entries = []
    for index in range(count):
        data = b"\x89PNG\r\n\x1a\n" + f"screen-{index + 1}".encode("ascii")
        ref = artifacts.put(RUN_ID, "screenshot", data, media_type="image/png")
        entries.append({"kind": ref.kind, "content_hash": ref.content_hash, "path": ref.path,
                        "media_type": ref.media_type, "data": data})
    return artifacts, entries


def _tool_step(call_id, image, *, input_modalities=IMAGE_MODALITIES, text=None):
    # 一步里的两次记录：模型发出的工具调用，与带截图引用的工具结果
    call = {"type": "function_call", "call_id": call_id, "name": "browser_take_screenshot",
            "arguments": json.dumps({"path": call_id})}
    result = tool_result_item(call_id, True, {"accessibility": text or f"页面结构 {call_id}",
                                              "images": [{key: image[key] for key in IMAGE_REF_FIELDS}]},
                              None, input_modalities=input_modalities)
    return [call, result]


def _history(images, *, input_modalities=IMAGE_MODALITIES):
    history = []
    for index, image in enumerate(images):
        history.extend(_tool_step(f"call-{index + 1}", image, input_modalities=input_modalities))
    return history


def _items(history, artifacts, *, input_modalities=IMAGE_MODALITIES):
    return request_history(history, run_id=RUN_ID, artifacts=artifacts, input_modalities=input_modalities)


def _tool_outputs(items):
    return [item for item in items if item.get("type") == "function_call_output"]


def _parts(item):
    output = item["output"]
    return output if isinstance(output, list) else [{"type": "input_text", "text": output}]


def _images(items):
    return [part for item in _tool_outputs(items) for part in _parts(item) if part["type"] == "input_image"]


def _texts(items):
    return [part["text"] for item in _tool_outputs(items) for part in _parts(item) if part["type"] == "input_text"]


def _placeholders(items):
    return [text for text in _texts(items) if text.startswith("截图 ")]


def _image_bytes(part):
    return base64.b64decode(part["image_url"].split(";base64,", 1)[1])


def _content_blocks(message):
    # Messages 的消息内容是文字的字符串，或者块列表
    content = message["content"]
    return content if isinstance(content, list) else [{"type": "text", "text": content}]


def test_responses_gets_the_three_most_recent_screenshots(tmp_path):
    # Responses 的图像输入写法：function_call_output 的 output 是内容块数组，图像块带 data URL
    artifacts, images = _screenshots(tmp_path, 6)
    provider_input = provider_input_for(model_call(_items(_history(images), artifacts)))
    outputs = [item for item in _responses_input_items(provider_input)
               if item.get("type") == "function_call_output"]
    sent = [part for item in outputs for part in item["output"]
            if isinstance(part, dict) and part.get("type") == "input_image"]
    assert [_image_bytes(part) for part in sent] == [entry["data"] for entry in images[-3:]]
    # 更早的 3 张换成占位文字，占位文字带证据编号
    assert [part["text"] for item in outputs for part in item["output"]
            if isinstance(part, dict) and part["type"] == "input_text" and part["text"].startswith("截图 ")] == [
        evidence_placeholder(entry["content_hash"]) for entry in images[:3]]


def test_chat_completions_gets_the_screenshots_as_a_user_message(tmp_path):
    # Chat Completions 的 tool 消息只收文字：图像写成紧跟其后的一条 user 消息，逐个写明是哪个调用的结果
    artifacts, images = _screenshots(tmp_path, 6)
    messages = _chat_messages(provider_input_for(model_call(_items(_history(images), artifacts))))
    tool_messages = [message for message in messages if message["role"] == "tool"]
    assert [message["tool_call_id"] for message in tool_messages] == [f"call-{index}" for index in range(1, 7)]
    assert all(isinstance(message["content"], str) for message in tool_messages)
    assert [message["content"] for message in tool_messages if "截图 " in message["content"]]
    user_parts = [part for message in messages if message["role"] == "user" and isinstance(message["content"], list)
                  for part in message["content"]]
    assert [base64.b64decode(part["image_url"]["url"].split(";base64,", 1)[1]) for part in user_parts
            if part["type"] == "image_url"] == [entry["data"] for entry in images[-3:]]
    assert [part["text"] for part in user_parts if part["type"] == "text"] == [
        f"工具调用 call-{index} 的结果图像" for index in range(4, 7)]


def test_messages_gets_the_screenshots_inside_the_tool_result(tmp_path):
    # Anthropic Messages 的 tool_result 自带图像块：文字块在前，图像块按顺序，更早的换成占位文字
    artifacts, images = _screenshots(tmp_path, 6)
    _system, messages = _messages_input(provider_input_for(model_call(_items(_history(images), artifacts))))
    results = [block for message in messages for block in _content_blocks(message)
               if block["type"] == "tool_result"]
    assert [result["tool_use_id"] for result in results] == [f"call-{index}" for index in range(1, 7)]
    sent = [block for result in results for block in _content_blocks(result)
            if block["type"] == "image" and block["source"]["type"] == "base64"]
    assert [base64.b64decode(block["source"]["data"]) for block in sent] == [
        entry["data"] for entry in images[-3:]]
    assert all(block["source"]["media_type"] == "image/png" for block in sent)
    placeholders = [line for result in results for block in _content_blocks(result)
                    if block["type"] == "text" for line in block["text"].split("\n")
                    if line.startswith("截图 ")]
    assert placeholders == [evidence_placeholder(entry["content_hash"]) for entry in images[:3]]


def test_screenshots_are_replaced_three_at_a_time(tmp_path):
    # 换出按 3 张一组（设计说明第 6.2 节，减少请求前段的变化）：5 张时一张也不换，
    # 第 6 张进来时一次换出 3 张，第 7 张以后保留 4 张
    for count, kept, replaced in ((5, 5, 0), (6, 3, 3), (7, 4, 3)):
        artifacts, images = _screenshots(tmp_path / f"case-{count}", count)
        items = _items(_history(images), artifacts)
        assert [_image_bytes(part) for part in _images(items)] == [entry["data"] for entry in images[count - kept:]]
        assert _placeholders(items) == [evidence_placeholder(entry["content_hash"]) for entry in images[:replaced]]


def test_a_text_only_call_target_gets_no_images_and_no_placeholder(tmp_path):
    # 调用目标只有文本时，工具结果里没有图像，也没有占位文字：截图只作为证据保存（第 6.2 节第 2 条）
    _artifacts, images = _screenshots(tmp_path, 1)
    history = _history(images, input_modalities=("text",))
    assert "images" not in history[1]
    assert _images(history) == [] and _placeholders(history) == []
    assert json.loads(history[1]["output"])["output"] == {"accessibility": "页面结构 call-1"}


def test_switching_to_a_text_only_model_replaces_the_screenshots_in_the_next_request(tmp_path):
    # 同一角色任务中途换成不含图像的模型：下一次请求里已有的截图全部换成占位文字（第 6.2 节第 3 条）
    artifacts, images = _screenshots(tmp_path, 3)
    items = _items(_history(images), artifacts, input_modalities=("text",))
    assert _images(items) == []
    assert _placeholders(items) == [evidence_placeholder(entry["content_hash"]) for entry in images]


def test_the_tool_result_carries_the_screenshot_reference_for_an_image_target(tmp_path):
    # 动作回执的输出里带图像时，工具结果带它的工件引用；引用不重复写进文字
    _artifacts, images = _screenshots(tmp_path, 1)
    image = images[0]
    item = tool_result_item("call-1", True, {"page": "首页", "images": [image]}, None,
                            input_modalities=IMAGE_MODALITIES)
    assert item["images"] == [{key: image[key] for key in IMAGE_REF_FIELDS}]
    assert json.loads(item["output"]) == {"ok": True, "output": {"page": "首页"}, "error": None}


def test_a_malformed_tool_image_is_rejected(tmp_path):
    # 图像必须是工件引用：缺字段时在写进部门历史之前拒绝，不把半张图带进请求
    with pytest.raises(ProviderError):
        tool_result_item("call-1", True, {"output": "x", "images": [{"kind": "screenshot"}]}, None,
                         input_modalities=IMAGE_MODALITIES)
    with pytest.raises(ProviderError):
        tool_result_item("call-1", True, {"output": "x", "images": "sha256:abc"}, None,
                         input_modalities=IMAGE_MODALITIES)


def test_tool_result_image_content_parts_must_be_data_urls():
    # 请求里的图像块按 data URL 携带：其他写法在发送之前拒绝，不把不该发给上游的形状交出去
    assert tool_image_from_url("data:image/png;base64,QUJD") == ToolImage(media_type="image/png", data="QUJD")
    assert split_tool_output([{"type": "input_text", "text": "a"},
                              {"type": "input_text", "text": "b"}]) == ("a\nb", ())
    for invalid in ("https://example.com/a.png", "data:;base64,QUJD", "data:image/png,QUJD"):
        with pytest.raises(ProtocolError):
            tool_image_from_url(invalid)
    for output in (7, [7], [{"type": "input_text"}], [{"type": "input_image", "image_url": "data:,QUJD"}]):
        with pytest.raises(ProtocolError):
            split_tool_output(output)


def test_the_unified_input_carries_tool_images():
    # 没有装配好的 raw_request 时，工具结果由统一输入组成：图像随结果一起交回协议实现
    provider_input = to_provider_input([], tool_results=[
        {"call_id": "call-1", "name": "browser_take_screenshot", "output": "已截图",
         "images": [{"media_type": "image/png", "data": "QUJD"}]},
        {"call_id": "call-2", "name": "read_file", "output": "print(1)",
         "images": [ToolImage(media_type="image/jpeg", data="REVG")]},
    ])
    assert provider_input.tool_results == (
        ToolResult(call_id="call-1", name="browser_take_screenshot", output="已截图",
                   images=(ToolImage(media_type="image/png", data="QUJD"),)),
        ToolResult(call_id="call-2", name="read_file", output="print(1)",
                   images=(ToolImage(media_type="image/jpeg", data="REVG"),)),
    )


def test_each_protocol_carries_tool_images_from_the_unified_input():
    # 没有装配好的 raw_request 时（诊断调用与假模型回显）三个协议按统一输入各写各的图像形状
    provider_input = to_provider_input([], tool_results=[
        {"call_id": "call-1", "name": "browser_take_screenshot", "output": "已截图",
         "images": [{"media_type": "image/png", "data": "QUJD"}]},
        {"call_id": "call-2", "name": "browser_take_screenshot", "output": "",
         "images": [{"media_type": "image/jpeg", "data": "REVG"}]},
        {"call_id": "call-3", "name": "read_file", "output": "print(1)"},
    ])
    assert _responses_input_items(provider_input) == [
        {"type": "function_call_output", "call_id": "call-1", "output": [
            {"type": "input_text", "text": "已截图"},
            {"type": "input_image", "image_url": "data:image/png;base64,QUJD"}]},
        {"type": "function_call_output", "call_id": "call-2", "output": [
            {"type": "input_image", "image_url": "data:image/jpeg;base64,REVG"}]},
        {"type": "function_call_output", "call_id": "call-3", "output": "print(1)"},
    ]
    assert _chat_messages(provider_input) == [
        {"role": "tool", "tool_call_id": "call-1", "content": "已截图"},
        {"role": "tool", "tool_call_id": "call-2", "content": ""},
        {"role": "tool", "tool_call_id": "call-3", "content": "print(1)"},
        {"role": "user", "content": [
            {"type": "text", "text": "工具调用 call-1 的结果图像"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}},
            {"type": "text", "text": "工具调用 call-2 的结果图像"},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,REVG"}}]},
    ]
    _system, messages = _messages_input(provider_input)
    assert messages == [
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "call-1", "content": [
                {"type": "text", "text": "已截图"},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"}}]},
            {"type": "tool_result", "tool_use_id": "call-2", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "REVG"}}]},
            {"type": "tool_result", "tool_use_id": "call-3", "content": "print(1)"},
        ]},
    ]


def test_request_history_needs_the_artifacts_of_the_screenshots(tmp_path):
    # 图像按工件引用记录：装配时读不到工件库就不能把图像放进请求，明确失败而不是静默丢掉
    _artifacts, images = _screenshots(tmp_path, 1)
    with pytest.raises(ValueError):
        request_history(_history(images), run_id=RUN_ID, artifacts=None, input_modalities=IMAGE_MODALITIES)


def test_the_tool_result_images_follow_the_call_target_modalities(tmp_path):
    # 工具结果里的截图是否随结果进入历史，按这次请求的调用目标的输入方式决定（模型管理设计说明第 5.6 节）
    class _Request:
        call_target = {"input_modalities": ["text", "image"]}

    assert tool_input_modalities(_Request()) == ("text", "image")
    assert tool_input_modalities(object()) == ()


def test_a_screenshot_counts_as_one_image_in_the_local_estimate():
    # 本地估算（设计说明第 8.2 节）里图像按张计固定值：几百 KB 的 data URL 不当文字估成几十万 token
    data = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 300_000).decode("ascii")
    item = {"type": "function_call_output", "call_id": "call-1", "output": [
        {"type": "input_text", "text": json.dumps({"ok": True, "output": "页面结构", "error": None})},
        {"type": "input_image", "image_url": f"data:image/png;base64,{data}"},
    ]}
    assert IMAGE_TOKEN_ESTIMATE <= request_input_tokens([item], []) < IMAGE_TOKEN_ESTIMATE + 200
    twice = [item, {**item, "call_id": "call-2"}]
    assert 2 * IMAGE_TOKEN_ESTIMATE <= request_input_tokens(twice, []) < 2 * IMAGE_TOKEN_ESTIMATE + 300
    # 只有文字的工具结果照旧按字节估：这里没有图像要单独计
    text_only = {"type": "function_call_output", "call_id": "call-3", "output": "页面结构"}
    assert 0 < request_input_tokens([text_only], []) < IMAGE_TOKEN_ESTIMATE


def _plan_at_a_boundary(records):
    # 找一档窗口，使整理请求在步骤边界上停下（分界位置只能在步骤边界上，模型管理设计说明第 8.5 节）。
    # 窗口按场景的需要试出来，不写死一个数：摘要规则本身的长短由它自己决定
    from harness.compaction import CompactionError

    for window in range(2600, 12000, 200):
        try:
            plan = plan_compaction(records, None, window, [{"role": "developer", "content": "常驻材料"}], [],
                                   output_limit=None)
        except CompactionError:
            continue
        if plan is not None and plan.next_checkpoint.boundary and plan.next_checkpoint.covered_through_event_id:
            return plan
    raise AssertionError("没有任何窗口能让整理请求停在步骤边界上")


def test_compaction_keeps_the_evidence_identities(tmp_path):
    # 压缩的来源片段带着截图的证据编号；压缩以后剩下的图像仍按编号放进请求，换出的仍是带编号的占位文字
    artifacts, images = _screenshots(tmp_path, 12)
    history = []
    for index, image in enumerate(images):
        # 每一步的输出写得长一些：这一步的历史超过窗口，才需要整理
        history.extend(_tool_step(f"call-{index + 1}", image,
                                  text=f"页面结构 {index + 1} " + "x" * 1000))
    records = [{"event_id": f"evt-{index}", "seq": index + 1, "activation_id": "activation",
                "step_id": index // 2 + 1, "type": "function_call" if index % 2 == 0 else "tool_called",
                "item": item, "item_digest": canonical_hash(item), "target": {}}
               for index, item in enumerate(history)]
    plan = _plan_at_a_boundary(records)
    checkpoint = finish_compaction(plan, [{"type": "message", "role": "assistant",
                                          "content": [{"type": "output_text", "text": "前面几步的摘要"}]}])
    assert checkpoint is not None and checkpoint.summary == "前面几步的摘要"
    remaining = visible_history(records, checkpoint)
    # 被摘要掉的截图：它们的证据编号在整理请求的来源片段里，摘要可以引用
    summarized = {entry["content_hash"] for entry in images if entry["content_hash"] not in json.dumps(remaining)}
    assert summarized
    assert all(evidence in json.dumps(plan.input_items) for evidence in summarized)
    # 压缩以后剩下的截图：留下的按图像进入请求，换出的带证据编号
    items = request_history(remaining, run_id=RUN_ID, artifacts=artifacts, input_modalities=IMAGE_MODALITIES)
    remaining_images = [entry for entry in images if entry["content_hash"] in json.dumps(remaining)]
    assert remaining_images
    assert len(_images(items)) + len(_placeholders(items)) == len(remaining_images)
    assert set(_placeholders(items)) <= {evidence_placeholder(entry["content_hash"]) for entry in remaining_images}


def test_the_fake_model_sees_the_screenshots_it_receives(tmp_path):
    # 假模型按调用合同读到自己的请求：工具结果里的图像按内容块出现，测试据此核对模型看到了哪几张
    artifacts, images = _screenshots(tmp_path, 6)
    items = _items(_history(images), artifacts)
    assert [_image_bytes(part) for part in received_images(model_call(items))] == [
        entry["data"] for entry in images[-3:]]
