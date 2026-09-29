# 接口层：FastAPI 应用（设计说明第 2.2、7.1 节）。路由、OpenAPI 与能力清单由应用层的注册表生成；
# 处理函数不含业务规则，只调用应用层。生命周期中在服务的事件循环里建立控制核心与应用层，关闭时释放。

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from importlib.metadata import version
from typing import Annotated, Any

from fastapi import FastAPI, Query, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter

from ..app.application import DEFAULT_REGISTRY, Application
from ..app.contracts import Accepted, Capabilities, EventObject, OutputDelta, Rejected, Snapshot
from ..app.project_queries import NotFound
from ..app.registry import CommandDefinition, QueryDefinition, Registry

# 本机访问方式的提出者（第 6.2 节）
LOCAL_ACTOR = "user:local"
_COMPONENTS = "#/components/schemas/{model}"


def create_app(open_application: Callable[[], Application], *, registry: Registry = DEFAULT_REGISTRY) -> FastAPI:
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
        return _application(request).capabilities(request.app.state.contract_digest)

    api.add_api_route("/api/capabilities", capabilities, methods=["GET"], response_model=Capabilities,
                      operation_id="capabilities", tags=["capabilities"])
    api.openapi = lambda: _openapi(api)
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
        result = await _application(request).command(definition.name, body, actor=LOCAL_ACTOR)
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

    parameters = () if definition.request is None else (("params", Annotated[definition.request, Query()]),)
    endpoint.__signature__ = _signature(*parameters)
    api.add_api_route(
        f"/api/queries/{definition.name}", endpoint, methods=["GET"], response_model=Snapshot[definition.result],
        operation_id=_operation_id("query", definition.name), summary=definition.name, tags=["queries"],
    )


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
