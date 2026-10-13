# 执行环境的合同：步骤驱动与执行环境之间的往来。
# 动作：每次环境工具调用是一个动作（Action：身份、类别、工具与输入、前置条件），执行环境执行以后交回回执
# （ActionReceipt）；取消按动作身份生效。
# 工作区事实的只读查询：裁决规则（U）需要的工作区事实（公开树的清单与摘要、路径在工作区中的规范形式与种类、
# 检查回执）由执行环境查询，步骤驱动在工具许可之前取得，流程编排在提案判断之前取得，作为输入交给 U。
# 全部是可以序列化的数据，不含进程、线程标志或回调。

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import CheckReceipt

ActionKind = Literal["read", "write", "check", "command"]


class Preconditions(BaseModel):
    # 动作的前置条件：tree_digest 是工具许可所依据的公开树摘要，执行之前核对仍然相同
    model_config = ConfigDict(frozen=True, extra="forbid")

    tree_digest: str | None = None


class Action(BaseModel):
    # 一次环境工具调用：动作身份、类别（读取、写入、检查、登记的本地命令）、工具与模型给出的输入、
    # 调用的部门与前置条件
    model_config = ConfigDict(frozen=True, extra="forbid")

    action_id: str
    kind: ActionKind
    tool: str
    department: str
    input: dict[str, Any]
    preconditions: Preconditions = Field(default_factory=Preconditions)


class ActionReceipt(BaseModel):
    # 动作的回执。completed：动作完成，结果在 output；failed：动作没有完成，原因在 error；
    # timeout、cancelled：进程类动作超时或被取消，进程树已经结束，output 带截至结束时的输出；
    # 取消在动作开始之前到达时不执行，status 为 cancelled，只有 error
    model_config = ConfigDict(frozen=True, extra="forbid")

    action_id: str
    status: Literal["completed", "failed", "timeout", "cancelled"]
    output: Any = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class FactsQuery(BaseModel):
    # 一次查询要取得的事实：tree 为公开树的清单、摘要与检查回执；paths 为需要规范形式与种类的路径
    model_config = ConfigDict(frozen=True, extra="forbid")

    tree: bool = False
    paths: tuple[str, ...] = ()


class TreeFacts(BaseModel):
    # 公开树的清单（文件的相对路径）、摘要、每个文件的内容哈希，以及工作区中记录的检查回执。
    # hashes 与 files 同序同长：动作前后的公开树快照工件按它比较实际效果（工单 #308）
    model_config = ConfigDict(frozen=True, extra="forbid")

    digest: str
    files: tuple[str, ...]
    hashes: tuple[str, ...] = ()
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
