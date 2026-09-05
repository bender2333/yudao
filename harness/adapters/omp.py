"""OMP RPC/NDJSON adapter。未配置时报告 provider-unavailable，不降级到 fake。"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from typing import Any, Iterator
from uuid import uuid4

from ..models import Usage, estimate_tokens, json_dumps
from ..redact import redact_text
from ..tools import SUBMIT_KINDS, ToolRuntime, host_tool_definitions
from .base import AdapterResult, Availability, InvokeRequest, ProviderError
from .rpc_process import RpcAborted, RpcExited, RpcProcess, RpcTimeout

UNAVAILABLE_MESSAGE = (
    "OMP RPC 未配置。要使用真实模型，请设置 YUDAO_OMP_ENABLED=1，"
    "并确保 YUDAO_OMP_COMMAND（默认 omp）可执行；可选 YUDAO_OMP_PROVIDER 与 YUDAO_OMP_MODEL。"
    "系统不会在 OMP 不可用时静默改用 fake adapter。"
)

ISOLATION_FLAGS = ("--no-tools", "--no-lsp", "--no-session", "--no-extensions", "--no-skills", "--no-rules")


@dataclass
class OmpConfig:
    command: list[str]
    provider: str | None = None
    model: str | None = None
    enabled: bool = False
    timeout_sec: float = 180.0

    @classmethod
    def from_env(cls) -> OmpConfig:
        enabled = os.environ.get("YUDAO_OMP_ENABLED", "").strip().lower() in {"1", "true", "yes"}
        raw_command = os.environ.get("YUDAO_OMP_COMMAND", "omp").strip() or "omp"
        extra = os.environ.get("YUDAO_OMP_ARGS", "").strip()
        command = [raw_command]
        if extra:
            command.extend(extra.split())
        if "--mode" not in command:
            command.extend(["--mode", "rpc"])
        for flag in ISOLATION_FLAGS:
            if flag not in command:
                command.append(flag)
        return cls(
            command=command,
            provider=os.environ.get("YUDAO_OMP_PROVIDER") or None,
            model=os.environ.get("YUDAO_OMP_MODEL") or None,
            enabled=enabled,
            timeout_sec=float(os.environ.get("YUDAO_OMP_TIMEOUT", "180")),
        )

    @property
    def binary(self) -> str:
        return self.command[0]


def map_omp_failure(exc: BaseException) -> tuple[str, str]:
    """把 OMP/进程错误映射到闭合停止原因。"""
    if isinstance(exc, ProviderError):
        return exc.reason, redact_text(str(exc))
    if isinstance(exc, FileNotFoundError):
        return "provider_unavailable", f"未找到 OMP 可执行文件: {exc}"
    text = str(exc).lower()
    if "not configured" in text or "unconfigured" in text or "provider-unavailable" in text:
        return "provider_unavailable", redact_text(str(exc))
    if "abort" in text or "cancelled" in text or "canceled" in text:
        return "cancelled", redact_text(str(exc))
    if "context" in text and ("overflow" in text or "too long" in text or "window" in text):
        return "context_overflow", redact_text(str(exc))
    return "provider_error", redact_text(str(exc))


def encode_frame(obj: dict[str, Any]) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def iter_logical_frames(lines: Iterator[str], *, max_reassembled: int = 67_108_864) -> Iterator[dict[str, Any]]:
    reassembler = FrameReassembler(max_reassembled=max_reassembled)
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        frame = json.loads(line)
        assembled = reassembler.push(frame)
        if assembled is not None:
            yield assembled


class FrameReassembler:
    def __init__(self, *, max_reassembled: int = 67_108_864) -> None:
        self.max_reassembled = max_reassembled
        self._chunks: dict[str, dict[str, Any]] = {}

    def push(self, frame: dict[str, Any]) -> dict[str, Any] | None:
        if frame.get("type") != "rpc_chunk":
            return frame
        chunk_id = frame["chunkId"]
        bucket = self._chunks.setdefault(
            chunk_id, {"parts": {}, "count": frame["count"], "byteLength": frame["byteLength"]}
        )
        bucket["parts"][frame["index"]] = frame["data"]
        if len(bucket["parts"]) != bucket["count"]:
            return None
        import base64

        ordered = "".join(bucket["parts"][index] for index in range(bucket["count"]))
        data = base64.b64decode(ordered)
        if len(data) > self.max_reassembled:
            raise ProviderError("OMP frame exceeds reassembly limit", reason="context_overflow")
        del self._chunks[chunk_id]
        return json.loads(data.decode("utf-8"))


class OmpRpcAdapter:
    name = "omp"

    def __init__(self, config: OmpConfig | None = None) -> None:
        self.config = config if config is not None else OmpConfig.from_env()
        self.model = self.config.model or "unconfigured"
        self._abort = __import__("threading").Event()
        self._session: RpcProcess | None = None

    def availability(self) -> Availability:
        if not self.config.enabled:
            return Availability(False, "provider_unavailable", UNAVAILABLE_MESSAGE)
        binary = self.config.binary
        if os.path.sep in binary or (len(binary) >= 2 and binary[1] == ":"):
            exists = os.path.isfile(binary)
        else:
            exists = shutil.which(binary) is not None
        if not exists:
            return Availability(
                False,
                "provider_unavailable",
                f"未找到 OMP 可执行文件 {binary!r}。{UNAVAILABLE_MESSAGE}",
            )
        return Availability(True)

    def abort(self, session_id: str) -> None:
        self._abort.set()
        session = self._session
        if session is None:
            return
        try:
            session.send({"type": "abort", "id": "abort-1"})
        except ProviderError:
            pass

    def invoke(self, request: InvokeRequest) -> AdapterResult:
        availability = self.availability()
        if not availability.available:
            raise ProviderError(availability.message, reason=availability.reason or "provider_unavailable")
        self._abort.clear()
        abort_flag = _combined_flag(request.abort_flag, self._abort)
        try:
            return self._invoke_process(request, abort_flag)
        except ProviderError:
            raise
        except Exception as exc:
            reason, message = map_omp_failure(exc)
            raise ProviderError(message, reason=reason) from exc

    def _invoke_process(self, request: InvokeRequest, abort_flag) -> AdapterResult:
        command = _launch_command(self.config)
        session = RpcProcess.spawn(
            command,
            cwd=str(request.workspace.root),
            env=os.environ.copy(),
            abort_flag=abort_flag,
        )
        self._session = session
        started = time.monotonic()
        deadline = started + self.config.timeout_sec
        runtime = ToolRuntime(request.workspace)
        reassembler = FrameReassembler()
        try:
            ready = self._wait_ready(session, min(deadline, started + min(self.config.timeout_sec, 15)))
            protocol = 1
            if 2 in (ready.get("supportedProtocolVersions") or []):
                negotiate_id = _rid("protocol")
                session.send({"id": negotiate_id, "type": "negotiate_protocol", "protocolVersion": 2})
                self._wait_command(session, deadline, negotiate_id, "negotiate_protocol", reassembler, runtime, request)
                protocol = 2
            tools_id = _rid("tools")
            definitions = host_tool_definitions(request.tools)
            session.send({"id": tools_id, "type": "set_host_tools", "tools": definitions})
            self._wait_command(session, deadline, tools_id, "set_host_tools", reassembler, runtime, request)
            prompt = _build_prompt(request)
            prompt_id = request.activation_id or _rid("prompt")
            session.send({"id": prompt_id, "type": "prompt", "message": prompt})
            transcript_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            usage = Usage(input_tokens=estimate_tokens(prompt))
            proposal: dict[str, Any] | None = None
            finish: str | None = None
            error = None
            last_frames: list[str] = []
            while True:
                try:
                    frame = self._next_frame(session, deadline, reassembler)
                except RpcTimeout as exc:
                    raise RpcTimeout(
                        f"{exc}; last_frames={last_frames[-8:] or ['<none>']}"
                    ) from exc
                last_frames.append(str(frame.get("type") or "unknown"))
                if frame.get("type") == "host_tool_call":
                    submitted = self._handle_host_tool(session, frame, runtime, request, tool_calls)
                    if submitted is not None:
                        proposal = submitted
                    continue
                if frame.get("type") == "host_tool_cancel":
                    continue
                if frame.get("type") == "extension_ui_request":
                    session.send({"type": "extension_ui_response", "id": frame.get("id"), "cancelled": True})
                    continue
                mapped = map_omp_frame(frame)
                if mapped.get("proposal"):
                    if proposal is None or not _is_submit_proposal(proposal):
                        proposal = mapped["proposal"]
                if mapped.get("text"):
                    transcript_parts.append(mapped["text"])
                if mapped.get("tool_call"):
                    tool_calls.append(mapped["tool_call"])
                if mapped.get("usage"):
                    usage = mapped["usage"]
                if mapped.get("finish_reason"):
                    finish = mapped["finish_reason"]
                    error = mapped.get("error")
                    break
                if mapped.get("error") and mapped.get("fatal"):
                    raise ProviderError(mapped["error"], reason=mapped.get("reason") or "provider_error")
                if frame.get("type") == "response" and frame.get("id") == prompt_id and frame.get("success") is False:
                    raise ProviderError(
                        redact_text(str(frame.get("error") or "OMP prompt failed")),
                        reason="provider_error",
                    )
            if finish is None:
                raise ProviderError(
                    redact_text(session.diagnostics() or "OMP RPC ended without agent_end"),
                    reason="provider_error",
                )
            elapsed = int((time.monotonic() - started) * 1000)
            usage.latency_ms = elapsed
            if usage.total_tokens == 0:
                usage.output_tokens = estimate_tokens("".join(transcript_parts))
                usage.total_tokens = usage.input_tokens + usage.output_tokens
            return AdapterResult(
                proposal=proposal,
                transcript="".join(transcript_parts),
                tool_calls=tool_calls,
                usage=usage,
                finish_reason=finish,
                error=error,
                provider=self.name,
                model=self.config.model or f"omp-protocol-v{protocol}",
            )
        except RpcAborted:
            session.kill()
            return AdapterResult(None, finish_reason="aborted", error="aborted", provider=self.name, model=self.config.model or "omp")
        except (RpcTimeout, RpcExited) as exc:
            session.kill()
            raise ProviderError(redact_text(str(exc)), reason=exc.reason) from exc
        finally:
            session.close()
            self._session = None

    def _wait_ready(self, session: RpcProcess, deadline: float) -> dict[str, Any]:
        reassembler = FrameReassembler()
        try:
            while True:
                frame = self._next_frame(session, deadline, reassembler)
                if frame.get("type") == "ready":
                    return frame
        except (RpcExited, RpcTimeout) as exc:
            session.kill()
            extra = session.diagnostics()
            message = str(exc)
            if extra and extra not in message:
                message = f"{message}: {extra}"
            raise ProviderError(f"OMP RPC did not emit a ready frame: {message}", reason=exc.reason) from exc

    def _wait_command(
        self,
        session: RpcProcess,
        deadline: float,
        command_id: str,
        command: str,
        reassembler: FrameReassembler,
        runtime: ToolRuntime,
        request: InvokeRequest,
    ) -> dict[str, Any]:
        while True:
            frame = self._next_frame(session, deadline, reassembler)
            if frame.get("type") == "host_tool_call":
                self._handle_host_tool(session, frame, runtime, request, [])
                continue
            if frame.get("type") == "response" and frame.get("id") == command_id:
                if frame.get("success") is False:
                    raise ProviderError(
                        redact_text(str(frame.get("error") or f"OMP {command} failed")),
                        reason="provider_error",
                    )
                return frame

    def _next_frame(self, session: RpcProcess, deadline: float, reassembler: FrameReassembler) -> dict[str, Any]:
        while True:
            raw = session.wait_frame(deadline)
            assembled = reassembler.push(raw)
            if assembled is not None:
                return assembled

    def _handle_host_tool(
        self,
        session: RpcProcess,
        frame: dict[str, Any],
        runtime: ToolRuntime,
        request: InvokeRequest,
        tool_calls: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        request_id = str(frame.get("id") or "")
        name = str(frame.get("toolName") or "")
        arguments = frame.get("arguments") if isinstance(frame.get("arguments"), dict) else {}
        result = runtime.execute(request.department, name, arguments)
        recorded = {
            "name": name,
            "id": frame.get("toolCallId") or request_id,
            "ok": result.ok,
            "error": result.error,
            "args": _public_args(name, arguments),
        }
        if isinstance(result.output, dict) and result.output.get("exit_code") is not None:
            recorded["exit_code"] = result.output.get("exit_code")
            recorded["snapshot_hash"] = result.output.get("snapshot_hash")
            recorded["executor"] = result.output.get("executor")
        tool_calls.append(recorded)
        session.send(_host_tool_result_frame(request_id, result.ok, result.output, result.error))
        if result.ok and name in SUBMIT_KINDS and isinstance(result.output, dict) and result.output.get("kind"):
            return result.output
        return None


def _launch_command(config: OmpConfig) -> list[str]:
    command = list(config.command)
    if config.provider and "--provider" not in command:
        command.extend(["--provider", config.provider])
    if config.model and "--model" not in command:
        command.extend(["--model", config.model])
    for flag in ISOLATION_FLAGS:
        if flag not in command:
            command.append(flag)
    return command


def _combined_flag(left, right):
    if left is right:
        return left

    class _Combined:
        def is_set(self) -> bool:
            return left.is_set() or right.is_set()

        def set(self) -> None:
            left.set()
            right.set()

        def clear(self) -> None:
            left.clear()
            right.clear()

    return _Combined()


def _build_prompt(request: InvokeRequest) -> str:
    return (
        request.context.prompt_text
        + "\n\n使用当前部门的 submit_* 工具提交结构化合同，或输出一个含 kind 的 JSON 对象。"
        + "自然语言不能宣布任务完成。检查必须通过 run_check/collect_evidence 由主机执行。"
        + "可用工具: "
        + ", ".join(request.tools)
    )


def _rid(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def _is_submit_proposal(proposal: dict[str, Any]) -> bool:
    return proposal.get("kind") in set(SUBMIT_KINDS.values())


def _public_args(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "write_file":
        return {"path": arguments.get("path")}
    if name in {"run_check", "collect_evidence"}:
        return {"name": arguments.get("name"), "argv": arguments.get("argv") or arguments.get("command")}
    return {key: value for key, value in arguments.items() if key != "content"}


def _host_tool_result_frame(request_id: str, ok: bool, output: Any, error: str | None) -> dict[str, Any]:
    if ok:
        if isinstance(output, str):
            text = output
            details: Any = {}
        else:
            text = json_dumps(output)
            details = output if isinstance(output, dict) else {"value": output}
    else:
        text = error or "tool failed"
        details = {}
    if len(text) > 20_000:
        text = text[:20_000] + "\n...truncated..."
    return {
        "type": "host_tool_result",
        "id": request_id,
        "result": {"content": [{"type": "text", "text": text}], "details": details},
        "isError": not ok,
    }


def map_omp_frame(frame: dict[str, Any]) -> dict[str, Any]:
    """把单条 NDJSON 帧映射为 Yudao adapter 片段。"""
    ftype = frame.get("type")
    result: dict[str, Any] = {}
    if ftype == "response" and frame.get("success") is False:
        error = redact_text(str(frame.get("error") or "OMP command failed"))
        result["error"] = error
        result["reason"] = map_omp_failure(ProviderError(error))[0]
        command = frame.get("command")
        if command in {"prompt", "abort", "set_host_tools", "negotiate_protocol"}:
            result["fatal"] = True
        return result
    if ftype in {"agent_end", "agent_settled"}:
        result["finish_reason"] = "completed"
        messages = frame.get("messages")
        if isinstance(messages, list):
            for message in reversed(messages):
                if not isinstance(message, dict) or message.get("role") != "assistant":
                    continue
                extracted = _extract_message(message)
                if extracted.get("text"):
                    result["text"] = extracted["text"]
                if extracted.get("proposal"):
                    result["proposal"] = extracted["proposal"]
                if extracted.get("usage"):
                    result["usage"] = extracted["usage"]
                if extracted.get("finish_reason"):
                    result["finish_reason"] = extracted["finish_reason"]
                break
        return result
    if ftype == "agent_start":
        return result
    if ftype in {"message_update", "message"}:
        text = _extract_text(frame)
        if text:
            result["text"] = text
            extracted = extract_json_proposal(text)
            if extracted:
                result["proposal"] = extracted
        return result
    if ftype == "message_end":
        message = frame.get("message")
        if isinstance(message, dict) and message.get("role") == "assistant":
            return _extract_message(message)
        return result
    if ftype == "tool_call":
        result["tool_call"] = {
            "name": frame.get("name") or frame.get("tool") or frame.get("toolName"),
            "id": frame.get("id") or frame.get("toolCallId"),
            "ok": True,
        }
        return result
    if ftype in {"error", "extension_error"}:
        error = redact_text(str(frame.get("error") or frame.get("message") or "OMP error"))
        result["error"] = error
        result["fatal"] = True
        result["reason"] = map_omp_failure(ProviderError(error))[0]
        if "overflow" in error.lower() or "context" in error.lower():
            result["reason"] = "context_overflow"
            result["finish_reason"] = "overflow"
        return result
    return result


def _extract_text(frame: dict[str, Any]) -> str:
    message = frame.get("message") or frame.get("delta") or frame.get("text") or ""
    if isinstance(message, str):
        return message
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and item.get("text"):
                    parts.append(str(item["text"]))
            return "".join(parts)
    return ""


def _extract_message(message: dict[str, Any]) -> dict[str, Any]:
    """Extract assistant text, proposal, usage, and stop reason from OMP message frames."""
    content = message.get("content")
    text_parts: list[str] = []
    if isinstance(content, str):
        text_parts.append(content)
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, str):
                text_parts.append(item)
            elif isinstance(item, dict) and item.get("type") in {"text", "output_text"} and item.get("text"):
                text_parts.append(str(item["text"]))
    text = "".join(text_parts)
    result: dict[str, Any] = {}
    if text:
        result["text"] = text
        proposal = extract_json_proposal(text)
        if proposal:
            result["proposal"] = proposal
    usage = message.get("usage")
    if isinstance(usage, dict):
        input_tokens = _number(usage.get("input", usage.get("input_tokens")))
        output_tokens = _number(usage.get("output", usage.get("output_tokens")))
        total_tokens = _number(usage.get("totalTokens", usage.get("total_tokens")))
        cost = usage.get("cost")
        if isinstance(cost, dict):
            cost = cost.get("total", 0)
        result["usage"] = Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens or input_tokens + output_tokens,
            cost=float(cost or 0),
        )
    stop_reason = message.get("stopReason")
    if stop_reason == "error":
        result["finish_reason"] = "error"
        result["error"] = message.get("errorMessage") or "OMP assistant message failed"
    return result


def _number(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def extract_json_proposal(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    if isinstance(obj, dict) and obj.get("kind"):
        return obj
    return None
