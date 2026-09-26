# 本机执行环境：run 的工作区所在的环境。控制核心经合同与它往来（actions.py），不直接读写工作区文件；
# 这里提供工作区事实的只读查询，以及交付封存所需的带文件内容的公开树。

from __future__ import annotations

import os

from .actions import FactsQuery, PathFacts, WorkspaceFacts
from .workspace import Workspace, WorkspaceSnapshot


class LocalEnvironment:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    def query(self, query: FactsQuery) -> WorkspaceFacts:
        tree = self.workspace.snapshot().facts if query.tree else None
        return WorkspaceFacts(tree=tree, paths={path: self._path(path) for path in query.paths})

    def snapshot(self) -> WorkspaceSnapshot:
        # 带文件内容的公开树与检查回执：提交交付时封存这份内容，判断使用同一次读取的事实（snapshot().facts）
        return self.workspace.snapshot()

    def _path(self, rel: str) -> PathFacts:
        # 规范形式：按公开树规则解析以后在工作区中的相对路径；私有、逃逸、链接与歧义的名称给出原因
        try:
            target = self.workspace.resolve(rel)
            canonical = target.relative_to(self.workspace.root.resolve()).as_posix()
            kind = ("missing" if not os.path.lexists(target)
                    else "directory" if target.is_dir() else "file")
        except (OSError, ValueError) as exc:
            return PathFacts(error=str(exc))
        return PathFacts(canonical=canonical, kind=kind)
