# 命令行入口（工单 #206、#373）：yudao --version 输出发布版本号。
# 模型目录与凭据文件的默认位置（工单 #298，docs/design/web-interface-and-release.md「数据目录」）：按生效的 --data-dir 求出。
# --data-dir 与 --provider-config 写在子命令之前或之后都生效（工单 #315）：解析器自身不给默认值，
# 生效值由 _data_dir 按子命令求出。
#
# 工单 #373 以后 yudao client install 子命令不再提供，界面改为服务提供的网页。


from contextlib import contextmanager
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path
import sqlite3
import sys
import threading
import time

import pytest

from harness.__main__ import _data_dir, build_parser, release_version, _provider_paths
from harness.app.application import Application, ReadOnlyCore
from harness.app.project_queries import ProjectsList
from harness.data_directory import default_dotenv
from harness.event_store import EventStore

def test_version_option_prints_the_release_version(capsys):
    assert release_version() == version("yudao-harness")
    try:
        build_parser().parse_args(["--version"])
    except SystemExit as exit_code:
        assert exit_code.code == 0
    assert capsys.readouterr().out.strip() == release_version()


def test_the_catalog_and_credentials_default_to_the_data_directory(tmp_path):
    # 没有明确给 --provider-config 时目录文件在 --data-dir 内，admissions.json 由门面按同目录派生
    data_dir = tmp_path / "data"
    parsed = build_parser().parse_args(["--data-dir", str(data_dir), "api"])
    assert parsed.provider_config is None
    config, dotenv = _provider_paths(parsed.data_dir, parsed.provider_config)
    assert config == (data_dir / "providers.json").resolve()
    assert dotenv == default_dotenv(data_dir).resolve()

def test_an_explicit_provider_config_wins_over_the_data_directory(tmp_path):
    # 明确给了 --provider-config 时以它为准，凭据文件仍在数据目录内
    data_dir = tmp_path / "data"
    elsewhere = tmp_path / "elsewhere" / "catalog.json"
    parsed = build_parser().parse_args(["api", "--data-dir", str(data_dir),
                                       "--provider-config", str(elsewhere)])
    config, dotenv = _provider_paths(parsed.data_dir, parsed.provider_config)
    assert config == elsewhere.resolve()
    assert dotenv == default_dotenv(data_dir).resolve()

def test_an_empty_provider_config_reads_no_catalog(tmp_path):
    # 空字符串表示不读取目录文件（服务锁与发布验收的测试这样启动空态服务）
    config, dotenv = _provider_paths(tmp_path / "data", "")
    assert config is None
    assert dotenv == default_dotenv(tmp_path / "data").resolve()


def test_smoke_takes_the_provider_config_from_either_position(tmp_path):
    # 写在 smoke 之前与之后的 --provider-config 都生效；两处都没有给出时按生效的数据目录求出
    for argv in (["--provider-config", str(tmp_path / "before.json"), "smoke"],
                 ["smoke", "--provider-config", str(tmp_path / "after.json")]):
        parsed = build_parser().parse_args(argv)
        assert parsed.provider_config == argv[argv.index("--provider-config") + 1]
    parsed = build_parser().parse_args(["--data-dir", str(tmp_path / "data"), "smoke"])
    config, dotenv = _provider_paths(_data_dir(parsed, "smoke"), parsed.provider_config)
    assert config == (tmp_path / "data" / "providers.json").resolve()
    assert dotenv == default_dotenv(tmp_path / "data").resolve()


def test_release_check_takes_the_repository_and_the_data_directory_from_either_position(tmp_path):
    # 发布检查（工单 #355）：待发布仓库是位置参数，--data-dir 写在子命令之前或之后都生效
    before = build_parser().parse_args(["--data-dir", str(tmp_path), "release-check", "some-repo"])
    assert before.command == "release-check" and before.repository == "some-repo"
    assert _data_dir(before, "release-check") == str(tmp_path)
    after = build_parser().parse_args(["release-check", "some-repo", "--data-dir", str(tmp_path)])
    assert after.command == "release-check" and after.repository == "some-repo"
    assert _data_dir(after, "release-check") == str(tmp_path)


@dataclass
class _SqliteShmDirectoryBlock:
    target_path: Path
    shm_path: Path
    release_on_retry: bool
    connect_attempts: int = 0
    closed_before_retry: bool = False
    released_on_retry: bool = False
    pending_handle: bool = False
    connections: list[sqlite3.Connection] = field(default_factory=list)


_ACTIVE_SHM_BLOCKS: dict[tuple[int, Path], _SqliteShmDirectoryBlock] = {}


def _is_connection_closed(connection: sqlite3.Connection) -> bool:
    try:
        connection.execute("PRAGMA query_only")
    except sqlite3.ProgrammingError:
        return True
    except sqlite3.OperationalError:
        return False
    return False


def _sqlite_shm_audit_hook(event: str, args: tuple[object, ...]) -> None:
    if not _ACTIVE_SHM_BLOCKS:
        return
    if event == "sqlite3.connect" and args:
        try:
            resolved = Path(str(args[0])).resolve()
        except OSError:
            return
        block = _ACTIVE_SHM_BLOCKS.get((threading.get_ident(), resolved))
        if block is None:
            return
        if block.release_on_retry and block.connect_attempts == 1:
            block.closed_before_retry = bool(block.connections) and all(
                _is_connection_closed(conn) for conn in block.connections
            )
            if block.shm_path.is_dir():
                block.shm_path.rmdir()
                block.released_on_retry = True
        block.connect_attempts += 1
        block.pending_handle = True
    elif event == "sqlite3.connect/handle" and args:
        tid = threading.get_ident()
        for (watch_tid, _), block in list(_ACTIVE_SHM_BLOCKS.items()):
            if watch_tid == tid and block.pending_handle:
                block.pending_handle = False
                conn = args[0]
                if isinstance(conn, sqlite3.Connection):
                    block.connections.append(conn)
                break


sys.addaudithook(_sqlite_shm_audit_hook)


@contextmanager
def _sqlite_shm_directory_block(sqlite_path: Path, *, release_on_retry: bool):
    # 在 WAL 共享内存路径建立真实空目录：连接与 query_only 正常完成后，首次读取 log_id 打开共享内存文件失败并抛出 OperationalError；
    # 审计钩子在第二次 sqlite3.connect 事件到达时核对首次失败连接已关闭并移除目录，实现无轮询与无固定时长等待的确定性恢复
    resolved = sqlite_path.resolve()
    shm_path = sqlite_path.with_name(sqlite_path.name + "-shm")
    shm_path.mkdir()
    key = (threading.get_ident(), resolved)
    block = _SqliteShmDirectoryBlock(
        target_path=resolved,
        shm_path=shm_path,
        release_on_retry=release_on_retry,
    )
    _ACTIVE_SHM_BLOCKS[key] = block
    try:
        yield block
    finally:
        _ACTIVE_SHM_BLOCKS.pop(key, None)
        if shm_path.is_dir():
            shm_path.rmdir()


def test_read_only_event_store_retries_transient_operational_error_and_closes_failed_connection(tmp_path: Path) -> None:
    # 守 R3（docs/design/test-pyramid.md「测试按三环留」）：只读打开事件库遇到瞬时 OperationalError 时先关闭失败连接并在上限内重试恢复
    sqlite_path = tmp_path / "data" / "events.sqlite"
    writable = EventStore(sqlite_path)
    expected_log_id = writable.log_id
    writable.close()

    with _sqlite_shm_directory_block(sqlite_path, release_on_retry=True) as block:
        store = EventStore(sqlite_path, read_only=True)
    assert block.connect_attempts == 2
    assert block.released_on_retry
    assert block.closed_before_retry
    try:
        assert store.log_id == expected_log_id
        assert len(store._opened) == 1
    finally:
        store.close()
    assert all(_is_connection_closed(conn) for conn in block.connections)
    sqlite_path.unlink()


def test_open_readonly_application_retries_transient_sqlite_operational_error(tmp_path: Path) -> None:
    # 守 R3（docs/design/app-and-interface.md「命令行」）：命令行离线只读查询经 ReadOnlyCore 打开数据目录时可从瞬时锁错误恢复
    data_dir = tmp_path / "data"
    sqlite_path = data_dir / "events.sqlite"
    writable = EventStore(sqlite_path)
    writable.close()

    with _sqlite_shm_directory_block(sqlite_path, release_on_retry=True) as block:
        application = Application.open_readonly(data_dir)
    assert block.connect_attempts == 2
    assert block.released_on_retry
    assert block.closed_before_retry
    try:
        snapshot = application.query("projects.list", ProjectsList())
        assert snapshot.data.projects == []
    finally:
        application.close()
    assert all(_is_connection_closed(conn) for conn in block.connections)
    sqlite_path.unlink()


def test_read_only_open_reraises_operational_error_after_timeout_and_closes_connections(tmp_path: Path) -> None:
    # 守 R3（docs/design/test-pyramid.md「测试按三环留」）：只读打开持续遭遇 OperationalError 超过 5 秒上限时关闭连接并原样抛出异常
    data_dir = tmp_path / "data"
    sqlite_path = data_dir / "events.sqlite"
    writable = EventStore(sqlite_path)
    writable.close()

    started = time.monotonic()
    with _sqlite_shm_directory_block(sqlite_path, release_on_retry=False) as block:
        with pytest.raises(sqlite3.OperationalError):
            ReadOnlyCore(data_dir)
    elapsed = time.monotonic() - started
    assert 5.0 <= elapsed < 15.0
    assert block.connect_attempts >= 2
    assert all(_is_connection_closed(conn) for conn in block.connections)
    sqlite_path.unlink()
