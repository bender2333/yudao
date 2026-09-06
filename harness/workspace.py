"""Run 工作区：受限文件读写、代码快照和检查回执。"""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .models import CheckReceipt, json_dumps
from .public_tree import CapturedTree, capture_public_tree, materialize_tree, resolve_public_path, validate_public_path

CHECKS_DIR = ".checks"


@dataclass(frozen=True)
class WorkspaceSnapshot:
    tree: CapturedTree
    checks: tuple[CheckReceipt, ...]

    @property
    def digest(self) -> str:
        return self.tree.digest

    @property
    def files(self) -> tuple[str, ...]:
        return tuple(item.path for item in self.tree.files)

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
        effective_contract_hash: str | None = None,
        engineering_plan_hash: str | None = None,
    ) -> CheckReceipt | None:
        found = [
            item
            for item in self.checks
            if item.department == department and item.name == name and item.snapshot_hash == self.digest
            and not item.tree_changed
        ]
        if product_spec_hash is not None:
            found = [item for item in found if item.product_spec_hash == product_spec_hash]
        if delivery_spec_hash is not None:
            found = [item for item in found if item.delivery_spec_hash == delivery_spec_hash]
        if activation_id is not None:
            found = [item for item in found if item.activation_id == activation_id]
        if effective_contract_hash is not None:
            found = [item for item in found if item.effective_contract_hash == effective_contract_hash]
        if engineering_plan_hash is not None:
            found = [item for item in found if item.engineering_plan_hash == engineering_plan_hash]
        return found[-1] if found else None


class Workspace:
    def __init__(self, root: str | Path) -> None:
        supplied = Path(root).absolute()
        self.root = resolve_public_path(supplied.parent, supplied.name)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / CHECKS_DIR).mkdir(exist_ok=True)
        self._receipts_path = self.root / CHECKS_DIR / "receipts.jsonl"
        self.check_activation_id: str | None = None
        self.check_product_spec_hash: str | None = None
        self.check_delivery_spec_hash: str | None = None
        self.check_effective_contract_hash: str | None = None
        self.check_engineering_plan_hash: str | None = None

    def bind_check(
        self,
        *,
        activation_id: str | None,
        product_spec_hash: str | None,
        delivery_spec_hash: str | None,
        effective_contract_hash: str | None = None,
        engineering_plan_hash: str | None = None,
    ) -> None:
        self.check_activation_id = activation_id
        self.check_product_spec_hash = product_spec_hash
        self.check_delivery_spec_hash = delivery_spec_hash
        self.check_effective_contract_hash = effective_contract_hash
        self.check_engineering_plan_hash = engineering_plan_hash

    def resolve(self, rel: str) -> Path:
        return resolve_public_path(self.root, rel)

    def write_file(self, rel: str, content: str) -> str:
        path = self.resolve(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.resolve(rel)
        path.write_text(content, encoding="utf-8")
        return rel

    def read_file(self, rel: str) -> str:
        path = self.resolve(rel)
        return path.read_text(encoding="utf-8")

    def list_files(self, prefix: str | None = None) -> list[str]:
        files = [item.path for item in capture_public_tree(self.root).files]
        if not prefix:
            return files
        validate_public_path(prefix.rstrip("/"))
        return [rel for rel in files if rel.startswith(prefix)]

    def delete_file(self, rel: str) -> str:
        path = self.resolve(rel)
        if not path.is_file():
            raise ValueError("delete_file requires an existing regular file")
        path.unlink()
        return rel

    def move_file(self, source: str, destination: str) -> dict[str, str]:
        source_path, destination_path = self.resolve(source), self.resolve(destination)
        if not source_path.is_file():
            raise ValueError("move_file requires an existing regular source file")
        if os.path.lexists(destination_path):
            raise FileExistsError(f"move_file destination already exists: {destination}")
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        self.resolve(source)
        self.resolve(destination)
        # link() creates the new name exclusively on both Windows and POSIX.
        os.link(source_path, destination_path, follow_symlinks=False)
        try:
            source_path.unlink()
        except OSError:
            destination_path.unlink()
            raise
        return {"source": source, "destination": destination}

    def digest(self) -> str:
        return capture_public_tree(self.root).digest

    @contextmanager
    def check_copy(self, tree: CapturedTree) -> Iterator[Path]:
        """Yield an isolated copy of the exact bytes captured for this check."""
        with tempfile.TemporaryDirectory(prefix="yudao-check-") as tmp:
            dest = materialize_tree(tree, Path(tmp) / "workspace")
            yield dest

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
            effective_contract_hash=self.check_effective_contract_hash,
            engineering_plan_hash=self.check_engineering_plan_hash,
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
                    effective_contract_hash=data["effective_contract_hash"],
                    engineering_plan_hash=data["engineering_plan_hash"],
                )
            )
        return items

    def snapshot(self) -> WorkspaceSnapshot:
        return WorkspaceSnapshot(tree=capture_public_tree(self.root), checks=tuple(self.receipts()))


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
        "effective_contract_hash": receipt.effective_contract_hash,
        "engineering_plan_hash": receipt.engineering_plan_hash,
    }
