import os
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
TESTS_DIR = ROOT / "harness" / "tests"
LAYERS_TOML = TESTS_DIR / "layers.toml"

UNIT = "unit"
MODULE = "module"
INTEGRATION = "integration"

TIMEOUTS = {UNIT: 5, MODULE: 60, INTEGRATION: 300}
# 有些文件的工作量天然超过本层的上限（工单 #753）：发布构建那条用例要装依赖、构建页面并构建 wheel，
# 在 CI 上要三百多秒。上限到了以后 pytest-timeout 在 Windows 上结束整个进程，集成层用 -n 4 运行，
# 结束的进程就是一个 worker，它消失以后报成「worker crashed」而不是一条失败。这些文件单独定时限。
FILE_TIMEOUTS = {"test_release_script.py": 1200}
TMP_FIXTURES = ("tmp_path", "tmp_path_factory", "data_dir")

AUDIT_RESOURCES = {
    "subprocess.Popen": "子进程",
    "socket.connect": "网络连接",
    "socket.bind": "网络端口绑定",
}
UNIT_DENIED = ("subprocess.Popen", "socket.connect", "socket.bind")
MODULE_DENIED = ("socket.connect", "socket.bind")

# Windows 上 asyncio 建 ProactorEventLoop 时，标准库的 socket.socketpair 用一对回环
# 连接实现，产生一次 socket.bind 与一次 socket.connect（回退实现 _fallback_socketpair
# 在标准库 socket.py 中）。activate_once 内部走 asyncio.run，所以这两个事件放行。
# 按地址放行会放过测试里绑定 127.0.0.1:0 起服务的写法，所以看调用栈。
_SOCKET_STDLIB = str(Path(os.__file__).parent / "socket.py")

# 真实模型测试：模型服务的地址、凭据与模型名取自这三个变量（运行配置第 4 节）。
REAL_MODEL = "real_model"
REAL_MODEL_ENV = ("YUDAO_EVAL_BASE_URL", "YUDAO_EVAL_API_KEY", "YUDAO_EVAL_MODEL")

REWRITE_OPTIONS = ("--write-event-baselines", "--write-openapi-snapshot")

_LAYER_KEY = pytest.StashKey[str]()

_current_layer: str | None = None


def _is_event_loop_self_pipe() -> bool:
    frame = sys._getframe(1)
    while frame is not None:
        code = frame.f_code
        if code.co_filename == _SOCKET_STDLIB and code.co_name.endswith("socketpair"):
            return True
        frame = frame.f_back
    return False


def _audit_hook(event: str, _args: object) -> None:
    layer = _current_layer
    if layer is None:
        return
    denied = UNIT_DENIED if layer == UNIT else MODULE_DENIED if layer == MODULE else ()
    if event in denied and not _is_event_loop_self_pipe():
        pytest.fail(f"{layer} 层不允许使用{AUDIT_RESOURCES[event]}（{event}）")


sys.addaudithook(_audit_hook)


def _load_registry() -> dict[str, str]:
    try:
        with open(LAYERS_TOML, "rb") as stream:
            return tomllib.load(stream)["layers"]
    except (OSError, ValueError, KeyError) as exc:
        raise pytest.UsageError(f"读取测试分层登记表失败（{LAYERS_TOML}）：{exc}")


def _relative(path: Path) -> str | None:
    try:
        return path.resolve().relative_to(TESTS_DIR.resolve()).as_posix()
    except ValueError:
        return None


def _registry_layer(nodeid: str, registry: dict[str, str]) -> str | None:
    path = nodeid.split("::", 1)[0].removeprefix("harness/tests/")
    return registry.get(path)


def _refuse_unregistered_and_missing(collected: list[str], registry: dict[str, str]) -> None:
    problems = []
    unregistered = sorted(path for path in collected if path not in registry)
    if unregistered:
        problems.append("以下测试文件没有在 harness/tests/layers.toml 登记层级：\n" + "\n".join(unregistered))
    missing = sorted(path for path in registry if not (TESTS_DIR / path).is_file())
    if missing:
        problems.append("登记表中有以下文件不存在：\n" + "\n".join(missing))
    if problems:
        raise pytest.UsageError("\n".join(problems))


def _workers(config: pytest.Config) -> int:
    if hasattr(config, "workerinput"):
        return 1
    try:
        value = config.getoption("numprocesses")
    except ValueError:
        return 0
    return value if isinstance(value, int) else 0


def _refuse_rewrite_with_workers(config: pytest.Config) -> None:
    rewrites = [option for option in REWRITE_OPTIONS if config.getoption(option[2:].replace("-", "_"), False)]
    if rewrites and _workers(config):
        raise pytest.UsageError(f"{'、'.join(rewrites)} 只允许单进程运行，不能与 -n 同时使用")


def _outside_integration(nodeids: list[str], registry: dict[str, str]) -> list[str]:
    return sorted({nodeid for nodeid in nodeids if _registry_layer(nodeid, registry) != INTEGRATION})


def _refuse_outside_integration(workers: int, outside: list[str]) -> None:
    if workers and outside:
        shown = "\n".join(outside[:10])
        extra = f"\n……共 {len(outside)} 项" if len(outside) > 10 else ""
        raise pytest.UsageError(f"多进程（-n {workers}）只能运行集成层测试，以下选中的测试不是集成层：\n{shown}{extra}")


def _deselect_real_model(config: pytest.Config, items: list[pytest.Item]) -> None:
    """没有明确选择 `-m real_model` 时，真实模型测试不进入本次运行（凭据在环境中也不运行）。"""
    if REAL_MODEL in (config.getoption("markexpr", "") or ""):
        return
    kept = [item for item in items if item.get_closest_marker(REAL_MODEL) is None]
    dropped = [item for item in items if item.get_closest_marker(REAL_MODEL) is not None]
    if dropped:
        config.hook.pytest_deselected(items=dropped)
        items[:] = kept


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    _deselect_real_model(config, items)
    registry = _load_registry()
    for item in items:
        path = getattr(item, "path", None)
        relative = _relative(path) if path is not None else None
        layer = registry.get(relative) if relative is not None else None
        if layer is None:
            continue
        item.add_marker(getattr(pytest.mark, layer))
        item.add_marker(pytest.mark.timeout(FILE_TIMEOUTS.get(relative, TIMEOUTS[layer])))
        item.stash[_LAYER_KEY] = layer


def pytest_collection_finish(session: pytest.Session) -> None:
    registry = _load_registry()
    collected: list[str] = []
    nodeids: list[str] = []
    for item in session.items:
        path = getattr(item, "path", None)
        name = _relative(path) if path is not None else None
        if name is None:
            continue
        collected.append(name)
        nodeids.append(item.nodeid)
    _refuse_unregistered_and_missing(collected, registry)
    if hasattr(session.config, "workerinput"):
        return
    _refuse_rewrite_with_workers(session.config)
    _refuse_outside_integration(_workers(session.config), _outside_integration(nodeids, registry))


def pytest_xdist_node_collection_finished(node: object, ids: list[str]) -> None:  # noqa: ARG001
    from _pytest.config import Config

    config = node.config if hasattr(node, "config") else None
    assert isinstance(config, Config)
    _refuse_rewrite_with_workers(config)
    _refuse_outside_integration(1, _outside_integration(list(ids), _load_registry()))


def _tmp_fixtures(item: pytest.Item) -> list[str]:
    info = getattr(item, "_fixtureinfo", None)
    names = info.argnames if info is not None else getattr(item, "fixturenames", ())
    return [name for name in TMP_FIXTURES if name in names]


def pytest_runtest_setup(item: pytest.Item) -> None:
    if item.get_closest_marker(REAL_MODEL) is not None:
        missing = [name for name in REAL_MODEL_ENV if not os.environ.get(name)]
        if missing:
            pytest.skip("真实模型测试缺少环境变量：" + "、".join(missing))
    layer = item.stash.get(_LAYER_KEY, None)
    if layer is None:
        return
    requested = _tmp_fixtures(item)
    if layer == UNIT and requested:
        pytest.fail(f"unit 层不允许使用临时目录（{', '.join(requested)}）")
    global _current_layer
    _current_layer = layer


def pytest_sessionfinish() -> None:
    global _current_layer
    _current_layer = None
