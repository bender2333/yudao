import pytest

from harness.providers import capabilities
from harness.providers.discovery import _parse_candidates

# 候选的窗口与输出上限预填（模型管理设计说明第 4.3 节）：上游模型列表的容量写法有四种，
# 按列出的次序取到第一个有效的就停；只认正整数字；窗口与输出上限各自独立按这个次序取，取到的值来源写 models_url。
# 自定义服务方案（preset_id 为空）在能力表里没有条目，候选里的容量只能来自上游模型列表，
# 读到的值因此只说明上游列表这一处。

CUSTOM = ""

WRITINGS = {
    "limit": {"limit": {"context": 128000, "output": 8192}},
    "top_level": {"context_length": 1048576, "max_completion_tokens": 65536},
    "top_provider": {"top_provider": {"context_length": 200000, "max_completion_tokens": 32000}},
    "capabilities": {"capabilities": {"contextWindow": 400000, "maxOutput": 128000}},
}
EXPECTED = {
    "limit": (128000, 8192),
    "top_level": (1048576, 65536),
    "top_provider": (200000, 32000),
    "capabilities": (400000, 128000),
}


def _item_with(writing: str, window, output) -> dict:
    # 按一种写法把窗口与输出上限放进候选（上游列表的一项）
    if writing == "limit":
        return {"limit": {"context": window, "output": output}}
    if writing == "top_level":
        return {"context_length": window, "max_completion_tokens": output}
    if writing == "top_provider":
        return {"top_provider": {"context_length": window, "max_completion_tokens": output}}
    return {"capabilities": {"contextWindow": window, "maxOutput": output}}


@pytest.mark.parametrize("writing", sorted(WRITINGS))
def test_candidates_carry_each_upstream_writing_of_both_limits(writing):
    # 四种写法各自能被取到：窗口与输出上限的值与来源都在候选里（验收第 1 项）
    window, output = EXPECTED[writing]
    [candidate] = _parse_candidates({"data": [{"id": "model-a", **WRITINGS[writing]}]}, CUSTOM)
    assert (candidate["context_window"], candidate["max_output_tokens"]) == (window, output)
    assert candidate["context_window_source"] == "models_url"
    assert candidate["max_output_tokens_source"] == "models_url"


def test_candidates_try_the_writings_in_the_listed_order():
    # 优先级：同时给出几种写法时取列在前面的那种（验收第 2 项）
    item: dict = {"id": "model-a"}
    for writing in ("capabilities", "top_provider", "top_level", "limit"):
        item.update(WRITINGS[writing])
        [candidate] = _parse_candidates({"data": [item]}, CUSTOM)
        assert (candidate["context_window"], candidate["max_output_tokens"]) == EXPECTED[writing]


def test_candidates_read_the_window_and_the_output_limit_independently():
    # 窗口与输出上限各自独立按次序取：一处有、另一处都没有时只填有的那一项
    [candidate] = _parse_candidates({"data": [{"id": "model-a", "max_completion_tokens": 65536}]}, CUSTOM)
    assert "context_window" not in candidate and "context_window_source" not in candidate
    assert (candidate["max_output_tokens"], candidate["max_output_tokens_source"]) == (65536, "models_url")
    [candidate] = _parse_candidates({"data": [{"id": "model-a",
                                               "top_provider": {"context_length": 200000}}]}, CUSTOM)
    assert (candidate["context_window"], candidate["context_window_source"]) == (200000, "models_url")
    assert "max_output_tokens" not in candidate and "max_output_tokens_source" not in candidate
    # 两种写法各出一项：窗口取第二种写法，输出上限取第一种写法
    [candidate] = _parse_candidates({"data": [{"id": "model-a", "limit": {"output": 8192},
                                               "context_length": 1048576}]}, CUSTOM)
    assert (candidate["context_window"], candidate["max_output_tokens"]) == (1048576, 8192)


INVALID_VALUES = [0, -1, 1.5, 1048576.0, True, False, "128000", None, [], {}]


@pytest.mark.parametrize("value", INVALID_VALUES)
@pytest.mark.parametrize("writing", sorted(WRITINGS))
def test_candidates_ignore_values_that_are_not_positive_integers(writing, value):
    # 0、负数、小数、布尔与字符串都不采用，候选里没有这两个键（验收第 3 项）
    [candidate] = _parse_candidates({"data": [{"id": "model-a", **_item_with(writing, value, value)}]}, CUSTOM)
    assert "context_window" not in candidate and "context_window_source" not in candidate
    assert "max_output_tokens" not in candidate and "max_output_tokens_source" not in candidate


def test_candidates_fall_through_an_invalid_writing():
    # 前一种写法给出的值不合法时继续看下一种写法；中间一层不是对象时同样跳过
    [candidate] = _parse_candidates({"data": [{"id": "model-a", "limit": {"context": 0, "output": -1},
                                               "context_length": 1048576,
                                               "max_completion_tokens": 65536}]}, CUSTOM)
    assert (candidate["context_window"], candidate["max_output_tokens"]) == (1048576, 65536)
    [candidate] = _parse_candidates({"data": [{"id": "model-a", "limit": 3, "top_provider": "none",
                                               "capabilities": {"contextWindow": 400000,
                                                                "maxOutput": 128000}}]}, CUSTOM)
    assert (candidate["context_window"], candidate["max_output_tokens"]) == (400000, 128000)


def test_candidates_fall_back_to_the_capability_table():
    # 上游列表没有容量时仍取模型能力表的值与来源：两处的次序没有变
    recorded = capabilities.capability("opencode-go", "deepseek-v4-flash")
    assert recorded is not None
    [candidate] = _parse_candidates({"data": [{"id": "deepseek-v4-flash"}]}, "opencode-go")
    assert (candidate["context_window"], candidate["context_window_source"]) == (
        recorded.context_window, "capability_table")
    assert (candidate["max_output_tokens"], candidate["max_output_tokens_source"]) == (
        recorded.max_output_tokens, "capability_table")
