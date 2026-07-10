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


def _response(tool_calls):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="", tool_calls=tool_calls),
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
    completions = _ScriptedCompletions(
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
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setattr(
        "harness.run_multi.load_provider",
        lambda _: {"model": "test-model"},
    )
    monkeypatch.setattr("harness.run_multi.make_client", lambda _: client)
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
