"""Batch statistics over L1-verified evidence packs. Never executes deliveries."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .pack import load_evidence_pack
from .records import MANIFEST_NAME, EvidenceError


@dataclass(frozen=True)
class SubmissionRow:
    path: Path
    readable: bool
    verified: bool
    duplicate: bool
    material_id: str | None = None
    review_id: str | None = None
    source: str | None = None
    content_digest: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class BatchReport:
    submissions: tuple[SubmissionRow, ...]
    submission_count: int
    valid_count: int
    duplicate_count: int
    damaged_count: int
    missing_count: int
    unique_review_count: int
    unique_material_count: int


def analyze_batch(paths: Sequence[str | Path]) -> BatchReport:
    """Keep a submission row for every input, then count unique verified reviews."""
    if isinstance(paths, (str, Path)):
        raise TypeError("analyze_batch expects a sequence of pack paths")

    rows: list[SubmissionRow] = []
    seen_reviews: set[str] = set()
    unique_materials: set[str] = set()
    valid = duplicate = damaged = missing = 0

    for raw in paths:
        path = Path(raw)
        if not path.exists():
            missing += 1
            rows.append(SubmissionRow(path=path, readable=False, verified=False, duplicate=False, error="missing"))
            continue
        try:
            pack = load_evidence_pack(path)
        except EvidenceError as exc:
            damaged += 1
            material_id, review_id, source = _declared_identity(path)
            rows.append(
                SubmissionRow(
                    path=path,
                    readable=True,
                    verified=False,
                    duplicate=False,
                    material_id=material_id,
                    review_id=review_id,
                    source=source,
                    error=str(exc),
                )
            )
            continue
        valid += 1
        is_duplicate = pack.review.id in seen_reviews
        if is_duplicate:
            duplicate += 1
        else:
            seen_reviews.add(pack.review.id)
            unique_materials.add(pack.material.id)
        rows.append(
            SubmissionRow(
                path=path,
                readable=True,
                verified=True,
                duplicate=is_duplicate,
                material_id=pack.material.id,
                review_id=pack.review.id,
                source=pack.material.source,
                content_digest=pack.content_digest,
            )
        )

    return BatchReport(
        submissions=tuple(rows),
        submission_count=len(rows),
        valid_count=valid,
        duplicate_count=duplicate,
        damaged_count=damaged,
        missing_count=missing,
        unique_review_count=len(seen_reviews),
        unique_material_count=len(unique_materials),
    )


def _declared_identity(path: Path) -> tuple[str | None, str | None, str | None]:
    """Unverified labels from a readable manifest. Never treated as a verified pack."""
    manifest = path / MANIFEST_NAME
    if not manifest.is_file():
        return None, None, None
    try:
        payload = json.loads(manifest.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, None, None
    if not isinstance(payload, dict):
        return None, None, None
    material = payload.get("material")
    review = payload.get("review")
    material_id = material.get("id") if isinstance(material, dict) else None
    source = material.get("source") if isinstance(material, dict) else None
    review_id = review.get("id") if isinstance(review, dict) else None
    return (
        material_id if isinstance(material_id, str) else None,
        review_id if isinstance(review_id, str) else None,
        source if isinstance(source, str) else None,
    )
