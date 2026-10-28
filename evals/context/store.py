"""读事件库与工件库，把一个 run 的每一步还原成「装配的输入与输出」。

只读：以只读方式打开 sqlite，按路径读工件文件，不写任何东西。

为什么从这里读：`model_request_serialized` 事件记录的是这一步真正发给模型的请求
（工件里是协议原样的请求体），`context_assembled` 事件记录的是同一步的上下文清单
（每一段材料的来源、版本、估算用量，以及被排除的来源与理由）。两者相加就是
「这一步的视图」的完整记录，不需要重跑装配，也不需要模型。

协议差异：串行化之后的请求体形状取决于调用目标的协议。chat_completions 是
`messages` + `tools`，responses 是 `input` + `tools`。这里统一成项目条目列表
（见 items.py）。

用法见 evals/context/README.md。
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Iterator

ARTIFACTS_DIRNAME = "artifacts"


class StoreError(RuntimeError):
    """事件库或工件库不满足回放所需的前提。"""


@dataclass(frozen=True)
class RequestRecord:
    """一步真正发给模型的请求，连同它的清单与身份。"""

    event_id: str
    position: int
    run_id: str
    project_id: str | None
    department: str
    session_id: str | None
    activation_id: str
    step_id: int
    attempt: int
    purpose: str
    context_window: int
    provider: str | None
    model: str | None
    created_at: str
    body: dict[str, Any]
    manifest_event_id: str | None
    manifest: dict[str, Any] | None


@dataclass(frozen=True)
class OutputRecord:
    """这一步模型的输出与工具结果（真值集合从这些输出里抽）。"""

    items: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)


class EventLog:
    """事件库的只读视图。"""

    def __init__(self, db_path: str, artifacts_root: str | None = None) -> None:
        if not os.path.isfile(db_path):
            raise StoreError(f"事件库不存在：{db_path}")
        self.db_path = db_path
        self.artifacts_root = artifacts_root or os.path.join(os.path.dirname(db_path), ARTIFACTS_DIRNAME)
        uri = "file:" + db_path.replace("\\", "/") + "?mode=ro"
        self._conn = sqlite3.connect(uri, uri=True)
        self._conn.row_factory = sqlite3.Row
        self._cache: dict[str, list[sqlite3.Row]] = {}

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "EventLog":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # --- 工件 ---
    def artifact(self, ref: dict[str, Any]) -> Any:
        """按工件引用读回内容。工件都是 UTF-8 的 JSON 或文本。"""
        path = ref.get("path")
        if not path:
            raise StoreError(f"工件引用没有 path：{ref}")
        full = os.path.join(self.artifacts_root, *str(path).split("/"))
        if not os.path.isfile(full):
            raise StoreError(f"工件文件缺失：{full}")
        with open(full, encoding="utf-8") as handle:
            text = handle.read()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    # --- 事件 ---
    def runs(self, *, provider: str | None = None) -> list[str]:
        """有工作请求的 run（按首次出现的位置排序）。"""
        sql = ("select run_id, min(position) p from events "
               "where type = 'model_request_serialized' and run_id is not null "
               "group by run_id order by p")
        return [row["run_id"] for row in self._conn.execute(sql)]

    def events(self, run_id: str) -> list[sqlite3.Row]:
        cached = self._cache.get(run_id)
        if cached is None:
            cached = list(self._conn.execute(
                "select * from events where run_id = ? order by position", (run_id,)))
            self._cache[run_id] = cached
        return cached

    def steps(self, run_id: str) -> list[RequestRecord]:
        """这个 run 的工作请求，按位置排序。

        「工作请求」= purpose 为 work 的请求；压缩请求（purpose 为 compaction）不进
        这一步的视图，本工具只测工作请求。
        """
        rows = self.events(run_id)
        manifests: dict[str, dict[str, Any]] = {}
        for row in rows:
            if row["type"] == "context_assembled":
                manifests[row["event_id"]] = json.loads(row["payload_json"])
        steps: list[RequestRecord] = []
        for row in rows:
            if row["type"] != "model_request_serialized":
                continue
            payload = json.loads(row["payload_json"])
            if payload.get("purpose") != "work":
                continue
            ref = payload.get("request_ref")
            if not ref:
                raise StoreError(f"请求事件 {row['event_id']} 没有 request_ref，无法回放")
            body = self.artifact(ref)
            if not isinstance(body, dict):
                raise StoreError(f"请求工件不是对象：{row['event_id']}")
            manifest = manifests.get(payload.get("context_event_id") or "")
            steps.append(RequestRecord(
                event_id=row["event_id"], position=row["position"], run_id=run_id,
                project_id=row["project_id"], department=row["department"] or payload.get("department") or "",
                session_id=row["session_id"], activation_id=payload.get("activation_id") or "",
                step_id=int(payload.get("step_id") or 0), attempt=int(payload.get("attempt") or 1),
                purpose=payload.get("purpose") or "", context_window=int(payload.get("context_window") or 0),
                provider=payload.get("provider_name"), model=payload.get("requested_model"),
                created_at=row["created_at"] or "", body=body,
                manifest_event_id=payload.get("context_event_id"), manifest=manifest,
            ))
        steps.sort(key=lambda item: item.position)
        return steps

    def outputs_for(self, step: RequestRecord, next_position: int | None) -> OutputRecord:
        """这一步的模型输出与工具结果。

        模型输出按 (activation_id, step_id) 与请求同属一步；位置在本次请求之后、
        下一次请求之前。工具结果取同一激活同一 step 的 `tool_called` 里带
        `input_item` 的那些（同一位模型服务的用量事件叫 provider_usage，不带工具结果）。
        """
        items: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []
        for row in self.events(step.run_id):
            if row["position"] <= step.position:
                continue
            if next_position is not None and row["position"] >= next_position:
                continue
            payload = json.loads(row["payload_json"])
            if row["type"] in ("model_message", "model_reasoning"):
                if (payload.get("activation_id"), payload.get("step_id")) != (step.activation_id, step.step_id):
                    continue
                if payload.get("purpose") not in (None, "work"):
                    continue
                ref = payload.get("message_ref") or payload.get("reasoning_ref")
                if ref:
                    items.append(self.artifact(ref))
            elif row["type"] in ("tool_called", "tool_skipped"):
                if not isinstance(payload, dict) or "input_item" not in payload:
                    continue
                if (payload.get("activation_id"), payload.get("step_id")) != (step.activation_id, step.step_id):
                    continue
                results.append({"name": payload.get("name"), "args": payload.get("args"),
                                "ok": payload.get("ok"),
                                "item": payload["input_item"]})
        return OutputRecord(items=items, tool_results=results)

    def iter_steps(self, run_id: str) -> Iterator[tuple[RequestRecord, OutputRecord]]:
        steps = self.steps(run_id)
        for index, step in enumerate(steps):
            next_position = steps[index + 1].position if index + 1 < len(steps) else None
            yield step, self.outputs_for(step, next_position)
