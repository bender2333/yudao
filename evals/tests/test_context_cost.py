"""缓存感知费用折算的两条基本性质：只追加的请求整段命中，折叠旧内容以后从那一处起全部未命中。"""

from __future__ import annotations

from evals.context.cost import CACHED_PRICE, cached_prefix_tokens, implied_hit, step_cost


def _keys(*texts: str) -> list[tuple]:
    return [("tool", text) for text in texts]


def test_append_only_request_hits_the_whole_previous_request():
    previous = _keys("a", "b", "c")
    current = _keys("a", "b", "c", "d")
    tokens = [100, 200, 300, 50]
    cached = cached_prefix_tokens(previous, current, tokens)
    assert cached == 600
    assert step_cost(sum(tokens), cached) == 600 * CACHED_PRICE + 50


def test_folding_an_old_entry_misses_everything_after_it():
    previous = _keys("a", "b", "c")
    current = _keys("a", "placeholder", "c", "d")
    tokens = [100, 10, 300, 50]
    # 第二条不同：第二条起的 360 token 全部未命中，只有第一条命中
    assert cached_prefix_tokens(previous, current, tokens) == 100


def test_first_step_of_a_session_has_no_cache():
    assert cached_prefix_tokens((), _keys("a"), [100]) == 0


def test_implied_hit_round_trips_the_cost_model():
    tokens, hit = 1000.0, 0.8
    cost = hit * tokens * CACHED_PRICE + (1 - hit) * tokens
    assert abs(implied_hit(tokens, cost) - hit) < 1e-9
