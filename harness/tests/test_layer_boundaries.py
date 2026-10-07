# 分层边界检查的测试（测试分层设计说明第 2 节）
#
# 每项检查各有一项测试证明它会拒绝：用 pytest 自带的 pytester 起独立的 pytest
# 会话，示例会话导入仓库根 conftest 的真实钩子，只把登记表指向临时目录。
# 这些检查测试自己会启动子进程，只能登记为 module。

from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

ROOT = Path(__file__).resolve().parents[2]
SESSION_CONFTEST = (
    "import importlib.util\n"
    "from pathlib import Path\n"
    "\n"
    f"_ROOT = Path(r\"{ROOT}\")\n"
    '_spec = importlib.util.spec_from_file_location("_yudao_layers", _ROOT / "conftest.py")\n'
    "_layers = importlib.util.module_from_spec(_spec)\n"
    "_spec.loader.exec_module(_layers)\n"
    "_layers.TESTS_DIR = Path(__file__).parent\n"
    '_layers.LAYERS_TOML = Path(__file__).parent / "layers.toml"\n'
    "\n"
    "def pytest_addoption(parser):\n"
    '    parser.addoption("--write-event-baselines", action="store_true", default=False)\n'
    '    parser.addoption("--write-openapi-snapshot", action="store_true", default=False)\n'
    "\n"
    "def pytest_collection_modifyitems(config, items):\n"
    "    _layers.pytest_collection_modifyitems(config, items)\n"
    "\n"
    "def pytest_collection_finish(session):\n"
    "    _layers.pytest_collection_finish(session)\n"
    "\n"
    "def pytest_xdist_node_collection_finished(node, ids):\n"
    "    _layers.pytest_xdist_node_collection_finished(node, ids)\n"
    "\n"
    "def pytest_runtest_setup(item):\n"
    "    _layers.pytest_runtest_setup(item)\n"
    "\n"
    "def pytest_sessionfinish(session):\n"
    "    _layers.pytest_sessionfinish()\n"
)

LAYERS_TOML = "[layers]\n{entries}\n"

PASS_CASE = "def test_example():\n    pass\n"
SUBPROCESS_CASE = (
    "import subprocess\nimport sys\n\n\n"
    "def test_example():\n"
    "    subprocess.run([sys.executable, '-c', 'pass'], check=True)\n"
)
CONNECT_CASE = (
    "import socket\n\n\n"
    "def test_example():\n"
    "    socket.socket().connect(('127.0.0.1', 9))\n"
)
BIND_CASE = (
    "import socket\n\n\n"
    "def test_example():\n"
    "    sock = socket.socket()\n"
    "    try:\n"
    "        sock.bind(('127.0.0.1', 0))\n"
    "    finally:\n"
    "        sock.close()\n"
)
TMP_CASE = "def test_example(tmp_path):\n    pass\n"
GIT_CASE = (
    "import subprocess\n\n\n"
    "def test_example(tmp_path):\n"
    "    subprocess.run(['git', '--version'], check=True, capture_output=True)\n"
)
SLEEP_CASE = "import time\n\n\ndef test_example():\n    time.sleep(30)\n"


def _scaffold(pytester: pytest.Pytester, cases: dict[str, str], layers: dict[str, str]) -> None:
    pytester.makeconftest(SESSION_CONFTEST)
    for name, body in cases.items():
        pytester.makepyfile(**{name: body})
    entries = "\n".join(f'"{name}.py" = "{layer}"' for name, layer in layers.items())
    (pytester.path / "layers.toml").write_text(LAYERS_TOML.format(entries=entries), encoding="utf-8")


def _unit_session(pytester: pytest.Pytester, body: str) -> pytest.RunResult:
    _scaffold(pytester, {"test_example": body}, {"test_example": "unit"})
    return pytester.runpytest_subprocess()


def _failed_with(result: pytest.RunResult, word: str) -> None:
    result.stdout.fnmatch_lines("*1 failed*")
    assert word in result.stdout.str()


def test_unit_denies_subprocess(pytester: pytest.Pytester) -> None:
    _failed_with(_unit_session(pytester, SUBPROCESS_CASE), "子进程")


def test_unit_denies_socket_connect(pytester: pytest.Pytester) -> None:
    _failed_with(_unit_session(pytester, CONNECT_CASE), "网络连接")


def test_unit_denies_socket_bind(pytester: pytest.Pytester) -> None:
    _failed_with(_unit_session(pytester, BIND_CASE), "网络端口绑定")


def test_unit_denies_tmp_dir(pytester: pytest.Pytester) -> None:
    _scaffold(pytester, {"test_example": TMP_CASE}, {"test_example": "unit"})
    result = pytester.runpytest_subprocess()
    result.stdout.fnmatch_lines("*1 error*")
    assert "临时目录" in result.stdout.str()


def test_module_denies_socket_bind(pytester: pytest.Pytester) -> None:
    _scaffold(pytester, {"test_example": BIND_CASE}, {"test_example": "module"})
    _failed_with(pytester.runpytest_subprocess(), "网络端口绑定")


def test_module_allows_tmp_dir_and_git_subprocess(pytester: pytest.Pytester) -> None:
    _scaffold(pytester, {"test_example": GIT_CASE}, {"test_example": "module"})
    pytester.runpytest_subprocess().assert_outcomes(passed=1)


def test_unit_timeout_fails_and_dumps_stacks(pytester: pytest.Pytester) -> None:
    _scaffold(pytester, {"test_example": SLEEP_CASE}, {"test_example": "unit"})
    result = pytester.runpytest_subprocess()
    assert result.ret != 0
    assert "Timeout" in result.stdout.str()


def test_unregistered_file_fails_collection(pytester: pytest.Pytester) -> None:
    _scaffold(pytester, {"test_example": PASS_CASE}, {})
    result = pytester.runpytest_subprocess()
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "test_example.py" in result.stderr.str()


def test_missing_registered_file_fails_collection(pytester: pytest.Pytester) -> None:
    _scaffold(pytester, {"test_example": PASS_CASE},
              {"test_example": "integration", "test_gone.py": "integration"})
    result = pytester.runpytest_subprocess()
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "test_gone.py" in result.stderr.str()


def test_workers_refuse_non_integration(pytester: pytest.Pytester) -> None:
    _scaffold(pytester, {"test_example": PASS_CASE}, {"test_example": "unit"})
    result = pytester.runpytest_subprocess("-n", "2")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "只能运行集成层" in result.stderr.str()


def test_workers_run_integration_only(pytester: pytest.Pytester) -> None:
    _scaffold(pytester, {"test_example": PASS_CASE}, {"test_example": "integration"})
    pytester.runpytest_subprocess("-n", "2").assert_outcomes(passed=1)


def test_rewrite_with_workers_is_refused(pytester: pytest.Pytester) -> None:
    _scaffold(pytester, {"test_example": PASS_CASE}, {"test_example": "integration"})
    result = pytester.runpytest_subprocess("-n", "2", "--write-event-baselines")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "只允许单进程" in result.stderr.str()
