# R3：模型准入的往返测试认无参数工具调用的三种合法写法（工单 #1332）。
# 测试工具要证明的是「模型会调工具、能接受工具结果」，不是「它把参数写成什么样」：
# arguments 为 {}、为 null、缺省、以及带任意字段的对象都算通过（工单 #1332 第 2 轮）；
# 不是对象的形状（数组、字符串、数字、布尔、解不出来的字符串）仍然拒绝，原因里带上收到的原文。
# 这里直接调验收往返结果的那一处纯函数（不经过 HTTP），是能得出结论的最低一层。

import pytest

from harness.providers.errors import ProviderError
from harness.providers.facade import _model_test_tool_outputs
from harness.providers.invoke import InvokeResult


def _result(**call: object) -> InvokeResult:
    # 一次只有测试工具调用的模型回答；call 是这次调用的字段（arguments 可以省略）
    return InvokeResult(output=[{"type": "function_call", "name": "yudao_model_test",
                                 "call_id": "probe-call", **call}])


def test_the_three_empty_argument_shapes_pass_the_round_trip():
    for shape in ({"arguments": "{}"}, {"arguments": "null"}, {}, {"arguments": None}, {"arguments": ""}):
        outputs = _model_test_tool_outputs(_result(**shape))
        assert outputs == [{"type": "function_call_output", "call_id": "probe-call", "output": "pong"}], shape


def test_arguments_that_carry_extra_fields_still_pass():
    # 模型自己加字段也通过（工单 #1332 第 2 轮）：准入要证的是会不会调工具、能不能用工具结果
    for arguments in ('{"reason": "测试连接"}', '{"path": "a.py", "note": "准备写文件"}', '{"a": {"b": 1}}'):
        outputs = _model_test_tool_outputs(_result(arguments=arguments))
        assert outputs == [{"type": "function_call_output", "call_id": "probe-call", "output": "pong"}], arguments


def test_a_shape_that_is_not_an_object_is_rejected_even_when_it_carries_fields():
    # 带字段但不是对象的形状仍然拒绝，原因里带上收到的原文
    for arguments in ('[{"reason": "测试连接"}]', '"{\\"reason\\": 1}"', '{"a": 1}extra'):
        with pytest.raises(ProviderError) as raised:
            _model_test_tool_outputs(_result(arguments=arguments))
        assert "应当是对象" in str(raised.value), arguments


def test_a_shape_that_is_not_an_object_is_rejected_with_what_arrived():
    for shape in ("[]", '"text"', "42", "not json", "true"):
        with pytest.raises(ProviderError) as raised:
            _model_test_tool_outputs(_result(arguments=shape))
        assert shape in str(raised.value), shape


def test_the_rejection_text_is_truncated_to_a_readable_length():
    # 截断只用在被拒绝的形状上：一个很长的 JSON 字符串（不是对象）
    with pytest.raises(ProviderError) as raised:
        _model_test_tool_outputs(_result(arguments='"' + "a" * 400 + '"'))
    message = str(raised.value)
    assert "…" in message
    assert len(message) < 200, message
