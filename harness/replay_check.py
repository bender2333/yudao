"""Replay integrity: projection determinism plus persisted delivery-tree and Git checks.

A replay must fail closed. Rebuilding the same canonical state twice only proves
the projection is deterministic; it says nothing about whether the persisted
delivery blobs or the Git history survived. This module verifies every delivery
archive referenced by the projection with ``load_tree`` and replays the accepted
Git history with ``verify_git_history``. Any failure raises
``ReplayIntegrityError`` with a ``reason`` that distinguishes tree damage from
Git damage.
"""

from __future__ import annotations

from .artifacts import ArtifactStore
from .event_store import EventStore
from .git_audit import verify_git_history
from .git_versions import GitVersionStore
from .models import GIT_VERSION_EVENTS, DeliverySpec, RunProjection
from .projection import project_run
from .tree_archive import load_tree


TREE_REASON = "tree_archive"
GIT_REASON = "git_history"
PROJECTION_REASON = "projection"


class ReplayIntegrityError(ValueError):
    """A replay failed its fail-closed integrity checks."""

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


def verify_replay(
    store: EventStore,
    artifacts: ArtifactStore,
    versions: GitVersionStore,
    run_id: str,
) -> RunProjection:
    """Rebuild a run projection and verify its persisted delivery tree and Git history."""
    first = project_run(store, run_id)
    second = project_run(store, run_id)
    if first.canonical_state() != second.canonical_state():
        raise ReplayIntegrityError("replay projection is not deterministic", reason=PROJECTION_REASON)
    for delivery in first.delivery_specs:
        _verify_delivery_tree(artifacts, run_id, delivery)
    events = store.list_events(run_id)
    if any(event.type in GIT_VERSION_EVENTS for event in events):
        try:
            verify_git_history(versions, artifacts, events)
        except Exception as exc:
            raise ReplayIntegrityError(
                f"replay git history check failed: {exc}", reason=GIT_REASON
            ) from exc
    return first


def _verify_delivery_tree(artifacts: ArtifactStore, run_id: str, delivery: DeliverySpec) -> None:
    try:
        tree = load_tree(artifacts, run_id, delivery.tree_ref)
    except Exception as exc:
        raise ReplayIntegrityError(
            f"replay tree archive check failed for delivery {delivery.id}: {exc}",
            reason=TREE_REASON,
        ) from exc
    if tree.digest != delivery.code_tree_digest:
        raise ReplayIntegrityError(
            f"replay tree archive check failed for delivery {delivery.id}: "
            "archived tree digest does not match its accepted delivery",
            reason=TREE_REASON,
        )
