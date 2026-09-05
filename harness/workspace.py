"""Run 工作区：受限文件读写、代码快照和检查回执。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .models import CheckReceipt, canonical_hash, json_dumps

CHECKS_DIR = ".checks"


def is_private_path(rel: str) -> bool:
    relative = rel.replace("\\", "/").lstrip("/")
    return relative == CHECKS_DIR or relative.startswith(f"{CHECKS_DIR}/")


@dataclass(frozen=True)
class WorkspaceSnapshot:
    digest: str
    files: tuple[str, ...]
    checks: tuple[CheckReceipt, ...]

    def has_file(self, rel: str) -> bool:
        return rel.replace("\\", "/") in self.files

    def latest_check(self, department: str, name: str) -> CheckReceipt | None:
        found = [item for item in self.checks if item.department == department and item.name == name and item.snapshot_hash == self.digest]
        return found[-1] if found else None


class Workspace:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / CHECKS_DIR).mkdir(exist_ok=True)
        self._receipts_path = self.root / CHECKS_DIR / "receipts.jsonl"

    def resolve(self, rel: str, *, allow_private: bool = False) -> Path:
        relative = rel.replace("\\", "/").lstrip("/")
        if not relative or ".." in Path(relative).parts:
            raise PermissionError("path escapes workspace")
        if not allow_private and is_private_path(relative):
            raise PermissionError(".checks is host-private and cannot be read or written by agents")
        path = (self.root / relative).resolve()
        root = self.root.resolve()
        if path != root and root not in path.parents:
            raise PermissionError("path escapes workspace")
        return path

    def write_file(self, rel: str, content: str) -> str:
        path = self.resolve(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return rel.replace("\\", "/")

    def read_file(self, rel: str) -> str:
        path = self.resolve(rel)
        return path.read_text(encoding="utf-8")

    def list_files(self, prefix: str | None = None) -> list[str]:
        files: list[str] = []
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(self.root).as_posix()
            if is_private_path(rel):
                continue
            if prefix and not rel.startswith(prefix.replace("\\", "/").lstrip("/")):
                continue
            files.append(rel)
        return files

    def digest(self) -> str:
        entries = []
        for rel in self.list_files():
            data = self.resolve(rel).read_bytes()
            entries.append({"hash": canonical_hash(data.decode("utf-8", errors="surrogateescape")), "path": rel})
        return canonical_hash({"files": entries})

    def capture_tree(self) -> dict[str, bytes]:
        tree: dict[str, bytes] = {}
        for path in self.root.rglob("*"):
            if path.is_file():
                tree[path.relative_to(self.root).as_posix()] = path.read_bytes()
        return tree

    def restore_tree(self, tree: dict[str, bytes]) -> None:
        current: list[Path] = [path for path in self.root.rglob("*") if path.is_file()]
        for path in current:
            rel = path.relative_to(self.root).as_posix()
            if rel not in tree:
                path.unlink()
        for rel, data in tree.items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def record_check(self, department: str, name: str, exit_code: int, summary: str) -> CheckReceipt:
        receipt = CheckReceipt(
            name=name,
            department=department,
            exit_code=int(exit_code),
            summary=summary,
            snapshot_hash=self.digest(),
        )
        self._receipts_path.parent.mkdir(parents=True, exist_ok=True)
        with self._receipts_path.open("a", encoding="utf-8") as handle:
            handle.write(json_dumps(_receipt_dict(receipt)) + "\n")
        return receipt

    def receipts(self) -> list[CheckReceipt]:
        if not self._receipts_path.exists():
            return []
        items: list[CheckReceipt] = []
        for line in self._receipts_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            items.append(
                CheckReceipt(
                    name=data["name"],
                    department=data["department"],
                    exit_code=int(data["exit_code"]),
                    summary=data["summary"],
                    snapshot_hash=data["snapshot_hash"],
                )
            )
        return items

    def snapshot(self) -> WorkspaceSnapshot:
        return WorkspaceSnapshot(digest=self.digest(), files=tuple(self.list_files()), checks=tuple(self.receipts()))

    def file_contents(self, rels: Iterable[str]) -> dict[str, str]:
        return {rel: self.read_file(rel) for rel in rels}


def _receipt_dict(receipt: CheckReceipt) -> dict[str, object]:
    return {
        "department": receipt.department,
        "exit_code": receipt.exit_code,
        "name": receipt.name,
        "snapshot_hash": receipt.snapshot_hash,
        "summary": receipt.summary,
    }
