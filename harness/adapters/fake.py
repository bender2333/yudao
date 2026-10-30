from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator, Callable, Generator, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from ..models import Usage, json_dumps
from ..providers.call import CallUsage, ModelCall, ModelResponse, ModelStreamEvent
from ..tools import submit_tool
from .base import Availability, ProviderError

# 确定性的模型回答；工具仍由原生循环执行。脚本的一项可以是回答本身，也可以是接收模型调用合同的函数；
# 函数若是生成器，先逐条交出流式输出（ModelStreamEvent），最后 return 回答
TurnFactory = Callable[[ModelCall], "FakeTurn | dict[str, Any] | ModelResponse | Generator"]
TurnSpec = "FakeTurn | dict[str, Any] | ModelResponse | TurnFactory | BaseException"

# 一条按先后排队的列表脚本被工程与质检同时取用时，谁拿到哪一项随调度变化（工单 #557），
# 用例时好时坏，坏的时候报的是别处的错。假模型记下这件事（工单 #879）：
#   - 在进程内：由 harness/tests/conftest.py 在用例结束时核对，让用例失败
#   - 在子进程里：写进子进程的输出，父进程读到以后让用例失败
SHARED_LIST_SCRIPT_PREFIX = "假模型的列表脚本被工程与质检同时取用"

_SHARED_LIST_SCRIPTS: list[str] = []


def shared_list_scripts() -> list[str]:
    """这一轮里被工程与质检同时取用的列表脚本（工单 #879）。"""
    return list(_SHARED_LIST_SCRIPTS)


def clear_shared_list_scripts() -> None:
    """清掉记下的违反（工单 #879）：用例开始时调用。"""
    _SHARED_LIST_SCRIPTS.clear()


@dataclass
class FakeTurn:
    proposal: dict[str, Any] | None = None
    writes: dict[str, str] = field(default_factory=dict)
    checks: dict[str, int | dict[str, Any]] = field(default_factory=dict)
    transcript: str = ""
    usage: Usage | None = None
    finish_reason: str = "completed"
    error: str | None = None
    raise_error: ProviderError | None = None


def prompt_parts(call: ModelCall) -> dict[str, str]:
    # 假模型与真实模型一样只读自己收到的请求：本步装配的部门材料是以「[intend]」开头的那条消息，
    # 每段以「[来源]」一行开头，段之间空一行
    material = next((item["content"] for item in call.input_items
                     if isinstance(item.get("content"), str) and item["content"].startswith("[intend]\n")), "")
    parts: dict[str, str] = {}
    for segment in ("\n\n" + material).split("\n\n[")[1:]:
        source, separator, text = segment.partition("]\n")
        if separator:
            parts.setdefault(source, text)
    return parts


def prompt_part(call: ModelCall, source: str) -> str | None:
    return prompt_parts(call).get(source)


def received_images(call: ModelCall) -> list[dict[str, Any]]:
    # 这次调用收到的图像内容块：工具结果带图像时，它的输出是文字块与图像块组成的列表
    # （浏览器与 computer use 设计说明第 6.2 节）。测试按它核对模型实际看到了哪几张
    images: list[dict[str, Any]] = []
    for item in call.input_items:
        output = item.get("output")
        if not isinstance(output, list):
            continue
        images.extend(part for part in output
                      if isinstance(part, dict) and part.get("type") == "input_image")
    return images


def session_key(call: ModelCall) -> str:
    # 会话身份：主线按部门区分，询问分支按所属询问区分
    if call.session_id.startswith("ses_ask_"):
        return f"{call.department}:ask"
    return call.department


class FakeAdapter:
    name = "fake"
    model = "fake-script"
    def __init__(self, script: Sequence[TurnSpec] | Mapping[str, Sequence[TurnSpec]] | None = None, *,
                 stream_gap_sec: float = 0.0) -> None:
        # 脚本两种给法：一个队列按请求先后取用（只有一个会话的场景）；按会话给的每个会话一份，
        # 几个会话同时运行时各自取用自己的，与请求先后无关
        if isinstance(script, Mapping):
            self.scripts = {key: list(turns) for key, turns in script.items()}
            self.script: list[TurnSpec] = []
        else:
            self.scripts: dict[str, list[TurnSpec]] = {}
            self.script = list(script or [])
        self.invocations: list[ModelCall] = []
        self.cancelled: set[str] = set()
        # 列表模式下每一项被哪个部门取用过（工单 #879）：工程与质检同时取用同一条列表脚本时，
        # 记下这件事并让用例失败
        self.list_script_takes: list[tuple[int, str]] = []
        self.shared_list_script: str | None = None
        # 流式轮次里片段之间的停顿：需要订阅方在请求进行中读到 attempt.live 时给出（部门房间验收）
        self.stream_gap_sec = stream_gap_sec

    def availability(self) -> Availability:
        return Availability(True)

    def cancel(self, attempt_id: str) -> None:
        self.cancelled.add(attempt_id)

    async def stream(self, call: ModelCall) -> AsyncIterator[ModelStreamEvent | ModelResponse]:
        self.invocations.append(call)
        if call.attempt_id in self.cancelled:
            yield self._aborted()
            return
        queue = self.scripts.get(session_key(call), self.scripts.get(call.session_id, self.scripts.get(call.department, self.script))) if self.scripts else self.script
        if not queue:
            raise ProviderError("fake adapter script exhausted")
        item = queue.pop(0)
        if not self.scripts:
            # 列表模式：记下这一项被哪个部门取用（工单 #879）
            self._take_list_script_item(call.department)
        if callable(item):
            item = item(call)
        if isinstance(item, Generator):
            while True:
                try:
                    event = next(item)
                except StopIteration as finished:
                    item = finished.value
                    break
                yield event
                if self.stream_gap_sec:
                    # 片段之间让出事件循环并停顿：订阅方（例如部门房间的思考气泡）能在请求进行中
                    # 读到 attempt.live 的已收到文字。停顿不写入事件，只影响这一轮的节奏
                    await asyncio.sleep(self.stream_gap_sec)
        if call.attempt_id in self.cancelled:
            yield self._aborted()
            return
        if isinstance(item, BaseException):
            raise item
        yield self._response(call, item)

    def _aborted(self) -> ModelResponse:
        return ModelResponse(finish_reason="aborted", error="aborted", provider=self.name, model=self.model)

    def _take_list_script_item(self, department: str) -> None:
        # 列表模式：记下这一项被哪个部门取用（工单 #879）。
        # 工程与质检同时取用同一条列表脚本时，谁拿到哪一项随调度变化（工单 #557），
        # 这样的脚本让用例失败：写明是哪条脚本、被哪两个部门取用、应当按部门给出
        index = len(self.list_script_takes)
        self.list_script_takes.append((index, department))
        if self.shared_list_script is not None:
            return
        departments = {taken[1] for taken in self.list_script_takes}
        if not {"engineering", "quality"} <= departments:
            return
        self.shared_list_script = self._shared_list_script_message()
        _SHARED_LIST_SCRIPTS.append(self.shared_list_script)
        # 子进程里的违反写进子进程的输出（工单 #879）：父进程读到以后让用例失败
        print(self.shared_list_script, file=sys.stderr, flush=True)

    def _shared_list_script_message(self) -> str:
        taken = "；".join(f"第 {index + 1} 项由 {department} 取用"
                          for index, department in self.list_script_takes)
        return (f"{SHARED_LIST_SCRIPT_PREFIX}：{taken}。"
                "一条按先后排队的列表脚本被两个部门同时取用时，谁拿到哪一项随调度变化（工单 #557）。"
                "请按部门给出脚本：FakeAdapter({\"engineering\": [...], \"quality\": [...]})（工单 #879）。")

    def _response(self, call: ModelCall, item: Any) -> ModelResponse:
        if isinstance(item, ModelResponse):
            # 脚本没有写明的回答身份按这个假模型填写
            identity = {key: value for key, value in (("provider", self.name), ("model", self.model))
                        if key not in item.model_fields_set}
            return item.model_copy(update=identity)
        if isinstance(item, dict):
            item = FakeTurn(proposal=item)
        if not isinstance(item, FakeTurn):
            raise ProviderError(f"unsupported fake turn: {type(item)!r}")
        if item.raise_error is not None:
            raise item.raise_error
        output: list[dict[str, Any]] = []
        if item.transcript:
            output.append({"id": f"message-{call.activation_id}-{call.step_id}", "type": "message", "role": "assistant",
                           "content": [{"type": "output_text", "text": item.transcript}]})
        usage = CallUsage(**asdict(item.usage)) if item.usage is not None else CallUsage(reported=False)
        if usage.total_tokens == 0:
            usage.total_tokens = (usage.input_tokens + usage.output_tokens
                                  + usage.cache_read_tokens + usage.cache_write_tokens)

        def tool_call(name: str, args: dict[str, Any]) -> None:
            identity = f"call-{call.activation_id}-{call.step_id}-{len(output) + 1}"
            output.append({"id": identity, "call_id": identity, "type": "function_call", "name": name,
                           "arguments": json_dumps(args)})

        for path, content in item.writes.items():
            tool_call("write_file", {"path": path, "content": content})
        for name, spec in item.checks.items():
            tool_call("run_check", _fake_check_payload(name, spec))
        proposal = None if item.proposal is None else dict(item.proposal)
        if proposal:
            proposal.pop("_writes", None)
            proposal.pop("_checks", None)
            submit_name = _submit_tool_for(proposal.get("kind"))
            if submit_name:
                tool_call(submit_name, {key: value for key, value in proposal.items() if key != "kind"})
            else:
                raise ProviderError(f"unsupported fake proposal kind: {proposal.get('kind')}")
        return ModelResponse(
            output=output,
            usage=usage,
            finish_reason=item.finish_reason,
            error=item.error,
            provider=self.name,
            model=self.model,
        )


def _fake_check_payload(name: str, spec: int | dict[str, Any]) -> dict[str, Any]:
    # Fake 只选择要跑的进程；exit_code 仍由主机执行产生
    if isinstance(spec, dict) and spec.get("command"):
        payload = dict(spec)
        payload["name"] = name
        payload.pop("exit_code", None)
        payload["source"] = "fake_script_process"
        return payload
    code = int(spec if not isinstance(spec, dict) else spec.get("exit_code", 0))
    interpreter = sys.executable.replace("\\", "/")
    return {
        "name": name,
        "command": f"\"{interpreter}\" -c \"raise SystemExit({code})\"",
        "source": "fake_script_process",
    }


def _submit_tool_for(kind: Any) -> str | None:
    return submit_tool(kind) if isinstance(kind, str) else None
