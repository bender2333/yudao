# 命令行入口（工单 #206、#373）：yudao --version 输出发布版本号。
# 模型目录与凭据文件的默认位置（工单 #298，docs/design/web-interface-and-release.md「数据目录」）：按生效的 --data-dir 求出。
# --data-dir 与 --provider-config 写在子命令之前或之后都生效（工单 #315）：解析器自身不给默认值，
# 生效值由 _data_dir 按子命令求出。
#
# 工单 #373 以后 yudao client install 子命令不再提供，界面改为服务提供的网页。


from contextlib import contextmanager
from importlib.metadata import version
import os
from pathlib import Path
import sqlite3
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


@contextmanager
def _locked_sqlite_data_pages(sqlite_path: Path):
    # 锁定事件库数据页制造真实的 sqlite3.OperationalError，保留文件头可读使连接先进入已打开列表再在读取 log_id 时失败
    if os.name == "nt":
        import msvcrt

        lock_len = max(4096, sqlite_path.stat().st_size - 4096)
        handle = sqlite_path.open("r+b")
        handle.seek(4096)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, lock_len)
        try:
            yield
        finally:
            handle.seek(4096)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, lock_len)
            handle.close()
    else:
        os.chmod(sqlite_path, 0)
        try:
            yield
        finally:
            os.chmod(sqlite_path, 0o644)


@contextmanager
def _transient_sqlite_read_lock(sqlite_path: Path):
    # 持有真实文件锁直到观测到首次只读查询建立并关闭共享内存映射文件，随即释放锁供后续重试恢复
    locked = threading.Event()
    stop_waiting = threading.Event()
    released_after_failure = threading.Event()
    shm_path = sqlite_path.with_name(sqlite_path.name + "-shm")

    def holder() -> None:
        with _locked_sqlite_data_pages(sqlite_path):
            locked.set()
            deadline = time.monotonic() + 10.0
            if os.name == "nt":
                first_ctime_ns: int | None = None
                while not stop_waiting.is_set() and time.monotonic() < deadline:
                    if first_ctime_ns is None:
                        if shm_path.exists():
                            try:
                                first_ctime_ns = shm_path.stat().st_ctime_ns
                            except OSError:
                                released_after_failure.set()
                                break
                    else:
                        try:
                            if shm_path.stat().st_ctime_ns != first_ctime_ns:
                                released_after_failure.set()
                                break
                        except OSError:
                            released_after_failure.set()
                            break
                    time.sleep(0.005)
            else:
                stop_waiting.wait(timeout=0.25)
                released_after_failure.set()

    worker = threading.Thread(target=holder, daemon=True)
    worker.start()
    assert locked.wait(timeout=10.0)
    try:
        yield released_after_failure
    finally:
        stop_waiting.set()
        worker.join(timeout=10.0)


def test_read_only_event_store_retries_transient_operational_error_and_closes_failed_connection(tmp_path: Path) -> None:
    # 守 R3（docs/design/test-pyramid.md「测试按三环留」）：只读打开事件库遇到瞬时 OperationalError 时先关闭失败连接并在上限内重试恢复
    sqlite_path = tmp_path / "data" / "events.sqlite"
    writable = EventStore(sqlite_path)
    expected_log_id = writable.log_id
    writable.close()

    with _transient_sqlite_read_lock(sqlite_path) as released_after_failure:
        store = EventStore(sqlite_path, read_only=True)
    assert released_after_failure.is_set()
    try:
        assert store.log_id == expected_log_id
        assert len(store._opened) == 1
    finally:
        store.close()
    sqlite_path.unlink()


def test_open_readonly_application_retries_transient_sqlite_operational_error(tmp_path: Path) -> None:
    # 守 R3（docs/design/app-and-interface.md「命令行」）：命令行离线只读查询经 ReadOnlyCore 打开数据目录时可从瞬时锁错误恢复
    data_dir = tmp_path / "data"
    writable = EventStore(data_dir / "events.sqlite")
    writable.close()

    with _transient_sqlite_read_lock(data_dir / "events.sqlite") as released_after_failure:
        application = Application.open_readonly(data_dir)
    assert released_after_failure.is_set()
    try:
        snapshot = application.query("projects.list", ProjectsList())
        assert snapshot.data.projects == []
    finally:
        application.close()
    (data_dir / "events.sqlite").unlink()


def test_read_only_open_reraises_operational_error_after_timeout_and_closes_connections(tmp_path: Path) -> None:
    # 守 R3（docs/design/test-pyramid.md「测试按三环留」）：只读打开持续遭遇 OperationalError 超过 5 秒上限时关闭连接并原样抛出异常
    data_dir = tmp_path / "data"
    sqlite_path = data_dir / "events.sqlite"
    writable = EventStore(sqlite_path)
    writable.close()

    started = time.monotonic()
    with _locked_sqlite_data_pages(sqlite_path):
        with pytest.raises(sqlite3.OperationalError):
            ReadOnlyCore(data_dir)
    elapsed = time.monotonic() - started
    assert 5.0 <= elapsed < 15.0
    sqlite_path.unlink()
