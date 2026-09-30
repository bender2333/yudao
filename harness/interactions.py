# 保存用户的输入、部门指导与部门提示词：工件、原始意图材料与 Git 版本在这里写好，事件在调用方的事务中追加；
# 不分派部门的工作。

from __future__ import annotations

from dataclasses import asdict
import os
from pathlib import Path
import tempfile
import threading
from typing import Any

from .artifacts import ArtifactStore
from .definitions import DEFINITIONS
from .department_prompts import save_department_prompt
from .event_store import EventStore
from .projection import project_run
from .write_path import NewEvent, Transaction
from .git_versions import GitVersionStore
from .materials import append_intend
from .models import ArtifactRef, DEPARTMENTS, Event, EventType, new_id


class RunTerminalError(ValueError):
    """A completed or stopped run cannot receive new work."""


class CancelledInputSaveError(RuntimeError):
    def __init__(self, run_id: str, *, cancellation_recorded: bool) -> None:
        super().__init__("Execution was cancelled, but the command's input version could not be saved.")
        self.run_id = run_id
        self.cancelled = True
        self.cancellation_recorded = cancellation_recorded


class InteractionWriter:
    def __init__(self, store: EventStore, artifacts: ArtifactStore, materials_root: Path,
                 git_versions: GitVersionStore) -> None:
        self.store, self.artifacts, self.materials_root = store, artifacts, materials_root
        self.git_versions = git_versions
        # 原始意图材料的发布依次进行：「读取已经提交的原始意图、写出文件」之间不插入另一次发布
        self._publication = threading.Lock()

    def initial(self, run_id: str, text: str, *, department_prompts: dict[str, str] | None = None) -> dict[str, Any]:
        # 写入首个输入与各部门的初始 Prompt：内置默认 Prompt 取自定义，项目层用项目部门设置替代
        received = self._input(run_id, text, version=1, kind="text", previous_ref=None, parent_commit=None)
        prompt_texts = ({department: DEFINITIONS.role(department).prompt for department in DEPARTMENTS}
                        if department_prompts is None else department_prompts)
        prompts = {department: self._prompt(run_id, department, text, 1)
                   for department, text in prompt_texts.items()}
        return {"initial_input": received, "department_prompts": prompts,
                "intend_ref": received["intend_ref"], "git_version": received["git_version"]}

    def receive(self, transaction: Transaction, text: str, *, command: bool,
                base_version: int | None = None) -> Event:
        # 保存输入的原文：更新并发布原始意图，在事务中追加 user_input_received。
        # 事务提交或没有提交以后，都按已经提交的运行状态重新发布原始意图：同时到达的几次输入各自发布了
        # 没有提交的内容，最后一次发布总是已经提交的内容
        projection = transaction.projection
        run_id = projection.run_id
        payload = self._input(run_id, text, version=projection.input_version + 1,
                              kind="command" if command else "text",
                              previous_ref=ArtifactRef(**projection.intend_ref),
                              parent_commit=projection.git_version["commit"], base_version=base_version)
        transaction.on_abort(lambda: self._publish_committed(run_id))
        transaction.on_commit(lambda: self._publish_committed(run_id))
        return transaction.append(NewEvent(
            EventType.USER_INPUT_RECEIVED, actor="user:local",
            state_before=projection.phase, state_after=projection.phase, payload=payload,
            artifact_hashes=[payload["input_ref"]["content_hash"], payload["intend_ref"]["content_hash"]],
        ))[0]

    def update_prompt(self, transaction: Transaction, department: str, text: str) -> Event:
        projection = transaction.projection
        payload = self._prompt(projection.run_id, department, text,
                               projection.department_prompts[department].version + 1)
        return transaction.append(NewEvent(
            EventType.DEPARTMENT_PROMPT_UPDATED, actor="user:local", department=department,
            state_before=projection.phase, state_after=projection.phase, payload=payload,
            artifact_hashes=[payload["prompt_ref"]["content_hash"]],
        ))[0]

    def receive_guidance(self, transaction: Transaction, department: str, text: str, *,
                         base_version: int | None = None) -> Event:
        if department not in DEPARTMENTS:
            raise ValueError("unknown department")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("guidance must be a non-empty string")
        projection = transaction.projection
        previous = [item.version for item in projection.department_guidance if item.department == department]
        version = max(previous, default=0) + 1
        ref = self.artifacts.put(projection.run_id, "department_guidance", text, media_type="text/plain")
        payload = {
            "id": new_id("guidance"),
            "department": department,
            "version": version,
            "text": text,
            "guidance_ref": asdict(ref),
            "status": "received",
        }
        if base_version is not None:
            payload["base_version"] = base_version
        return transaction.append(NewEvent(
            EventType.DEPARTMENT_GUIDANCE_RECEIVED,
            actor="user:local",
            department=department,
            state_before=projection.phase,
            state_after=projection.phase,
            payload=payload,
            artifact_hashes=[ref.content_hash],
        ))[0]

    def _input(self, run_id: str, text: str, *, version: int, kind: str,
               previous_ref: ArtifactRef | None, parent_commit: str | None,
               base_version: int | None = None) -> dict[str, Any]:
        material = append_intend(self.artifacts, run_id, text, previous_ref=previous_ref)
        original = self.artifacts.get_for_run(run_id, material.intend_ref)
        revision = self.git_versions.prepare(
            run_id, parent_commit=parent_commit, updates={"intend.md": original},
            message=f"Receive user input v{version}",
        )
        self._publish(run_id, original)
        payload = {"id": new_id("input"), "version": version, "text": text, "kind": kind,
                   "input_ref": asdict(material.input_ref), "intend_ref": asdict(material.intend_ref),
                   "byte_start": material.byte_start, "byte_end": material.byte_end, "git_version": revision}
        if base_version is not None:
            payload["base_version"] = base_version
        return payload

    def _publish(self, run_id: str, original: bytes) -> None:
        with self._publication:
            self._write_intend(run_id, original)

    def _publish_committed(self, run_id: str) -> None:
        # 发布已经提交的运行状态中的原始意图
        with self._publication:
            ref = ArtifactRef(**project_run(self.store, run_id).intend_ref)
            self._write_intend(run_id, self.artifacts.get_for_run(run_id, ref))

    def _write_intend(self, run_id: str, original: bytes) -> None:
        folder = (self.materials_root / run_id).resolve()
        if folder == self.materials_root.resolve() or not folder.is_relative_to(self.materials_root.resolve()):
            raise ValueError("run_id must stay within the run materials directory")
        folder.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=folder, prefix=".intend-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(original)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, folder / "intend.md")
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _prompt(self, run_id: str, department: str, text: str, version: int) -> dict[str, Any]:
        ref = save_department_prompt(self.artifacts, run_id, department, text)
        return {"department": department, "version": version, "text": text, "prompt_ref": asdict(ref)}
