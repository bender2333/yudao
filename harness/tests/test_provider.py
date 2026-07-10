"""Tests for harness.provider.load_provider (spec §1 / §5)."""

import pytest

from harness.provider import load_provider
from harness.run_multi import run_multi_cli
from harness.run_solo import run_solo


def _write(tmp_path, text):
    p = tmp_path / "provider.md"
    p.write_text(text, encoding="utf-8")
    return str(p)


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
