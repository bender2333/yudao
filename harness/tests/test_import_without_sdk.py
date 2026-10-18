import json
import subprocess
import sys
from pathlib import Path

# 模型 SDK（openai 与 anthropic）每个要导入约 2 秒，只在模型目录用到对应协议时才导入（D09）。
# 没有用到协议的进程不付这笔时间：测试每启动一个子进程都会付一次。

REPOSITORY = Path(__file__).resolve().parents[2]

LOADED_SDKS = "import json, sys; print(json.dumps(sorted(name for name in ('openai', 'anthropic') if name in sys.modules)))"


def _loaded_sdks(prelude: str) -> list[str]:
    completed = subprocess.run([sys.executable, "-c", prelude + LOADED_SDKS], cwd=REPOSITORY,
                               capture_output=True, text=True, timeout=300)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_importing_the_runtime_does_not_import_the_model_sdks():
    assert _loaded_sdks("import harness.runtime\n") == []


def test_fake_protocol_catalog_does_not_import_the_model_sdks():
    prelude = """
from harness.providers import ProviderFacade
ProviderFacade(startup_mode="test").store_document({
    "providers": [{"id": "p", "name": "P", "base_url": "http://127.0.0.1:1/v1",
                   "credential_ref": "K", "timeout_sec": 20.0, "preset_id": ""}],
    "models": [{"id": "m", "provider_id": "p", "model": "x", "protocol": "fake",
                "context_window": 32000, "max_output_tokens": 2048, "capability_source": "preset-v1"}],
    "bindings": {},
})
"""
    assert _loaded_sdks(prelude) == []


def test_catalog_with_one_protocol_imports_only_that_sdk():
    prelude = """
from harness.providers import ProviderFacade
facade = ProviderFacade()
document = {
    "providers": [{"id": "p", "name": "P", "base_url": "http://127.0.0.1:1/v1",
                   "credential_ref": "K", "timeout_sec": 20.0, "preset_id": ""}],
    "models": [{"id": "m", "provider_id": "p", "model": "x", "protocol": "messages",
                "context_window": 32000, "max_output_tokens": 2048, "capability_source": "preset-v1"}],
    "bindings": {},
}
facade.store_document(document)
"""
    assert _loaded_sdks(prelude) == ["anthropic"]


def test_version_command_does_not_import_the_model_sdks():
    prelude = """
import runpy, sys
sys.argv = ["harness", "--version"]
try:
    runpy.run_module("harness", run_name="__main__")
except SystemExit:
    pass
"""
    assert _loaded_sdks(prelude) == []
