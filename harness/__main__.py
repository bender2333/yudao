"""命令入口：demo、serve、replay。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .demo import run_demo
from .runtime import LoopSystem, build_adapter
from .smoke import DEFAULT_DIR as SMOKE_DIR
from .smoke import run_smoke, smoke_exit_code
from .web.server import serve

DEFAULT_DIR = Path(".yudao") / "loop"


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
    web.add_argument("--adapter", choices=("omp", "fake"), default="omp")
    replay = sub.add_parser("replay", help="rebuild projection from the event store")
    replay.add_argument("run_id")
    replay.add_argument("--data-dir", default=str(DEFAULT_DIR))
    smoke = sub.add_parser("smoke", help="run a real-provider three-department smoke test")
    smoke.add_argument("--data-dir", default=str(SMOKE_DIR))
    smoke.add_argument("--scenario", choices=("happy", "ask", "all"), default="all")
    args = parser.parse_args(argv)

    if args.command == "demo":
        system, run_id = run_demo(args.data_dir)
        projection = system.project(run_id)
        print(f"demo run: {run_id}")
        print(f"phase={projection.phase} outcome={projection.outcome} stop={projection.stop_reason}")
        print(f"transitions: {' | '.join(projection.transitions)}")
        print(f"asks={projection.ask_count} reworks={projection.rework_count} events={projection.last_seq}")
        if args.serve:
            return _serve(system, args.host, args.port)
        print(f"console: python -m harness serve --adapter fake --data-dir {args.data_dir}")
        return 0
    if args.command == "serve":
        adapter = build_adapter(args.adapter)
        system = LoopSystem(args.data_dir, adapter)
        return _serve(system, args.host, args.port)
    if args.command == "replay":
        system = LoopSystem(args.data_dir, build_adapter("fake"))
        projection = system.replay(args.run_id)
        print(json.dumps(projection.canonical_state(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "smoke":
        scenarios = ["happy", "ask"] if args.scenario == "all" else [args.scenario]
        report = run_smoke(args.data_dir, scenarios=scenarios)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"report: {Path(args.data_dir) / 'smoke-report.md'}")
        return smoke_exit_code(report)
    return 1


def _serve(system: LoopSystem, host: str, port: int) -> int:
    availability = system.adapter.availability()
    if not availability.available:
        print(availability.message, file=sys.stderr)
    server = serve(system, host=host, port=port)
    print(f"Yudao console {server.base_url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
