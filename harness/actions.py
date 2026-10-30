# 执行环境的合同：步骤驱动与执行环境之间的往来。
# 动作：每次环境工具调用是一个动作（Action：身份、类别、工具与输入、前置条件，以及这一类动作的核实方法与
# 能否取消），执行环境执行以后交回回执（ActionReceipt）；取消按动作身份生效；工具许可拒绝时由工具一侧交回
# 被拒绝的回执，执行环境没有被调用。
# 工作区事实的只读查询：裁决规则（U）需要的工作区事实（公开树的清单与摘要、路径在工作区中的规范形式与种类、
# 检查回执）由执行环境查询，步骤驱动在工具许可之前取得，流程编排在提案判断之前取得，作为输入交给 U。
# 全部是可以序列化的数据，不含进程、线程标志或回调。

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# 动作类别：读取、写入、检查、本地命令，以及网络取回、MCP 工具、试用会话、浏览器与屏幕动作。
# 后四类由各自的处理分支提供，动作合同与这四类相同（恢复契约第 4 节；网络取回与 MCP 设计说明第 18 节）
ActionKind = Literal["read", "write", "check", "command", "fetch", "mcp", "trial", "browser"]

# 核实方法（恢复契约第 4 节「结果未知时向哪里查」）：none 不查询外部结果，snapshot 以动作前后的公开树快照
# 核对实际效果，query 按尝试身份查询执行环境的动作记录、检查回执或试用会话记录
Verification = Literal["none", "snapshot", "query"]

# 每类动作的既定合同：（核实方法，取消能否确认停止）。None 表示这一类里随工具不同，必须由定义写明。
# 前四类是在这份合同之前就有的动作：读取与命令没有可以查询的外部结果，写入以树快照核实，检查的结果是检查回执、
# 经执行环境的查询取得；它们的定义可以省略这两项，按这里的值解释（恢复契约第 4 节「动作分类与处置」）
ESTABLISHED_CONTRACTS: dict[ActionKind, tuple[Verification | None, bool | None]] = {
    "read": ("none", True),
    "write": ("snapshot", True),
    "check": ("query", True),
    "command": ("none", True),
    "fetch": ("none", True),
    "mcp": ("none", None),
    "trial": (None, True),
    "browser": (None, True),
}

# 新增的四类动作：静态环境工具的定义里必须写明核实方法与能否取消；旧类别可以省略（网络取回与 MCP 设计说明第 18 节）
ADDED_KINDS: frozenset[str] = frozenset({"fetch", "mcp", "trial", "browser"})


def established_verification(kind: ActionKind) -> Verification | None:
    # 这一类动作的既定核实方法；None 表示这一类里随工具不同，必须写明
    return ESTABLISHED_CONTRACTS[kind][0]


def established_cancellable(kind: ActionKind) -> bool | None:
    # 这一类动作的既定取消合同；None 表示这一类里随工具不同，必须写明
    return ESTABLISHED_CONTRACTS[kind][1]


def check_contract(kind: ActionKind, verification: Verification | None, cancellable: bool | None) -> None:
    # 定义与动作请求里的两项元数据按类别的既定合同核对：写错的值立刻拒绝，新类别缺少这两项也拒绝
    expected_verification = established_verification(kind)
    if verification is not None and expected_verification is not None and verification != expected_verification:
        raise ValueError(f"a {kind} action is verified by {expected_verification!r}, not {verification!r}")
    expected_cancellable = established_cancellable(kind)
    if cancellable is not None and expected_cancellable is not None and cancellable != expected_cancellable:
        raise ValueError(f"cancelling a {kind} action can be confirmed: {expected_cancellable!r}, "
                         f"not {cancellable!r}")
    if kind in ADDED_KINDS and (verification is None or cancellable is None):
        raise ValueError(f"a {kind} action requires verification and cancellable")


@dataclass(frozen=True)
class CheckReceipt:
    # 一次检查的回执，属于工作区事实：部门、检查名、退出码、结论摘要、检查时工作区的树摘要，
    # 以及这次检查依据的成果与执行权编号；tree_changed 表示检查自己改动了树，
    # 这样的回执不能作为通过的依据（工单 #308）。它随工作区事实交给裁决（S5a 起住在这里，
    # 内核的裁决模块要用它，而 models.py 不再算内核）
    name: str
    department: str
    exit_code: int
    summary: str
    snapshot_hash: str
    product_spec_hash: str | None = None
    delivery_spec_hash: str | None = None
    activation_id: str | None = None
    tree_changed: bool = False
    effective_contract_hash: str | None = None
    qa_tests_hash: str | None = None


class Preconditions(BaseModel):
    # 动作的前置条件：tree_digest 是工具许可所依据的公开树摘要，执行之前核对仍然相同
    model_config = ConfigDict(frozen=True, extra="forbid")

    tree_digest: str | None = None


class Action(BaseModel):
    # 一次环境工具调用：动作身份、类别（读取、写入、检查、本地命令与新增的四类）、工具与模型给出的输入、
    # 调用的部门、前置条件，以及这一类动作的核实方法与取消能否确认停止。两项元数据在旧合同里没有：
    # 缺少时按类别的既定值解释（check_contract），新增的类别必须写明
    model_config = ConfigDict(frozen=True, extra="forbid")

    action_id: str
    kind: ActionKind
    tool: str
    department: str
    input: dict[str, Any]
    verification: Verification | None = None
    cancellable: bool | None = None
    preconditions: Preconditions = Field(default_factory=Preconditions)

    @model_validator(mode="after")
    def _declared_contract(self) -> Action:
        check_contract(self.kind, self.verification, self.cancellable)
        return self


class ActionReceipt(BaseModel):
    # 动作的回执。completed：动作完成，结果在 output；failed：动作没有完成，原因在 error；
    # timeout、cancelled：进程类动作超时或被取消，进程树已经结束，output 带截至结束时的输出；
    # 取消在动作开始之前到达时不执行，status 为 cancelled，只有 error。
    # refused：工具许可拒绝，动作没有交给执行环境，原因同时写在 refused_reason 与 error；
    # 旧合同没有这两个字段，读出来是 false 与空
    model_config = ConfigDict(frozen=True, extra="forbid")

    action_id: str
    status: Literal["completed", "failed", "timeout", "cancelled"]
    output: Any = None
    error: str | None = None
    refused: bool = False
    refused_reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @classmethod
    def refusal(cls, action_id: str, reason: str) -> ActionReceipt:
        # 工具许可拒绝：动作没有交给执行环境，回执照常带动作身份、原因与被拒绝标记
        return cls(action_id=action_id, status="failed", error=reason, refused=True, refused_reason=reason)


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
