"""Verify immutable Git versions against their accepted event materials."""

from __future__ import annotations

from dataclasses import asdict
import json
from typing import Any, Iterator

from .artifacts import ArtifactStore
from .git_versions import GitVersionStore
from .models import ArtifactRef, Event, EventType, GIT_VERSION_EVENTS, RunProjection
from .projection import apply_event
from .tree_archive import load_tree


class GitBindingError(ValueError):
    """A Git snapshot does not reproduce its formally accepted materials."""


def git_version_detail(versions: GitVersionStore, artifacts: ArtifactStore,
                       events: list[Event], event: Event) -> dict[str, Any]:
    accepted = next((item for item in events if item.event_id == event.event_id), None)
    if accepted != event or event.type not in GIT_VERSION_EVENTS:
        raise GitBindingError("Git version is not bound to this accepted event")
    previous = None
    for group, revision, files in _expected_versions(artifacts, events):
        if any(item.event_id == event.event_id for item in group):
            if previous is not None:
                parent_revision, parent_files = previous
                _verify_files(versions, event.run_id, parent_revision, parent_files)
            _verify_files(versions, event.run_id, revision, files)
            return versions.show(event.run_id, revision)
        previous = revision, files
    raise GitBindingError("Accepted event has no verifiable Git version")


def verify_git_history(versions: GitVersionStore, artifacts: ArtifactStore,
                       events: list[Event]) -> list[dict[str, Any]]:
    history = []
    for group, revision, files in _expected_versions(artifacts, events):
        _verify_files(versions, group[0].run_id, revision, files)
        history.append({**revision, "event_ids": [item.event_id for item in group]})
    if not history:
        raise GitBindingError("No accepted Git versions were recorded")
    return history


def _verify_files(versions: GitVersionStore, run_id: str, revision: dict[str, Any],
                  files: dict[str, bytes]) -> None:
    if versions.read_files(run_id, revision) != files:
        raise GitBindingError("Git files differ from the accepted event materials")


def _expected_versions(artifacts: ArtifactStore, events: list[Event]) -> Iterator[
    tuple[list[Event], dict[str, Any], dict[str, bytes]]
]:
    current = RunProjection()
    expected: dict[str, bytes] = {}
    revision = None
    group: list[Event] = []
    seen = set()
    try:
        for event in events:
            if current.run_id and event.run_id != current.run_id or event.seq <= current.last_seq:
                raise GitBindingError("Git history must follow one run's event order")
            candidate = event.payload.get("git_version")
            if event.type in GIT_VERSION_EVENTS:
                if not isinstance(candidate, dict) or set(candidate) != {"commit", "parent_commit", "tree"}:
                    raise GitBindingError("Accepted event has no complete Git version reference")
                if revision is None or candidate["commit"] != revision["commit"]:
                    if revision is not None:
                        _validate_group(group)
                        yield group, revision, dict(expected)
                    parent = None if revision is None else revision["commit"]
                    if candidate["commit"] in seen or candidate["parent_commit"] != parent:
                        raise GitBindingError("Git parent does not match the preceding accepted version")
                    seen.add(candidate["commit"])
                    revision, group = candidate, []
                elif candidate != revision:
                    raise GitBindingError("Events sharing a Git commit disagree on its reference")
                group.append(event)
            elif candidate is not None:
                raise GitBindingError("Git version is attached to an event that does not accept materials")
            apply_event(current, event)
            if event.type in GIT_VERSION_EVENTS:
                _apply_materials(expected, artifacts, current, event)
        if revision is not None:
            _validate_group(group)
            yield group, revision, dict(expected)
    except GitBindingError:
        raise
    except (KeyError, TypeError, AttributeError, OSError, ValueError) as exc:
        raise GitBindingError("Accepted Git materials could not be verified") from exc


def _validate_group(group: list[Event]) -> None:
    types = [item.type for item in group]
    if types in ([EventType.SPEC_ACCEPTED, EventType.CONTRACT_ACCEPTED],
                 [EventType.PRODUCT_DECISION_ACCEPTED, EventType.CONTRACT_ACCEPTED]):
        return
    if len(types) != 1 or types[0] in {
        EventType.SPEC_ACCEPTED, EventType.PRODUCT_DECISION_ACCEPTED, EventType.CONTRACT_ACCEPTED,
    }:
        raise GitBindingError("Git commit does not match one atomic material acceptance")


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _apply_materials(files: dict[str, bytes], artifacts: ArtifactStore,
                     current: RunProjection, event: Event) -> None:
    payload = {key: value for key, value in event.payload.items() if key != "git_version"}
    run_id, kind = event.run_id, event.type
    if kind in {EventType.RUN_CREATED, EventType.USER_INPUT_RECEIVED}:
        item = payload["initial_input"] if kind == EventType.RUN_CREATED else payload
        text = item["text"].encode("utf-8")
        original = artifacts.get_for_run(run_id, ArtifactRef(**item["intend_ref"]))
        if (original != files.get("intend.md", b"") + text
                or artifacts.get_for_run(run_id, ArtifactRef(**item["input_ref"])) != text):
            raise GitBindingError("Git intend source differs from the received original input")
        files["intend.md"] = original
    elif kind == EventType.SPEC_ACCEPTED:
        files["specs/product.json"] = _json_bytes(payload)
    elif kind == EventType.PLAN_ACCEPTED:
        files["specs/plan.json"] = _json_bytes(payload)
        files["PLAN.md"] = artifacts.get_for_run(run_id, ArtifactRef(**payload["plan_ref"]))
    elif kind == EventType.CONTRACT_ACCEPTED:
        decisions = [{key: value for key, value in asdict(item).items()
                      if key not in {"run_id", "created_event_id"}} for item in current.effective_decisions]
        files["specs/contract.json"] = _json_bytes({**payload, "decisions": decisions})
        files["PRD.md"] = artifacts.get_for_run(run_id, ArtifactRef(**payload["prd_ref"]))
    elif kind == EventType.DELIVERY_ACCEPTED:
        tree = load_tree(artifacts, run_id, ArtifactRef(**payload["tree_ref"]))
        if tree.digest != payload["code_tree_digest"]:
            raise GitBindingError("Git code source differs from its accepted delivery")
        for path in list(files):
            if path.startswith("code/"):
                del files[path]
        files.update({"code/" + item.path: item.data for item in tree.files})
        files["specs/delivery.json"] = _json_bytes(payload)
        files["specs/delivery-tree.json"] = _json_bytes(tree.manifest)
    elif kind == EventType.QA_SUBMITTED:
        files["specs/qa.json"] = _json_bytes(payload)
