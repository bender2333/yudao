from __future__ import annotations

import argparse
import json
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, get_args

from filelock import FileLock, Timeout

from .api.server import listen_error
from .api.server import serve as serve_api
from .app.application import Application
from .app.contracts import AccessMode
from .app.project_queries import NotFound, ProjectOverview, ProjectsList, ReplayCheck
from .data_directory import DISTRIBUTION, configure_logging, default_data_dir
from .data_directory import default_dotenv as default_dotenv_path
from .data_directory import default_provider_config as default_provider_config_path
from .demo import run_demo
from .smoke import DEFAULT_DIR as SMOKE_DIR
from .smoke import run_smoke, smoke_exit_code

# 数据目录的进程锁：同一个数据目录只允许一个服务进程（应用层与接口层设计说明第 7.2 节），锁在进程退出时释放
SERVICE_LOCK = "service.lock"

def release_version() -> str:
    # 发布版本号取自 wheel 的元数据；从源码运行时用同一个版本，读不到元数据时说不知道
    try:
        return version(DISTRIBUTION)
    except PackageNotFoundError:  # pragma: no cover - 只在没有安装元数据时出现
        return "0+unknown"


def build_parser() -> argparse.ArgumentParser:
    # 命令行的子命令、选项与默认值。--data-dir 自身不给默认值，写在子命令之前或之后都生效，
    # 两处都没有给出时由 _data_dir 按子命令求出（设计说明第 3.4 节），因此测试用环境变量
    # 改写用户数据目录的根就能改变默认值
    # Provider 目录文件与 .env 按生效的数据目录求出，因此 --provider-config 不给默认值
    parser = argparse.ArgumentParser(description="Yudao Loop System")
    parser.add_argument("--version", action="version", version=release_version())
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    # 访问方式（设计说明第 6.2 节）：本机只能监听回环地址；局域网监听任意地址
    parser.add_argument("--access", choices=get_args(AccessMode), default="local")
    parser.add_argument("--provider-config", default=None)
    sub = parser.add_subparsers(dest="command")
    demo = sub.add_parser("demo", help="run a fake end-to-end sample")
    demo.add_argument("--data-dir", default=argparse.SUPPRESS)
    # 写在 api 之前或之后的选项都有效；没有写时取上面的默认值
    api = sub.add_parser("api", help="serve the application interface (commands, queries, capabilities)")
    api.add_argument("--data-dir", default=argparse.SUPPRESS)
    api.add_argument("--host", default=argparse.SUPPRESS)
    api.add_argument("--port", type=int, default=argparse.SUPPRESS)
    api.add_argument("--access", choices=get_args(AccessMode), default=argparse.SUPPRESS)
    api.add_argument("--provider-config", default=argparse.SUPPRESS)
    replay = sub.add_parser("replay", help="rebuild a run or project projection from the event store")
    replay.add_argument("run_id", nargs="?")
    replay.add_argument("--project", dest="project_id", help="rebuild a project projection twice and compare")
    replay.add_argument("--data-dir", default=argparse.SUPPRESS)
    # 写在 smoke 之前或之后的 --data-dir 与 --provider-config 都有效，两处都没有给出时由 _data_dir 求出
    smoke = sub.add_parser("smoke", help="run a real-provider three-department smoke test")
    smoke.add_argument("--data-dir", default=argparse.SUPPRESS)
    smoke.add_argument("--scenario", choices=("happy", "collaboration", "all"), default="all")
    smoke.add_argument("--provider-config", default=argparse.SUPPRESS)
    project = sub.add_parser("project", help="read-only project queries")
    project_sub = project.add_subparsers(dest="project_command", required=True)
    project_list = project_sub.add_parser("list", help="list projects")
    project_list.add_argument("--data-dir", default=argparse.SUPPRESS)
    project_list.add_argument("--archived", action="store_true", help="include archived projects")
    project_show = project_sub.add_parser("show", help="print one project projection")
    project_show.add_argument("project_id")
    project_show.add_argument("--data-dir", default=argparse.SUPPRESS)
    return parser

def _data_dir(args: argparse.Namespace, command: str) -> str:
    # 生效的数据目录：命令行给出时以它为准（写在子命令之前或之后都生效）；
    # 没有给出时 smoke 取 harness/smoke.py 的 DEFAULT_DIR，其余子命令取用户数据目录（设计说明第 3.4 节）
    given = getattr(args, "data_dir", None)
    return given if given is not None else str(SMOKE_DIR if command == "smoke" else default_data_dir())

def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # 不写子命令时启动新接口（应用层与接口层设计说明第 7.3、7.4 节）
    command = args.command or "api"
    args.data_dir = _data_dir(args, command)

    if command == "demo":
        lock = _lock_data_dir(args.data_dir)
        if lock is None:
            return 1
        system, run_id = run_demo(args.data_dir)
        projection = system.project(run_id)
        print(f"demo run: {run_id}")
        print(f"phase={projection.phase} outcome={projection.outcome} stop={projection.stop_reason}")
        print(f"transitions: {' | '.join(projection.transitions)}")
        print(f"requests={projection.request_count} reworks={projection.rework_count} events={projection.stream_version}")
        print(f"api: yudao api --data-dir {args.data_dir}")
        return 0
    if command == "api":
        error = listen_error(args.access, args.host)
        if error is not None:
            print(error, file=sys.stderr)
            return 1
        lock = _lock_data_dir(args.data_dir)
        if lock is None:
            return 1
        # 服务的日志写在 <数据目录>/logs/，按大小轮换（设计说明第 4.2 节）
        log_path = configure_logging(args.data_dir)
        print(f"logs: {log_path}")
        config, dotenv = _provider_paths(args.data_dir, args.provider_config)
        serve_api(lambda: Application.open(args.data_dir, provider_config=config, dotenv=dotenv),
                  access=args.access, host=args.host, port=args.port)
        return 0
    if command == "replay":
        if (args.run_id is None) == (args.project_id is None):
            parser.error("replay needs exactly one of: run_id or --project <project_id>")
        request = (ReplayCheck(project_id=args.project_id) if args.project_id is not None
                   else ReplayCheck(run_id=args.run_id))
        return _print_query(args.data_dir, "replay.check", request)
    if command == "project":
        if args.project_command == "list":
            return _print_query(args.data_dir, "projects.list",
                                ProjectsList(include_archived=args.archived))
        return _print_query(args.data_dir, "project.overview", ProjectOverview(project_id=args.project_id))
    if command == "smoke":
        lock = _lock_data_dir(args.data_dir)
        if lock is None:
            return 1
        scenarios = ["happy", "collaboration"] if args.scenario == "all" else [args.scenario]
        report = run_smoke(
            args.data_dir,
            provider_config=args.provider_config,
            scenarios=scenarios,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"report: {Path(args.data_dir) / 'smoke-report.md'}")
        return smoke_exit_code(report)
    return 1


def _print_query(data_dir: str | Path, name: str, request: Any) -> int:
    # 只读的子命令：经应用层的查询以只读方式打开数据目录，不写保存的投影，不需要进程锁
    application = Application.open_readonly(data_dir)
    try:
        snapshot = application.query(name, request)
    except NotFound as exc:
        print(f"{name}: {exc}", file=sys.stderr)
        return 1
    finally:
        application.close()
    print(json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False, indent=2))
    if name == "replay.check" and not snapshot.data.consistent:
        return 1
    return 0



def _lock_data_dir(data_dir: str | Path) -> FileLock | None:
    # 取得数据目录的进程锁；另一个服务进程持有时说明原因并返回空，调用方以非零状态退出。
    # 返回的锁在服务进程结束之前保持引用
    directory = Path(data_dir)
    directory.mkdir(parents=True, exist_ok=True)
    lock = FileLock(directory / SERVICE_LOCK)
    try:
        lock.acquire(timeout=0)
    except Timeout:
        print(f"data directory is in use by another service process: {directory.resolve()}", file=sys.stderr)
        return None
    return lock


def _provider_paths(data_dir: str | Path, provider_config: str | Path | None) -> tuple[Path | None, Path]:
    # 服务进程读取的模型目录与凭据文件：默认都在数据目录内（设计说明第 3.4 节），解析为固定的绝对路径；
    # 没有明确给 --provider-config 时按生效的 --data-dir 求出，明确给了以它为准；目录文件为空字符串时不读取
    config = (default_provider_config_path(Path(data_dir).resolve()) if provider_config is None else
              (None if provider_config == "" else Path(provider_config).resolve()))
    return config, default_dotenv_path(data_dir).resolve()




if __name__ == "__main__":
    raise SystemExit(main())
