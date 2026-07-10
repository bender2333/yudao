"""Tests for harness.provider.load_provider (spec §1 / §5)."""

import json
from types import SimpleNamespace

import pytest

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
                finish_reason="tool_calls",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=5,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=2),
        ),
    )


class _ScriptedCompletions:
    def __init__(self, responses):
        self.responses = list(responses)

    def create(self, **kwargs):
        return self.responses.pop(0)


def _patch_multi_provider(monkeypatch, responses):
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=_ScriptedCompletions(responses))
    )
    monkeypatch.setattr(
        "harness.run_multi.load_provider",
        lambda _: {"model": "test-model"},
    )
    monkeypatch.setattr("harness.run_multi.make_client", lambda _: client)


def _read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


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
