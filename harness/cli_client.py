# 通用命令行网络客户端（docs/design/external-ops-agent.md「接口」「连接、认证与请求头规则」「零维护的单项合同自省」「查询读取与幂等命令提交」）。
# 位于总图第四节「接口」的缝外侧，只使用标准库与 httpx，不导入 harness 内的其他模块（由 pyproject.toml 的 import-linter 合同守卫）。

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TextIO
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

# 连接与超时常量（docs/design/external-ops-agent.md「边界与范围」）
DEFAULT_SERVER_URL = "http://127.0.0.1:8765"
DEFAULT_TIMEOUT_SEC = 30.0
MIN_TIMEOUT_SEC = 5.0
MAX_TIMEOUT_SEC = 600.0

# 本机回环主机名集合（docs/design/app-and-interface.md「能力清单与认证」）
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

# 退出码（docs/design/external-ops-agent.md「查询读取与幂等命令提交」）
EXIT_OK = 0
EXIT_REJECTED = 1
EXIT_INVALID = 2
EXIT_CONNECTION_OR_AUTH = 3

# 本工单接入的网络子命令集合；结构预留后续子命令扩展
NETWORK_SUBCOMMANDS = frozenset({"capabilities", "describe", "query", "command"})


class _OrderedParamAction(argparse.Action):
    # 按命令行出现顺序记录 --param 与 --string-param，同名键后者覆盖前者
    def __init__(self, option_strings: Sequence[str], dest: str, *, param_kind: str, **kwargs: Any) -> None:
        super().__init__(option_strings, dest, **kwargs)
        self._param_kind = param_kind

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> None:
        items = list(getattr(namespace, self.dest, None) or [])
        items.append((self._param_kind, str(values)))
        setattr(namespace, self.dest, items)


@dataclass(frozen=True)
class ClientConfig:
    base_url: str
    token: str | None
    timeout_sec: float
    is_loopback: bool


class _CliArgumentError(Exception):
    # 命令行参数冲突、格式非法或超出常量界限（对应退出码 2）
    pass


class _SyncTransportAdapter(httpx.AsyncBaseTransport):
    # 将同步 BaseTransport 适配到 AsyncClient，供模块层测试注入故障传输器
    def __init__(self, inner: httpx.BaseTransport) -> None:
        self._inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return self._inner.handle_request(request)

    async def aclose(self) -> None:
        self._inner.close()


def _add_common_network_arguments(parser: argparse.ArgumentParser, *, is_subparser: bool) -> None:
    str_default: Any = argparse.SUPPRESS if is_subparser else None
    bool_default: Any = argparse.SUPPRESS if is_subparser else False
    parser.add_argument("--url", default=str_default, help="running Yudao server URL (overrides YUDAO_URL)")
    parser.add_argument("--token", default=str_default, help="Bearer access token (overrides YUDAO_TOKEN)")
    parser.add_argument(
        "--token-stdin",
        action="store_true",
        default=bool_default,
        help="read single-line Bearer access token from standard input",
    )
    parser.add_argument(
        "--timeout",
        default=str_default,
        help="single request timeout in seconds (default 30, allowed 5-600)",
    )


def register_network_subcommands(
    root_parser: argparse.ArgumentParser,
    subparsers: Any,
) -> None:
    # 在根解析器与各网络子命令上同时登记公共连接参数，使选项写在子命令前后均生效
    _add_common_network_arguments(root_parser, is_subparser=False)

    cap = subparsers.add_parser("capabilities", help="fetch server capabilities over HTTP")
    _add_common_network_arguments(cap, is_subparser=True)

    desc = subparsers.add_parser("describe", help="inspect contract details for a single command or query")
    _add_common_network_arguments(desc, is_subparser=True)
    desc.add_argument("target_name", metavar="name", help="registered command or query name")

    qry = subparsers.add_parser("query", help="execute a registered read-only query over HTTP")
    _add_common_network_arguments(qry, is_subparser=True)
    qry.add_argument("target_name", metavar="name", help="registered query name")
    qry.add_argument(
        "--param",
        dest="query_params",
        action="append",
        default=None,
        metavar="KEY=VALUE",
        help="query filter parameter (repeatable for multi-value keys)",
    )
    qry.add_argument("--json", dest="json_payload", default=None, help="query parameters as a JSON object")
    qry.add_argument("--at", dest="at_position", default=None, help="optional replay log position")

    cmd = subparsers.add_parser("command", help="submit an idempotent command over HTTP")
    _add_common_network_arguments(cmd, is_subparser=True)
    cmd.add_argument("target_name", metavar="name", help="registered command name")
    cmd.add_argument(
        "--param",
        dest="command_params",
        action=_OrderedParamAction,
        param_kind="json",
        default=None,
        metavar="KEY=VALUE",
        help="command field (parsed as JSON literal, falling back to string)",
    )
    cmd.add_argument(
        "--string-param",
        dest="command_params",
        action=_OrderedParamAction,
        param_kind="string",
        default=None,
        metavar="KEY=VALUE",
        help="command field kept strictly as raw string",
    )
    cmd.add_argument("--json", dest="json_payload", default=None, help="command payload as a JSON object")
    cmd.add_argument(
        "--stdin",
        dest="payload_stdin",
        action="store_true",
        default=False,
        help="read command JSON object payload from standard input",
    )
    cmd.add_argument("--command-id", dest="command_id", default=None, help="explicit idempotency command UUID")


def _resolve_config(
    args: argparse.Namespace,
    *,
    stdin: TextIO,
    environ: Mapping[str, str],
) -> ClientConfig:
    explicit_token = getattr(args, "token", None)
    token_stdin = bool(getattr(args, "token_stdin", False))
    payload_stdin = bool(getattr(args, "payload_stdin", False))

    if explicit_token is not None and token_stdin:
        raise _CliArgumentError("参数冲突：--token 与 --token-stdin 不能同时指定")
    if token_stdin and payload_stdin:
        raise _CliArgumentError("参数冲突：--token-stdin 与 --stdin 不能同时占用标准输入")

    raw_url = getattr(args, "url", None)
    if raw_url is None:
        env_url = environ.get("YUDAO_URL", "").strip()
        raw_url = env_url if env_url else DEFAULT_SERVER_URL
    else:
        raw_url = str(raw_url).strip()

    base_url, is_loopback = _normalize_server_url(raw_url)
    timeout_sec = _parse_timeout(getattr(args, "timeout", None))

    token: str | None
    if explicit_token is not None:
        stripped = str(explicit_token).strip()
        token = stripped if stripped else None
    elif token_stdin:
        line = stdin.readline().strip()
        if not line:
            raise _CliArgumentError("参数错误：--token-stdin 未从标准输入读到有效令牌")
        token = line
    else:
        env_token = environ.get("YUDAO_TOKEN", "").strip()
        token = env_token if env_token else None

    return ClientConfig(
        base_url=base_url,
        token=token,
        timeout_sec=timeout_sec,
        is_loopback=is_loopback,
    )


def _normalize_server_url(raw_url: str) -> tuple[str, bool]:
    if not raw_url:
        raise _CliArgumentError("参数错误：服务地址不能为空")
    parts = urlsplit(raw_url)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or not parts.hostname:
        raise _CliArgumentError(f"参数错误：服务地址须包含 http 或 https 协议与主机名：{raw_url}")
    if parts.query or parts.fragment:
        raise _CliArgumentError(f"参数错误：服务根地址不能包含查询串或片段：{raw_url}")
    clean_path = parts.path.rstrip("/")
    normalized = urlunsplit((scheme, parts.netloc, clean_path, "", ""))
    is_loopback = parts.hostname.lower() in LOOPBACK_HOSTS
    return normalized, is_loopback


def _parse_timeout(raw_timeout: Any) -> float:
    if raw_timeout is None:
        return DEFAULT_TIMEOUT_SEC
    try:
        value = float(raw_timeout)
    except (TypeError, ValueError) as exc:
        raise _CliArgumentError(
            f"参数错误：--timeout 须为 {int(MIN_TIMEOUT_SEC)} 到 {int(MAX_TIMEOUT_SEC)} 秒之间的数值：{raw_timeout}"
        ) from exc
    if not math.isfinite(value) or value < MIN_TIMEOUT_SEC or value > MAX_TIMEOUT_SEC:
        raise _CliArgumentError(
            f"参数错误：--timeout 超出有效范围（允许 {int(MIN_TIMEOUT_SEC)}–{int(MAX_TIMEOUT_SEC)} 秒，收到 {raw_timeout}）"
        )
    return value


def _split_key_value(pair: str, flag_name: str) -> tuple[str, str]:
    key, sep, value = pair.partition("=")
    if not sep or not key:
        raise _CliArgumentError(f"参数错误：{flag_name} 须采用 key=value 格式：{pair}")
    return key, value


def _reject_non_finite_constant(token: str) -> Any:
    raise ValueError(f"non-finite JSON constant: {token}")


def _parse_json_or_string(raw_value: str) -> Any:
    if raw_value == "":
        return ""
    try:
        return json.loads(raw_value, parse_constant=_reject_non_finite_constant)
    except (ValueError, TypeError):
        return raw_value


def _build_query_params(args: argparse.Namespace) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    json_text = getattr(args, "json_payload", None)
    base_dict: dict[str, Any] = {}
    if json_text is not None:
        try:
            loaded = json.loads(json_text, parse_constant=_reject_non_finite_constant)
        except ValueError as exc:
            raise _CliArgumentError(f"参数错误：--json 须为合法 JSON 对象（行 {exc.lineno} 列 {exc.colno}）") from exc
        if not isinstance(loaded, dict):
            raise _CliArgumentError("参数错误：--json 查询参数须为 JSON 对象")
        base_dict = dict(loaded)

    cli_pairs_raw: list[str] = list(getattr(args, "query_params", None) or [])
    parsed_cli_pairs = [_split_key_value(item, "--param") for item in cli_pairs_raw]
    overridden_keys = {key for key, _ in parsed_cli_pairs}

    at_raw = getattr(args, "at_position", None)
    at_value: str | None = None
    if at_raw is not None:
        try:
            at_int = int(str(at_raw).strip())
        except ValueError as exc:
            raise _CliArgumentError(f"参数错误：--at 回放位置须为整数：{at_raw}") from exc
        at_value = str(at_int)
        overridden_keys.add("at")

    for key, val in base_dict.items():
        if key in overridden_keys or val is None:
            continue
        if isinstance(val, list):
            for elem in val:
                if elem is not None:
                    pairs.append((key, _stringify_query_scalar(elem)))
        else:
            pairs.append((key, _stringify_query_scalar(val)))

    pairs.extend(parsed_cli_pairs)
    if at_value is not None:
        pairs.append(("at", at_value))
    return pairs


def _stringify_query_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _build_command_payload(args: argparse.Namespace, *, stdin: TextIO) -> dict[str, Any]:
    json_text = getattr(args, "json_payload", None)
    use_stdin = bool(getattr(args, "payload_stdin", False))
    if json_text is not None and use_stdin:
        raise _CliArgumentError("参数冲突：--json 与 --stdin 不能同时指定")

    payload: dict[str, Any] = {}
    if json_text is not None:
        try:
            loaded = json.loads(json_text, parse_constant=_reject_non_finite_constant)
        except ValueError as exc:
            raise _CliArgumentError(f"参数错误：--json 载荷须为合法 JSON 对象（行 {exc.lineno} 列 {exc.colno}）") from exc
        if not isinstance(loaded, dict):
            raise _CliArgumentError("参数错误：--json 命令载荷须为 JSON 对象")
        payload.update(loaded)
    elif use_stdin:
        raw_stdin = stdin.read()
        try:
            loaded_stdin = json.loads(raw_stdin, parse_constant=_reject_non_finite_constant)
        except ValueError as exc:
            # 不在错误信息中回显标准输入原文，避免敏感凭据出现在错误输出中
            raise _CliArgumentError(
                f"参数错误：--stdin 标准输入须为合法 JSON 对象（行 {exc.lineno} 列 {exc.colno}）"
            ) from exc
        if not isinstance(loaded_stdin, dict):
            raise _CliArgumentError("参数错误：--stdin 标准输入载荷须为 JSON 对象")
        payload.update(loaded_stdin)

    ordered_params: list[tuple[str, str]] = list(getattr(args, "command_params", None) or [])
    for param_kind, raw_pair in ordered_params:
        flag_label = "--string-param" if param_kind == "string" else "--param"
        key, raw_val = _split_key_value(raw_pair, flag_label)
        payload[key] = raw_val if param_kind == "string" else _parse_json_or_string(raw_val)

    explicit_cid = getattr(args, "command_id", None)
    if explicit_cid is not None:
        cid_text = str(explicit_cid).strip()
        if not cid_text:
            raise _CliArgumentError("参数错误：--command-id 不能为空字符串")
        payload["command_id"] = cid_text
    else:
        existing_cid = payload.get("command_id")
        if existing_cid is None or (isinstance(existing_cid, str) and not existing_cid.strip()):
            payload["command_id"] = str(uuid.uuid4())

    return payload


def _adapt_transport(
    transport: httpx.BaseTransport | httpx.AsyncBaseTransport | None,
) -> httpx.AsyncBaseTransport | None:
    if transport is None:
        return None
    if isinstance(transport, httpx.AsyncBaseTransport):
        return transport
    if isinstance(transport, httpx.BaseTransport):
        return _SyncTransportAdapter(transport)
    raise TypeError(f"Unsupported transport type: {type(transport)!r}")


def _build_headers(config: ClientConfig, *, json_body: bool = False) -> dict[str, str]:
    headers: dict[str, str] = {"Accept": "application/json"}
    if config.token is not None:
        headers["Authorization"] = f"Bearer {config.token}"
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


def _extract_error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        text = response.text.strip()
        return text
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, str) and err.strip():
            return err.strip()
        msg = body.get("message")
        if isinstance(msg, str) and msg.strip():
            return msg.strip()
        detail = body.get("detail")
        if detail is not None:
            return json.dumps(detail, ensure_ascii=False)
    return json.dumps(body, ensure_ascii=False)


def _handle_common_http_errors(
    response: httpx.Response,
    *,
    config: ClientConfig,
    target_desc: str,
    stderr: TextIO,
) -> int | None:
    status = response.status_code
    if status == 200:
        return None
    if status == 401:
        print(
            f"认证失败（HTTP 401）：目标服务 {config.base_url} 需要有效的访问令牌（可通过 --token、--token-stdin 或环境变量 YUDAO_TOKEN 提供）",
            file=stderr,
        )
        return EXIT_CONNECTION_OR_AUTH
    if status == 403:
        print(
            f"访问被拒绝（HTTP 403）：目标服务 {config.base_url} 拒绝当前请求的主机头或来源（本机模式仅接受回环地址访问）",
            file=stderr,
        )
        return EXIT_CONNECTION_OR_AUTH
    if status == 404:
        detail = _extract_error_message(response)
        suffix = f"：{detail}" if detail else ""
        print(f"未找到目标（HTTP 404）：{target_desc}{suffix}", file=stderr)
        return EXIT_INVALID
    if status in (400, 405, 415, 422):
        detail = _extract_error_message(response)
        suffix = f"：{detail}" if detail else ""
        print(f"请求参数不符合接口合同（HTTP {status}，{target_desc}）{suffix}", file=stderr)
        return EXIT_INVALID
    if status >= 500:
        detail = _extract_error_message(response)
        suffix = f"：{detail}" if detail else ""
        print(f"服务端错误（HTTP {status}，目标 {config.base_url}）{suffix}", file=stderr)
        return EXIT_CONNECTION_OR_AUTH
    detail = _extract_error_message(response)
    suffix = f"：{detail}" if detail else ""
    print(f"未预期的响应状态（HTTP {status}，{target_desc}）{suffix}", file=stderr)
    return EXIT_INVALID


def _ref_name(ref_uri: str) -> str:
    return ref_uri.rsplit("/", 1)[-1]


def _resolve_schema(
    schema: Mapping[str, Any],
    schemas: Mapping[str, Any],
) -> tuple[str | None, Mapping[str, Any]]:
    ref = schema.get("$ref")
    if isinstance(ref, str):
        name = _ref_name(ref)
        target = schemas.get(name)
        if isinstance(target, Mapping):
            return name, target
        return name, {}
    return None, schema


def _describe_schema_type(schema: Mapping[str, Any], schemas: Mapping[str, Any]) -> str:
    ref_name, resolved = _resolve_schema(schema, schemas)
    any_of = resolved.get("anyOf")
    if isinstance(any_of, list) and any_of:
        parts: list[str] = []
        for branch in any_of:
            if isinstance(branch, Mapping):
                branch_type = _describe_schema_type(branch, schemas)
                if branch_type not in parts:
                    parts.append(branch_type)
        if parts:
            return " | ".join(parts)

    schema_type = resolved.get("type")
    if schema_type == "array":
        items = resolved.get("items")
        if isinstance(items, Mapping):
            return f"array<{_describe_schema_type(items, schemas)}>"
        return "array"
    if schema_type == "object" or "properties" in resolved:
        return ref_name if ref_name is not None else "object"
    if isinstance(schema_type, str):
        return schema_type
    if ref_name is not None:
        return ref_name
    return "any"


def _extract_enum_values(schema: Mapping[str, Any], schemas: Mapping[str, Any]) -> list[Any] | None:
    _ref, resolved = _resolve_schema(schema, schemas)
    direct_enum = resolved.get("enum")
    if isinstance(direct_enum, list):
        return list(direct_enum)
    if "const" in resolved and resolved["const"] is not None:
        return [resolved["const"]]

    items = resolved.get("items")
    if isinstance(items, Mapping):
        item_enum = _extract_enum_values(items, schemas)
        if item_enum is not None:
            return item_enum

    any_of = resolved.get("anyOf")
    if isinstance(any_of, list):
        collected: list[Any] = []
        for branch in any_of:
            if isinstance(branch, Mapping):
                branch_enum = _extract_enum_values(branch, schemas)
                if branch_enum:
                    for val in branch_enum:
                        if val not in collected:
                            collected.append(val)
        if collected:
            return collected
    return None


def _extract_nested_fields(
    schema: Mapping[str, Any],
    schemas: Mapping[str, Any],
    *,
    seen_refs: frozenset[str],
) -> list[dict[str, Any]] | None:
    ref_name, resolved = _resolve_schema(schema, schemas)
    if ref_name is not None:
        if ref_name in seen_refs:
            return None
        next_seen = seen_refs | {ref_name}
    else:
        next_seen = seen_refs

    properties = resolved.get("properties")
    if isinstance(properties, Mapping):
        return _extract_object_fields(resolved, schemas, seen_refs=next_seen)

    if resolved.get("type") == "array" and isinstance(resolved.get("items"), Mapping):
        return _extract_nested_fields(resolved["items"], schemas, seen_refs=next_seen)

    any_of = resolved.get("anyOf")
    if isinstance(any_of, list):
        for branch in any_of:
            if isinstance(branch, Mapping) and branch.get("type") != "null":
                nested = _extract_nested_fields(branch, schemas, seen_refs=next_seen)
                if nested is not None:
                    return nested
    return None


def _build_field_entry(
    name: str,
    schema: Mapping[str, Any],
    schemas: Mapping[str, Any],
    *,
    required: bool,
    outer_description: str | None = None,
    seen_refs: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    _ref, resolved = _resolve_schema(schema, schemas)
    default_val = schema.get("default", resolved.get("default", None))
    description = (
        outer_description
        or schema.get("description")
        or resolved.get("description")
        or schema.get("title")
        or resolved.get("title")
        or ""
    )
    entry: dict[str, Any] = {
        "name": name,
        "type": _describe_schema_type(schema, schemas),
        "required": required,
        "default": default_val,
        "enum": _extract_enum_values(schema, schemas),
        "description": str(description),
    }
    nested = _extract_nested_fields(schema, schemas, seen_refs=seen_refs)
    if nested is not None:
        entry["fields"] = nested
    return entry


def _extract_object_fields(
    object_schema: Mapping[str, Any],
    schemas: Mapping[str, Any],
    *,
    seen_refs: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    ref_name, resolved = _resolve_schema(object_schema, schemas)
    active_seen = seen_refs | ({ref_name} if ref_name is not None else set())
    properties = resolved.get("properties")
    if not isinstance(properties, Mapping):
        return []
    required_set = set(resolved.get("required") or ())
    fields: list[dict[str, Any]] = []
    for prop_name, prop_schema in properties.items():
        if not isinstance(prop_schema, Mapping):
            continue
        fields.append(
            _build_field_entry(
                str(prop_name),
                prop_schema,
                schemas,
                required=prop_name in required_set,
                seen_refs=active_seen,
            )
        )
    return fields


def _extract_response_summary(
    operation: Mapping[str, Any],
    schemas: Mapping[str, Any],
) -> dict[str, Any]:
    resp_200 = (
        operation.get("responses", {})
        .get("200", {})
        .get("content", {})
        .get("application/json", {})
        .get("schema", {})
    )
    if not isinstance(resp_200, Mapping) or not resp_200:
        return {"schema": None, "type": "object", "fields": []}
    ref_name, resolved = _resolve_schema(resp_200, schemas)
    title = resolved.get("title") or ref_name
    seen = frozenset({ref_name}) if ref_name is not None else frozenset()
    return {
        "schema": title,
        "type": _describe_schema_type(resp_200, schemas),
        "fields": _extract_object_fields(resolved, schemas, seen_refs=seen),
    }


def _build_describe_document(
    target_name: str,
    capabilities: Mapping[str, Any],
    openapi: Mapping[str, Any],
) -> dict[str, Any] | None:
    commands_map = {
        str(item["name"]): item
        for item in capabilities.get("commands", [])
        if isinstance(item, Mapping) and "name" in item
    }
    queries_map = {
        str(item["name"]): item
        for item in capabilities.get("queries", [])
        if isinstance(item, Mapping) and "name" in item
    }
    schemas = openapi.get("components", {}).get("schemas", {})
    if not isinstance(schemas, Mapping):
        schemas = {}
    paths = openapi.get("paths", {})
    if not isinstance(paths, Mapping):
        paths = {}

    if target_name in commands_map:
        cmd_meta = commands_map[target_name]
        operation = paths.get(f"/api/commands/{target_name}", {}).get("post", {})
        req_schema = (
            operation.get("requestBody", {})
            .get("content", {})
            .get("application/json", {})
            .get("schema", {})
        )
        request_fields = (
            _extract_object_fields(req_schema, schemas)
            if isinstance(req_schema, Mapping)
            else []
        )
        return {
            "kind": "command",
            "name": target_name,
            "request": request_fields,
            "response": _extract_response_summary(operation, schemas),
            "rejections": list(cmd_meta.get("reasons", [])),
        }

    if target_name in queries_map:
        qry_meta = queries_map[target_name]
        operation = paths.get(f"/api/queries/{target_name}", {}).get("get", {})
        parameters = operation.get("parameters", [])
        request_fields = []
        if isinstance(parameters, list):
            for param in parameters:
                if not isinstance(param, Mapping) or param.get("in") != "query":
                    continue
                p_name = str(param.get("name", ""))
                p_schema = param.get("schema", {})
                if not p_name or not isinstance(p_schema, Mapping):
                    continue
                request_fields.append(
                    _build_field_entry(
                        p_name,
                        p_schema,
                        schemas,
                        required=bool(param.get("required", False)),
                        outer_description=param.get("description"),
                    )
                )
        return {
            "kind": "query",
            "name": target_name,
            "request": request_fields,
            "response": _extract_response_summary(operation, schemas),
            "refresh_on": list(qry_meta.get("changed_by", [])),
            "replayable": bool(qry_meta.get("replayable", False)),
        }

    return None


def _format_unknown_describe_hint(target_name: str, capabilities: Mapping[str, Any]) -> str:
    cmd_names = sorted(
        str(item["name"])
        for item in capabilities.get("commands", [])
        if isinstance(item, Mapping) and "name" in item
    )
    qry_names = sorted(
        str(item["name"])
        for item in capabilities.get("queries", [])
        if isinstance(item, Mapping) and "name" in item
    )
    prefix = target_name.partition(".")[0]
    lines = [f"未知的命令或查询名称：{target_name}"]
    if prefix:
        prefix_dot = f"{prefix}."
        matched = [
            name for name in (*cmd_names, *qry_names)
            if name == prefix or name.startswith(prefix_dot)
        ]
        if matched:
            lines.append(f"同前缀（{prefix}）可用名称：{', '.join(matched)}")
    lines.append(f"可用命令（{len(cmd_names)} 项）：{', '.join(cmd_names)}")
    lines.append(f"可用查询（{len(qry_names)} 项）：{', '.join(qry_names)}")
    return "\n".join(lines)


def _write_json(stdout: TextIO, data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2), file=stdout)


async def _run_async_command(
    args: argparse.Namespace,
    config: ClientConfig,
    *,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
    transport: httpx.AsyncBaseTransport | None,
) -> int:
    command = args.command
    query_params: list[tuple[str, str]] = []
    command_payload: dict[str, Any] = {}
    if command == "query":
        query_params = _build_query_params(args)
    elif command == "command":
        command_payload = _build_command_payload(args, stdin=stdin)

    client_kwargs: dict[str, Any] = {
        "base_url": config.base_url,
        "timeout": httpx.Timeout(config.timeout_sec),
        # 访问本机回环地址时绕过环境变量代理（trust_env=False），且不附带 Origin 头
        "trust_env": not config.is_loopback,
    }
    if transport is not None:
        client_kwargs["transport"] = transport

    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            if command == "capabilities":
                resp = await client.get("/api/capabilities", headers=_build_headers(config))
                err_code = _handle_common_http_errors(
                    resp,
                    config=config,
                    target_desc="GET /api/capabilities",
                    stderr=stderr,
                )
                if err_code is not None:
                    return err_code
                _write_json(stdout, resp.json())
                return EXIT_OK

            if command == "describe":
                target_name = str(args.target_name)
                cap_resp = await client.get("/api/capabilities", headers=_build_headers(config))
                cap_err = _handle_common_http_errors(
                    cap_resp,
                    config=config,
                    target_desc="GET /api/capabilities",
                    stderr=stderr,
                )
                if cap_err is not None:
                    return cap_err
                capabilities = cap_resp.json()

                oa_resp = await client.get("/openapi.json", headers=_build_headers(config))
                oa_err = _handle_common_http_errors(
                    oa_resp,
                    config=config,
                    target_desc="GET /openapi.json",
                    stderr=stderr,
                )
                if oa_err is not None:
                    return oa_err
                openapi = oa_resp.json()

                doc = _build_describe_document(target_name, capabilities, openapi)
                if doc is None:
                    print(_format_unknown_describe_hint(target_name, capabilities), file=stderr)
                    return EXIT_INVALID
                _write_json(stdout, doc)
                return EXIT_OK

            if command == "query":
                target_name = str(args.target_name)
                encoded_name = quote(target_name, safe="._-~")
                resp = await client.get(
                    f"/api/queries/{encoded_name}",
                    params=query_params,
                    headers=_build_headers(config),
                )
                err_code = _handle_common_http_errors(
                    resp,
                    config=config,
                    target_desc=f"查询 {target_name}",
                    stderr=stderr,
                )
                if err_code is not None:
                    return err_code
                _write_json(stdout, resp.json())
                return EXIT_OK

            if command == "command":
                target_name = str(args.target_name)
                encoded_name = quote(target_name, safe="._-~")
                body_bytes = json.dumps(command_payload, ensure_ascii=False).encode("utf-8")
                resp = await client.post(
                    f"/api/commands/{encoded_name}",
                    content=body_bytes,
                    headers=_build_headers(config, json_body=True),
                )
                if resp.status_code == 409:
                    # 业务拒绝（Rejected）：标准输出完整打印拒绝原因与说明 JSON，返回退出码 1
                    _write_json(stdout, resp.json())
                    return EXIT_REJECTED
                err_code = _handle_common_http_errors(
                    resp,
                    config=config,
                    target_desc=f"命令 {target_name}",
                    stderr=stderr,
                )
                if err_code is not None:
                    return err_code
                _write_json(stdout, resp.json())
                return EXIT_OK

    except httpx.TimeoutException as exc:
        print(
            f"请求超时：连接目标服务 {config.base_url} 超过时限（{config.timeout_sec:g} 秒）：{exc}",
            file=stderr,
        )
        return EXIT_CONNECTION_OR_AUTH
    except httpx.RequestError as exc:
        print(
            f"连接失败：无法访问目标服务 {config.base_url}：{exc}",
            file=stderr,
        )
        return EXIT_CONNECTION_OR_AUTH

    print(f"未知网络子命令：{command}", file=stderr)
    return EXIT_INVALID


def execute_network_command(
    args: argparse.Namespace,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    environ: Mapping[str, str] | None = None,
    transport: httpx.BaseTransport | httpx.AsyncBaseTransport | None = None,
) -> int:
    in_stream = sys.stdin if stdin is None else stdin
    out_stream = sys.stdout if stdout is None else stdout
    err_stream = sys.stderr if stderr is None else stderr
    env_map = os.environ if environ is None else environ

    try:
        config = _resolve_config(args, stdin=in_stream, environ=env_map)
        adapted_transport = _adapt_transport(transport)
        return asyncio.run(
            _run_async_command(
                args,
                config,
                stdin=in_stream,
                stdout=out_stream,
                stderr=err_stream,
                transport=adapted_transport,
            )
        )
    except _CliArgumentError as exc:
        print(str(exc), file=err_stream)
        return EXIT_INVALID
