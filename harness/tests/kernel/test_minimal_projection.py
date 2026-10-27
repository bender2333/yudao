# 最小投影模块（骨架与应用设计说明第 4 节）：从骨架事件折叠裁决要读的几样。
# 守 R1（第三环的不变式：同样的事件重放出同样的状态）与 R2（第二环的合同：成果的种类来自定义，
# 加一种成果不改最小投影的代码；模块只导入内核、标准库与 pydantic）。
#
# 这一张只建模块，不接给裁决用：与 RunProjection 逐项一致的重放在
# test_minimal_projection_baselines.py（集成层）里，对事件序列基准逐个场景做。

import ast
import json
import shutil
import sys
from pathlib import Path

from harness.definitions import DEFINITIONS_DIR, load_definitions
from harness.minimal_projection import AcceptedArtifact, fold_events
from harness.models import Event, EventType

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE = REPO_ROOT / "harness" / "minimal_projection.py"
MANIFEST = REPO_ROOT / "harness" / "definitions" / "kernel-manifest.json"
RUN_STREAM = "run:run_824"


def _event(etype: str, version: int, *, payload: dict | None = None, session: str | None = None,
           department: str | None = None, event_id: str | None = None, stop_reason: str | None = None,
           state: str = "running", epoch: int | None = None) -> Event:
    # 一条 run 流的事件：位置与流内版本都按给出的顺序，时间与本次讨论无关
    return Event(
        event_id=event_id or f"evt_{version}", run_id="run_824", type=etype, role=None,
        parent_event_id=None, state_before=state, state_after=state, payload=payload or {},
        artifact_hashes=[], session_id=session, provider=None, model=None, context_digest=None,
        stop_reason=stop_reason, error=None, created_at="2026-10-27T00:00:00+00:00",
        position=version, stream=RUN_STREAM, stream_version=version,
        project_id="prj_824", work_item_id="wi_824", department=department, epoch=epoch,
    )


def _run_created(version: int = 1) -> Event:
    return _event(EventType.RUN_CREATED, version, payload={
        "kind": "onboarding",
        "project_id": "prj_824",
        "work_item_id": "wi_824",
        "definitions_version": "sha256:definitions",
        "parameters_version": "sha256:parameters",
        "max_cycles": 7,
        "run_time_limit_sec": 900,
    })


def test_the_minimal_projection_folds_the_items_the_design_lists():
    # 设计说明第 4 节那张表的六项与之后补齐的几样，每一样都来自骨架事件
    events = [
        _run_created(),
        _event(EventType.DEPARTMENT_ACTIVATED, 2, session="ses_pro", department="product",
               payload={"activation_id": "act_1", "cycle": 1}, epoch=1),
        _event(EventType.MODEL_REQUESTED, 3, session="ses_pro", department="product"),
        _event(EventType.MODEL_REQUESTED, 4, session="ses_pro", department="product"),
        _event(EventType.ACTIVATION_FINISHED, 5, session="ses_pro", department="product",
               payload={"activation_id": "act_1", "elapsed_ms": 1200, "session_elapsed_ms": 1200}),
        _event(EventType.SPEC_ACCEPTED, 6, session="ses_pro", department="product", payload={
            "content_hash": "sha256:spec1", "artifact_kind": "product_spec", "artifact_version": 1,
            "artifact_basis": {},
        }),
        _event(EventType.CONTRACT_ACCEPTED, 7, session="ses_pro", department="product", payload={
            "content_hash": "sha256:contract1", "artifact_kind": "contract", "artifact_version": 1,
            "artifact_basis": {"product_spec": "sha256:spec1"},
            "artifact_ref": {"kind": "prd", "content_hash": "sha256:prd1", "path": "run_824/prd.md",
                             "media_type": "text/markdown"},
        }),
        _event(EventType.DECISION_REQUESTED, 8, event_id="evt_dec_open",
               payload={"kind": "model_unavailable", "blocks": "run"}),
        _event(EventType.DECISION_REQUESTED, 9, event_id="evt_dec_answered",
               payload={"kind": "pause", "blocks": "run"}),
        _event(EventType.DECISION_ANSWERED, 10, event_id="evt_answer",
               payload={"decision_id": "evt_dec_answered", "option": "resume", "note": "",
                        "base_version": 1}),
        _event(EventType.ACTIVATION_FINISHED, 11, session="ses_pro", department="product",
               payload={"activation_id": "act_1", "elapsed_ms": 2500, "session_elapsed_ms": 2500}),
        _event(EventType.RUN_DONE, 12, stop_reason="released", state="done"),
    ]
    projection = fold_events(events)

    assert projection.run_id == "run_824"
    assert (projection.project_id, projection.work_item_id) == ("prj_824", "wi_824")
    assert projection.work_item_kind == "onboarding"
    assert (projection.status, projection.stop_reason) == ("done", "released")
    assert projection.definitions_version == "sha256:definitions"
    assert projection.parameters_version == "sha256:parameters"
    assert (projection.max_cycles, projection.run_time_limit_sec) == (7, 900)
    assert projection.execution_right == 1
    assert projection.stream_versions == {RUN_STREAM: 12}
    assert projection.used.activations == 1
    assert projection.used.model_steps == 2
    # 中断那一轮还没结算的时间不计：只取已结算的那一条
    assert projection.used.settled_ms == 2500
    session = projection.sessions["ses_pro"]
    assert (session.activations, session.model_steps, session.settled_ms) == (1, 2, 2500)
    assert session.round_id == "act_1"
    assert projection.artifacts["product_spec"] == AcceptedArtifact(version=1, content_hash="sha256:spec1")
    contract = projection.artifacts["contract"]
    assert (contract.version, contract.content_hash) == (1, "sha256:contract1")
    assert contract.basis == {"product_spec": "sha256:spec1"}
    assert contract.ref["content_hash"] == "sha256:prd1"
    # 待回答的决定请求只有还没回答的那一条
    assert projection.pending_decisions == ("evt_dec_open",)


def test_a_new_artifact_kind_from_the_definitions_folds_without_changing_the_module(tmp_path: Path):
    # 第二环的合同（设计说明第 5.4 节第 6 条）：成果的种类来自定义，加一种成果不改最小投影的代码。
    # 定义里加一个提交新成果种类的工具，写一条它的接纳事件，模块代码一行不改就能折叠出它的当前版本
    root = _definitions_with_a_new_artifact_kind(tmp_path)
    definitions = load_definitions(root)
    new_kind = "task_card"
    assert new_kind in {tool.proposal for tool in definitions.tools.values() if tool.proposal}
    events = [
        _run_created(),
        _event(EventType.QA_SUBMITTED, 2, session="ses_qua", department="quality", payload={
            "content_hash": "sha256:card2", "artifact_kind": new_kind, "artifact_version": 2,
            "artifact_basis": {"task_card": "sha256:card1"},
            "artifact_ref": {"kind": "task_card", "content_hash": "sha256:card2", "path": "run_824/card.json",
                             "media_type": "application/json"},
        }),
    ]
    projection = fold_events(events)
    assert projection.artifacts[new_kind] == AcceptedArtifact(
        version=2,
        content_hash="sha256:card2",
        basis={"task_card": "sha256:card1"},
        ref={"kind": "task_card", "content_hash": "sha256:card2", "path": "run_824/card.json",
             "media_type": "application/json"},
    )
    # 模块里没有这个种类的名字：折叠依据的是接纳事件的统一字段，不是内核认识的具体种类
    assert new_kind not in MODULE.read_text(encoding="utf-8")


def _definitions_with_a_new_artifact_kind(tmp_path: Path) -> Path:
    # 定义文件的一份副本，tools.json 里多一个提交新成果种类的工具（一种提案只由一个工具提交）
    root = tmp_path / "definitions"
    shutil.copytree(DEFINITIONS_DIR, root, ignore=shutil.ignore_patterns("__pycache__", "kernel-manifest.json"))
    tools = json.loads((root / "tools.json").read_text(encoding="utf-8"))
    tools["publish_task_card"] = {
        "kind": "host",
        "proposal": "task_card",
        "description": "Publish a task card to the pool.",
        "parameters": {"type": "object", "properties": {"title": {"type": "string"}},
                       "additionalProperties": False, "required": ["title"]},
    }
    (root / "tools.json").write_text(json.dumps(tools, ensure_ascii=False, indent=2), encoding="utf-8")
    return root


def test_the_same_events_fold_to_the_same_projection():
    # R1：同样是这组事件重放，结果相同；重放不读时钟，也不调用模型
    events = [
        _run_created(),
        _event(EventType.DEPARTMENT_ACTIVATED, 2, session="ses_eng", department="engineering",
               payload={"activation_id": "act_2", "cycle": 1}),
        _event(EventType.DELIVERY_ACCEPTED, 3, session="ses_eng", department="engineering", payload={
            "content_hash": "sha256:delivery1", "artifact_kind": "delivery_spec", "artifact_version": 1,
            "artifact_basis": {"product_spec": "sha256:spec1"},
        }),
    ]
    assert fold_events(events) == fold_events(events)


def test_the_module_imports_only_kernel_files_stdlib_and_pydantic():
    # R1：最小投影要列入内核清单（S1d），导入方向与内核的其余模块相同
    kernel = {entry["path"] for entry in json.loads(MANIFEST.read_text(encoding="utf-8"))["paths"]
              if entry["kind"] == "module"}
    offenders = []
    for line, module in _imported_modules("harness/minimal_projection.py"):
        top = module.split(".")[0]
        if top == "harness":
            resolved = _resolve(module)
            if resolved is None or resolved not in kernel:
                offenders.append((line, module, resolved))
        elif top not in sys.stdlib_module_names and module != "__future__" and top != "pydantic":
            offenders.append((line, module, "不是内核文件、标准库或 pydantic"))
    assert offenders == []


def _resolve(module: str) -> str | None:
    relative = module[len("harness."):] if module.startswith("harness.") else module
    for candidate in (relative + ".py", relative + "/__init__.py"):
        if (REPO_ROOT / "harness" / candidate).exists():
            return "harness/" + candidate
    return None


def _imported_modules(relative: str) -> list[tuple[int, str]]:
    # 文件里的导入语句按模块名给出，不执行任何代码（与 harness/tests/kernel/test_manifest.py 同一种读法）
    package = ".".join(["harness"] + relative[len("harness/"):].split("/")[:-1])
    found = []
    for node in ast.walk(ast.parse((REPO_ROOT / relative).read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                base = ".".join(parts[:len(parts) - (node.level - 1)])
                found.append((node.lineno, f"{base}.{node.module}" if node.module else base))
            else:
                found.append((node.lineno, node.module or ""))
    return found
