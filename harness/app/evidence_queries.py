# 证据查询：按工件引用读取一份外部来源工件（网络取回与 MCP 设计说明第 9 节；应用层与接口层设计说明第 4.3 节）。
# 界面按页读取取回的内容，证据核对读取工件保存的原文。查询只读取，不写入任何内容；工件的内容与引用里的
# 摘要不一致时返回找不到这份工件（内容被改动过，引用指向的工件就不在了）。

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from ..artifacts import EXTERNAL_SOURCE_KIND
from ..models import EventType
from ..tree_archive import artifact_run
from .contracts import Contract, Snapshot
from .project_queries import NotFound
from .registry import QueryDefinition

if TYPE_CHECKING:
    from .application import Application

_HASH = re.compile(r"sha256:[0-9a-f]{64}")


class ExternalSourceEvidence(Contract):
    # 读一份外部来源工件：所属事件（它在事件日志中的位置就是这份快照的位置）与工件引用的各个字段。
    # 引用的字段与别处的查询一样平铺成查询参数
    event_id: str
    kind: str
    content_hash: str
    path: str
    media_type: str | None = None


class ExternalSourceEvidenceResult(Contract):
    # 内容与来源字段：来源（地址，或服务器名称与工具名）、最终地址、状态码、内容类型、
    # 摘要值、取得时间、总行数与全文
    source: str
    content_hash: str
    fetched_at: str
    total_lines: int
    content: str
    final_url: str | None = None
    status_code: int | None = None
    content_type: str | None = None


def _evidence_external_source(application: Application,
                              request: ExternalSourceEvidence) -> Snapshot[ExternalSourceEvidenceResult]:
    store = application.system.store
    event = store.get_event(request.event_id)
    if event is None:
        raise NotFound(f"event not found: {request.event_id}")
    if request.kind != EXTERNAL_SOURCE_KIND or not _HASH.fullmatch(request.content_hash):
        raise NotFound(f"not an external source reference: {request.content_hash}")
    digest = request.content_hash.split(":", 1)[1]
    scope = artifact_run(request.path)
    if Path(request.path).as_posix() != (Path(scope) / digest[:2] / digest).as_posix() or scope != event.run_id:
        raise NotFound(f"external source does not belong to the event: {request.event_id}")
    try:
        entry = application.system.artifacts.external_source(scope, request.content_hash)
    except FileNotFoundError as exc:
        raise NotFound(f"external source not found: {request.content_hash}") from exc
    except ValueError as exc:
        raise NotFound(f"external source content does not match its reference: {exc}") from exc
    return Snapshot[ExternalSourceEvidenceResult](
        position=event.position,
        data=ExternalSourceEvidenceResult(
            source=entry.source,
            content_hash=entry.content_hash,
            fetched_at=entry.fetched_at,
            total_lines=entry.total_lines,
            content=entry.text,
            final_url=entry.final_url,
            status_code=entry.status_code,
            content_type=entry.content_type,
        ),
    )


EVIDENCE_EXTERNAL_SOURCE = QueryDefinition(
    name="evidence.external_source", request=ExternalSourceEvidence, result=ExternalSourceEvidenceResult,
    handle=_evidence_external_source,
    # 工件由工具调用的回执存下来：这类事件到达以后重新查询，读到新的外部来源
    changed_by=(EventType.TOOL_CALLED,),
)
