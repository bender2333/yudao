"""Persist user inputs and department prompts without routing department work."""

from __future__ import annotations

from dataclasses import asdict
import os
from pathlib import Path
import tempfile
from typing import Any

from .artifacts import ArtifactStore
from .department_prompts import DEFAULT_PROMPTS, save_department_prompt
from .write_path import NewEvent, WritePath
from .git_versions import GitVersionStore
from .materials import append_intend
from .models import ArtifactRef, DEPARTMENTS, Event, EventType, RunProjection, new_id


class RunTerminalError(ValueError):
    """A completed or stopped run cannot receive new work."""


class CancelledInputSaveError(RuntimeError):
    def __init__(self, run_id: str, *, cancellation_recorded: bool) -> None:
        super().__init__("Execution was cancelled, but the command's input version could not be saved.")
        self.run_id = run_id
        self.cancelled = True
        self.cancellation_recorded = cancellation_recorded


class InteractionWriter:
    def __init__(self, writes: WritePath, artifacts: ArtifactStore, materials_root: Path,
                 git_versions: GitVersionStore) -> None:
        self.writes, self.artifacts, self.materials_root = writes, artifacts, materials_root
        self.git_versions = git_versions

    def initial(self, run_id: str, text: str, *, department_prompts: dict[str, str] | None = None) -> dict[str, Any]:
        """写入首个输入与三部门初始 Prompt；项目层可用项目配置替代默认 Prompt。"""
        received = self._input(run_id, text, version=1, kind="text", previous_ref=None, parent_commit=None)
        prompt_texts = DEFAULT_PROMPTS if department_prompts is None else department_prompts
        prompts = {department: self._prompt(run_id, department, text, 1)
                   for department, text in prompt_texts.items()}
        return {"initial_input": received, "department_prompts": prompts,
                "intend_ref": received["intend_ref"], "git_version": received["git_version"]}

    def receive(self, projection: RunProjection, text: str, *, command: bool) -> Event:
        payload = self._input(projection.run_id, text, version=projection.input_version + 1,
                              kind="command" if command else "text",
                              previous_ref=ArtifactRef(**projection.intend_ref),
                              parent_commit=projection.git_version["commit"])
        try:
            return self.writes.append(projection.run_id, NewEvent(
                EventType.USER_INPUT_RECEIVED, role="user",
                state_before=projection.phase, state_after=projection.phase, payload=payload,
                artifact_hashes=[payload["input_ref"]["content_hash"], payload["intend_ref"]["content_hash"]],
            ))[0]
        except Exception:
            self._publish(projection.run_id, self.artifacts.get_for_run(
                projection.run_id, ArtifactRef(**projection.intend_ref)))
            raise

    def update_prompt(self, projection: RunProjection, department: str, text: str) -> Event:
        payload = self._prompt(projection.run_id, department, text,
                               projection.department_prompts[department].version + 1)
        return self.writes.append(projection.run_id, NewEvent(
            EventType.DEPARTMENT_PROMPT_UPDATED, role="user",
            state_before=projection.phase, state_after=projection.phase, payload=payload,
            artifact_hashes=[payload["prompt_ref"]["content_hash"]],
        ))[0]

    def receive_guidance(self, projection: RunProjection, department: str, text: str) -> Event:
        if department not in DEPARTMENTS:
            raise ValueError("unknown department")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("guidance must be a non-empty string")
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
        return self.writes.append(projection.run_id, NewEvent(
            EventType.DEPARTMENT_GUIDANCE_RECEIVED,
            role="user",
            state_before=projection.phase,
            state_after=projection.phase,
            payload=payload,
            artifact_hashes=[ref.content_hash],
        ))[0]

    def _input(self, run_id: str, text: str, *, version: int, kind: str,
               previous_ref: ArtifactRef | None, parent_commit: str | None) -> dict[str, Any]:
        material = append_intend(self.artifacts, run_id, text, previous_ref=previous_ref)
        original = self.artifacts.get_for_run(run_id, material.intend_ref)
        revision = self.git_versions.prepare(
            run_id, parent_commit=parent_commit, updates={"intend.md": original},
            message=f"Receive user input v{version}",
        )
        self._publish(run_id, original)
        return {"id": new_id("input"), "version": version, "text": text, "kind": kind,
                "input_ref": asdict(material.input_ref), "intend_ref": asdict(material.intend_ref),
                "byte_start": material.byte_start, "byte_end": material.byte_end, "git_version": revision}

    def _publish(self, run_id: str, original: bytes) -> None:
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
