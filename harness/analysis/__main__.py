"""Read-only evidence commands. Saving is a function; L2 attaches manifests."""

from __future__ import annotations

import argparse
import sys

from ..models import json_dumps
from .pack import verify_evidence_pack
from .records import EvidenceError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Yudao evidence packs")
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify", help="read-only verify a movable evidence directory")
    verify.add_argument("directory")
    args = parser.parse_args(argv)
    if args.command != "verify":
        return 1
    try:
        receipt = verify_evidence_pack(args.directory)
    except EvidenceError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    sys.stdout.write(json_dumps(receipt) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
