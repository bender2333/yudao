# 证据查询：按工件引用读取一份外部来源工件（网络取回与 MCP 设计说明「结果、工件与证据」；应用层与接口层设计说明「查询清单」）
# 与一张截图（浏览器与 computer use 设计说明「查询」，工单 #152）。
# 界面按页读取取回的内容，证据核对读取工件保存的原文；试用记录页按截图引用取图。查询只读取，不写入任何内容；
# 工件的内容与引用里的摘要不一致时返回找不到这份工件（内容被改动过，引用指向的工件就不在了）。

from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import TYPE_CHECKING

from ..artifacts import EXTERNAL_SOURCE_KIND
from ..models import ArtifactRef, EventType
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


# ---------------------------------------------------------------------------
# 截图（浏览器与 computer use 设计说明「保存与绑定」、「查询」，工单 #152）：按工件引用返回一张截图，
# 按摘要核对以后返回内容；所属事件的位置（快照的 position，与 delivery.file、evidence.external_source
# 同一做法）告诉页面这张截图来自哪条事件

# 截图的工件种类（浏览器把动作结果里的图像存成工件时用的种类，见 harness/browser.py）
SCREENSHOT_KIND = "screenshot"


class ScreenshotEvidence(Contract):
    # 读一张截图：所属事件（它在事件日志中的位置就是这份快照的位置）与工件引用的各个字段。
    # 引用的字段与 evidence.external_source 一样平铺成查询参数
    event_id: str
    kind: str
    content_hash: str
    path: str
    media_type: str | None = None


class ScreenshotEvidenceResult(Contract):
    # 截图的内容：媒体类型与 base64 编码的字节（与 delivery.file 的二进制文件同一做法）。
    # content_hash 是返回内容的摘要，与请求里的引用相同
    content_hash: str
    media_type: str
    base64: str


def _evidence_screenshot(application: Application,
                         request: ScreenshotEvidence) -> Snapshot[ScreenshotEvidenceResult]:
    store = application.system.store
    event = store.get_event(request.event_id)
    if event is None:
        raise NotFound(f"event not found: {request.event_id}")
    if request.kind != SCREENSHOT_KIND or not _HASH.fullmatch(request.content_hash):
        raise NotFound(f"not a screenshot reference: {request.content_hash}")
    digest = request.content_hash.split(":", 1)[1]
    scope = artifact_run(request.path)
    if Path(request.path).as_posix() != (Path(scope) / digest[:2] / digest).as_posix() \
            or scope != event.run_id:
        raise NotFound(f"screenshot does not belong to the event: {request.event_id}")
    try:
        raw = application.system.artifacts.get_for_run(scope, ArtifactRef(
            kind=request.kind, content_hash=request.content_hash, path=request.path,
            media_type=request.media_type))
    except FileNotFoundError as exc:
        raise NotFound(f"screenshot not found: {request.content_hash}") from exc
    except ValueError as exc:
        raise NotFound(f"screenshot content does not match its reference: {exc}") from exc
    return Snapshot[ScreenshotEvidenceResult](
        position=event.position,
        data=ScreenshotEvidenceResult(
            content_hash=request.content_hash,
            media_type=request.media_type or "image/png",
            base64=base64.b64encode(raw).decode("ascii"),
        ),
    )


EVIDENCE_SCREENSHOT = QueryDefinition(
    name="evidence.screenshot", request=ScreenshotEvidence, result=ScreenshotEvidenceResult,
    handle=_evidence_screenshot,
    # 截图由工具调用的回执存下来：这类事件到达以后重新查询，读到新的截图（与 evidence.external_source 同一口径）
    changed_by=(EventType.TOOL_CALLED,),
)

