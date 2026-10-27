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
from .contracts import render_structure
from .event_store import run_stream
from .write_path import NewEvent, Transaction
from .environment import LocalEnvironment
from .git_versions import GitVersionStore
from .models import ArtifactRef, Event, EventType, RunProjection, canonical_hash, new_id, utc_now
from .projection import apply_event
from .tree_archive import load_tree, store_tree
from .workspace import WorkspaceSnapshot


# 成果接纳事件的统一字段（设计说明第 4 节、第 5.4 节第 6 条）：成果种类、版本、依据与内容摘要。
# 最小投影按这组字段折叠，不按事件种类逐个写，加一种成果种类不改最小投影的代码。
# 「依据」按「成果种类 → 内容摘要」记下这一版建立在哪些成果版本上：载荷里指名所依据成果版本的字段
# 就是这几种；上一版（parent_hash）的依据是同一类成果的上一版。
_BASIS_FIELDS = (
    ("product_spec_hash", "product_spec"),
    ("effective_contract_hash", "contract"),
    ("structure_hash", "structure"),
    ("delivery_spec_hash", "delivery_spec"),
)

# 一种成果可以多版并存（设计说明第 4 节 2026-10-27 补）：产品决定各自是一件成果，新的决定不让旧的失效，
# 最小投影按种类记当前有效各版的摘要清单（通用条件 6 的不重复接纳读它）
_MULTIPLE_KINDS = frozenset({"product_decision"})
# 成果记下的树摘要：交付记代码树、建档记快照的树；没有这一项的成果不带
_TREE_FIELDS = ("code_tree_digest", "code_snapshot_hash")


def acceptance_fields(kind: str, artifact: dict[str, Any], *, version: int,
                      ref: dict[str, Any] | None = None) -> dict[str, Any]:
    # 写进接纳事件的那一组统一字段。只增不改：已有的字段不动，内容摘要仍是各自的 content_hash。
    # 2026-10-27（S1d）补作者部门、记下的树摘要与「这一种成果多版并存」三个字段（工单 #860）
    basis = {name: artifact[key] for key, name in _BASIS_FIELDS
             if isinstance(artifact.get(key), str) and artifact[key]}
    parent = artifact.get("parent_hash")
    if isinstance(parent, str) and parent:
        basis.setdefault(kind, parent)
    fields: dict[str, Any] = {"artifact_kind": kind, "artifact_version": version, "artifact_basis": basis}
    issuer = artifact.get("issuer")
    if isinstance(issuer, str) and issuer:
        fields["artifact_issuer"] = issuer
    for name in _TREE_FIELDS:
        tree = artifact.get(name)
        if isinstance(tree, str) and tree:
            fields["artifact_tree_digest"] = tree
            break
    if kind in _MULTIPLE_KINDS:
        fields["artifact_multiple"] = True
    if ref is not None:
        fields["artifact_ref"] = ref
    return fields


def contract_payload(projection: RunProjection) -> dict[str, Any]:
    # 有效合同的身份：它记下的 PRD 与有效决定的摘要，加上进入了模型输入的用户输入版本（设计说明第 3.1 节）。
    # 读的是成果的内容，住在应用侧（S1d 从内核的 contracts.py 搬来，工单 #860）
    spec = projection.product_spec
    if spec is None or spec.status != "active":
        raise ValueError("an active ProductSpec is required")
    basis = {
        "product_spec_hash": spec.content_hash,
        "decision_hashes": [item.content_hash for item in projection.effective_decisions],
        "input_version": spec.input_version,
    }
    return {**basis, "content_hash": canonical_hash(basis)}


def render_prd(projection: RunProjection, contract: dict[str, Any]) -> str:
    # PRD 的 Markdown：主机由接纳的 PRD、有效决定与有效合同生成（材料之一）。读的是成果的内容，住在应用侧
    spec = projection.product_spec
    if spec is None:
        raise ValueError("PRD requires an active ProductSpec")
    lines = ["# PRD", "", f"Effective contract: {contract['content_hash']}",
             f"ProductSpec: {spec.content_hash}", f"Accepted user input through version: {spec.input_version}",
             "", "## Goal", "", spec.goal]
    for title, values in (
        ("Requirements", spec.requirements), ("Boundaries", spec.boundaries),
        ("Constraints and recorded defaults", spec.constraints), ("Acceptance Criteria", spec.acceptance_criteria),
        ("Fatal Conditions", spec.fatal_conditions), ("Non-goals", spec.non_goals),
    ):
        lines.extend(["", f"## {title}", ""])
        lines.extend(f"- {item}" for item in values)
        if not values:
            lines.append("None.")
    lines.extend(["", "## Effective Product Decisions", ""])
    for index, decision in enumerate(projection.effective_decisions, 1):
        lines.extend([f"### {index}. {decision.statement}", "", f"Rationale: {decision.rationale}",
                      "", f"Source: {decision.content_hash}", f"Original ProductSpec: {decision.product_spec_hash}", ""])
    if not projection.effective_decisions:
        lines.append("None.")
    if spec.decision_changes:
        lines.extend(["", "## Treatment of Earlier Decisions", ""])
        lines.extend(f"- {item['decision_hash']}: {item['disposition']}. {item['rationale']}" for item in spec.decision_changes)
    if spec.change_record is not None:
        lines.extend(["", "## Requirement Changes", "", f"Previous ProductSpec: {spec.parent_hash}",
                      f"Rationale: {spec.change_record['rationale']}"])
        for field in ("changed", "retained", "retired"):
            lines.extend(["", f"### {field.title()}", ""])
            lines.extend(f"- {item}" for item in spec.change_record[field])
            if not spec.change_record[field]:
                lines.append("None.")
    return "\n".join(lines).rstrip() + "\n"


def invalidation(current: RunProjection, reason: str) -> tuple[str, dict[str, Any]] | None:
    # 接纳以后当前交付失效的一条事件（骨架事件「成果失效」，S1b，设计说明第 4 节）：
    # 载荷给出成果种类、版本与原因。没有当前交付时没有要失效的成果，这一刻不记事件
    delivery = current.delivery_spec
    if delivery is None:
        return None
    return EventType.ARTIFACT_INVALIDATED, {"artifact_kind": "delivery_spec",
                                            "artifact_version": delivery.revision, "reason": reason}


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
                        parent_event_id=parent_event_id, state_before=projection.status,
                        state_after=projection.status, session_id=session_id, provider=provider, model=model)
        prepared: list[tuple[str, dict[str, Any], list[str]]] = []
        updates: dict[str, bytes | None] = {}
        materials: dict[str, bytes] = {}
        current = deepcopy(projection)

        def append(event_type: str, payload: dict[str, Any], hashes: list[str] | None = None) -> int:
            prepared.append((event_type, payload, hashes or []))
            event = Event(event_id="uncommitted", run_id=run_id, type=event_type, role=None, **metadata,
                          payload=payload,
                          artifact_hashes=hashes or [], context_digest=None, stop_reason=None, error=None,
                          created_at=utc_now(), position=0, stream=run_stream(run_id),
                          stream_version=projection.stream_version + len(prepared),
                          project_id=projection.project_id, work_item_id=projection.work_item_id)
            apply_event(current, event)
            return len(prepared) - 1

        def invalidate(reason: str) -> None:
            # 接纳以后当前交付失效：记一条成果失效事件（S1b，设计说明第 4 节）。没有当前交付时不记
            event = invalidation(current, reason)
            if event is not None:
                append(*event)

        def product_spec(spec: dict[str, Any]) -> int:
            spec = {**spec, "id": new_id("spec")}
            if projection.product_spec:
                append(EventType.SPEC_SUPERSEDED, {"content_hash": projection.product_spec.content_hash,
                                                 "revision": projection.product_spec.revision})
            spec.update(acceptance_fields("product_spec", spec, version=int(spec["revision"])))
            index = append(EventType.SPEC_ACCEPTED, spec, [spec["content_hash"]])
            # 新的 PRD 被接纳，当前交付失效（紧接着契约也会重新签发，那一条失效事件不再重复记）
            invalidate("product_spec_changed")
            return index

        kind = artifact["kind"]
        if kind == "product_spec":
            event = product_spec(artifact)
            updates["specs/product.json"] = _json_bytes(prepared[event][1])
        elif kind == "product_decision":
            artifact["id"] = new_id("decision")
            # 产品决策各自是一件成果，没有版本号：记作它的第一版
            artifact.update(acceptance_fields("product_decision", artifact, version=1))
            event = append(EventType.PRODUCT_DECISION_ACCEPTED, artifact, [artifact["content_hash"]])
        elif kind == "delivery_spec":
            if artifact["code_tree_digest"] != snapshot.digest:
                raise ValueError("Delivery does not match the validated workspace snapshot")
            artifact["id"] = new_id("del")
            ref = store_tree(self.artifacts, run_id, snapshot.tree)
            environment.verify_tree(snapshot)
            artifact["tree_ref"] = asdict(ref)
            artifact.update(acceptance_fields("delivery_spec", artifact, version=int(artifact["revision"]),
                                              ref=asdict(ref)))
            # 新交付被接纳，它之前的那一版失效（事件记在接纳之前，投影按顺序折叠）
            invalidate("replaced")
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
            artifact.update(acceptance_fields("qa_review", artifact, version=int(artifact["revision"]),
                                              ref=asdict(ref)))
            event = append(EventType.QA_SUBMITTED, artifact, [artifact["content_hash"], ref.content_hash])
            updates["specs/qa.json"] = _json_bytes(prepared[event][1])
            if artifact.get("verdict") == "rework_engineering":
                # 质检退回工程：工程要重新交付，当前交付失效（S1b）
                invalidate("qa_rework_engineering")
        elif kind == "structure":
            # 建档事项的现有结构说明：接纳时再核对一次工作区的树摘要与快照相同（设计第 4.1 节）
            if projection.snapshot is None or artifact["code_tree_digest"] != projection.snapshot["tree_digest"]:
                raise ValueError("Structure does not match the snapshot of the onboarding run")
            environment.verify_tree(snapshot)
            artifact["id"] = new_id("structure")
            ref = self.artifacts.put(run_id, "structure", render_structure(artifact), media_type="text/markdown")
            artifact["structure_ref"] = asdict(ref)
            artifact.update(acceptance_fields("structure", artifact, version=int(artifact["revision"]),
                                              ref=asdict(ref)))
            event = append(EventType.STRUCTURE_ACCEPTED, artifact, [artifact["content_hash"], ref.content_hash])
            updates["specs/structure.json"] = _json_bytes(prepared[event][1])
            updates["STRUCTURE.md"] = materials["STRUCTURE.md"] = self.artifacts.get_for_run(run_id, ref)
        elif kind == "baseline_review":
            if projection.snapshot is None or artifact["code_snapshot_hash"] != projection.snapshot["tree_digest"]:
                raise ValueError("Baseline review does not match the snapshot of the onboarding run")
            environment.verify_tree(snapshot)
            artifact["id"] = new_id("baseline")
            artifact.update(acceptance_fields("baseline_review", artifact, version=int(artifact["revision"])))
            event = append(EventType.BASELINE_REVIEW_ACCEPTED, artifact, [artifact["content_hash"]])
            updates["specs/baseline.json"] = _json_bytes(prepared[event][1])
            if artifact.get("verdict") == "rework_product":
                # 基线核验退回产品：产品要重写初始 PRD，当前交付失效（S1b）。
                # 建档事项的工程部门没有提交交付的工具，这一刻通常没有当前交付，也就不记事件
                invalidate("baseline_rework_product")
        else:
            raise ValueError(f"unhandled artifact kind {kind}")

        if kind in {"product_spec", "product_decision"}:
            contract = contract_payload(current)
            if current.effective_contract is None or contract["content_hash"] != current.effective_contract.content_hash:
                contract["revision"] = 1 if current.effective_contract is None else current.effective_contract.revision + 1
                markdown = render_prd(current, contract)
                ref = self.artifacts.put(run_id, "prd", markdown, media_type="text/markdown")
                contract["prd_ref"] = asdict(ref)
                contract.update(acceptance_fields("contract", contract, version=int(contract["revision"]),
                                                  ref=asdict(ref)))
                contract_event = append(EventType.CONTRACT_ACCEPTED, contract,
                                        [contract["content_hash"], ref.content_hash])
                # 新合同被接纳，当前交付失效（S1b）
                invalidate("effective_contract_changed")
                decisions = [{key: value for key, value in asdict(item).items()
                              if key not in {"run_id", "created_event_id"}} for item in current.effective_decisions]
                updates["specs/contract.json"] = _json_bytes({**prepared[contract_event][1], "decisions": decisions})
                updates["PRD.md"] = materials["PRD.md"] = self.artifacts.get_for_run(run_id, ref)
        if updates:
            revision = self.git_versions.prepare(
                run_id, parent_commit=projection.git_version["commit"], updates=updates,
                message=f"Accept {kind} {artifact['content_hash']}",
                code_tree=snapshot.tree if kind == "delivery_spec" else None,
            )
            for event_type, payload, _hashes in prepared:
                if event_type not in {EventType.SPEC_SUPERSEDED, EventType.ARTIFACT_INVALIDATED}:
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
                    ref = None
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
