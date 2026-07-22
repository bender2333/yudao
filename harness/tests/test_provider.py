"""Tests for harness.provider.load_provider (spec §1 / §5)."""

import json
from types import SimpleNamespace

import httpx
import pytest
from openai import APIResponseValidationError, APIStatusError, BadRequestError, OpenAI

import harness.llm as llm_module
from harness.agent_loop import run_agent_loop
from harness.llm import (
    ContextOverflow,
    LlmClient,
    ProviderProtocolError,
    ProviderUnavailable,
)
from harness.provider import load_provider
from harness.run_solo import run_solo


def _write(tmp_path, text):
    p = tmp_path / "provider.md"
    p.write_text(text, encoding="utf-8")
    return str(p)


def _tool_call(call_id, name, args):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(args)),
    )


def _response(tool_calls, text=""):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=text, tool_calls=tool_calls),
                finish_reason="tool_calls" if tool_calls else "stop",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=5,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=2),
        ),
    )


def _response_without_usage(tool_calls):
    response = _response(tool_calls)
    response.usage = None
    return response


class _ScriptedCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response



def _patch_solo_provider(monkeypatch, responses):
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=_ScriptedCompletions(responses))
    )
    monkeypatch.setattr(
        "harness.run_solo.load_provider",
        lambda _: {"model": "test-model"},
    )
    monkeypatch.setattr("harness.run_solo.make_client", lambda _: client)


def _read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _bad_request(body):
    response = httpx.Response(
        400,
        request=httpx.Request("POST", "https://provider.invalid/v1/chat/completions"),
    )
    return BadRequestError("bad request", response=response, body=body)


def _api_status_error(body):
    response = httpx.Response(
        502,
        request=httpx.Request("POST", "https://provider.invalid/v1/chat/completions"),
    )
    return APIStatusError("provider-private-detail", response=response, body=body)


def _api_response_validation_error(body):
    response = httpx.Response(
        200,
        request=httpx.Request("POST", "https://provider.invalid/v1/chat/completions"),
    )
    return APIResponseValidationError(
        response=response,
        body=body,
        message="provider-private-detail",
    )


def test_parses_bare_model_line(tmp_path):
    path = _write(
        tmp_path,
        "key: sk-abc123\nurl: https://penguinapi.vip/\ngemini-2.5-flash\n",
    )
    cfg = load_provider(path)
    assert cfg["key"] == "sk-abc123"
    assert cfg["url"] == "https://penguinapi.vip/"
    assert cfg["model"] == "gemini-2.5-flash"


def test_parses_model_prefix(tmp_path):
    path = _write(
        tmp_path,
        "key: sk-abc\nurl: https://x.example/\nmodel: some-model\n",
    )
    cfg = load_provider(path)
    assert cfg["model"] == "some-model"


def test_ignores_blank_lines(tmp_path):
    path = _write(
        tmp_path,
        "\nkey: sk-abc\n\nurl: https://x.example/\n\ngemini-2.5-flash\n\n",
    )
    cfg = load_provider(path)
    assert cfg["key"] == "sk-abc"
    assert cfg["model"] == "gemini-2.5-flash"


def test_missing_key_raises(tmp_path):
    path = _write(tmp_path, "url: https://x.example/\ngemini-2.5-flash\n")
    with pytest.raises(ValueError):
        load_provider(path)


def test_missing_url_raises(tmp_path):
    path = _write(tmp_path, "key: sk-abc\ngemini-2.5-flash\n")
    with pytest.raises(ValueError):
        load_provider(path)


def test_runner_rejects_existing_run_directory(tmp_path):
    with pytest.raises(FileExistsError):
        run_solo(
            "task", "task-1", str(tmp_path), "missing-seed", "missing-checks",
            provider_path=str(tmp_path / "missing-provider.md"),
        )


def test_solo_uses_the_same_token_budget(tmp_path, monkeypatch):
    _patch_solo_provider(monkeypatch, [_response([], text="done")])
    seed = tmp_path / "seed"
    seed.mkdir()
    checks = tmp_path / "checks.json"
    checks.write_text('{"protected_paths":[],"checks":{}}', encoding="utf-8")
    provider = tmp_path / "provider.md"
    provider.write_text("key: fake\nurl: https://provider.invalid\nmodel: test-model\n", encoding="utf-8")

    summary = run_solo(
        "task",
        "task-1",
        str(tmp_path / "solo-token-budget"),
        str(seed),
        str(checks),
        max_tokens=5,
        provider_path=str(provider),
    )

    assert summary["treatment"] == "S"
    assert summary["stopped_reason"] == "budget_exhausted"
    assert summary["calls"] == 1
    assert summary["prompt_tokens"] + summary["completion_tokens"] == 15
    assert summary["limits"]["max_tokens"] == 5


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_calls": 0},
        {"max_tokens": 0},
        {"max_seconds": 0},
        {"max_seconds": float("nan")},
        {"max_seconds": float("inf")},
    ],
)
def test_llm_rejects_invalid_budget(kwargs):
    with pytest.raises(ValueError):
        LlmClient(object(), "test-model", **kwargs)



def test_transient_failures_are_wrapped_after_three_actual_retries(monkeypatch):
    completions = _ScriptedCompletions([RuntimeError("offline")] * 4)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    llm = LlmClient(client, "test-model")
    monkeypatch.setattr(llm_module, "_RETRYABLE", (RuntimeError,))
    monkeypatch.setattr(llm_module.time, "sleep", lambda _: None)

    with pytest.raises(ProviderUnavailable):
        llm.chat([], [])

    assert completions.calls == 4
    assert llm.retry_attempts == 3


def test_exact_context_length_code_maps_to_context_overflow():
    completions = _ScriptedCompletions(
        [_bad_request({"code": "context_length_exceeded", "message": "too long"})]
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    with pytest.raises(ContextOverflow):
        LlmClient(client, "test-model").chat([], [])


@pytest.mark.parametrize(
    "body",
    [
        {"message": "thinking signature is invalid"},
        {"message": "ordinary bad request"},
        {"code": "unknown", "message": "context_length_exceeded"},
    ],
    ids=["thinking-signature", "ordinary-400", "unknown-code"],
)
def test_other_bad_requests_map_to_provider_protocol_error(body):
    completions = _ScriptedCompletions([_bad_request(body)])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    with pytest.raises(ProviderProtocolError):
        LlmClient(client, "test-model").chat([], [])


def test_other_api_status_error_is_sanitized_protocol_error():
    secret_detail = "provider-private-detail"
    completions = _ScriptedCompletions(
        [_api_status_error({"message": secret_detail})]
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    with pytest.raises(ProviderProtocolError) as raised:
        LlmClient(client, "test-model").chat([], [])

    assert secret_detail not in str(raised.value)


@pytest.mark.parametrize("finish_reason", ["stop", "content_filter"])
def test_optional_sdk_response_fields_normalize_to_empty_values(finish_reason):
    response = _response([], text="done")
    response.choices[0].finish_reason = finish_reason
    response.choices[0].message.tool_calls = None
    response.usage.completion_tokens_details.reasoning_tokens = None
    completions = _ScriptedCompletions([response])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    result = LlmClient(client, "test-model").chat([], [])

    assert result.finish_reason == finish_reason
    assert result.tool_calls == []
    assert result.reasoning_tokens == 0


@pytest.mark.parametrize(
    "malformed_field",
    [
        "missing_choices",
        "empty_choices",
        "missing_message",
        "finish_reason_type",
        "finish_reason_none",
        "finish_reason_empty",
        "finish_reason_unknown",
        "content",
        "tool_id",
        "tool_name",
        "tool_arguments",
    ],
)
def test_malformed_provider_response_stops_loop_without_leaking(
    tmp_path, malformed_field
):
    secret_detail = "provider-private-detail"
    response = _response([])
    response.provider_private_detail = secret_detail
    choice = response.choices[0]
    message = choice.message
    tool_call = _tool_call("call", "list_dir", {})

    if malformed_field == "missing_choices":
        del response.choices
    elif malformed_field == "empty_choices":
        response.choices = []
    elif malformed_field == "missing_message":
        choice.message = None
    elif malformed_field == "finish_reason_type":
        choice.finish_reason = True
    elif malformed_field == "finish_reason_none":
        choice.finish_reason = None
    elif malformed_field == "finish_reason_empty":
        choice.finish_reason = ""
    elif malformed_field == "finish_reason_unknown":
        choice.finish_reason = "unexpected"
    elif malformed_field == "content":
        message.content = {"secret": secret_detail}
    elif malformed_field == "tool_id":
        tool_call.id = None
        message.tool_calls = [tool_call]
    elif malformed_field == "tool_name":
        tool_call.function.name = 7
        message.tool_calls = [tool_call]
    else:
        tool_call.function.arguments = {"secret": secret_detail}
        message.tool_calls = [tool_call]

    completions = _ScriptedCompletions([response])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    llm = LlmClient(client, "test-model")
    messages = [{"role": "system", "content": "system"}]

    result = run_agent_loop(
        llm,
        "system",
        "task",
        [],
        lambda _name, _args: "unused",
        accounting_role="ROLE",
        messages=messages,
    )

    assert result.stopped_reason == "provider_protocol_error"
    assert result.calls == 1
    assert llm.calls_made == 1
    assert llm.usage_by_role["ROLE"]["calls"] == 1
    assert (
        llm.prompt_tokens_total,
        llm.completion_tokens_total,
        llm.reasoning_tokens_total,
    ) == (10, 5, 2)
    failed_call = result.events[0]
    assert failed_call["type"] == "llm_call"
    assert (
        failed_call["prompt_tokens"],
        failed_call["completion_tokens"],
        failed_call["reasoning_tokens"],
    ) == (10, 5, 2)
    assert [event["type"] for event in result.events] == [
        "llm_call",
        "provider_error",
        "stop",
    ]
    assert secret_detail not in json.dumps([result.events, messages])


@pytest.mark.parametrize(
    "usage_error",
    [
        "missing",
        "none",
        "prompt_negative",
        "prompt_none",
        "completion_bool",
        "reasoning_string",
    ],
)
def test_unavailable_usage_stops_as_accounting_error_by_default(
    tmp_path, usage_error
):
    response = _response([], text="must not be recorded")
    if usage_error == "missing":
        del response.usage
    elif usage_error == "none":
        response.usage = None
    elif usage_error == "prompt_negative":
        response.usage.prompt_tokens = -1
    elif usage_error == "prompt_none":
        response.usage.prompt_tokens = None
    elif usage_error == "completion_bool":
        response.usage.completion_tokens = True
    else:
        response.usage.completion_tokens_details.reasoning_tokens = "2"
    completions = _ScriptedCompletions([response])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    llm = LlmClient(client, "test-model")
    messages = [{"role": "system", "content": "system"}]

    result = run_agent_loop(
        llm,
        "system",
        "task",
        [],
        lambda _name, _args: "unused",
        accounting_role="ROLE",
        messages=messages,
    )

    assert result.stopped_reason == "budget_accounting_error"
    assert result.calls == llm.usage_by_role["ROLE"]["calls"] == 1
    assert result.prompt_tokens == result.completion_tokens == 0
    assert [event["type"] for event in result.events] == ["llm_call", "stop"]
    assert result.events[0]["stopped_reason"] == "budget_accounting_error"
    assert [message["role"] for message in messages] == ["system", "user"]


def test_sdk_response_validation_error_is_accounted_protocol_stop(tmp_path):
    secret_detail = "provider-private-detail"
    completions = _ScriptedCompletions(
        [_api_response_validation_error({"message": secret_detail})]
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    llm = LlmClient(client, "test-model")
    messages = [{"role": "system", "content": "system"}]

    result = run_agent_loop(
        llm,
        "system",
        "task",
        [],
        lambda _name, _args: "unused",
        accounting_role="ROLE",
        messages=messages,
    )

    assert result.stopped_reason == "provider_protocol_error"
    assert result.calls == llm.usage_by_role["ROLE"]["calls"] == 1
    assert [event["type"] for event in result.events] == [
        "llm_call",
        "provider_error",
        "stop",
    ]
    assert result.events[0]["failed"] is True
    assert secret_detail not in json.dumps([result.events, messages])



def test_post_response_budget_precedes_malformed_message(tmp_path):
    secret_detail = "provider-private-detail"
    response = _response([], text=secret_detail)
    response.choices[0].message = None
    completions = _ScriptedCompletions([response])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    llm = LlmClient(client, "test-model", max_tokens=1)
    messages = [{"role": "system", "content": "system"}]

    result = run_agent_loop(
        llm,
        "system",
        "task",
        [],
        lambda _name, _args: "unused",
        accounting_role="ROLE",
        messages=messages,
    )

    assert result.stopped_reason == "budget_exhausted"
    assert result.calls == llm.usage_by_role["ROLE"]["calls"] == 1
    assert (result.prompt_tokens, result.completion_tokens, result.reasoning_tokens) == (
        10,
        5,
        2,
    )
    assert [event["type"] for event in result.events] == ["llm_call", "stop"]
    assert result.events[0]["stopped_reason"] == "budget_exhausted"
    assert [message["role"] for message in messages] == ["system", "user"]
    assert secret_detail not in json.dumps([result.events, messages])


def _invalid_json_openai_client(secret_detail):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=f"{{invalid-{secret_detail}".encode(),
            request=request,
        )
    )
    sdk = OpenAI(
        api_key="test-key",
        base_url="https://provider.invalid/v1",
        http_client=httpx.Client(transport=transport),
        max_retries=0,
    )
    return LlmClient(sdk, "test-model")


def test_invalid_json_response_is_accounted_protocol_stop(tmp_path):
    secret_detail = "provider-private-detail"
    llm = _invalid_json_openai_client(secret_detail)
    messages = [{"role": "system", "content": "system"}]

    result = run_agent_loop(
        llm,
        "system",
        "task",
        [],
        lambda _name, _args: "unused",
        accounting_role="ROLE",
        messages=messages,
    )

    assert result.stopped_reason == "provider_protocol_error"
    assert result.calls == llm.usage_by_role["ROLE"]["calls"] == 1
    assert [event["type"] for event in result.events] == [
        "llm_call",
        "provider_error",
        "stop",
    ]
    assert llm.usage_by_role["ROLE"]["llm_duration_ms"] >= 0
    assert secret_detail not in json.dumps([result.events, messages])


def test_invalid_json_response_yields_to_expired_wall_budget(tmp_path):
    secret_detail = "provider-private-detail"
    llm = _invalid_json_openai_client(secret_detail)
    llm.max_seconds = 1
    llm._started_at -= 2
    original_check_budget = llm.check_budget
    checks = 0

    def allow_request_then_check(*, before_call=False):
        nonlocal checks
        checks += 1
        if checks <= 2:
            return None
        return original_check_budget(before_call=before_call)

    llm.check_budget = allow_request_then_check
    messages = [{"role": "system", "content": "system"}]

    result = run_agent_loop(
        llm,
        "system",
        "task",
        [],
        lambda _name, _args: "unused",
        accounting_role="ROLE",
        messages=messages,
    )

    assert result.stopped_reason == "budget_exhausted"
    assert result.calls == llm.usage_by_role["ROLE"]["calls"] == 1
    assert [event["type"] for event in result.events] == ["llm_call", "stop"]
    assert secret_detail not in json.dumps([result.events, messages])


@pytest.mark.parametrize("contradiction", ["missing_calls", "unexpected_calls"])
def test_tool_finish_contradiction_is_sanitized_protocol_failure(
    tmp_path, contradiction
):
    secret_detail = "provider-private-detail"
    if contradiction == "missing_calls":
        response = _response([], text=secret_detail)
        response.choices[0].finish_reason = "tool_calls"
    else:
        response = _response([_tool_call("call", "list_dir", {})], text=secret_detail)
        response.choices[0].finish_reason = "stop"
    completions = _ScriptedCompletions([response])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    llm = LlmClient(client, "test-model")
    messages = [{"role": "system", "content": "system"}]

    result = run_agent_loop(
        llm,
        "system",
        "task",
        [],
        lambda _name, _args: "unused",
        accounting_role="ROLE",
        messages=messages,
    )

    assert result.stopped_reason == "provider_protocol_error"
    assert (result.prompt_tokens, result.completion_tokens, result.reasoning_tokens) == (
        10,
        5,
        2,
    )
    assert [event["type"] for event in result.events] == [
        "llm_call",
        "provider_error",
        "stop",
    ]
    assert result.events[0]["failed"] is True
    assert [message["role"] for message in messages] == ["system", "user"]
    assert secret_detail not in json.dumps([result.events, messages])


@pytest.mark.parametrize("usage_error", ["missing", "invalid"])
def test_unknown_usage_yields_to_expired_wall_budget(tmp_path, usage_error):
    response = _response([], text="provider-private-detail")
    if usage_error == "missing":
        response.usage = None
    else:
        response.usage.prompt_tokens = "10"
    completions = _ScriptedCompletions([response])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    llm = LlmClient(client, "test-model")
    llm.max_seconds = 1
    llm._started_at -= 2
    original_check_budget = llm.check_budget
    checks = 0

    def allow_request_then_check(*, before_call=False):
        nonlocal checks
        checks += 1
        if checks <= 2:
            return None
        return original_check_budget(before_call=before_call)

    llm.check_budget = allow_request_then_check
    messages = [{"role": "system", "content": "system"}]

    result = run_agent_loop(
        llm,
        "system",
        "task",
        [],
        lambda _name, _args: "unused",
        accounting_role="ROLE",
        messages=messages,
    )

    assert result.stopped_reason == "budget_exhausted"
    assert result.calls == llm.usage_by_role["ROLE"]["calls"] == 1
    assert [event["type"] for event in result.events] == ["llm_call", "stop"]
    assert result.events[0]["stopped_reason"] == "budget_exhausted"
    assert [message["role"] for message in messages] == ["system", "user"]
