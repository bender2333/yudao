# 保存接纳的部门工件并发布共享材料：工件、Git 版本与材料在这里写好，接纳的全部事件在调用方的事务中一起追加；
# 事务没有提交时恢复原来的材料。

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .artifacts import ArtifactStore
from .contracts import contract_payload, render_plan, render_prd, render_structure
from .event_store import run_stream
from .write_path import NewEvent, Transaction
from .environment import LocalEnvironment
from .git_versions import GitVersionStore
from .models import ArtifactRef, Event, EventType, RunProjection, new_id, utc_now
from .projection import apply_event
from .tree_archive import load_tree, store_tree
from .workspace import WorkspaceSnapshot


@dataclass(frozen=True)
class Acceptance:
    # 准备好的一次接纳：要追加的全部事件、其中承载接纳结果的那一条，以及恢复原来材料的补偿
    events: list[NewEvent]
    source: int
    restore: Callable[[], None]

    def append(self, transaction: Transaction) -> Event:
        # 在事务中追加接纳的全部事件；事务没有提交时恢复原来的材料
        committed = transaction.append(*self.events)
        transaction.on_abort(self.restore)
        return committed[self.source]


class SubmissionWriter:
    def __init__(self, artifacts: ArtifactStore, materials_root: Path, git_versions: GitVersionStore) -> None:
        self.artifacts = artifacts
        self.materials_root = Path(materials_root).absolute().resolve()
        self.git_versions = git_versions

    def prepare(self, transaction: Transaction, *, projection: RunProjection, snapshot: WorkspaceSnapshot,
                environment: LocalEnvironment, artifact: dict[str, Any], department: str, parent_event_id: str,
                session_id: str, provider: str | None, model: str | None) -> Acceptance:
        # 接纳之前的全部准备：工件、Git 版本、交付封存与材料。projection 是接纳所依据的运行状态，
        # 流程编排给出事务中的运行状态。出错时事务中没有追加任何事件，已经写出的材料恢复原样
        run_id = projection.run_id
        artifact = dict(artifact)
        # 角色任务的提交记录由部门提出（设计第 5.2 节）；接纳事件与预览的 Event 用同一份元数据
        metadata = dict(actor=f"department:{department}", department=department,
                        parent_event_id=parent_event_id, state_before=projection.phase,
                        state_after=projection.phase, session_id=session_id, provider=provider, model=model)
        prepared: list[tuple[str, dict[str, Any], list[str]]] = []
        updates: dict[str, bytes | None] = {}
        materials: dict[str, bytes] = {}
        current = deepcopy(projection)
        request_id = None if projection.pending_request is None else projection.pending_request.id

        def append(event_type: str, payload: dict[str, Any], hashes: list[str] | None = None) -> int:
            if event_type not in {
                EventType.COLLABORATION_REQUESTED,
                EventType.COLLABORATION_RESPONDED,
                EventType.DEPARTMENT_GUIDANCE_RESPONDED,
            }:
                payload = {**payload, "request_id": request_id}
            prepared.append((event_type, payload, hashes or []))
            event = Event(event_id="uncommitted", run_id=run_id, type=event_type, role=None, **metadata,
                          payload=payload,
                          artifact_hashes=hashes or [], context_digest=None, stop_reason=None, error=None,
                          created_at=utc_now(), position=0, stream=run_stream(run_id),
                          stream_version=projection.stream_version + len(prepared),
                          project_id=projection.project_id, work_item_id=projection.work_item_id)
            apply_event(current, event)
            return len(prepared) - 1

        def product_spec(spec: dict[str, Any]) -> int:
            spec = {**spec, "id": new_id("spec")}
            if projection.product_spec:
                append(EventType.SPEC_SUPERSEDED, {"content_hash": projection.product_spec.content_hash,
                                                 "revision": projection.product_spec.revision})
            return append(EventType.SPEC_ACCEPTED, spec, [spec["content_hash"]])

        kind = artifact["kind"]
        if kind == "product_spec":
            event = product_spec(artifact)
            updates["specs/product.json"] = _json_bytes(prepared[event][1])
        elif kind == "product_decision":
            artifact["id"] = new_id("decision")
            event = append(EventType.PRODUCT_DECISION_ACCEPTED, artifact, [artifact["content_hash"]])
        elif kind == "engineering_plan":
            artifact["id"] = new_id("plan")
            markdown = render_plan(artifact)
            ref = self.artifacts.put(run_id, "engineering_plan", markdown, media_type="text/markdown")
            artifact["plan_ref"] = asdict(ref)
            event = append(EventType.PLAN_ACCEPTED, artifact, [artifact["content_hash"], ref.content_hash])
            updates["specs/plan.json"] = _json_bytes(prepared[event][1])
            updates["PLAN.md"] = materials["PLAN.md"] = self.artifacts.get_for_run(run_id, ref)
        elif kind == "collaboration_request":
            artifact["id"] = new_id("request")
            event = append(EventType.COLLABORATION_REQUESTED, artifact, [artifact["content_hash"]])
        elif kind == "collaboration_response":
            artifact["id"] = new_id("response")
            metadata["state_after"] = artifact["return_phase"]
            environment.verify_tree(snapshot)
            event = append(EventType.COLLABORATION_RESPONDED, artifact, [artifact["content_hash"]])
        elif kind == "department_guidance_response":
            event = append(EventType.DEPARTMENT_GUIDANCE_RESPONDED, artifact, [artifact["content_hash"]])
        elif kind == "delivery_spec":
            if artifact["code_tree_digest"] != snapshot.digest:
                raise ValueError("Delivery does not match the validated workspace snapshot")
            artifact["id"] = new_id("del")
            ref = store_tree(self.artifacts, run_id, snapshot.tree)
            environment.verify_tree(snapshot)
            artifact["tree_ref"] = asdict(ref)
            event = append(EventType.DELIVERY_ACCEPTED, artifact, [artifact["content_hash"], ref.content_hash])
            updates["specs/delivery.json"] = _json_bytes(prepared[event][1])
            updates["specs/delivery-tree.json"] = _json_bytes(snapshot.tree.manifest)
        elif kind == "qa_review":
            if artifact["verdict"] == "release":
                delivery = projection.delivery_spec
                if delivery is None:
                    raise ValueError("QA release requires an active delivery")
                try:
                    archived_tree = load_tree(self.artifacts, run_id, delivery.tree_ref)
                except (ValueError, OSError) as exc:
                    raise ValueError(f"QA release requires an intact persisted delivery tree: {exc}") from exc
                if archived_tree.digest != delivery.code_tree_digest:
                    raise ValueError("QA release delivery archive does not match the DeliverySpec tree digest")
                if archived_tree != snapshot.tree:
                    raise ValueError("QA release delivery archive does not match the validated workspace snapshot")
            artifact["id"] = new_id("qa")
            ref = self.artifacts.put(run_id, "qa_evidence", artifact["rationale"], media_type="text/plain")
            environment.verify_tree(snapshot)
            artifact["evidence_refs"] = [asdict(ref)]
            event = append(EventType.QA_SUBMITTED, artifact, [artifact["content_hash"], ref.content_hash])
            updates["specs/qa.json"] = _json_bytes(prepared[event][1])
        elif kind == "structure":
            # 建档事项的现有结构说明：接纳时再核对一次工作区的树摘要与快照相同（设计第 4.1 节）
            if projection.snapshot is None or artifact["code_tree_digest"] != projection.snapshot["tree_digest"]:
                raise ValueError("Structure does not match the snapshot of the onboarding run")
            environment.verify_tree(snapshot)
            artifact["id"] = new_id("structure")
            ref = self.artifacts.put(run_id, "structure", render_structure(artifact), media_type="text/markdown")
            artifact["structure_ref"] = asdict(ref)
            event = append(EventType.STRUCTURE_ACCEPTED, artifact, [artifact["content_hash"], ref.content_hash])
            updates["specs/structure.json"] = _json_bytes(prepared[event][1])
            updates["STRUCTURE.md"] = materials["STRUCTURE.md"] = self.artifacts.get_for_run(run_id, ref)
        elif kind == "baseline_review":
            if projection.snapshot is None or artifact["code_snapshot_hash"] != projection.snapshot["tree_digest"]:
                raise ValueError("Baseline review does not match the snapshot of the onboarding run")
            environment.verify_tree(snapshot)
            artifact["id"] = new_id("baseline")
            event = append(EventType.BASELINE_REVIEW_ACCEPTED, artifact, [artifact["content_hash"]])
            updates["specs/baseline.json"] = _json_bytes(prepared[event][1])
        else:
            raise ValueError(f"unhandled artifact kind {kind}")

        if kind in {"product_spec", "product_decision"}:
            contract = contract_payload(current)
            if current.effective_contract is None or contract["content_hash"] != current.effective_contract.content_hash:
                contract["revision"] = len(current.effective_contracts) + 1
                markdown = render_prd(current, contract)
                ref = self.artifacts.put(run_id, "prd", markdown, media_type="text/markdown")
                contract["prd_ref"] = asdict(ref)
                append(EventType.CONTRACT_ACCEPTED, contract, [contract["content_hash"], ref.content_hash])
                decisions = [{key: value for key, value in asdict(item).items()
                              if key not in {"run_id", "created_event_id"}} for item in current.effective_decisions]
                updates["specs/contract.json"] = _json_bytes({**prepared[-1][1], "decisions": decisions})
                updates["PRD.md"] = materials["PRD.md"] = self.artifacts.get_for_run(run_id, ref)
        if updates:
            revision = self.git_versions.prepare(
                run_id, parent_commit=projection.git_version["commit"], updates=updates,
                message=f"Accept {kind} {artifact['content_hash']}",
                code_tree=snapshot.tree if kind == "delivery_spec" else None,
            )
            for event_type, payload, _hashes in prepared:
                if event_type != EventType.SPEC_SUPERSEDED:
                    payload["git_version"] = revision
        if kind in {"delivery_spec", "qa_review", "structure", "baseline_review"}:
            environment.verify_tree(snapshot)
        previous_materials: dict[str, bytes | None] = {}

        def restore_materials() -> None:
            for name, raw in previous_materials.items():
                if raw is None:
                    (self.materials_root / run_id / name).unlink(missing_ok=True)
                else:
                    self._write_material(run_id, name, raw)

        try:
            for name, raw in materials.items():
                if name == "PRD.md":
                    ref = projection.effective_contract.prd_ref if projection.effective_contract else None
                elif name == "STRUCTURE.md":
                    ref = (ArtifactRef(**projection.structures[-1]["structure_ref"])
                           if projection.structures else None)
                else:
                    ref = projection.engineering_plans[-1].plan_ref if projection.engineering_plans else None
                previous_materials[name] = None if ref is None else self.artifacts.get_for_run(run_id, ref)
                self._write_material(run_id, name, raw)
        except Exception:
            restore_materials()
            raise
        # Git 对象与材料已经就绪，接纳的全部事件一起追加，在事务中一起提交
        return Acceptance([NewEvent(event_type, **metadata, payload=payload, artifact_hashes=hashes)
                           for event_type, payload, hashes in prepared], event, restore_materials)

    def _write_material(self, run_id: str, name: str, raw: bytes) -> None:
        folder = self.materials_root / run_id
        if not folder.is_relative_to(self.materials_root) or folder == self.materials_root:
            raise ValueError("run materials must stay within their root")
        folder.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=folder, prefix=f".{name}-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, folder / name)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
