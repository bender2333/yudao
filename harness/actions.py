# 执行环境的合同：工作区事实的只读查询。裁决规则（U）需要的工作区事实（公开树的清单与摘要、路径在工作区中的
# 规范形式与种类、检查回执）由执行环境查询：步骤驱动在工具许可之前取得，流程编排在提案判断之前取得，作为输入交给 U。
# 全部是可以序列化的数据，不含进程内的对象。

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import CheckReceipt


class FactsQuery(BaseModel):
    # 一次查询要取得的事实：tree 为公开树的清单、摘要与检查回执；paths 为需要规范形式与种类的路径
    model_config = ConfigDict(frozen=True, extra="forbid")

    tree: bool = False
    paths: tuple[str, ...] = ()


class TreeFacts(BaseModel):
    # 公开树的清单（文件的相对路径）与摘要，以及工作区中记录的检查回执
    model_config = ConfigDict(frozen=True, extra="forbid")

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


class PathFacts(BaseModel):
    # 一个路径在工作区中的规范形式（工作区内的相对路径）与种类；路径不能在工作区中表示时只有原因
    model_config = ConfigDict(frozen=True, extra="forbid")

    canonical: str | None = None
    kind: Literal["file", "directory", "missing"] | None = None
    error: str | None = None


class WorkspaceFacts(BaseModel):
    # 一次查询的结果：没有查询公开树时 tree 为空；paths 以查询给出的路径为键
    model_config = ConfigDict(frozen=True, extra="forbid")

    tree: TreeFacts | None = None
    paths: dict[str, PathFacts] = Field(default_factory=dict)
