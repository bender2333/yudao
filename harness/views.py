"""只读视图：压缩记录与它覆盖的事件范围。"""

from __future__ import annotations

from typing import Any

def compaction_coverage(item: Any) -> dict[str, Any] | None:
    """Return seq / covered_through range for a compaction record or event."""

    if item is None:
        return None
    payload = getattr(item, "payload", None)
    if not isinstance(payload, dict):
        payload = item if isinstance(item, dict) else None
    if not isinstance(payload, dict):
        return None
    body = payload
    checkpoint = body.get("checkpoint") if isinstance(body.get("checkpoint"), dict) else {}
    refs = body.get("source_refs") if isinstance(body.get("source_refs"), list) else []
    seqs = [entry.get("seq") for entry in refs if isinstance(entry, dict) and type(entry.get("seq")) is int]
    event_ids = [entry.get("event_id") for entry in refs if isinstance(entry, dict) and entry.get("event_id")]
    event_id = getattr(item, "event_id", None) or body.get("source_event_id") or body.get("event_id") or body.get("compaction_event_id")
    covered_id = checkpoint.get("covered_through_event_id")
    covered_seq = next(
        (entry.get("seq") for entry in refs
         if isinstance(entry, dict) and entry.get("event_id") == covered_id and type(entry.get("seq")) is int),
        None,
    )
    if event_id is None and covered_id is None and not seqs:
        return None
    return {
        "compaction_event_id": event_id,
        "covered_through_event_id": covered_id,
        "covered_through_seq": covered_seq,
        "source_seq_from": min(seqs) if seqs else None,
        "source_seq_through": max(seqs) if seqs else None,
        "source_event_ids": event_ids,
    }
