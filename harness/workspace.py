"""Run 工作区：受限文件读写、代码快照和检查回执。"""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .actions import TreeFacts
from .models import CheckReceipt, json_dumps
from .public_tree import CapturedTree, TreeError, capture_public_tree, excluded_by_ignore_rules, materialize_tree, resolve_public_path, validate_public_path

CHECKS_DIR = ".checks"


@dataclass(frozen=True)
class WorkspaceSnapshot:
    # 一次读取的公开树（带文件内容，交付封存使用）与检查回执；facts 是同一次读取的工作区事实
    tree: CapturedTree
    checks: tuple[CheckReceipt, ...]

    @property
    def digest(self) -> str:
        return self.tree.digest

    @property
    def facts(self) -> TreeFacts:
        return TreeFacts(digest=self.tree.digest, files=tuple(item.path for item in self.tree.files),
                         checks=self.checks)


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

    def resolve_writable(self, rel: str) -> Path:
        # 写入、删除与移动的目标：被项目忽略规则排除的路径拒绝执行，原因写明忽略规则
        if rel in excluded_by_ignore_rules(self.root, (rel,)):
            raise TreeError(f"Excluded by the project's ignore rules: {rel}")
        return self.resolve(rel)

    def write_file(self, rel: str, content: str) -> str:
        path = self.resolve_writable(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.resolve_writable(rel)
        path.write_text(content, encoding="utf-8")
        return rel

    def read_file(self, rel: str) -> str:
        path = self.resolve(rel)
        return path.read_text(encoding="utf-8")

    def list_files(self, prefix: str | None = None) -> list[str]:
        files = [item.path for item in self._public_tree().files]
        if not prefix:
            return files
        validate_public_path(prefix.rstrip("/"))
        return [rel for rel in files if rel.startswith(prefix)]

    def delete_file(self, rel: str) -> str:
        path = self.resolve_writable(rel)
        if not path.is_file():
            raise ValueError("delete_file requires an existing regular file")
        path.unlink()
        return rel

    def move_file(self, source: str, destination: str) -> dict[str, str]:
        source_path, destination_path = self.resolve_writable(source), self.resolve_writable(destination)
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

    def _public_tree(self) -> CapturedTree:
        # run 工作区的公开树：按项目的忽略规则取得（Git 命令行判断），被忽略的路径不进入
        return capture_public_tree(self.root, True)

    def digest(self) -> str:
        return self._public_tree().digest

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
        return WorkspaceSnapshot(tree=self._public_tree(), checks=tuple(self.receipts()))


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
