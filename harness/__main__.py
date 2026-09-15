"""命令入口：demo、serve、replay、smoke、project。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .demo import run_demo
from .provider_catalog import CatalogValidationError, ProviderCatalog
from .runtime import LoopSystem, environment_credentials
from .smoke import DEFAULT_DIR as SMOKE_DIR
from .smoke import run_smoke, smoke_exit_code
from .web.server import serve

DEFAULT_DIR = Path(".yudao") / "native-loop"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Yudao Loop System")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="run a fake end-to-end sample")
    demo.add_argument("--data-dir", default=str(DEFAULT_DIR))
    demo.add_argument("--serve", action="store_true")
    demo.add_argument("--host", default="127.0.0.1")
    demo.add_argument("--port", type=int, default=8765)
    web = sub.add_parser("serve", help="serve the loop console")
    web.add_argument("--data-dir", default=str(DEFAULT_DIR))
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8765)
    web.add_argument("--provider-config", required=True)
    replay = sub.add_parser("replay", help="rebuild a run or project projection from the event store")
    replay.add_argument("run_id", nargs="?")
    replay.add_argument("--project", dest="project_id", help="rebuild a project projection twice and compare")
    replay.add_argument("--data-dir", default=str(DEFAULT_DIR))
    smoke = sub.add_parser("smoke", help="run a real-provider three-department smoke test")
    smoke.add_argument("--data-dir", default=str(SMOKE_DIR))
    smoke.add_argument("--scenario", choices=("happy", "collaboration", "all"), default="all")
    smoke.add_argument("--provider-config", required=True)
    project = sub.add_parser("project", help="read-only project queries")
    project_sub = project.add_subparsers(dest="project_command", required=True)
    project_list = project_sub.add_parser("list", help="list projects")
    project_list.add_argument("--data-dir", default=str(DEFAULT_DIR))
    project_list.add_argument("--archived", action="store_true", help="include archived projects")
    project_show = project_sub.add_parser("show", help="print one project projection")
    project_show.add_argument("project_id")
    project_show.add_argument("--data-dir", default=str(DEFAULT_DIR))
    args = parser.parse_args(argv)

    if args.command == "demo":
        system, run_id = run_demo(args.data_dir)
        projection = system.project(run_id)
        print(f"demo run: {run_id}")
        print(f"phase={projection.phase} outcome={projection.outcome} stop={projection.stop_reason}")
        print(f"transitions: {' | '.join(projection.transitions)}")
        print(f"requests={projection.request_count} reworks={projection.rework_count} events={projection.last_seq}")
        if args.serve:
            return _serve(system, args.host, args.port)
        print(f"console: python -m harness demo --serve --data-dir {args.data_dir}")
        return 0
    if args.command == "serve":
        system = _production_system(args.data_dir, args.provider_config)
        return _serve(system, args.host, args.port)
    if args.command == "replay":
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
        projection = system.replay(args.run_id)
        print(json.dumps(projection.canonical_state(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "project":
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
    if args.command == "smoke":
        scenarios = ["happy", "collaboration"] if args.scenario == "all" else [args.scenario]
        report = run_smoke(
            args.data_dir,
            provider_config=args.provider_config,
            credentials=environment_credentials,
            scenarios=scenarios,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"report: {Path(args.data_dir) / 'smoke-report.md'}")
        return smoke_exit_code(report)
    return 1


def _serve(system: LoopSystem, host: str, port: int) -> int:
    status = system.provider_status()
    if not status.get("available", False):
        print(status.get("message", "provider unavailable"), file=sys.stderr)
    server = serve(system, host=host, port=port)
    print(f"Yudao console {server.base_url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopped")
    finally:
        server.server_close()
    return 0


def _production_system(data_dir: str | Path, provider_config: str | Path) -> LoopSystem:
    try:
        catalog = ProviderCatalog.load(provider_config)
    except CatalogValidationError as exc:
        raise SystemExit(f"provider config is invalid: {exc}") from exc
    return LoopSystem(
        data_dir,
        provider_catalog=catalog,
        credentials=environment_credentials,
        provider_config_path=provider_config,
    )


if __name__ == "__main__":
    raise SystemExit(main())
