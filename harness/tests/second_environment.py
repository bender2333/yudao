# 第二种执行环境实现（工单 #1170；只在测试里用，产品代码不导入它）。
#
# 动作合同（`harness/actions.py`；执行环境服务设计说明第 4 节「执行环境的合同」；总图第四节「动作」缝）的
# 第二种实现。它真实执行文件动作：读取与写入都在给定的工作区目录里做，结果只留在工作区。形状与真实现
# （`environment.py` 的 `LocalEnvironment`）不同：没有工作区对象、没有后台命令与检查，只有动作合同用到的
# 三个操作：执行、取消、查询公开树事实。合同允许的唯一跨步状态是「取消先于动作到达」的登记，其余一概不留：
# 同一个工作区上新起一个实现，读到的结果与原来相同。
#
# 按动作类别分派（与真实现同一个做法），实际工具名只用来在同一类里取执行方法；它不读请求里的部门，
# 也不带任何阶段的名字。

from __future__ import annotations

from pathlib import Path
from typing import Any

from harness.actions import Action, ActionReceipt, FactsQuery, TreeFacts, WorkspaceFacts
from harness.models import hash_bytes
from harness.public_tree import capture_public_tree

# 这一版实现执行的工具，按动作类别分组：读取与写入的文件动作
_KIND_TOOLS = {
    "read": frozenset({"read_file"}),
    "write": frozenset({"write_file"}),
}


class SecondEnvironment:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).absolute()
        # 取消先于动作到达时记下的动作身份：合同允许的唯一跨步状态
        self._cancelled: set[str] = set()

    async def perform(self, action: Action) -> ActionReceipt:
        # 按动作类别分派；不支持的类别与不在这一类里的工具立刻失败，不静默换成别的动作
        tools = _KIND_TOOLS.get(action.kind)
        if tools is None:
            raise ValueError(f"the second environment does not execute {action.kind} actions")
        if action.tool not in tools:
            raise ValueError(f"{action.tool} is not a {action.kind} action")
        if action.action_id in self._cancelled:
            self._cancelled.discard(action.action_id)
            return ActionReceipt(action_id=action.action_id, status="cancelled",
                                 error="The action was cancelled before it started.")
        try:
            if action.kind == "read":
                output: Any = self._read(action.input)
            else:
                output = self._write(action.input)
        except (OSError, ValueError) as exc:
            return ActionReceipt(action_id=action.action_id, status="failed", error=str(exc))
        return ActionReceipt(action_id=action.action_id, status="completed", output=output)

    def cancel(self, action_id: str) -> None:
        self._cancelled.add(action_id)

    def query(self, query: FactsQuery) -> WorkspaceFacts:
        # 公开树事实与真实现取自同一份清单：摘要、文件路径与内容哈希
        tree = capture_public_tree(self.root) if query.tree else None
        facts = None if tree is None else TreeFacts(
            digest=tree.digest,
            files=tuple(item.path for item in tree.files),
            hashes=tuple(hash_bytes(item.data) for item in tree.files),
            checks=(),
        )
        return WorkspaceFacts(tree=facts, paths={})

    def _path(self, rel: Any) -> Path:
        # 只接受工作区里的相对路径：绝对路径与跳出工作区的路径立刻失败
        if not isinstance(rel, str) or not rel:
            raise ValueError("a file action requires a workspace-relative path")
        target = (self.root / rel).resolve()
        if target != self.root and self.root not in target.parents:
            raise ValueError(f"{rel} is outside the workspace")
        return target

    def _read(self, args: dict[str, Any]) -> str:
        return self._path(args.get("path")).read_text(encoding="utf-8")

    def _write(self, args: dict[str, Any]) -> str:
        content = args.get("content")
        if not isinstance(content, str):
            raise ValueError("write_file requires text content")
        rel = args.get("path")
        path = self._path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))
        return str(rel)
