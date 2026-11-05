# 执行环境的合同：步骤驱动与执行环境之间的往来。
# 动作：每次环境工具调用是一个动作（Action：身份、类别、工具与输入、前置条件，以及这一类动作的核实方法与
# 能否取消），执行环境执行以后交回回执（ActionReceipt）；取消按动作身份生效；工具许可拒绝时由工具一侧交回
# 被拒绝的回执，执行环境没有被调用。
# 工作区事实的只读查询：裁决规则（U）需要的工作区事实（公开树的清单与摘要、路径在工作区中的规范形式与种类、
# 检查回执）由执行环境查询，步骤驱动在工具许可之前取得，流程编排在提案判断之前取得，作为输入交给 U。
# 全部是可以序列化的数据，不含进程、线程标志或回调。

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

# 动作类别与核实方法的取值在定义一侧（harness/definitions/__init__.py 的 tools.json 格式）：这里是动作合同，
# 从定义取用，定义不反过来导入动作合同（工单 #1275）。每类动作的既定合同与核对也住在那一边
from .definitions import ActionKind, Verification, check_contract


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
    # 这次检查主机执行的命令（检验的有效性设计说明第 7.2 节，工单 #1181）：交付检查的回执带它，
    # 基线检查按名字取同名交付检查的命令运行，质检不能改写；旧回执没有这一项，读出来是空
    command: str | None = None
    # 这份回执绑定的成果种类与它们的版本摘要（工单 #1456）：回执只说「绑定了哪一种成果的哪一版」，
    # 内核按定义里写的名称核对，不认识具体有哪几种成果；新加一种成果种类不用改这里
    bindings: dict[str, str] = field(default_factory=dict)
    # 旧字段：绑定的两种成果与这一轮的工作依据各有一个字段名（字段只增，旧的读法与旧的回执文件照旧能读）
    product_spec_hash: str | None = None
    delivery_spec_hash: str | None = None
    activation_id: str | None = None
    tree_changed: bool = False
    effective_contract_hash: str | None = None
    qa_tests_hash: str | None = None
    # 基线回执（检验的有效性设计说明第 7.2 节，工单 #1181）：主机在基线副本上运行同名交付检查写下的回执。
    # 它不是交付检查的证据：`binds` 只被交付回执使用，基线回执按这一位识别
    baseline: bool = False

    def binds(self, bindings: Mapping[str, str]) -> bool:
        # 这份回执绑定的成果版本是不是都在 bindings 里写的那些（种类 → 摘要）
        return all(self.bindings.get(kind) == digest for kind, digest in bindings.items())


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


class SnapshotRef(BaseModel):
    # 终点快照的引用（工单 #1398）：动作结束以后公开树的快照工件。kind 是工件区域里的用途名，
    # content_hash 是快照内容的摘要，path 是工件区域里的相对路径；与事件 tool_called 上的
    # after_snapshot_ref 是同一种引用，读回执的一方不用再去事件载荷里找快照
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str
    content_hash: str
    path: str
    media_type: str | None = None


class TreeChange(BaseModel):
    # 动作前后的公开树摘要（工单 #1398）：两个相同表示这个动作没有改动公开树
    model_config = ConfigDict(frozen=True, extra="forbid")

    before_digest: str
    after_digest: str


class ActionReceipt(BaseModel):
    # 动作的回执。completed：动作完成，结果在 output；failed：动作没有完成，原因在 error；
    # timeout、cancelled：进程类动作超时或被取消，进程树已经结束，output 带截至结束时的输出；
    # 取消在动作开始之前到达时不执行，status 为 cancelled，只有 error。
    # refused：工具许可拒绝，动作没有交给执行环境，原因同时写在 refused_reason 与 error；
    # 旧合同没有这两个字段，读出来是 false 与空。
    # tree_change 与 after_snapshot_ref：动作前后的两个树摘要与终点快照的引用（工单 #1398），
    # 动作没有执行或执行环境取不到公开树时为空；旧合同没有这两项，读出来也是空
    model_config = ConfigDict(frozen=True, extra="forbid")

    action_id: str
    status: Literal["completed", "failed", "timeout", "cancelled"]
    output: Any = None
    error: str | None = None
    refused: bool = False
    refused_reason: str | None = None
    tree_change: TreeChange | None = None
    after_snapshot_ref: SnapshotRef | None = None

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
        bindings: Mapping[str, str] | None = None,
        activation_id: str | None = None,
    ) -> CheckReceipt | None:
        # 这条检查在这一次一轮工作里、绑定当前几份成果的最近一条回执。要绑定的成果按定义里写的名称给
        # （种类 → 当前版本的摘要），内核不认识具体有哪几种（工单 #1456）。
        # 基线回执不是交付检查的证据（检验的有效性设计说明第 7.2 节，工单 #1181）：即使基线副本的
        # 摘要与工作区相同（声明带全部改动文件的那一角），交付证据也不取它
        found = [
            item
            for item in self.checks
            if item.department == department and item.name == name and item.snapshot_hash == self.digest
            and not item.tree_changed and not item.baseline
        ]
        if bindings:
            found = [item for item in found if item.binds(bindings)]
        if activation_id is not None:
            found = [item for item in found if item.activation_id == activation_id]
        return found[-1] if found else None


def snapshot_payload(tree: TreeFacts) -> dict[str, Any]:
    # 公开树快照的内容（工单 #17）：树摘要与每个文件的路径与内容哈希，不含文件内容。动作前后两条事件上的
    # 快照工件与回执里的终点快照引用是同一份内容（工单 #1398），这里只给出要存的内容，存取由实现做
    return {"digest": tree.digest, "entries": [list(item) for item in zip(tree.files, tree.hashes)]}


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
