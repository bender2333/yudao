# 接口层：FastAPI 应用（设计说明第 2.2、7.1 节）。路由、OpenAPI 与能力清单由应用层的注册表生成；
# 处理函数不含业务规则，只调用应用层。生命周期中在服务的事件循环里建立控制核心与应用层，关闭时释放。

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from importlib.metadata import version
from typing import Annotated, Any

from fastapi import FastAPI, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import TypeAdapter

from ..app.application import DEFAULT_REGISTRY, Application
from ..app.contracts import AccessMode, Accepted, Capabilities, EventObject, OutputDelta, Rejected, Snapshot
from ..app.event_stream import EventScope, EventStream, StreamCheckpoint, StreamDelta, StreamEvent
from ..app.project_queries import NotFound
from ..app.registry import CommandDefinition, QueryDefinition, Registry
from ..app.replay import ReplayOutOfRange
from .access import CLIENT_ORIGINS, AccessMiddleware

_COMPONENTS = "#/components/schemas/{model}"


def create_app(open_application: Callable[[], Application], *, registry: Registry = DEFAULT_REGISTRY,
               access: AccessMode = "local", keepalive_sec: float = 15.0) -> FastAPI:
    @asynccontextmanager
    async def lifespan(api: FastAPI) -> AsyncIterator[None]:
        application = open_application()
        if application.registry is not registry:
            application.close()
            raise ValueError("the application was opened with a different registry than the routes")
        api.state.application = application
        api.state.contract_digest = contract_digest(api)
        try:
            yield
        finally:
            application.close()

    api = FastAPI(title="Yudao", version=version("yudao-harness"), docs_url=None, redoc_url=None,
                  openapi_url="/openapi.json", lifespan=lifespan)
    for command in registry.commands.values():
        _add_command(api, registry, command)
    for query in registry.queries.values():
        _add_query(api, query)

    async def capabilities(request: Request) -> Capabilities:
        return _application(request).capabilities(request.app.state.contract_digest, access=access)

    api.add_api_route("/api/capabilities", capabilities, methods=["GET"], response_model=Capabilities,
                      operation_id="capabilities", tags=["capabilities"])
    # CORS 只允许客户端页面的来源（第 6.2 节）。中间件最后添加的最先执行：认证在 CORS 之前
    api.add_middleware(CORSMiddleware, allow_origins=list(CLIENT_ORIGINS), allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type"])
    api.add_middleware(AccessMiddleware, access=access)
    api.openapi = lambda: _openapi(api)
    _add_events(api, keepalive_sec=keepalive_sec)
    return api


def contract_digest(api: FastAPI) -> str:
    # 合同摘要：OpenAPI 文档的摘要，客户端据此判断生成类型时的合同与服务是否一致
    document = json.dumps(api.openapi(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(document.encode("utf-8")).hexdigest()


def _application(request: Request) -> Application:
    return request.app.state.application


def _operation_id(kind: str, name: str) -> str:
    return f"{kind}_{name.replace('.', '_')}"


def _add_command(api: FastAPI, registry: Registry, definition: CommandDefinition) -> None:
    accepted = Accepted[definition.refs]

    async def endpoint(request: Request, body: Any) -> Any:
        result = await _application(request).command(definition.name, body, actor=request.state.actor)
        if isinstance(result, Rejected):
            return JSONResponse(status_code=409, content=result.model_dump(mode="json"))
        return result

    endpoint.__signature__ = _signature(("body", definition.request))
    reasons = ", ".join(registry.reasons(definition.name))
    api.add_api_route(
        f"/api/commands/{definition.name}", endpoint, methods=["POST"], response_model=accepted,
        responses={409: {"model": Rejected, "description": f"命令被拒绝，可能的原因：{reasons}"}},
        operation_id=_operation_id("command", definition.name), summary=definition.name, tags=["commands"],
    )


def _add_query(api: FastAPI, definition: QueryDefinition) -> None:
    async def endpoint(request: Request, params: Any = None) -> Any:
        try:
            return _application(request).query(definition.name, params)
        except NotFound as exc:
            return JSONResponse(status_code=404, content={"error": str(exc)})
        except ReplayOutOfRange as exc:
            # at 大于日志末尾：按位置读取的合同拒绝（设计说明第 4.1 节）
            return JSONResponse(status_code=422, content={"error": str(exc)})

    parameters = () if definition.request is None else (("params", Annotated[definition.request, Query()]),)
    endpoint.__signature__ = _signature(*parameters)
    api.add_api_route(
        f"/api/queries/{definition.name}", endpoint, methods=["GET"], response_model=Snapshot[definition.result],
        operation_id=_operation_id("query", definition.name), summary=definition.name, tags=["queries"],
    )


def _add_events(api: FastAPI, *, keepalive_sec: float) -> None:
    # GET /api/events（设计说明第 5.1 节）：SSE 事件流。参数 after（或 Last-Event-ID 请求头，请求头优先）、
    # 项目、事项、run、部门、角色、种类与 live。事件与检查点的 SSE id 是位置，片段的事件名为 delta、不带 id；
    # 空闲每 15 秒发送一次 SSE 注释作为保活（第 5.4 节第 5 项）
    async def events(
        request: Request,
        after: Annotated[int | None, Query(ge=0)] = None,
        project: Annotated[list[str] | None, Query()] = None,
        work_item: Annotated[list[str] | None, Query()] = None,
        run: Annotated[list[str] | None, Query()] = None,
        department: Annotated[list[str] | None, Query()] = None,
        role: Annotated[list[str] | None, Query()] = None,
        type: Annotated[list[str] | None, Query()] = None,
        live: Annotated[bool, Query()] = False,
        last_event_id: Annotated[str | None, Header()] = None,
    ) -> AsyncIterator[Any]:
        scope = EventScope(projects=tuple(project or ()), work_items=tuple(work_item or ()),
                           runs=tuple(run or ()), departments=tuple(department or ()), roles=tuple(role or ()),
                           types=tuple(type or ()))
        start = _resume_position(last_event_id, after)
        if start is None:
            # 续传位置不是非负整数：客户端记录的位置无法按位置解释，按位置未知重新同步（第 5.5 节）
            yield _frame("resync", {"reason": "position_unknown", "end_position": 0}, None)
            return
        stream = _application(request).open_event_stream(scope, after=start, live=live)
        next_task: asyncio.Task[Any] | None = None
        keepalive: asyncio.Task[Any] | None = None
        try:
            iterator = stream.messages().__aiter__()
            next_task = asyncio.ensure_future(anext(iterator))
            keepalive = asyncio.ensure_future(asyncio.sleep(keepalive_sec))
            while True:
                # 取下一条消息与保活计时竞争：空闲超过间隔时发一条 SSE 注释，已发出的取消息请求保持不变
                done, _still = await asyncio.wait({next_task, keepalive}, return_when=asyncio.FIRST_COMPLETED)
                if next_task in done:
                    keepalive.cancel()
                    try:
                        message = next_task.result()
                    except StopAsyncIteration:
                        return
                    next_task = asyncio.ensure_future(anext(iterator))
                    keepalive = asyncio.ensure_future(asyncio.sleep(keepalive_sec))
                elif keepalive in done:
                    yield ServerSentEvent(comment="keep-alive")
                    keepalive = asyncio.ensure_future(asyncio.sleep(keepalive_sec))
                    continue
                else:
                    continue
                if isinstance(message, StreamEvent):
                    yield _frame("event", message.event.model_dump(mode="json"), message.position)
                elif isinstance(message, StreamCheckpoint):
                    yield _frame("checkpoint", {"position": message.position, "previous": message.previous},
                                 message.position)
                elif isinstance(message, StreamDelta):
                    yield ServerSentEvent(event="delta", data=message.delta.model_dump(mode="json"))
                else:
                    yield _frame("resync", {"reason": message.reason, "end_position": message.end_position}, None)
                    return
        finally:
            if next_task is not None:
                next_task.cancel()
            if keepalive is not None:
                keepalive.cancel()

    api.add_api_route("/api/events", events, methods=["GET"], response_class=EventSourceResponse,
                      operation_id="events", summary="events", tags=["events"])

def _resume_position(last_event_id: str | None, after: int | None) -> int | None:
    # 续传位置：Last-Event-ID 请求头优先，其次 after，都没有时从 0 开始。
    # 请求头不是非负整数时按位置未知处理（返回 None），连接随后发送 resync 并关闭（第 5.5 节）
    if last_event_id is not None and last_event_id.strip():
        try:
            position = int(last_event_id)
        except ValueError:
            return None
        return position if position >= 0 else None
    return 0 if after is None else after

def _frame(name: str, data: dict[str, Any], position: int | None) -> ServerSentEvent:
    # 事件与检查点带 id（位置），片段不带 id；SSE 的 id 是字符串
    return ServerSentEvent(event=name, data=data, id=None if position is None else str(position))

def _signature(*parameters: tuple[str, Any]) -> inspect.Signature:
    # 路由由注册表生成：处理函数的参数类型取自登记的请求类型，FastAPI 据此校验请求并生成 OpenAPI
    kind = inspect.Parameter.POSITIONAL_OR_KEYWORD
    return inspect.Signature([inspect.Parameter("request", kind, annotation=Request)]
                             + [inspect.Parameter(name, kind, annotation=annotation) for name, annotation in parameters])


def _openapi(api: FastAPI) -> dict[str, Any]:
    # 路由生成的文档，加上经事件流送达、不出现在 JSON 回答中的合同类型：事件对象与模型输出片段
    if api.openapi_schema is None:
        document = get_openapi(title=api.title, version=api.version, routes=api.routes)
        schemas = document.setdefault("components", {}).setdefault("schemas", {})
        for name, contract in (("EventObject", EventObject), ("OutputDelta", OutputDelta)):
            generated = TypeAdapter(contract).json_schema(ref_template=_COMPONENTS)
            for key, value in generated.pop("$defs", {}).items():
                if schemas.setdefault(key, value) != value:
                    raise ValueError(f"contract type {key} has two different schemas")
            schemas[name] = generated
        api.openapi_schema = document
    return api.openapi_schema
