# 本机执行环境：run 的工作区所在的环境。控制核心经合同与它往来（actions.py），不直接读写工作区文件：
# establish 从封存快照建立工作区，open 打开已经建立的工作区，perform 执行环境工具的动作并交回回执，
# cancel 按动作身份取消，query 提供工作区事实的只读查询，snapshot 交回交付封存所需的带文件内容的公开树，
# verify_tree 核对当前公开树仍与判断所依据的快照一致。运行工作区与会话的检查工作区的来源、什么时候
# 建立或换成新的交付也在这一层（`Workspaces`，S4c 工单 #863）：薄驱动只问它这个会话用哪份工作区。
# 进程类动作（检查、bash 命令）以异步方式启动与等待；超时或取消时结束整个进程树，回执带截至结束时的输出；
# 取消在动作开始之前到达时不启动进程。

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import re

import shutil
import subprocess
import threading

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
import time
from threading import Lock
from typing import Any, Mapping

from .actions import Action, ActionReceipt, FactsQuery, PathFacts, WorkspaceFacts
from .artifacts import ArtifactStore, ExternalSource
from .event_store import run_stream
from .models import ArtifactRef, EventType, hash_bytes, json_dumps, new_id
from .public_tree import CapturedTree, UnrepresentableWorkspace, capture_public_tree, materialize_tree
from .definitions import DEFINITIONS, DefinitionError
from .path_rules import QA_TESTS_DIR, TreeError
from .process_tree import STOP_LIMIT_SEC, ProcessTree, spawn_options
from .redact import redact_text
from .tools import tool_action
from .tree_archive import artifact_run, load_tree
from .workspace import CHECKS_DIR, Workspace, WorkspaceSnapshot
# 一次工具结果的输出上限，取规则登记中的现值
_OUTPUT_LIMIT = DEFINITIONS.rule_value("tool_output_limit")
# 单页默认命中数；单页输出同样受 _OUTPUT_LIMIT 约束
SEARCH_DEFAULT_PAGE = 50
# 单行过长时保留的片段长度，避免一行占满整页输出
SEARCH_SNIPPET_LIMIT = 1000
# 超时与取消的退出码：124 与 timeout 命令相同，130 是被中断的进程的惯例
TIMEOUT_EXIT_CODE = 124
CANCELLED_EXIT_CODE = 130

_BASH_TIMEOUT_DEFAULT = DEFINITIONS.rule_value("bash_timeout_default_sec")
_BASH_TIMEOUT_MAX = DEFINITIONS.rule_value("bash_timeout_max_sec")
_CHECK_TIMEOUT_MAX = DEFINITIONS.rule_value("check_timeout_max_sec")

_BASH_PATH: str | None = None
_BASH_OUTPUT_SUBDIR = "tool-output"
INSPECTIONS_DIR = "inspections"
# Windows 句柄占用时清理目录的退避：3 次尝试，间隔按毫秒级递增（工单 #479 教训）
_CLEANUP_ATTEMPTS = 3
_CLEANUP_INITIAL_BACKOFF_SEC = 0.05


def inspection_root(run_root: str | Path, session_id: str) -> Path:
    # 每个会话的检查工作区根：<运行工作区同级>/inspections/<run_id>/<会话>。
    # 放在运行工作区外面以免被 capture_public_tree 当作运行内容（工单 #481）。
    # 每个会话一个（本地通用工具设计说明第 2 节）：主线会话与它在询问分支里的会话各用各的，
    # 嵌套询问时同一部门的两个会话不共用一个目录，也就不互相删除对方的检查工作区（工单 #473）
    path = Path(run_root)
    return path.parent / INSPECTIONS_DIR / path.name / session_id


def workspace_tree(run_root: str | Path) -> CapturedTree:
    # 运行工作区的当前公开树：建立检查工作区的源。放在执行环境里是因为控制核心不直接
    # 读写工作区文件（工作区边界的检查只看这里与工件、快照模块）
    return capture_public_tree(run_root, True)


def _prune_empty_inspection_parents(root: Path) -> None:
    # 空的上级目录一并删掉，不留空骨架目录。
    # 只删到 inspections 这一层：别的 run 的检查工作区还在时父目录非空，自然跳过
    for parent in root.parents:
        try:
            parent.rmdir()
        except OSError:
            return
        if parent.name == INSPECTIONS_DIR:
            break


def cleanup_run_inspections(run_root: str | Path) -> None:
    # 删除 run 的全部检查工作区：启动扫描用（进程异常退出时留下的目录以 run 已结束为信号删除）。
    # 目录不存在时是幂等的
    path = Path(run_root)
    root = path.parent / INSPECTIONS_DIR / path.name
    if not root.exists():
        return
    shutil.rmtree(root)
    _prune_empty_inspection_parents(root)


def cleanup_inspection_workspace(run_root: str | Path, session_id: str) -> None:
    # 删除会话的检查工作区：会话结束、取消、异常三种路径都调用。Windows 上有进程仍持有目录句柄时
    # shutil.rmtree 会抛 PermissionError（工单 #479）；按固定次数与递增退避重试，仍失败时把最后一次
    # 异常透传，由调用方决定是放行还是写进事件。多次调用与目录不存在都是幂等的
    root = inspection_root(run_root, session_id)
    if not root.exists():
        return
    backoff = _CLEANUP_INITIAL_BACKOFF_SEC

    for attempt in range(_CLEANUP_ATTEMPTS):
        try:
            shutil.rmtree(root)
            break
        except OSError as exc:
            if attempt + 1 >= _CLEANUP_ATTEMPTS:
                raise RuntimeError(
                    f"failed to remove inspection workspace for session {session_id} at {root} after "
                    f"{_CLEANUP_ATTEMPTS} attempts: {type(exc).__name__}: {exc}"
                ) from exc
            time.sleep(backoff)
            backoff *= 2
    _prune_empty_inspection_parents(root)


# ---------------------------------------------------------------------------
# 运行工作区与会话的检查工作区（骨架与应用设计说明第 6 节、本地通用工具设计说明第 2 节；S4c 工单 #863）
#
# 这一块从薄驱动搬来（工单 #473、#481、#558）：薄驱动只问两件事——这个部门在这个会话里用哪份工作区，
# 这一轮进行中检查工作区要不要换成新的交付。来源是哪份快照、什么时候建立或重建、检查回执绑定哪几样，
# 都在执行实现这里。
#
# 部门按两件定义事实分，代码里不写部门的名称（薄驱动不含部门与成果的名称，设计说明第 6 节）：
#   · 交出交付的部门（它的工具清单里有提议成「交付」的那件工具）的主线会话用运行工作区；
#   · 关注交付的部门（组织定义的 watched 里有「交付」）的检查工作区从最新的封存交付建立，
#     有新的交付封存时在它的下一步重建；其余部门的检查工作区从当前运行工作区建立。
# ---------------------------------------------------------------------------

# 成果驱动的两件定义事实：交付这件提议的种类与组织定义里「关注交付」这一项
DELIVERY_KIND = "delivery_spec"
DELIVERY_WATCHED = "delivery"


def handing_over_departments(definitions: Any = None) -> frozenset[str]:
    # 交出交付的部门（持有交接）：它的工具清单里有提议成交付的那件提交工具
    definitions = DEFINITIONS if definitions is None else definitions
    return frozenset(
        department for department in definitions.departments
        if any(tool in definitions.tools and definitions.tools[tool].proposal == DELIVERY_KIND
               for tool in definitions.tools_for(department))
    )


def delivery_inspecting_departments(definitions: Any = None) -> frozenset[str]:
    # 检查工作区从封存的交付建立的部门：组织定义里关注交付的那一个
    definitions = DEFINITIONS if definitions is None else definitions
    return frozenset(department for department in definitions.departments
                     if DELIVERY_WATCHED in definitions.watched_outputs(department))


@dataclass(frozen=True)
class RoundWorkspace:
    # 一轮工作的会话用哪份工作区：这一轮的身份（检查回执要绑定的激活）、依据的合同，
    # 以及它有没有可能在进行中换成新的交付
    run_id: str
    department: str
    session_id: str
    activation_id: str
    effective_contract_hash: str | None = None


class Workspaces:
    """运行工作区与会话的检查工作区（执行实现的一部分）。

    薄驱动在 `__init__` 里接上它，之后只调 `environment_for`（这个会话用哪份工作区）与
    `refresh_for`（这一轮进行中检查工作区要不要换成新的交付），以及 `bind`（检查回执绑定哪几样）。
    """


    def __init__(
        self,
        root: str | Path,
        *,
        view: Callable[[str], Any],
        writes: Any,
        artifacts: Any,
        sessions: Any = None,
        check_timeout: Callable[[str], int] | None = None,
        definitions: Any = None,
    ) -> None:
        self.root = Path(root)
        # 运行状态投影由薄驱动给（它只读最小投影，运行状态投影是它自己的事实）
        self._view = view
        # 读运行流的事件：会话用过文件工具或命令没有，决定检查工作区按会话保留还是每次建立
        self._writes = writes
        # 封存交付与项目起点的树
        self._artifacts = artifacts
        self.sessions = sessions
        # 检查的时限按这个 run 创建时冻结的取值（迭代底座 B3，工单 #351）
        self._check_timeout = check_timeout or (lambda run_id: DEFINITIONS.rule_value("check_timeout_sec"))
        self.handing_over = handing_over_departments(definitions)
        self.delivery_inspecting = delivery_inspecting_departments(definitions)
        # 每个会话的检查工作区是从哪一份交付建立的（工单 #558）：新的交付封存以后据此判断要不要重建
        self._source: dict[tuple[str, str], str | None] = {}

    # ---- 运行工作区 ----
    def parameters_for(self, run_id: str) -> dict[str, Any]:
        # 这个 run 冻结的参数取值（工单 #1189）：执行环境的输出上限、命令与检查的时限上限读它，
        # 建 run 之后改参数事件不影响已经创建的 run。旧 run 没有冻结字典时按定义初值解释
        from .parameters import frozen_run_parameters

        return frozen_run_parameters(self._view(run_id))

    # ---- 运行工作区 ----
    def run_environment(self, run_id: str, *, session_id: str | None = None,
                        jobs: Any | None = None) -> LocalEnvironment:
        return LocalEnvironment.open(
            self.root / run_id,
            check_timeout_sec=self._check_timeout(run_id),
            jobs=jobs,
            session_id=session_id,
            artifacts=self._artifacts,
            run_id=run_id,
            parameters=self.parameters_for(run_id),
        )

    # ---- 会话用哪份工作区 ----
    def environment_for(self, run_id: str, department: str, *, refresh: bool = False) -> LocalEnvironment:
        # 持有交接的部门的主线会话使用运行工作区，其他会话使用检查工作区。
        # refresh 只在激活开始时为真：按会话保留检查工作区（会话建立阶段从当前源建立，
        # 用过以后保留）；提案提交时为假，沿用激活内的同一份工作区，
        # 使写入与检查回执在提交判断时仍然可见
        projection = self._view(run_id)
        session_id, jobs = self.session_of(run_id, department)
        if self.hands_over(department, session_id, projection):
            return self.run_environment(run_id, session_id=session_id, jobs=jobs)
        if refresh:
            return self.session_inspection(run_id, department, session_id=session_id, jobs=jobs)
        return self.inspection_environment(run_id, department, session_id=session_id, jobs=jobs)

    def session_of(self, run_id: str, department: str) -> tuple[str | None, Any]:
        # 这个部门在这个 run 里的会话与它自己的后台命令表；还没有会话时按事实里的会话编号建立
        if self.sessions is None:
            return None, None
        try:
            session = self.sessions.get(run_id, department)
        except KeyError:
            projection = self._view(run_id)
            ids = ({item.department: item.session_id for item in projection.sessions.values()}
                   if projection.sessions else None)
            sessions = self.sessions.create_run_sessions(run_id, ids)
            session = sessions[department]
        return session.session_id, getattr(self.sessions, "jobs", None)

    def hands_over(self, department: str, session_id: str | None, projection: Any) -> bool:
        # 产出进入运行工作区的主线会话：交出交付的部门，且不在询问分支里
        if department not in self.handing_over:
            return False
        return session_id not in projection.branch_sessions

    # ---- 检查工作区 ----
    def inspection_environment(self, run_id: str, department: str, *, session_id: str | None = None,
                               jobs: Any | None = None) -> LocalEnvironment:
        # 打开会话已经有的检查工作区：激活开始与提案提交都按同一根打开，不重新建立，
        # 激活里写入的文件与检查回执在提交判断时仍然可见
        if not session_id:
            raise RuntimeError(f"inspection workspace for {department} needs a session id")
        return LocalEnvironment.open(
            inspection_root(self.root / run_id, session_id),
            check_timeout_sec=self._check_timeout(run_id),
            jobs=jobs,
            session_id=session_id,
            artifacts=self._artifacts,
            run_id=run_id,
            parameters=self.parameters_for(run_id),
        )

    def session_inspection(self, run_id: str, department: str, *, session_id: str | None = None,
                           jobs: Any | None = None) -> LocalEnvironment:
        # 会话还没有用过文件工具或命令时，每次激活都从当前源建立（会话建立阶段，源是最新的）；
        # 会话用过以后就保留，不再每次激活重建；工作区不在了（会话结束清理过）时重新建立
        if not session_id:
            raise RuntimeError(f"inspection workspace for {department} needs a session id")
        root = inspection_root(self.root / run_id, session_id)
        if root.exists() and self.used_inspection(run_id, session_id):
            return self.inspection_environment(run_id, department, session_id=session_id, jobs=jobs)
        return self.new_inspection(run_id, department, session_id=session_id, jobs=jobs)

    def used_inspection(self, run_id: str, session_id: str) -> bool:
        # 这个会话用过文件工具或命令没有：用过以后它的检查工作区按会话保留（工单 #558）
        events = self._writes.read(run_stream(run_id)).events()
        return any(event.type == EventType.TOOL_CALLED and event.session_id == session_id
                   and tool_action(str((event.payload or {}).get("name") or "")) is not None
                   for event in events)

    def source_hash(self, department: str, projection: Any) -> str | None:
        # 从封存交付建立的部门（质检）的检查工作区：这份交付的摘要就是工作区的来源；
        # 其他会话的检查工作区来自运行工作区，不随交付变化（没有交付时为空）
        if department not in self.delivery_inspecting:
            return None
        delivery = projection.delivery_spec
        return None if delivery is None else delivery.content_hash

    def source_tree(self, department: str, projection: Any) -> CapturedTree:
        # 检查工作区的建立源：从封存交付建立的部门取它当前面对的快照——最新的封存交付，
        # 还没有交付时是事项开始时的项目起点（采纳成果或项目的起始文件夹快照，都没有时为空树），
        # 不读运行工作区；其他会话从当前运行工作区快照建立。
        # 封存交付读不出来（归档缺失或损坏）时不退回运行工作区：ADR-0038 与 local-tools 第 2 节
        # 要求检查工作区从封存的交付建立，退回会让质检在并非交付的树上检查；这个失败由激活开始的
        # host_commit_error 正式报告
        if department in self.delivery_inspecting:
            if projection.delivery_spec is not None and projection.delivery_spec.tree_ref is not None:
                tree_ref = projection.delivery_spec.tree_ref
                return load_tree(self._artifacts, artifact_run(tree_ref.path), tree_ref)
            for record in (projection.baseline, projection.snapshot):
                # 事项开始时的项目起点：run_created 写下的采纳成果或起始文件夹快照，两者都没有时为空树
                if not record:
                    continue
                start_ref = ArtifactRef(**record["tree_ref"])
                return load_tree(self._artifacts, artifact_run(start_ref.path), start_ref)
            return CapturedTree(directories=(), files=())
        return workspace_tree(self.root / projection.run_id)

    def new_inspection(self, run_id: str, department: str, *, session_id: str | None = None,
                       jobs: Any | None = None) -> LocalEnvironment:
        # 旧的检查工作区按工单的重试清理删除，再按当前源建立；源可能在上一次激活后被新交付覆盖，
        # 从交付建立的部门必须看到最新交付而不是上一次的副本
        projection = self._view(run_id)
        run_root = self.root / run_id
        if session_id is None:
            session_id, table = self.session_of(run_id, department)
            jobs = jobs if jobs is not None else table
        if session_id is None:
            raise RuntimeError(f"inspection workspace for {department} needs a session id")
        root = inspection_root(run_root, session_id)
        if jobs is None and self.sessions is not None:
            jobs = getattr(self.sessions, "jobs", None)
        if jobs is not None:
            jobs.stop_and_remove_for_workspace(session_id, root)
        if root.exists():
            cleanup_inspection_workspace(run_root, session_id)
        env = LocalEnvironment.establish(
            root,
            self.source_tree(department, projection),
            check_timeout_sec=self._check_timeout(run_id),
            jobs=jobs,
            session_id=session_id,
            artifacts=self._artifacts,
            run_id=run_id,
            parameters=self.parameters_for(run_id),
        )
        if department in self.delivery_inspecting:
            ref = projection.qa_tests_archive_ref
            if ref is not None:
                if isinstance(ref, dict):
                    ref = ArtifactRef(**ref)
                env.place_qa_tests(load_tree(self._artifacts, artifact_run(ref.path), ref))
            else:
                env.place_qa_tests(None)
        self._source[(run_id, session_id)] = self.source_hash(department, projection)
        return env

    def forget(self, run_id: str, session_id: str) -> None:
        # 检查工作区删掉以后不再记它的来源
        self._source.pop((run_id, session_id), None)

    # ---- 检查回执绑定的身份与交付到达时的重建 ----
    def bind(self, environment: LocalEnvironment, projection: Any, *, activation_id: str | None,
             effective_contract_hash: str | None = None) -> None:
        # 检查回执随这一刻的运行状态身份记录：哪一份合同、哪一份产品合同与哪一份交付。
        # 薄驱动不知道哪几份成果参与，这里按运行状态投影取
        environment.bind_check(
            activation_id=activation_id,
            product_spec_hash=(None if projection.product_spec is None
                               else projection.product_spec.content_hash),
            delivery_spec_hash=(None if projection.delivery_spec is None
                                else projection.delivery_spec.content_hash),
            effective_contract_hash=effective_contract_hash,
        )

    def refresh_for(self, round: RoundWorkspace) -> Callable[[], LocalEnvironment | None]:
        # 检查工作区按会话保留（工单 #558）：从封存交付建立的部门进行中有新的交付封存时，
        # 在它的下一步从这份交付重建；询问与通知都不重建
        def refresh() -> LocalEnvironment | None:
            if round.department not in self.delivery_inspecting:
                return None
            projection = self._view(round.run_id)
            current = self.source_hash(round.department, projection)
            if current is None:
                return None
            if self._source.get((round.run_id, round.session_id)) == current:
                return None
            environment = self.new_inspection(round.run_id, round.department, session_id=round.session_id)
            self.bind(environment, projection, activation_id=round.activation_id,
                      effective_contract_hash=round.effective_contract_hash)
            return environment

        return refresh


def _bash_slice(full: str, start: int, limit: int) -> tuple[str, int | None]:
    # 从字符偏移 start 取一页：尽量在 limit（这个 run 冻结的 tool_output_limit）个字符内不断行；
    # 取完返回 (剩余全文, None)，否则返回 (页, 下一页的字符偏移)
    end = start + limit
    if end >= len(full):
        return full[start:], None
    newline = full.rfind("\n", start, end)
    cut = newline + 1 if newline > start else end
    return full[start:cut], cut


def _locate_expected(text: str, expected: str, rel: str,
                     start: int | None, end: int | None) -> int:
    """按原文定位要替换的那一段的字符偏移（工单 #719）。

    原文在文件里只出现一次时直接用它——行号可以是过期的（文件的上半部分改过以后行号会移动，
    这时候按行号定位会把后面的编辑全部拒掉）。
    出现多次时用 start_line 消歧：取起点落在那一行的那一处；没有这样的一处就拒绝，并写明匹配了几次。
    """
    offsets = [match.start() for match in re.finditer(re.escape(expected), text)]
    if not offsets:
        raise ValueError(f"expected text does not occur in {rel}; re-read the file before editing")
    if len(offsets) == 1:
        return offsets[0]
    starts = [text.count("\n", 0, offset) + 1 for offset in offsets]
    if start is None:
        raise ValueError(f"expected text is ambiguous: it matches {len(offsets)} times in {rel}; "
                         "pass start_line to choose one")
    candidates = [offset for offset, line in zip(offsets, starts) if line == start]
    if not candidates:
        raise ValueError(f"expected text is ambiguous: it matches {len(offsets)} times in {rel}; "
                         f"none of them starts at line {start}; re-read with a unique span")
    if len(candidates) > 1 and end is not None:
        # 同一行里出现多次时用 end_line 再收一次
        narrowed = [offset for offset in candidates
                    if text.count("\n", 0, offset + len(expected) - 1) + 1 == end]
        if narrowed:
            candidates = narrowed
    if len(candidates) > 1:
        raise ValueError(f"expected text is ambiguous: it matches {len(candidates)} times at line {start} in {rel}; "
                         "pass end_line to choose one")
    return candidates[0]


def _resolve_bash() -> str:
    # 找到可执行的 bash：Windows 上先看 Git 安装目录，再看 PATH；POSIX 上只认 /bin/bash。
    # 找不到就直接报错，不回退到 cmd 或 PowerShell。
    global _BASH_PATH
    if _BASH_PATH is not None:
        return _BASH_PATH
    if os.name == "nt":
        candidates = [
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files (x86)\Git\bin\bash.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\bin\bash.exe"),
            shutil.which("bash.exe"),
            shutil.which("bash"),
        ]
        for candidate in candidates:
            if candidate and os.path.isfile(candidate):
                _BASH_PATH = candidate
                return candidate
        raise FileNotFoundError("Git for Windows bash not found; install Git for Windows or add bash.exe to PATH")
    posix = "/bin/bash"
    if os.path.isfile(posix):
        _BASH_PATH = posix
        return posix
    raise FileNotFoundError(f"bash not found at {posix}")

# 环境工具与执行它的方法：直接执行的工具，与以进程执行、可以超时与取消的工具
_HANDLERS = {
    "read_file": "_read_file",
    "list_files": "_list_files",
    "search": "_search",
    "read_range": "_read_range",
    "read_external_source": "_read_external_source",
    "write_file": "_write_file",
    "edit_range": "_edit_range",
    "delete_file": "_delete_file",
    "move_file": "_move_file",
    "read_output": "_read_output",
    "stop_job": "_stop_job",
}
_PROCESSES = {"run_check": "_run_check", "bash": "_bash"}

# 动作类别与属于它的工具：执行环境按类别分派，再从上面两种执行方式里按实际工具名取执行方法。
# 实际工具名仍供工具许可、提案与装配读取；新增的类别由各自的处理分支提供（网络取回与 MCP 设计说明第 18 节）
_KIND_TOOLS = {
    "read": frozenset({"read_file", "list_files", "search", "read_range", "read_external_source"}),
    "write": frozenset({"write_file", "edit_range", "delete_file", "move_file"}),
    "check": frozenset({"run_check"}),
    "command": frozenset({"bash", "read_output", "stop_job"}),
}

# 定义中的每个环境工具都要在它动作类别的分派里有执行方法，否则启动失败
_UNIMPLEMENTED = sorted(name for name, tool in DEFINITIONS.tools.items()
                        if tool.kind == "environment"
                        and (name not in _KIND_TOOLS.get(tool.action, ())
                             or (name not in _HANDLERS and name not in _PROCESSES)))
if _UNIMPLEMENTED:
    raise DefinitionError([("tools.json", name, "执行环境没有这个环境工具的实现") for name in _UNIMPLEMENTED])


@dataclass(frozen=True)
class _Finished:
    # 一个进程的结束：completed、timeout 或 cancelled，以及截至结束时的输出。
    # stopped 说明整棵进程树确实停了没有（确实杀不掉时回执要说清楚，不把「已停止」当结论写出去），
    # left_behind 说明命令结束时它留下了子进程（那些进程随这次调用一起结束了）
    status: str
    returncode: int | None
    stdout: str
    stderr: str
    stopped: bool = True
    left_behind: bool = False

class _Job:
    def __init__(
        self,
        job_id: str,
        output_path: Path,
        process: subprocess.Popen[Any] | None = None,
        file_handle: Any = None,
        status: str = "running",
        exit_code: int | None = None,
        timer: threading.Timer | None = None,
        session_id: str | None = None,
        workspace_root: Path | None = None,
        tree: ProcessTree | None = None,
    ) -> None:
        self.job_id = job_id
        self.output_path = output_path
        self.process = process
        self.file_handle = file_handle
        self.status = status
        self.exit_code = exit_code
        self.timer = timer
        self.session_id = session_id
        self.workspace_root = workspace_root
        # 这个后台作业的整棵进程树（工单 #1215）：直接子进程退出以后它留下的子进程还在树里，
        # 按直接子进程的进程号结束打不到它们
        self.tree = tree
        self.read_offset = 0
        # 上一次结束整棵树时它是否确实停了下来
        self._tree_stopped = True
        # 后台作业的时限到了由计时器线程调 stop()，读输出与停止来自另一条线程：状态与句柄只能
        # 在锁里改，否则两边同时关同一个句柄会关到别人刚拿到的那一个
        self._lock = Lock()
        # 已经结束过时的回执：重复调 stop() 交回同一条，不再动已经放掉的资源
        self._stop_receipt: dict[str, Any] | None = None

    def read(self) -> dict[str, Any]:
        with self._lock:
            return self._read()

    def _read(self) -> dict[str, Any]:
        if self.status == "running" and self.process is not None:
            ret = self.process.poll()
            if ret is not None:
                self.status = "exited"
                self.exit_code = ret
                if self.timer is not None:
                    self.timer.cancel()
                    self.timer = None
                if self.file_handle is not None:
                    self.file_handle.close()
                    self.file_handle = None

        chunk = ""
        if self.output_path.exists():
            full_text = redact_text(_text(self.output_path.read_bytes()))
            if self.read_offset < len(full_text):
                chunk = full_text[self.read_offset:]
                self.read_offset = len(full_text)

        return {
            "job_id": self.job_id,
            "output": chunk,
            "status": self.status,
            "exit_code": self.exit_code,
        }

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if self._stop_receipt is not None:
                return dict(self._stop_receipt)
            receipt = self._stop()
            self._stop_receipt = dict(receipt)
            return receipt

    def _stop(self) -> dict[str, Any]:
        if self.status == "running" and self.process is not None:
            ret = self.process.poll()
            if ret is not None:
                self.status = "exited"
                self.exit_code = ret
            else:
                self.status = "stopped"
        elif self.status == "running":
            self.status = "stopped"
        # 直接子进程已经退出时它留下的子进程还在树里：无论哪一种都结束整棵树（工单 #1215）
        left_behind = self.status == "exited" and self._tree_has_processes()
        self._stop_tree()

        if self.timer is not None:
            self.timer.cancel()
            self.timer = None
        if self.file_handle is not None:
            self.file_handle.close()
            self.file_handle = None

        if self.status == "exited":
            output_msg = f"job {self.job_id} has already exited"
            if self.exit_code is not None:
                output_msg += f" with exit code {self.exit_code}"
            if left_behind:
                output_msg += "; the processes it left behind were stopped"
            return {
                "job_id": self.job_id,
                "output": output_msg,
                "status": self.status,
                "exit_code": self.exit_code,
            }
        stopped = self._tree_stopped
        return {
            "job_id": self.job_id,
            "output": (f"job {self.job_id} was stopped; the process tree was stopped" if stopped
                       else f"job {self.job_id} was stopped; some processes from the job could not be stopped"),
            "status": self.status,
            "exit_code": self.exit_code,
        }

    def _tree_has_processes(self) -> bool:
        return self.tree is not None and self.tree.has_live_processes()

    def _stop_tree(self) -> None:
        # 结束整棵树并等它真正停下；停不下来时记下来，回执里如实写
        if self.tree is None:
            return
        self.tree.stop()
        stopped = self.tree.wait_stopped(STOP_LIMIT_SEC)
        if self.process is not None and self.process.poll() is None:
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
        self.tree.close()
        self._tree_stopped = stopped
        self.tree = None


class BackgroundJobTable:
    def __init__(self) -> None:
        self._jobs: dict[str, _Job] = {}
        self._lock = Lock()

    def register(self, job: _Job) -> None:
        with self._lock:
            self._jobs[job.job_id] = job

    def read_output(self, job_id: str, session_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.session_id != session_id:
                return {"job_id": job_id, "output": "", "status": "ended", "exit_code": None}
            return job.read()

    def stop_job(self, job_id: str, session_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.session_id != session_id:
                return {"job_id": job_id, "output": f"job {job_id} has ended", "status": "ended", "exit_code": None}
            return job.stop()

    def stop_for_sessions(self, session_ids: Iterable[str]) -> None:
        targets = set(session_ids)
        with self._lock:
            for job in list(self._jobs.values()):
                if job.session_id in targets:
                    job.stop()

    def stop_and_remove_for_workspace(self, session_id: str, workspace_root: Path | str) -> None:
        target_root = Path(workspace_root).resolve()
        with self._lock:
            matching = [
                job_id for job_id, job in self._jobs.items()
                if job.session_id == session_id and job.workspace_root is not None and job.workspace_root.resolve() == target_root
            ]
            for job_id in matching:
                job = self._jobs.pop(job_id)
                job.stop()

    def get_status(self, job_id: str) -> str | None:
        # 只读状态查询：不读取输出、不移动 read_output 读取位置
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.status == "running" and job.process is not None:
                if job.process.poll() is not None:
                    return "exited"
            return job.status


class LocalEnvironment:
    def __init__(
        self,
        workspace: Workspace,
        check_timeout_sec: int = DEFINITIONS.rule_value("check_timeout_sec"),
        *,
        jobs: BackgroundJobTable | None = None,
        session_id: str | None = None,
        artifacts: ArtifactStore | None = None,
        run_id: str | None = None,
        parameters: Mapping[str, Any] | None = None,
    ) -> None:
        self.workspace = workspace
        self._check_timeout_sec = check_timeout_sec
        self._jobs = jobs
        self._session_id = session_id
        # 这个 run 的外部来源工件：read_external_source 只读这个 run 的工件库
        self._artifacts = artifacts
        self._run_id = run_id
        # 这个 run 冻结的参数取值（工单 #1189）；直接构造环境（测试、没有冻结字典的旧 run）时为空
        self._parameters = dict(parameters or {})
        # 正在进行的动作与它的停止信号；取消在动作开始之前到达时先记下，开始时不执行
        self._lock = Lock()
        self._running: dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Event]] = {}
        self._cancelled: set[str] = set()
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {
            name: getattr(self, method) for name, method in _HANDLERS.items()}
        self._processes: dict[str, Callable[[Action, asyncio.Event], Awaitable[tuple[Any, str]]]] = {
            name: getattr(self, method) for name, method in _PROCESSES.items()}
    def _limit(self, name: str, default: Any) -> Any:
        # 这个 run 冻结的参数取值；没有冻结字典时用定义文件里的初始值（工单 #1189）
        value = self._parameters.get(name)
        return default if value is None else value

    def _output_limit(self) -> int:
        return int(self._limit('tool_output_limit', _OUTPUT_LIMIT))


    @classmethod
    def establish(
        cls,
        root: str | Path,
        tree: CapturedTree | None,
        *,
        check_timeout_sec: int = DEFINITIONS.rule_value("check_timeout_sec"),
        jobs: BackgroundJobTable | None = None,
        session_id: str | None = None,
        artifacts: ArtifactStore | None = None,
        run_id: str | None = None,
        parameters: Mapping[str, Any] | None = None,
    ) -> LocalEnvironment:
        # 从封存快照建立工作区：快照给出时按它的内容新建目录并核对，没有快照时建立空的工作区
        if tree is not None:
            Path(root).parent.mkdir(parents=True, exist_ok=True)
            materialize_tree(tree, root)
        return cls(Workspace(root), check_timeout_sec=check_timeout_sec, jobs=jobs, session_id=session_id,
                   artifacts=artifacts, run_id=run_id, parameters=parameters)

    @classmethod
    def open(
        cls,
        root: str | Path,
        *,
        check_timeout_sec: int = DEFINITIONS.rule_value("check_timeout_sec"),
        jobs: BackgroundJobTable | None = None,
        session_id: str | None = None,
        artifacts: ArtifactStore | None = None,
        run_id: str | None = None,
        parameters: Mapping[str, Any] | None = None,
    ) -> LocalEnvironment:
        # 打开已经建立的工作区
        return cls(Workspace(root), check_timeout_sec=check_timeout_sec, jobs=jobs, session_id=session_id,
                   artifacts=artifacts, run_id=run_id, parameters=parameters)

    def _limit(self, name: str, default: Any) -> Any:
        # 这个 run 冻结的参数取值；没有冻结字典时用定义文件里的初始值（工单 #1189）
        value = self._parameters.get(name)
        return default if value is None else value

    def _output_limit(self) -> int:
        return int(self._limit('tool_output_limit', _OUTPUT_LIMIT))

    def bind_check(self, *, activation_id: str | None, product_spec_hash: str | None,
                   delivery_spec_hash: str | None, effective_contract_hash: str | None = None) -> None:
        # 这次激活的运行状态身份随检查回执记录，供 U 判断回执是否属于当前有效的合同与快照
        self.workspace.bind_check(
            activation_id=activation_id, product_spec_hash=product_spec_hash,
            delivery_spec_hash=delivery_spec_hash, effective_contract_hash=effective_contract_hash,
        )

    def verify_tree(self, snapshot: WorkspaceSnapshot) -> None:
        # 交付核对：当前公开树仍与判断所依据的快照一致
        if self.workspace.snapshot().tree.manifest != snapshot.tree.manifest:
            raise TreeError("Public tree does not match the complete recorded manifest")

    def capture_qa_tests(self) -> CapturedTree:
        qa_dir = self.workspace.root / QA_TESTS_DIR
        if qa_dir.is_dir():
            return capture_public_tree(qa_dir)
        return CapturedTree((), ())
    def qa_tests_digest(self) -> str | None:
        return qa_tests_digest(self.capture_qa_tests())


    def place_qa_tests(self, tree: CapturedTree | None) -> None:
        qa_dir = self.workspace.root / QA_TESTS_DIR
        if tree is not None:
            materialize_tree(tree, qa_dir)
        else:
            qa_dir.mkdir(parents=True, exist_ok=True)

    async def perform(self, action: Action) -> ActionReceipt:
        # 按动作类别分派（总图第四节「动作」缝）：同一类里按实际工具名取执行方法；新的动作类别不在本机执行
        # 环境的处理分支里，立刻失败。工具的执行出错时回执为 failed，错误说明交回模型；工作区出现公开树无法
        # 表示的条目时（UnrepresentableWorkspace），按原样传出，由步骤驱动以 workspace_unrepresentable 暂停运行
        tools = _KIND_TOOLS.get(action.kind)
        if tools is None:
            raise ValueError(f"the local environment does not execute {action.kind} actions")
        if action.tool not in tools:
            raise ValueError(f"{action.tool} is not a {action.kind} action")
        process = self._processes.get(action.tool)
        handler = None if process is not None else self._handlers[action.tool]
        if action.department != "quality" and action.tool in self._handlers:
            for key in ("path", "source", "destination", "prefix"):
                val = action.input.get(key)
                if isinstance(val, str) and (val.replace("\\", "/").strip("/").split("/")[0] == QA_TESTS_DIR):
                    return ActionReceipt(action_id=action.action_id, status="failed",
                                         error=f"拒绝访问 {val}：这是质检的测试材料")
        stop = asyncio.Event()
        with self._lock:
            if action.action_id in self._cancelled:
                self._cancelled.discard(action.action_id)
                return ActionReceipt(action_id=action.action_id, status="cancelled",
                                     error="The action was cancelled before it started.")
            self._running[action.action_id] = (asyncio.get_running_loop(), stop)
        try:
            if process is not None:
                result = await process(action, stop)
                # 登记命令结束后主机立即取得的公开树核对结果随回执交回：附在回执上，步骤驱动在
                # 回执照常记录之后按它以 workspace_unrepresentable 暂停
                output, status, workspace_error = result if len(result) == 3 else (*result, None)
                if workspace_error is not None:
                    output = {**output, "workspace_unrepresentable": workspace_error}
            else:
                output, status = handler(action.input), "completed"
        except UnrepresentableWorkspace:
            raise
        except Exception as exc:
            return ActionReceipt(action_id=action.action_id, status="failed", error=str(exc))
        finally:
            with self._lock:
                self._running.pop(action.action_id, None)
        return ActionReceipt(action_id=action.action_id, status=status, output=output)

    def cancel(self, action_id: str) -> None:
        # 可以从任何线程调用。在锁内安排停止：登记在动作结束时于它的事件循环中移除，持有锁期间事件循环一定仍在运行
        with self._lock:
            running = self._running.get(action_id)
            if running is None:
                self._cancelled.add(action_id)
                return
            loop, stop = running
            loop.call_soon_threadsafe(stop.set)

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
            canonical = target.relative_to(self.workspace.root).as_posix()
            kind = ("missing" if not os.path.lexists(target)
                    else "directory" if target.is_dir() else "file")
        except (OSError, ValueError) as exc:
            return PathFacts(error=str(exc))
        return PathFacts(canonical=canonical, kind=kind)

    def _read_file(self, args: dict[str, Any]) -> str:
        return self.workspace.read_file(str(args["path"]))

    def _list_files(self, args: dict[str, Any]) -> list[str]:
        prefix = args.get("prefix")
        return self.workspace.list_files(None if prefix in (None, "") else str(prefix))

    def _search(self, args: dict[str, Any]) -> dict[str, Any]:
        pattern = args.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            raise ValueError("search requires a non-empty pattern")
        compiled = re.compile(pattern)
        scope = args.get("path")
        scope_rel = None if scope in (None, "") else str(scope).rstrip("/")
        page_size = _page_size(args.get("max_results"))
        offset = 0
        cursor_arg = args.get("cursor")
        cursor: dict[str, Any] | None = None
        if cursor_arg not in (None, ""):
            cursor = _decode_cursor(str(cursor_arg), kind="search")
            if cursor.get("pattern") != pattern or cursor.get("path") != scope_rel or cursor.get("page_size") != page_size:
                raise ValueError("cursor does not match the current search arguments")
            offset = cursor["offset"]
        snapshot = self.workspace.snapshot()
        digest = snapshot.digest
        if cursor is not None and cursor.get("digest") != digest:
            raise ValueError("workspace changed since the cursor was issued; start a new search")
        if scope_rel is None:
            files = list(snapshot.tree.files)
        else:
            # 作用域同样走公开路径校验，私有、逃逸、链接与歧义路径直接报错
            target = self.workspace.resolve(scope_rel)
            if not os.path.lexists(target):
                raise FileNotFoundError(f"search scope not found: {scope_rel}")
            if target.is_dir():
                files = [item for item in snapshot.tree.files
                         if item.path == scope_rel or item.path.startswith(scope_rel + "/")]
            else:
                files = [item for item in snapshot.tree.files if item.path == scope_rel]
                if not files:
                    raise FileNotFoundError(f"search scope not found: {scope_rel}")
        matches: list[dict[str, Any]] = []
        for item in files:
            # 二进制内容按替换字符解码后同样参与匹配，作用域内不静默跳过任何文件
            for number, line in enumerate(item.data.decode("utf-8", errors="replace").splitlines(), 1):
                if compiled.search(line):
                    matches.append({"path": item.path, "line": number, "snippet": _clip_snippet(line)})
        page = matches[offset:offset + page_size]
        truncated = offset + len(page) < len(matches)
        page, truncated = _fit_match_page(page, truncated, self._output_limit())
        return {
            "pattern": pattern,
            "path": scope_rel,
            "digest": digest,
            "matches": page,
            "total_matches": len(matches),
            "truncated": truncated,
            "next_cursor": _encode_cursor({
                "kind": "search", "pattern": pattern, "path": scope_rel,
                "page_size": page_size, "offset": offset + len(page), "digest": digest,
            }) if truncated else None,
        }

    def _read_range(self, args: dict[str, Any]) -> dict[str, Any]:
        rel = args.get("path")
        if not isinstance(rel, str) or not rel:
            raise ValueError("read_range requires a path")
        start = args.get("start_line")
        if type(start) is not int or start < 1:
            raise ValueError("start_line must be an integer >= 1")
        end = args.get("end_line")
        if end is not None and (type(end) is not int or end < start):
            raise ValueError("end_line must be an integer >= start_line")
        offset = start
        cursor: dict[str, Any] | None = None
        cursor_arg = args.get("cursor")
        if cursor_arg not in (None, ""):
            cursor = _decode_cursor(str(cursor_arg), kind="read_range")
            if cursor.get("path") != rel or cursor.get("start_line") != start or cursor.get("end_line") != end:
                raise ValueError("cursor does not match the current read_range arguments")
            offset = cursor["offset"]
        self.workspace.resolve_readable(rel)
        snapshot = self.workspace.snapshot()
        digest = snapshot.digest
        if cursor is not None and cursor.get("digest") != digest:
            raise ValueError("workspace changed since the cursor was issued; start a new read")
        raw = next((item.data for item in snapshot.tree.files if item.path == rel), None)
        if raw is None:
            raise FileNotFoundError(f"file not found: {rel}")
        # 与 read_file 一致使用严格解码，二进制内容直接报错而不猜测
        numbered = list(enumerate(raw.decode("utf-8").splitlines(), 1))
        total = len(numbered)
        wanted = [(number, text) for number, text in numbered if number >= offset and (end is None or number <= end)]
        entries, consumed = _fit_line_entries(wanted, self._output_limit())
        truncated = consumed < len(wanted)
        next_offset = offset + consumed
        last = offset + consumed - 1
        return {
            "path": rel,
            "digest": digest,
            "content_hash": hash_bytes(raw),
            "start_line": offset,
            "end_line": last if consumed else min(total, offset - 1),
            "total_lines": total,
            "lines": entries,
            "truncated": truncated,
            "next_cursor": _encode_cursor({
                "kind": "read_range", "path": rel, "start_line": start, "end_line": end,
                "offset": next_offset, "digest": digest,
            }) if truncated else None,
        }

    def _read_external_source(self, args: dict[str, Any]) -> dict[str, Any]:
        # 读一份已经存下来的外部来源（网络取回与 MCP 设计说明第 6.4 节）：按来源编号与行范围读，
        # 不重新取回；游标做法与 read_range 相同，并绑定这份正文的摘要
        source = args.get("source")
        if not isinstance(source, str) or not source:
            raise ValueError("read_external_source requires a source")
        start = args.get("start_line")
        if type(start) is not int or start < 1:
            raise ValueError("start_line must be an integer >= 1")
        end = args.get("end_line")
        if end is not None and (type(end) is not int or end < start):
            raise ValueError("end_line must be an integer >= start_line")
        offset = start
        cursor: dict[str, Any] | None = None
        cursor_arg = args.get("cursor")
        if cursor_arg not in (None, ""):
            cursor = _decode_cursor(str(cursor_arg), kind="read_external_source")
            if cursor.get("source") != source or cursor.get("start_line") != start or cursor.get("end_line") != end:
                raise ValueError("cursor does not match the current read_external_source arguments")
            offset = cursor["offset"]
        entry = self._external_source(source)
        if cursor is not None and cursor.get("content_hash") != entry.content_hash:
            raise ValueError("external source changed since the cursor was issued; start a new read")
        numbered = list(enumerate(entry.text.splitlines(), 1))
        total = len(numbered)
        wanted = [(number, text) for number, text in numbered if number >= offset and (end is None or number <= end)]
        entries, consumed = _fit_line_entries(wanted, self._output_limit())
        truncated = consumed < len(wanted)
        last = offset + consumed - 1
        return {
            "source": entry.source,
            "content_hash": entry.content_hash,
            "final_url": entry.final_url,
            "status_code": entry.status_code,
            "content_type": entry.content_type,
            "fetched_at": entry.fetched_at,
            "start_line": offset,
            "end_line": last if consumed else min(total, offset - 1),
            "total_lines": total,
            "lines": entries,
            "truncated": truncated,
            "next_cursor": _encode_cursor({
                "kind": "read_external_source", "source": source, "start_line": start, "end_line": end,
                "offset": offset + consumed, "content_hash": entry.content_hash,
            }) if truncated else None,
        }

    def _external_source(self, source: str) -> ExternalSource:
        # 这个 run 的外部来源工件：执行环境没有接上工件库时直接报错，不猜
        if self._artifacts is None or self._run_id is None:
            raise ValueError("external sources are not available in this environment")
        return self._artifacts.external_source(self._run_id, source)

    def _write_file(self, args: dict[str, Any]) -> str:
        return self.workspace.write_file(str(args["path"]), str(args["content"]))

    def _edit_range(self, args: dict[str, Any]) -> dict[str, Any]:
        rel = args.get("path")
        if not isinstance(rel, str) or not rel:
            raise ValueError("edit_range requires a path")
        # 行号是消歧用的提示，不再是必填（工单 #719）：原文唯一时按原文定位，行号可以过期
        start = args.get("start_line")
        if start is not None and (type(start) is not int or start < 1):
            raise ValueError("start_line must be an integer >= 1 when given")
        end = args.get("end_line")
        if end is not None and (type(end) is not int or end < 1):
            raise ValueError("end_line must be an integer >= 1 when given")
        if start is not None and end is not None and end < start:
            raise ValueError("end_line must be >= start_line when both are given")
        expected = args.get("expected_text")
        if not isinstance(expected, str) or not expected:
            raise ValueError("expected_text must be a non-empty string")
        new_text = args.get("new_text")
        if not isinstance(new_text, str):
            raise ValueError("new_text must be a string")
        expected_digest = args.get("expected_digest")
        if expected_digest is not None and (not isinstance(expected_digest, str) or not expected_digest):
            raise ValueError("expected_digest must be a file content hash string when given")
        for label, value in (("expected_text", expected), ("new_text", new_text)):
            try:
                value.encode("utf-8", errors="strict")
            except (UnicodeEncodeError, ValueError) as exc:
                raise ValueError(f"encoding difference: {label} cannot be encoded as UTF-8 identically") from exc
        # 路径校验复用公开树规则，私有、逃逸、链接与歧义名称直接报错；被忽略规则排除的路径拒绝编辑
        target = self.workspace.resolve_writable(rel)
        if not os.path.lexists(target):
            raise FileNotFoundError(f"file not found: {rel}")
        if not target.is_file():
            raise ValueError(f"edit_range requires an existing regular file: {rel}")
        # 原文按目标文件本身读取：公开树不含质检的测试材料目录（本地工具第 2 节），
        # 区间编辑与写入工具作用在同一批可写的目标文件上
        raw = target.read_bytes()
        # 文件级摘要只绑定目标文件，其它文件的改动不影响本次核对
        if expected_digest is not None and hash_bytes(raw) != expected_digest:
            raise ValueError("file changed since the read; re-read the span before editing")
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValueError(f"encoding difference: {rel} is not valid UTF-8; re-read and use matching bytes") from exc
        # 与 read_range 一致按通用换行分行，落盘时保留原换行格式
        crlf = "\r\n" in text
        normalized = text.replace("\r\n", "\n")
        # 按原文定位要替换的那一段（工单 #719）：原文唯一时直接用它，行号可以是过期的
        offset = _locate_expected(normalized, expected, rel, start, end)
        new_lines = new_text.split("\n")
        # 命中的那一段按字符替换：前后的内容原样保留，尾换行也跟着保留
        replaced = normalized[:offset] + new_text + normalized[offset + len(expected):]
        if crlf:
            replaced = replaced.replace("\n", "\r\n")
        new_raw = replaced.encode("utf-8")
        # 全部核对通过后才落盘；任一拒绝都不触碰文件字节
        self.workspace.resolve(rel).write_bytes(new_raw)
        final = self.workspace.snapshot()
        first_line = normalized.count("\n", 0, offset) + 1
        return {
            "path": rel,
            "start_line": first_line,
            "end_line": first_line + len(new_lines) - 1,
            "total_lines": len(replaced.splitlines()),
            "digest": final.digest,
            "content_hash": hash_bytes(new_raw),
        }

    def _delete_file(self, args: dict[str, Any]) -> str:
        _require_reason(args)
        return self.workspace.delete_file(args["path"])

    def _move_file(self, args: dict[str, Any]) -> dict[str, str]:
        _require_reason(args)
        return self.workspace.move_file(args["source"], args["destination"])

    async def _bash(self, action: Action, stop: asyncio.Event) -> tuple[dict[str, Any], str, str | None]:
        args = action.input
        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("bash requires a non-empty command string")
        timeout_sec = args.get("timeout_sec")
        if timeout_sec is None:
            timeout_sec = self._limit("bash_timeout_default_sec", _BASH_TIMEOUT_DEFAULT)
        else:
            if type(timeout_sec) is not int or timeout_sec < 1:
                raise ValueError("timeout_sec must be a positive integer")
            timeout_sec = min(timeout_sec, self._limit("bash_timeout_max_sec", _BASH_TIMEOUT_MAX))
        snapshot = self.workspace.snapshot()
        expected = action.preconditions.tree_digest
        if expected is not None and snapshot.digest != expected:
            raise ValueError("the workspace changed after the tool permission; call bash again")

        if args.get("background") is True:
            if self._jobs is None or self._session_id is None:
                raise RuntimeError("background commands require an environment with a session context")
            job_id = new_id("job")
            directory = self.workspace.root / CHECKS_DIR / _BASH_OUTPUT_SUBDIR
            directory.mkdir(parents=True, exist_ok=True)
            output_path = directory / f"{job_id}.output"
            file_handle = open(output_path, "wb")

            spawn: dict[str, Any] = spawn_options()
            process = subprocess.Popen(
                [_resolve_bash(), "-c", command],
                cwd=str(self.workspace.root),
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                stdin=subprocess.DEVNULL,
                stdout=file_handle,
                stderr=subprocess.STDOUT,
                **spawn,
            )
            # 整棵树收进容器：stop_job 与会话结束时一次停掉它，包括直接子进程退出以后留下的子进程
            tree = ProcessTree()
            try:
                tree.attach(process.pid)
            except BaseException:
                # 放不进容器也放不出去的时候：结束它、关掉输出文件，不留在机器上
                tree.stop()
                tree.close()
                file_handle.close()
                raise
            job = _Job(
                job_id=job_id,
                output_path=output_path,
                process=process,
                file_handle=file_handle,
                status="running",
                session_id=self._session_id,
                workspace_root=self.workspace.root,
                tree=tree,
            )
            timer = threading.Timer(timeout_sec, job.stop)
            timer.daemon = True
            timer.start()
            job.timer = timer
            self._jobs.register(job)
            return {"job_id": job_id, "status": "running"}, "completed", None

        finished = await _run_process(
            [_resolve_bash(), "-c", command], self.workspace.root,
            {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, timeout_sec, stop,
        )
        text = "\n".join(part for part in (finished.stdout.strip(), finished.stderr.strip()) if part)
        if finished.status == "timeout":
            exit_code, status = TIMEOUT_EXIT_CODE, "timeout"
            text = ((text + "\n") if text else "") + _tree_stopped_note("command timed out", timeout_sec,
                                                                      finished.stopped)
        elif finished.status == "cancelled":
            exit_code, status = CANCELLED_EXIT_CODE, "cancelled"
            text = ((text + "\n") if text else "") + _tree_stopped_note("command cancelled", None,
                                                                      finished.stopped)
        else:
            exit_code = finished.returncode
            status = "ok" if exit_code == 0 else "failed"
            if finished.left_behind:
                # 命令自己退出了，它留下的子进程随这次调用一起结束：要长期运行的服务用 background（工单 #1215）
                text = ((text + "\n") if text else "") + (
                    "the command left processes running; they were stopped with this call "
                    "(use background for a service that should keep running)")
        text = redact_text(text)
        meta = {"command": command, "exit_code": exit_code, "status": status,
                "snapshot_hash": snapshot.digest, "executor": "host"}

        workspace_error = None
        try:
            self.workspace.snapshot()
        except UnrepresentableWorkspace as exc:
            workspace_error = {"message": str(exc), "paths": list(exc.paths)}

        if len(text) <= self._output_limit():
            return {**meta, "output": text, "truncated": False}, finished.status, workspace_error

        if self._jobs is None or self._session_id is None:
            raise RuntimeError("truncated output requires an environment with a session context")

        job_id = new_id("job")
        directory = self.workspace.root / CHECKS_DIR / _BASH_OUTPUT_SUBDIR
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{job_id}.output"
        path.write_text(text, encoding="utf-8")

        page, cut = _bash_slice(text, 0, self._output_limit())
        job = _Job(
            job_id=job_id,
            output_path=path,
            process=None,
            file_handle=None,
            status="exited",
            exit_code=exit_code,
            session_id=self._session_id,
            workspace_root=self.workspace.root,
        )
        job.read_offset = cut
        self._jobs.register(job)

        truncated_marker = (
            f"\n...output truncated at {self._output_limit()} chars; the full output is saved, "
            f"use read_output with job_id {job_id!r} to read the rest"
        )
        return {
            **meta,
            "job_id": job_id,
            "output": page + truncated_marker,
            "truncated": True,
        }, finished.status, workspace_error

    def _read_output(self, args: dict[str, Any]) -> dict[str, Any]:
        job_id = args.get("job_id")
        if not isinstance(job_id, str) or not job_id.strip():
            raise ValueError("job_id is required")
        if self._jobs is None or self._session_id is None:
            return {"job_id": job_id, "output": "", "status": "ended", "exit_code": None}
        return self._jobs.read_output(job_id, self._session_id)

    def _stop_job(self, args: dict[str, Any]) -> dict[str, Any]:
        job_id = args.get("job_id")
        if not isinstance(job_id, str) or not job_id.strip():
            raise ValueError("job_id is required")
        if self._jobs is None or self._session_id is None:
            return {"job_id": job_id, "output": f"job {job_id} has ended", "status": "ended", "exit_code": None}
        return self._jobs.stop_job(job_id, self._session_id)

    async def _run_check(self, action: Action, stop: asyncio.Event) -> tuple[dict[str, Any], str]:
        args = action.input
        name = str(args.get("name") or "").strip()
        if not name:
            raise ValueError("check name is required")
        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("run_check requires a non-empty command string; argv is not accepted")
        timeout_sec = args.get("timeout_sec")
        if timeout_sec is None:
            timeout_sec = self._check_timeout_sec
        else:
            if type(timeout_sec) is not int or timeout_sec < 1:
                raise ValueError("timeout_sec must be a positive integer")
            timeout_sec = min(timeout_sec, self._limit("check_timeout_max_sec", _CHECK_TIMEOUT_MAX))
        # 模型自报 exit_code 不是证据：这里只读主机执行结果，从不读取该字段
        snapshot = self.workspace.snapshot()
        original_digest = snapshot.digest
        with self.workspace.check_copy(snapshot.tree) as copy_root:
            if action.department == "quality":
                qa_source = self.workspace.root / QA_TESTS_DIR
                if qa_source.exists():
                    shutil.copytree(qa_source, copy_root / QA_TESTS_DIR, dirs_exist_ok=True)
            finished = await _run_process(
                [_resolve_bash(), "-c", command], copy_root,
                {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                timeout_sec, stop,
            )
            if finished.status == "completed":
                exit_code = finished.returncode
                output = _summarize_output(finished.stdout, finished.stderr, self._output_limit())
            else:
                if finished.status == "timeout":
                    exit_code, output = TIMEOUT_EXIT_CODE, f"check timed out after {timeout_sec}s"
                else:
                    exit_code, output = CANCELLED_EXIT_CODE, "check cancelled; the process tree was stopped"
                if finished.stdout:
                    output += "\n" + finished.stdout
                if finished.stderr:
                    output += "\n" + finished.stderr
            snapshot_hash = original_digest
            verification_errors = []
            # A process result remains evidence even when its tested bytes cannot be verified.
            # 两处读取都按项目的忽略规则取得公开树；说明文字只出现标签，主机路径不进入模型可见的回执
            for label, root in (("tested tree", copy_root), ("source workspace", self.workspace.root)):
                try:
                    observed_digest = capture_public_tree(root, True).digest
                    if label == "tested tree":
                        snapshot_hash = observed_digest
                    if observed_digest != original_digest:
                        verification_errors.append(f"{label} changed")
                except Exception as exc:
                    verification_errors.append(f"{label} could not be verified: {exc}")
            tree_changed = bool(verification_errors)
            if tree_changed:
                output = (output + "\n" if output else "") + "; ".join(verification_errors)
                output += "; pass is not bound to the original snapshot"
            summary = redact_text(
                f"host-executed command={command} exit={exit_code}\n{output}".strip()
            )
            qa_tests_hash = None
            if action.department == "quality":
                qa_tests_hash = qa_tests_digest(self.capture_qa_tests())
            receipt = self.workspace.record_check(
                action.department,
                name,
                exit_code,
                summary,
                snapshot_hash=snapshot_hash,
                tree_changed=tree_changed,
                qa_tests_hash=qa_tests_hash,
            )
            return {
                "name": receipt.name,
                "exit_code": receipt.exit_code,
                "summary": receipt.summary,
                "snapshot_hash": receipt.snapshot_hash,
                "executor": "host",
                "tree_changed": receipt.tree_changed,
                "activation_id": receipt.activation_id,
                "product_spec_hash": receipt.product_spec_hash,
                "delivery_spec_hash": receipt.delivery_spec_hash,
                "effective_contract_hash": receipt.effective_contract_hash,
                "qa_tests_hash": receipt.qa_tests_hash,
            }, finished.status


async def _run_process(argv: list[str], cwd: Path, env: dict[str, str], timeout_sec: float,
                       stop: asyncio.Event) -> _Finished:
    # 命令在整棵进程树里启动（Windows 作业对象、POSIX 新会话的进程组，见 process_tree.py）：
    # 超时、取消与命令自己结束以后都一次结束整棵树，包括「直接子进程已经退出、它起的子进程还在」
    # 这一种。回执的返回不依赖输出管道关闭（工单 #1215）：命令留下的后台进程手里那根写端可能一直
    # 开着，读完输出不能等它关；直接子进程退出以后输出只再收这么久，到点就带已有输出返回。
    # 标准输入接空设备：bash 调用与检查都不读输入，若继承服务进程的标准输入（一根打开但无人写入的
    # 管道），解释器启动时对该句柄取状态会一直等待
    tree = ProcessTree()
    process = await asyncio.create_subprocess_exec(
        *argv, cwd=str(cwd), env=env, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, **spawn_options(),
    )
    try:
        tree.attach(process.pid)
    except BaseException:
        # 放不进容器也放不出去的时候不让挂起的子进程留在机器上
        tree.stop()
        tree.close()
        raise
    out: bytearray = bytearray()
    err: bytearray = bytearray()
    readers = [asyncio.ensure_future(_collect_output(process.stdout, out)),
               asyncio.ensure_future(_collect_output(process.stderr, err))]
    left_behind = False
    stopped = False
    try:
        status = await _wait_for_end(process, stop, timeout_sec)
        left_behind = status == "completed" and tree.has_live_processes()
        tree.stop()
        stopped = await _wait_tree_stopped(tree, STOP_LIMIT_SEC)
        await _finish_readers(readers, _OUTPUT_DRAIN_SEC, process)
    finally:
        tree.close()
    return _Finished(status, process.returncode, _text(bytes(out)), _text(bytes(err)),
                     stopped=stopped, left_behind=left_behind)


# 直接子进程退出以后等输出收尾的上限（秒）
_OUTPUT_DRAIN_SEC = 3.0
# 等直接子进程退出的轮询间隔（秒）；取消与时限仍按事件到达的时刻生效
_EXIT_POLL_SEC = 0.05


async def _wait_tree_stopped(tree: ProcessTree, limit: float) -> bool:
    # 等整棵树真正停下，最多等 limit 秒；到点还没停就交回 False，回执里如实写。
    # 这一条不占住事件循环（同时还有别的会话在跑）
    loop = asyncio.get_running_loop()
    deadline = loop.time() + limit
    while True:
        if tree.stopped():
            return True
        if loop.time() >= deadline:
            return False
        await asyncio.sleep(_EXIT_POLL_SEC)


async def _collect_output(stream: asyncio.StreamReader | None, sink: bytearray) -> None:
    # 读自己这一端的输出，读到管道关闭为止
    if stream is None:
        return
    while True:
        chunk = await stream.read(65536)
        if not chunk:
            return
        sink.extend(chunk)


async def _wait_for_end(process: asyncio.subprocess.Process, stop: asyncio.Event,
                        timeout_sec: float) -> str:
    # 直接子进程退出、时限到点、停止信号到达三者先到的是哪一个。
    # 不 await process.wait()：它要等输出管道一起关闭才返回，命令留下的后台进程还开着管道时等不到
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_sec
    stopper = asyncio.ensure_future(stop.wait())
    try:
        while True:
            if process.returncode is not None:
                return "completed"
            remaining = deadline - loop.time()
            if remaining <= 0:
                return "timeout"
            await asyncio.wait({stopper}, timeout=min(_EXIT_POLL_SEC, remaining))
            if stopper.done() and process.returncode is None:
                return "cancelled"
    finally:
        stopper.cancel()


async def _finish_readers(readers: list[asyncio.Future[Any]], limit: float,
                          process: asyncio.subprocess.Process) -> None:
    # 整棵树停下以后输出应该很快就读完；等不到就关掉自己这一端，带着已经收到的输出返回
    pending = [reader for reader in readers if not reader.done()]
    if not pending:
        return
    _done, still = await asyncio.wait(pending, timeout=limit)
    for reader in still:
        reader.cancel()
    if still:
        await asyncio.gather(*still, return_exceptions=True)
        _close_read_side(process)


def _close_read_side(process: asyncio.subprocess.Process) -> None:
    # 关掉自己这一端的读管道：有进程逃出了容器、一直开着写端时，调用不能跟着它一起挂着
    transport = getattr(process, "_transport", None)
    getter = getattr(transport, "get_pipe_transport", None)
    if getter is None:
        return
    for fd in (1, 2):
        pipe = getter(fd)
        if pipe is not None:
            try:
                pipe.close()
            except Exception:
                pass


def _tree_stopped_note(headline: str, timeout_sec: float | None, stopped: bool) -> str:
    # 超时与取消的说明：整棵树确实停了才写「已停止」；确实杀不掉时写明，不把「已停止」当结论写出去
    lead = headline if timeout_sec is None else f"{headline} after {timeout_sec}s"
    if stopped:
        return f"{lead}; the process tree was stopped"
    return f"{lead}; some processes from the command could not be stopped"


def _text(raw: bytes) -> str:
    # 与文本方式读取子进程输出相同：UTF-8 解码（无法解码的字节换成替换字符），换行统一为 \n
    return io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8", errors="replace", newline=None).read()


def qa_tests_digest(tree: CapturedTree | None) -> str | None:
    if tree is not None and (tree.files or tree.directories):
        return tree.digest
    return None

def _require_reason(args: dict[str, Any]) -> None:
    reason = args.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("a non-empty reason is required for deleting or moving files")


def _summarize_output(stdout: str, stderr: str, limit: int = _OUTPUT_LIMIT) -> str:
    text = "\n".join(part for part in (stdout.strip(), stderr.strip()) if part)
    if len(text) > limit:
        text = text[:limit] + "\n...truncated..."
    return text


def _page_size(value: Any) -> int:
    if value is None:
        return SEARCH_DEFAULT_PAGE
    if type(value) is not int or value < 1:
        raise ValueError("max_results must be an integer >= 1")
    return value


def _clip_snippet(line: str) -> str:
    if len(line) > SEARCH_SNIPPET_LIMIT:
        return line[:SEARCH_SNIPPET_LIMIT] + "\n...truncated..."
    return line


def _encode_cursor(payload: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json_dumps(payload).encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str, *, kind: str) -> dict[str, Any]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"invalid cursor: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("kind") != kind or type(payload.get("offset")) is not int:
        raise ValueError("invalid cursor")
    return payload


def _result_size(result: dict[str, Any]) -> int:
    return len(json_dumps(result))


def _fit_match_page(page: list[dict[str, Any]], truncated: bool,
                    limit: int = _OUTPUT_LIMIT) -> tuple[list[dict[str, Any]], bool]:
    # 按输出上限 limit 收缩本页，挤出去的命中留给下一页游标，不丢弃也不合并
    probe = {"matches": page}
    while len(page) > 1 and _result_size({**probe, "truncated": True}) > limit:
        page = page[:-1]
        truncated = True
    if len(page) == 1 and _result_size({"matches": page, "truncated": True}) > limit:
        only = dict(page[0])
        snippet = only["snippet"]
        while len(snippet) > 1 and _result_size({"matches": [{**only, "snippet": snippet}], "truncated": True}) > limit:
            snippet = snippet[:len(snippet) // 2]
        only["snippet"] = snippet + "\n...truncated..."
        page = [only]
        truncated = True
    return page, truncated


def _fit_line_entries(wanted: list[tuple[int, str]],
                      limit: int = _OUTPUT_LIMIT) -> tuple[list[dict[str, Any]], int]:
    # 逐行累加直到输出上限；单行超限则截断该行文本，保证每页至少返回一行或空
    entries: list[dict[str, Any]] = []
    for number, text in wanted:
        candidate = entries + [{"line": number, "text": text}]
        if _result_size({"lines": candidate, "truncated": True}) > limit:
            break
        entries = candidate
    if not entries and wanted:
        number, text = wanted[0]
        clipped = text
        while len(clipped) > 1 and _result_size({"lines": [{"line": number, "text": clipped}], "truncated": True}) > limit:
            clipped = clipped[:len(clipped) // 2]
        entries = [{"line": number, "text": clipped + "\n...truncated..."}]
        return entries, 1
    return entries, len(entries)
