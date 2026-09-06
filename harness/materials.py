"""Persist verbatim inputs and cumulative intend snapshots without runtime state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .artifacts import ArtifactStore
from .models import ArtifactRef


@dataclass(frozen=True)
class IntendMaterial:
    input_ref: ArtifactRef
    intend_ref: ArtifactRef
    byte_start: int
    byte_end: int


def append_intend(artifacts: ArtifactStore, run_id: str, text: str, *,
                  previous_ref: ArtifactRef | None = None) -> IntendMaterial:
    raw = _text_bytes(text)
    _validate_run_id(run_id)
    previous = b""
    if previous_ref is not None:
        if not isinstance(previous_ref, ArtifactRef) or previous_ref.kind != "intend":
            raise ValueError("previous input snapshot must be an intend artifact")
        previous = artifacts.get_for_run(run_id, previous_ref)
        previous.decode("utf-8")
    input_ref = _store_bytes(artifacts, run_id, "user_input", raw)
    intend_ref = _store_bytes(artifacts, run_id, "intend", previous + raw)
    return IntendMaterial(input_ref, intend_ref, len(previous), len(previous) + len(raw))


def save_text_material(artifacts: ArtifactStore, run_id: str, kind: str, text: str) -> ArtifactRef:
    raw = _text_bytes(text)
    _validate_run_id(run_id)
    return _store_bytes(artifacts, run_id, kind, raw)


def _store_bytes(artifacts: ArtifactStore, run_id: str, kind: str, raw: bytes) -> ArtifactRef:
    ref = artifacts.put(run_id, kind, raw, media_type="text/plain; charset=utf-8")
    if artifacts.get_for_run(run_id, ref) != raw:
        raise ValueError("stored material differs from its original bytes")
    return ref


def _text_bytes(text: str) -> bytes:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("material text must be a non-empty string")
    return text.encode("utf-8")


def _validate_run_id(run_id: str) -> None:
    if (not isinstance(run_id, str) or run_id in {"", ".", ".."}
            or "/" in run_id or "\\" in run_id or Path(run_id).name != run_id):
        raise ValueError("invalid material run id")
