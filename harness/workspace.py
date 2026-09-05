"""Run 工作区：受限文件读写、代码快照和检查回执。"""

from __future__ import annotations

import json
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from .models import CheckReceipt, canonical_hash, json_dumps

CHECKS_DIR = ".checks"


def is_private_path(rel: str) -> bool:
    relative = rel.replace("\\", "/").lstrip("/")
    return relative == CHECKS_DIR or relative.startswith(f"{CHECKS_DIR}/")


def public_files(root: str | Path) -> list[str]:
    base = Path(root)
    files: list[str] = []
    for path in sorted(base.rglob("*")):
        if path.is_symlink():
            continue
        if not path.is_file():
            continue
        rel = path.relative_to(base).as_posix()
        if is_private_path(rel):
            continue
        files.append(rel)
    return files


def tree_digest(root: str | Path) -> str:
    base = Path(root)
    entries = []
    for rel in public_files(base):
        data = (base / rel).read_bytes()
        entries.append({"hash": canonical_hash(data.decode("utf-8", errors="surrogateescape")), "path": rel})
    return canonical_hash({"files": entries})


@dataclass(frozen=True)
class WorkspaceSnapshot:
    digest: str
    files: tuple[str, ...]
    checks: tuple[CheckReceipt, ...]

    def has_file(self, rel: str) -> bool:
        return rel.replace("\\", "/") in self.files

    def latest_check(
        self,
        department: str,
        name: str,
        *,
        product_spec_hash: str | None = None,
        delivery_spec_hash: str | None = None,
        activation_id: str | None = None,
    ) -> CheckReceipt | None:
        found = [
            item
            for item in self.checks
            if item.department == department and item.name == name and item.snapshot_hash == self.digest
        ]
        if product_spec_hash is not None:
            found = [item for item in found if item.product_spec_hash == product_spec_hash]
        if delivery_spec_hash is not None:
            found = [item for item in found if item.delivery_spec_hash == delivery_spec_hash]
        if activation_id is not None:
            found = [item for item in found if item.activation_id == activation_id]
        return found[-1] if found else None


class Workspace:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / CHECKS_DIR).mkdir(exist_ok=True)
        self._receipts_path = self.root / CHECKS_DIR / "receipts.jsonl"
        self.check_activation_id: str | None = None
        self.check_product_spec_hash: str | None = None
        self.check_delivery_spec_hash: str | None = None

    def bind_check(
        self,
        *,
        activation_id: str | None,
        product_spec_hash: str | None,
        delivery_spec_hash: str | None,
    ) -> None:
        self.check_activation_id = activation_id
        self.check_product_spec_hash = product_spec_hash
        self.check_delivery_spec_hash = delivery_spec_hash

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
        files = public_files(self.root)
        if not prefix:
            return files
        needle = prefix.replace("\\", "/").lstrip("/")
        return [rel for rel in files if rel.startswith(needle)]

    def digest(self) -> str:
        return tree_digest(self.root)

    @contextmanager
    def check_copy(self) -> Iterator[Path]:
        """Yield a disposable regular-file copy. Links are not copied as links."""
        with tempfile.TemporaryDirectory(prefix="yudao-check-") as tmp:
            dest = Path(tmp)
            self._populate_check_copy(dest)
            yield dest

    def _populate_check_copy(self, dest: Path) -> None:
        root = self.root.resolve()
        for rel in self.list_files():
            src = self.root / rel
            if src.is_symlink():
                continue
            resolved = src.resolve()
            if resolved != root and root not in resolved.parents:
                continue
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(src.read_bytes())

    def record_check(
        self,
        department: str,
        name: str,
        exit_code: int,
        summary: str,
        *,
        snapshot_hash: str | None = None,
        tree_changed: bool = False,
    ) -> CheckReceipt:
        receipt = CheckReceipt(
            name=name,
            department=department,
            exit_code=int(exit_code),
            summary=summary,
            snapshot_hash=snapshot_hash or self.digest(),
            product_spec_hash=self.check_product_spec_hash,
            delivery_spec_hash=self.check_delivery_spec_hash,
            activation_id=self.check_activation_id,
            tree_changed=bool(tree_changed),
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
                    product_spec_hash=data.get("product_spec_hash"),
                    delivery_spec_hash=data.get("delivery_spec_hash"),
                    activation_id=data.get("activation_id"),
                    tree_changed=bool(data.get("tree_changed", False)),
                )
            )
        return items

    def snapshot(self) -> WorkspaceSnapshot:
        return WorkspaceSnapshot(digest=self.digest(), files=tuple(self.list_files()), checks=tuple(self.receipts()))

    def file_contents(self, rels: Iterable[str]) -> dict[str, str]:
        return {rel: self.read_file(rel) for rel in rels}


def _receipt_dict(receipt: CheckReceipt) -> dict[str, object]:
    return {
        "activation_id": receipt.activation_id,
        "delivery_spec_hash": receipt.delivery_spec_hash,
        "department": receipt.department,
        "exit_code": receipt.exit_code,
        "name": receipt.name,
        "product_spec_hash": receipt.product_spec_hash,
        "snapshot_hash": receipt.snapshot_hash,
        "summary": receipt.summary,
        "tree_changed": receipt.tree_changed,
    }
