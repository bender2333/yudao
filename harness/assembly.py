# 上下文装配（P）：部门历史的重建、每一步的请求装配（压缩计划、装配、请求构造与上下文清单）、
# 压缩完成以后的检查点。只读取投影、事件与工件，不写入；需要写入的内容交回调用方，由调用方写入。

from __future__ import annotations

import json
from typing import Any

from .artifacts import ArtifactStore
from .models import ArtifactRef, Event, EventType, canonical_hash


class ContextAssembly:
    def __init__(self, artifacts: ArtifactStore) -> None:
        self.artifacts = artifacts

    def department_history(self, events: list[Event], department: str) -> list[dict[str, Any]]:
        # 部门历史按事件顺序排列：本部门的工作消息、模型输出、主机提示与工具结果；
        # 失败尝试的模型输出与工具结果、压缩请求的输出不进入历史
        failed_steps = {
            (event.payload.get("activation_id"), event.payload.get("step_id"))
            for event in events
            if event.type == EventType.MODEL_ATTEMPT_FAILED and event.role == department
        }
        records: list[dict[str, Any]] = []
        for event in events:
            if event.role != department:
                continue
            if event.type in {EventType.MODEL_MESSAGE, EventType.DEPARTMENT_INPUT, EventType.TOOL_CALL_REQUIRED}:
                if event.payload.get("purpose") == "compaction":
                    continue
                if event.type == EventType.MODEL_MESSAGE and (
                    event.payload.get("activation_id"), event.payload.get("step_id")
                ) in failed_steps:
                    continue
                ref = ArtifactRef(**event.payload["message_ref" if event.type == EventType.MODEL_MESSAGE else "input_ref"])
                item = json.loads(self.artifacts.get_for_run(event.run_id, ref))
            elif event.type in {EventType.TOOL_CALLED, EventType.TOOL_SKIPPED} and "input_item" in event.payload:
                if (event.payload.get("activation_id"), event.payload.get("step_id")) in failed_steps:
                    continue
                item = event.payload["input_item"]
            else:
                continue
            records.append({"event_id": event.event_id, "seq": event.seq,
                            "activation_id": event.payload["activation_id"], "step_id": event.payload["step_id"],
                            "type": event.type, "item": item, "item_digest": canonical_hash(item)})
        return records
