import pytest

from harness.providers import capabilities
from harness.providers.discovery import _parse_candidates

# 候选的窗口与输出上限预填（模型管理设计说明第 4.3 节）：上游模型列表描述容量的写法各家不同，
# Provider 模块按列出的次序识别，取第一个有效的正整数；窗口与输出上限各自独立取值，
# 取到的值来源写 models_url。自定义服务方案（preset_id 为空）在能力表里没有条目，
# 候选里的容量只能来自上游模型列表，读到的值因此只说明上游模型列表这一处。
# 工单 #1351：原来的单元层文件 test_provider_candidate_capacity.py 与本文件测的是同一件事，
# 合成一处留在这个文件里（写法覆盖面更全），文件登记在单元层。

CUSTOM = ""

# 模板里的数值位置：每种写法只有一个数值，用同一个占位标出，换值时不改写别的键
VALUE = object()

# 窗口的写法，按取值的先后排列：同时出现时前面的写法先取
WINDOW_WRITINGS: list[tuple[str, dict, int]] = [
    ("limit.context", {"limit": {"context": VALUE}}, 128000),
    ("context_length", {"context_length": VALUE}, 1048576),
    ("top_provider.context_length", {"top_provider": {"context_length": VALUE}}, 200000),
    ("capabilities.contextWindow", {"capabilities": {"contextWindow": VALUE}}, 400000),
    ("model_info.context_length", {"model_info": {"gemma3.context_length": VALUE}}, 131072),
    ("model_info.num_ctx", {"model_info": {"gemma3.num_ctx": VALUE}}, 8192),
    ("max_context_window_tokens", {"max_context_window_tokens": VALUE}, 262144),
    ("max_model_len", {"max_model_len": VALUE}, 32768),
    ("loaded_context_length", {"loaded_context_length": VALUE}, 24576),
    ("max_context_length", {"max_context_length": VALUE}, 16384),
    ("context_window_tokens", {"context_window_tokens": VALUE}, 65536),
]

# 输出上限的写法，按取值的先后排列
OUTPUT_WRITINGS: list[tuple[str, dict, int]] = [
    ("limit.output", {"limit": {"output": VALUE}}, 8192),
    ("max_completion_tokens", {"max_completion_tokens": VALUE}, 65536),
    ("top_provider.max_completion_tokens", {"top_provider": {"max_completion_tokens": VALUE}}, 32000),
    ("capabilities.maxOutput", {"capabilities": {"maxOutput": VALUE}}, 128000),
    ("max_output_tokens", {"max_output_tokens": VALUE}, 16384),
    ("capabilities.limit.output", {"capabilities": {"limit": {"output": VALUE}}}, 4096),
]

# 不采用的值：字符串、布尔、0、负数、小数、整值浮点、空值、空列表与空对象
# （工单 #1351：两个文件里各自的无效值合并成这一份）
INVALID_VALUES = ["128000", True, False, 0, -1, 1.5, 1048576.0, None, [], {}]


def _with_value(template: dict, value) -> dict:
    # 把写法模板里的数值换成给定的值（无效值的用例用）
    return {key: (_with_value(sub, value) if isinstance(sub, dict) else value)
            for key, sub in template.items()}


def _merged(templates: list[dict]) -> dict:
    # 把几种写法合成上游模型列表的一项（同一层的键合并，不同层的键都留着）
    merged: dict = {}
    for template in templates:
        for key, value in template.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = _merged([merged[key], value])
            else:
                merged[key] = value
    return merged


def _candidate(item: dict) -> dict:
    # 上游模型列表的一项放进候选
    [candidate] = _parse_candidates({"data": [{"id": "model-a", **item}]}, CUSTOM)
    return candidate


def _window_ids(writing: tuple[str, dict, int]) -> str:
    return writing[0]


@pytest.mark.parametrize("writing", WINDOW_WRITINGS, ids=_window_ids)
def test_candidates_take_the_window_from_every_upstream_writing(writing):
    # R3：上游模型列表的每一种写法都能填出窗口，来源是上游模型列表
    _name, template, expected = writing
    candidate = _candidate(_with_value(template, expected))
    assert (candidate["context_window"], candidate["context_window_source"]) == (expected, "models_url")


@pytest.mark.parametrize("writing", OUTPUT_WRITINGS, ids=_window_ids)
def test_candidates_take_the_output_limit_from_every_upstream_writing(writing):
    # R3：上游模型列表的每一种写法都能填出输出上限，来源是上游模型列表
    _name, template, expected = writing
    candidate = _candidate(_with_value(template, expected))
    assert (candidate["max_output_tokens"], candidate["max_output_tokens_source"]) == (expected, "models_url")


@pytest.mark.parametrize("position", range(len(WINDOW_WRITINGS)))
def test_candidates_take_the_window_by_the_listed_order(position):
    # R3：几种写法同时出现时取列在前面的那种
    rest = WINDOW_WRITINGS[position:]
    candidate = _candidate(_merged([_with_value(template, value) for _name, template, value in rest]))
    assert candidate["context_window"] == rest[0][2]


@pytest.mark.parametrize("position", range(len(OUTPUT_WRITINGS)))
def test_candidates_take_the_output_limit_by_the_listed_order(position):
    # R3：几种写法同时出现时取列在前面的那种
    rest = OUTPUT_WRITINGS[position:]
    candidate = _candidate(_merged([_with_value(template, value) for _name, template, value in rest]))
    assert candidate["max_output_tokens"] == rest[0][2]


@pytest.mark.parametrize("value", INVALID_VALUES)
@pytest.mark.parametrize("writing", WINDOW_WRITINGS, ids=_window_ids)
def test_candidates_ignore_window_values_that_are_not_positive_integers(writing, value):
    # R3：字符串、布尔、0、负数与小数都不采用，候选里没有窗口这两个键
    _name, template, _expected = writing
    candidate = _candidate(_with_value(template, value))
    assert "context_window" not in candidate and "context_window_source" not in candidate


@pytest.mark.parametrize("value", INVALID_VALUES)
@pytest.mark.parametrize("writing", OUTPUT_WRITINGS, ids=_window_ids)
def test_candidates_ignore_output_values_that_are_not_positive_integers(writing, value):
    # R3：字符串、布尔、0、负数与小数都不采用，候选里没有输出上限这两个键
    _name, template, _expected = writing
    candidate = _candidate(_with_value(template, value))
    assert "max_output_tokens" not in candidate and "max_output_tokens_source" not in candidate


def test_candidates_continue_to_the_next_writing_after_an_unusable_value():
    # R3：前一种写法给出的值不采用时继续看下一种写法
    candidate = _candidate({"model_info": {"gemma3.context_length": "131072"},
                            "max_context_window_tokens": 0,
                            "max_model_len": 32768})
    assert (candidate["context_window"], candidate["context_window_source"]) == (32768, "models_url")
    # 中间一层不是对象时同样跳过这一种写法
    candidate = _candidate({"limit": 3, "top_provider": "none",
                            "capabilities": {"contextWindow": 400000, "maxOutput": 128000}})
    assert (candidate["context_window"], candidate["max_output_tokens"]) == (400000, 128000)


def test_candidates_take_the_context_length_key_from_a_model_info_with_several_keys():
    # R3：model_info 里有多个键时取以 .context_length 结尾的那个
    candidate = _candidate({"model_info": {"general.architecture": "gemma3",
                                          "gemma3.embedding_length": 2048,
                                          "gemma3.context_length": 131072}})
    assert (candidate["context_window"], candidate["context_window_source"]) == (131072, "models_url")


def test_candidates_prefer_the_loaded_context_length_over_the_maximum():
    # R3：LM Studio 的两个字段同时给出时取运行时真实值 loaded_context_length
    candidate = _candidate({"loaded_context_length": 24576, "max_context_length": 16384})
    assert (candidate["context_window"], candidate["context_window_source"]) == (24576, "models_url")


def test_candidates_keep_context_length_ahead_of_max_model_len():
    # R3：vLLM 的 max_model_len 与顶层 context_length 同时给出时仍取 context_length
    candidate = _candidate({"context_length": 1048576, "max_model_len": 32768})
    assert (candidate["context_window"], candidate["context_window_source"]) == (1048576, "models_url")


def test_candidates_read_the_window_and_the_output_limit_independently():
    # R3：窗口与输出上限各自独立按次序取，一处有、另一处没有时只填有的那一项
    candidate = _candidate({"model_info": {"gemma3.context_length": 131072}})
    assert (candidate["context_window"], candidate["context_window_source"]) == (131072, "models_url")
    assert "max_output_tokens" not in candidate and "max_output_tokens_source" not in candidate
    candidate = _candidate({"model_info": {"gemma3.context_length": 131072},
                            "max_output_tokens": 16384})
    assert (candidate["context_window"], candidate["max_output_tokens"]) == (131072, 16384)


def test_candidates_fall_back_to_the_capability_table():
    # 上游列表没有容量时仍取模型能力表的值与来源：两处的次序没有变
    recorded = capabilities.capability("opencode-go", "deepseek-v4-pro")
    assert recorded is not None
    [candidate] = _parse_candidates({"data": [{"id": "deepseek-v4-pro"}]}, "opencode-go")
    assert (candidate["context_window"], candidate["context_window_source"]) == (
        recorded.context_window, "capability_table")
    assert (candidate["max_output_tokens"], candidate["max_output_tokens_source"]) == (
        recorded.max_output_tokens, "capability_table")
