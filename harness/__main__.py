from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .demo import run_demo
from .providers import ProviderFacade
from .runtime import LoopSystem
from .smoke import DEFAULT_DIR as SMOKE_DIR
from .smoke import run_smoke, smoke_exit_code
from .web.server import serve

DEFAULT_DIR = Path(".yudao") / "native-loop"
DEFAULT_PROVIDER_CONFIG = Path(".yudao") / "providers.json"
DEFAULT_DOTENV = Path(".yudao") / ".env"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Yudao Loop System")
    parser.add_argument("--data-dir", default=str(DEFAULT_DIR))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--provider-config", default=str(DEFAULT_PROVIDER_CONFIG))
    sub = parser.add_subparsers(dest="command")
    demo = sub.add_parser("demo", help="run a fake end-to-end sample")
    demo.add_argument("--data-dir", default=str(DEFAULT_DIR))
    demo.add_argument("--serve", action="store_true")
    demo.add_argument("--host", default="127.0.0.1")
    demo.add_argument("--port", type=int, default=8765)
    web = sub.add_parser("serve", help="serve the loop console")
    web.add_argument("--data-dir", default=str(DEFAULT_DIR))
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8765)
    web.add_argument("--provider-config", default=str(DEFAULT_PROVIDER_CONFIG))
    replay = sub.add_parser("replay", help="rebuild a run or project projection from the event store")
    replay.add_argument("run_id", nargs="?")
    replay.add_argument("--project", dest="project_id", help="rebuild a project projection twice and compare")
    replay.add_argument("--data-dir", default=str(DEFAULT_DIR))
    smoke = sub.add_parser("smoke", help="run a real-provider three-department smoke test")
    smoke.add_argument("--data-dir", default=str(SMOKE_DIR))
    smoke.add_argument("--scenario", choices=("happy", "collaboration", "all"), default="all")
    smoke.add_argument("--provider-config", default=None)
    project = sub.add_parser("project", help="read-only project queries")
    project_sub = project.add_subparsers(dest="project_command", required=True)
    project_list = project_sub.add_parser("list", help="list projects")
    project_list.add_argument("--data-dir", default=str(DEFAULT_DIR))
    project_list.add_argument("--archived", action="store_true", help="include archived projects")
    project_show = project_sub.add_parser("show", help="print one project projection")
    project_show.add_argument("project_id")
    project_show.add_argument("--data-dir", default=str(DEFAULT_DIR))
    args = parser.parse_args(argv)
    command = args.command or "serve"

    if command == "demo":
        system, run_id = run_demo(args.data_dir)
        projection = system.project(run_id)
        print(f"demo run: {run_id}")
        print(f"phase={projection.phase} outcome={projection.outcome} stop={projection.stop_reason}")
        print(f"transitions: {' | '.join(projection.transitions)}")
        print(f"requests={projection.request_count} reworks={projection.rework_count} events={projection.stream_version}")
        if args.serve:
            return _serve(system, args.host, args.port)
        print(f"console: python -m harness demo --serve --data-dir {args.data_dir}")
        return 0
    if command == "serve":
        # 无参等价全默认 serve：缺配置空态启动，只读任务与配置管理可用
        system = _production_system(args.data_dir, args.provider_config)
        return _serve(system, args.host, args.port)
    if command == "replay":
        if (args.run_id is None) == (args.project_id is None):
            parser.error("replay needs exactly one of: run_id or --project <project_id>")
        system = LoopSystem(args.data_dir)
        if args.project_id is not None:
            first = system.projects.projection(args.project_id).canonical_state()
            second = system.projects.projection(args.project_id).canonical_state()
            print(json.dumps(first, ensure_ascii=False, indent=2))
            if first != second:
                print("project replay is not deterministic", file=sys.stderr)
                return 1
            return 0
        try:
            projection = system.replay(args.run_id)
        except (ValueError, OSError) as exc:
            print(f"replay failed: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(projection.canonical_state(), ensure_ascii=False, indent=2))
        return 0
    if command == "project":
        system = LoopSystem(args.data_dir)
        if args.project_command == "list":
            rows = [
                {
                    "project_id": item.project_id, "name": item.name, "pinned": item.pinned, "archived": item.archived,
                    "created_at": item.created_at, "updated_at": item.updated_at,
                    "work_item_count": len(item.work_items), "active_work_item_id": item.active_work_item_id,
                    "current_adoption": None if item.current_adoption is None else item.current_adoption.adoption_id,
                }
                for item in system.projects.list_projects(include_archived=args.archived)
            ]
            print(json.dumps(rows, ensure_ascii=False, indent=2))
            return 0
        print(json.dumps(system.projects.projection(args.project_id).to_dict(), ensure_ascii=False, indent=2))
        return 0
    if command == "smoke":
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


def _serve(system: LoopSystem, host: str, port: int) -> int:
    # 服务可启动与任务可创建分开：未就绪提示后仍进控制台，只禁新建真实任务
    status = system.provider_status()
    if not status.get("available", False):
        print(status.get("message", "provider unavailable"), file=sys.stderr)
    # 控制台默认只绑回环；若显式暴露到非本地网络，需要另行提供认证能力，
    # 本项不实现远程管理鉴权，凭据写入接口仍按本地管理能力处理
    if host not in {"127.0.0.1", "localhost", "::1"}:
        print("console is bound to a non-loopback address without remote authentication", file=sys.stderr)
    try:
        server = serve(system, host=host, port=port)
    except OSError as exc:
        print(f"cannot serve {host}:{port}: {exc}", file=sys.stderr)
        return 1
    print(f"Yudao console {server.base_url}")
    system.start_provider_watching()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopped")
    finally:
        server.server_close()
        system.close()
    return 0


def _production_system(data_dir: str | Path, provider_config: str | Path | None) -> LoopSystem:
    # 启动读取一致版本：路径解析为固定绝对路径，缺文件/坏内容均空态启动
    facade = ProviderFacade()
    config = None if provider_config in (None, "") else Path(provider_config).resolve()
    dotenv = DEFAULT_DOTENV.resolve()
    facade.configure_paths(config, dotenv)
    facade.reload()
    system = LoopSystem(data_dir, facade=facade)
    return system


if __name__ == "__main__":
    raise SystemExit(main())
