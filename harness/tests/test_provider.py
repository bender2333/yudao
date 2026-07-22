"""Tests for harness.provider.load_provider (spec §1 / §5)."""

import json
from types import SimpleNamespace

import httpx
import pytest
from openai import APIStatusError, BadRequestError

import harness.llm as llm_module
from harness.agent_loop import run_agent_loop
from harness.llm import (
    ContextOverflow,
    LlmClient,
    ProviderProtocolError,
    ProviderUnavailable,
)
from harness.provider import load_provider
from harness.run_multi import run_multi_cli
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


def _patch_multi_provider(monkeypatch, responses):
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=_ScriptedCompletions(responses))
    )
    monkeypatch.setattr(
        "harness.run_multi.load_provider",
        lambda _: {"model": "test-model"},
    )
    monkeypatch.setattr("harness.run_multi.make_client", lambda _: client)


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


@pytest.mark.parametrize("runner", [run_solo, run_multi_cli])
def test_runner_rejects_existing_run_directory(tmp_path, runner):
    with pytest.raises(FileExistsError):
        runner(
            "task",
            str(tmp_path),
            provider_path=str(tmp_path / "missing-provider.md"),
        )


def test_run_multi_cli_writes_summary_when_budget_exhausted(tmp_path, monkeypatch):
    understanding = {
        "summary": "s",
        "requirements": "r",
        "constraints": "c",
        "done_criteria": "d",
    }
    _patch_multi_provider(
        monkeypatch,
        [
            _response(
                [_tool_call("u", "submit_understanding", understanding)]
            ),
            _response(
                [
                    _tool_call(
                        "w",
                        "write_file",
                        {"path": "out.py", "content": "print(1)\n"},
                    )
                ]
            ),
        ]
    )
    run_dir = tmp_path / "budget-run"

    summary = run_multi_cli(
        "task",
        str(run_dir),
        max_calls=2,
        provider_path="ignored.md",
    )

    saved = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert saved == summary
    assert summary["outcome"] == "escalated"
    assert summary["stopped_reason"] == "budget_exhausted"
    assert summary["calls"] == 2
    for metric in (
        "calls",
        "prompt_tokens",
        "completion_tokens",
        "reasoning_tokens",
    ):
        assert summary[metric] == sum(
            role[metric] for role in summary["per_role"].values()
        )
    assert sorted(path.name for path in (run_dir / "sessions").iterdir()) == [
        "plan_execute.jsonl",
        "understand.jsonl",
        "verify.jsonl",
    ]
    assert summary["handoff_count"] == len(
        _read_jsonl(run_dir / "handoffs.jsonl")
    )


def test_run_multi_cli_writes_isolated_sessions_and_handoffs(tmp_path, monkeypatch):
    understanding = {
        "summary": "s",
        "requirements": "r",
        "constraints": "c",
        "done_criteria": "d",
    }
    _patch_multi_provider(
        monkeypatch,
        [
            _response(
                [_tool_call("u", "submit_understanding", understanding)],
                text="U_PRIVATE_TRACE",
            ),
            _response(
                [
                    _tool_call(
                        "w",
                        "write_file",
                        {"path": "out.py", "content": "print(1)\n"},
                    ),
                    _tool_call(
                        "p",
                        "submit_ready",
                        {"notes": "PLAN_NOTES_PRIVATE_TRACE"},
                    ),
                ],
                text="PLAN_PRIVATE_TRACE",
            ),
            _response(
                [
                    _tool_call(
                        "v",
                        "submit_verdict",
                        {"status": "pass", "reason": "verified"},
                    )
                ],
                text="VERIFY_PRIVATE_TRACE",
            ),
        ],
    )
    run_dir = tmp_path / "success-run"

    summary = run_multi_cli(
        "L0_ONLY_TRACE",
        str(run_dir),
        provider_path="ignored.md",
    )

    assert summary["session_model"] == "persistent"
    files = {
        "UNDERSTAND": "understand.jsonl",
        "PLAN_EXECUTE": "plan_execute.jsonl",
        "VERIFY": "verify.jsonl",
    }
    sessions = {
        role: _read_jsonl(run_dir / "sessions" / filename)
        for role, filename in files.items()
    }
    for role, messages in sessions.items():
        assert len(messages) == summary["per_role"][role]["message_count"]
        assert sum(
            len(json.dumps(message, ensure_ascii=False, separators=(",", ":")))
            for message in messages
        ) == summary["per_role"][role]["message_chars"]

    handoffs = _read_jsonl(run_dir / "handoffs.jsonl")
    assert [handoff["seq"] for handoff in handoffs] == [1, 2, 3]
    assert [handoff["kind"] for handoff in handoffs] == [
        "NewMission",
        "ExecuteAgainstUnderstanding",
        "VerifyAgainstUnderstanding",
    ]
    assert summary["handoff_count"] == len(handoffs)
    for handoff in handoffs:
        assert any(
            message.get("content") == handoff["content"]
            for message in sessions[handoff["target"]]
        )

    plan_blob = json.dumps(sessions["PLAN_EXECUTE"])
    verify_blob = json.dumps(sessions["VERIFY"])
    handoff_blob = json.dumps(handoffs)
    assert "L0_ONLY_TRACE" not in plan_blob and "L0_ONLY_TRACE" not in verify_blob
    assert "U_PRIVATE_TRACE" not in plan_blob and "U_PRIVATE_TRACE" not in verify_blob
    assert "PLAN_PRIVATE_TRACE" not in verify_blob
    assert "PLAN_NOTES_PRIVATE_TRACE" not in verify_blob
    assert "U_PRIVATE_TRACE" not in handoff_blob
    assert "PLAN_PRIVATE_TRACE" not in handoff_blob
    assert "PLAN_NOTES_PRIVATE_TRACE" not in handoff_blob
    assert "VERIFY_PRIVATE_TRACE" not in handoff_blob


def test_token_budget_is_shared_across_multi_roles(tmp_path, monkeypatch):
    understanding = {
        "summary": "s",
        "requirements": "r",
        "constraints": "c",
        "done_criteria": "d",
    }
    _patch_multi_provider(
        monkeypatch,
        [
            _response(
                [_tool_call("u", "submit_understanding", understanding)]
            ),
            _response(
                [
                    _tool_call(
                        "w",
                        "write_file",
                        {"path": "out.py", "content": "print(1)\n"},
                    )
                ]
            ),
        ],
    )

    run_dir = tmp_path / "token-budget"
    summary = run_multi_cli(
        "task",
        str(run_dir),
        max_tokens=25,
        provider_path="ignored.md",
    )

    assert summary["outcome"] == "escalated"
    assert summary["stopped_reason"] == "budget_exhausted"
    assert summary["calls"] == 2
    assert summary["prompt_tokens"] + summary["completion_tokens"] == 30
    assert summary["per_role"]["UNDERSTAND"]["calls"] == 1
    assert summary["per_role"]["PLAN_EXECUTE"]["calls"] == 1
    assert summary["budget"]["max_tokens"] == 25
    events = _read_jsonl(run_dir / "events.jsonl")
    assert sum(event["type"] == "llm_call" for event in events) == summary["calls"]
    plan_messages = _read_jsonl(run_dir / "sessions" / "plan_execute.jsonl")
    assert [message["role"] for message in plan_messages] == [
        "system",
        "user",
        "assistant",
    ]


def test_wall_budget_stops_before_first_multi_call(tmp_path, monkeypatch):
    _patch_multi_provider(monkeypatch, [])

    summary = run_multi_cli(
        "task",
        str(tmp_path / "wall-budget"),
        max_seconds=1e-12,
        provider_path="ignored.md",
    )

    assert summary["outcome"] == "escalated"
    assert summary["stopped_reason"] == "budget_exhausted"
    assert summary["calls"] == 0
    assert summary["budget"]["max_seconds"] == 1e-12


def test_solo_uses_the_same_token_budget(tmp_path, monkeypatch):
    _patch_solo_provider(monkeypatch, [_response([], text="done")])

    summary = run_solo(
        "task",
        str(tmp_path / "solo-token-budget"),
        max_tokens=5,
        provider_path="ignored.md",
    )

    assert summary["mode"] == "solo"
    assert summary["stopped_reason"] == "budget_exhausted"
    assert summary["calls"] == 1
    assert summary["prompt_tokens"] + summary["completion_tokens"] == 15
    assert summary["budget"]["max_tokens"] == 5


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


def test_missing_provider_usage_fails_token_budget_loudly(tmp_path, monkeypatch):
    _patch_multi_provider(
        monkeypatch,
        [
            _response_without_usage(
                [
                    _tool_call(
                        "u",
                        "submit_understanding",
                        {
                            "summary": "s",
                            "requirements": "r",
                            "constraints": "c",
                            "done_criteria": "d",
                        },
                    )
                ]
            )
        ],
    )
    run_dir = tmp_path / "missing-usage"

    summary = run_multi_cli(
        "task",
        str(run_dir),
        max_tokens=100,
        provider_path="ignored.md",
    )

    assert summary["outcome"] == "escalated"
    assert summary["stopped_reason"] == "budget_accounting_error"
    assert summary["calls"] == 1
    events = _read_jsonl(run_dir / "events.jsonl")
    assert sum(event["type"] == "llm_call" for event in events) == 1


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
        "finish_reason",
        "content",
        "tool_id",
        "tool_name",
        "tool_arguments",
        "prompt_tokens",
        "prompt_tokens_none",
        "completion_tokens",
        "reasoning_tokens",
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
    elif malformed_field == "finish_reason":
        choice.finish_reason = True
    elif malformed_field == "content":
        message.content = {"secret": secret_detail}
    elif malformed_field == "tool_id":
        tool_call.id = None
        message.tool_calls = [tool_call]
    elif malformed_field == "tool_name":
        tool_call.function.name = 7
        message.tool_calls = [tool_call]
    elif malformed_field == "tool_arguments":
        tool_call.function.arguments = {"secret": secret_detail}
        message.tool_calls = [tool_call]
    elif malformed_field == "prompt_tokens":
        response.usage.prompt_tokens = -1
    elif malformed_field == "prompt_tokens_none":
        response.usage.prompt_tokens = None
    elif malformed_field == "completion_tokens":
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
        str(tmp_path),
        accounting_role="ROLE",
        messages=messages,
    )

    assert result.stopped_reason == "provider_protocol_error"
    assert result.calls == 1
    assert llm.calls_made == 1
    assert llm.usage_by_role["ROLE"]["calls"] == 1
    assert llm.usage_by_role["ROLE"]["llm_duration_ms"] >= 0
    assert (
        llm.prompt_tokens_total,
        llm.completion_tokens_total,
        llm.reasoning_tokens_total,
    ) == (0, 0, 0)
    assert [event["type"] for event in result.events] == [
        "llm_call",
        "provider_error",
        "stop",
    ]
    assert secret_detail not in json.dumps([result.events, messages])
