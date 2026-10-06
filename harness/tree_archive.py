"""Persist and verify complete public trees using the existing artifact store."""

from __future__ import annotations

import json
from typing import Any

from .artifacts import ArtifactStore
from .models import ArtifactRef, canonical_hash, json_dumps
from .public_tree import CapturedFile, CapturedTree, TreeError, validate_manifest, validate_public_path


ARCHIVE_FORMAT = "yudao-tree-archive-v1"


def artifact_run(path: str) -> str:
    # 工件引用所属的范围：工件按所属范围的目录存放。运行内的树属于那个 run（工单 #136），
    # 项目起始文件夹的快照属于项目（工单 #321）。读取时按 tree_ref.path 的第一段取得，不假设属于某个 run
    return str(path).split("/", 1)[0]


def store_tree(store: ArtifactStore, scope: str, tree: CapturedTree) -> ArtifactRef:
    """Store every original blob and publish the manifest only after read-back checks."""
    _validate_scope(scope)
    if not isinstance(tree, CapturedTree):
        raise TreeError("Archiving requires a fully captured tree")
    blobs = []
    for item in tree.files:
        ref = store.put(scope, "tree_file", item.data, media_type="application/octet-stream")
        if store.get_for_run(scope, ref) != item.data:
            raise TreeError(f"Stored tree file differs from its captured bytes: {item.path}")
        blobs.append({"path": item.path, "artifact": ref.__dict__})
    payload = {
        "format": ARCHIVE_FORMAT,
        "tree_digest": tree.digest,
        "tree": tree.manifest,
        "blobs": blobs,
    }
    raw = json_dumps(payload).encode("utf-8")
    ref = store.put(scope, "tree_manifest", raw, media_type="application/json")
    if store.get_for_run(scope, ref) != raw:
        raise TreeError("Stored tree manifest differs from its captured contents")
    if load_tree(store, scope, ref) != tree:
        raise TreeError("Stored tree did not pass complete read-back verification")
    return ref


def load_tree(store: ArtifactStore, scope: str, ref: ArtifactRef) -> CapturedTree:
    """Read only persisted artifacts; never consult or execute an old workspace."""
    _validate_scope(scope)
    if not isinstance(ref, ArtifactRef) or ref.kind != "tree_manifest" or ref.media_type != "application/json":
        raise TreeError("A tree archive requires its manifest artifact reference")
    raw = store.get_for_run(scope, ref)
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TreeError("Tree archive manifest is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {"format", "tree_digest", "tree", "blobs"}:
        raise TreeError("Invalid tree archive manifest fields")
    if payload["format"] != ARCHIVE_FORMAT:
        raise TreeError("Unsupported tree archive format")
    manifest = payload["tree"]
    validate_manifest(manifest)
    if payload["tree_digest"] != canonical_hash(manifest):
        raise TreeError("Tree archive digest does not match its complete manifest")
    blobs = payload["blobs"]
    if not isinstance(blobs, list) or len(blobs) != len(manifest["files"]):
        raise TreeError("Tree archive does not contain every declared file")
    references = []
    for blob, item in zip(blobs, manifest["files"]):
        if not isinstance(blob, dict) or set(blob) != {"path", "artifact"} or blob["path"] != item["path"]:
            raise TreeError("Tree archive file references do not match the complete manifest")
        record = blob["artifact"]
        if not isinstance(record, dict) or set(record) != {"kind", "content_hash", "path", "media_type"}:
            raise TreeError("Invalid tree file artifact reference")
        if any(not isinstance(value, str) for value in record.values()):
            raise TreeError("Tree file artifact reference fields must be strings")
        if record["kind"] != "tree_file" or record["media_type"] != "application/octet-stream":
            raise TreeError("Invalid tree file artifact kind or media type")
        if record["content_hash"] != item["content_hash"]:
            raise TreeError("Tree file artifact hash does not match the manifest")
        references.append(ArtifactRef(**record))
    files = []
    for item, reference in zip(manifest["files"], references):
        data = store.get_for_run(scope, reference)
        if len(data) != item["size"]:
            raise TreeError(f"Tree file size does not match the manifest: {item['path']}")
        files.append(CapturedFile(item["path"], data))
    tree = CapturedTree(tuple(manifest["directories"]), tuple(files))
    if tree.manifest != manifest:
        raise TreeError("Loaded tree differs from the archived manifest")
    return tree


def _validate_scope(scope: str) -> None:
    validate_public_path(scope)
    if "/" in scope:
        raise TreeError("Artifact scope must be one path component")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise TreeError(f"Duplicate tree archive JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise TreeError(f"Non-finite value in tree archive JSON: {value}")
