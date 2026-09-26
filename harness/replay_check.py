# 重放核对：从头重放的运行状态投影必须与保存的投影相同，并核对保存的交付封存与 Git 历史。
# 核对失败时抛出 ReplayIntegrityError，reason 区分投影、交付封存与 Git 历史。

from __future__ import annotations

from .artifacts import ArtifactStore
from .event_store import EventStore
from .git_audit import verify_git_history
from .git_versions import GitVersionStore
from .models import GIT_VERSION_EVENTS, DeliverySpec, RunProjection
from .projection import project_run, replay_run
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
    # 重放 run 的全部事件，与保存的投影比较，再核对交付封存与 Git 历史；返回重放得到的投影
    first = replay_run(store, run_id)
    if first.to_dict() != project_run(store, run_id).to_dict():
        raise ReplayIntegrityError("the saved projection differs from the replayed projection",
                                   reason=PROJECTION_REASON)
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
