"""把一步请求的协议体拆成「视图的条目」，每条带上测量需要的元数据。

统一的条目形状（本包内部使用，不写回任何地方）：

    {"kind": ..., "role": ..., "text": ..., "tokens": ..., "index": i,
     "source": ..., "call_id": ..., "tool": ..., "ok": ..., "paths": [...], ...}

条目种类：

- `pinned`  开发消息，即部门材料。按 `[source]` 分段，逐段记录来源与用量。
- `input`   用户消息，即激活的部门输入；后来的通知也在这里。
- `message` 助手的文字回答。
- `call`    助手的工具调用（chat 协议里在 assistant.tool_calls，responses 协议里是 function_call 条目）。
- `tool`    工具结果（role tool 或 function_call_output）。
- `reasoning` 推理内容。
- `other`   其它（压缩摘要等），本测量不使用。

用量估算与装配实现同一条公式（4 个字符 1 个 token，向上取整），这样本工具算出的
用量与 `context_assembled` 清单里的 `tokens` 可比。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from typing import Any, Iterable

# 部门材料里一段材料的标题形如 `[intend]`，后面紧跟正文
SECTION = re.compile(r"^\[([a-z_]+)\]\n", re.MULTILINE)

# 文件路径类记号：带扩展名或带目录分隔符
PATH_TOKEN = re.compile(
    r"(?:[A-Za-z]:)?(?:[A-Za-z0-9_.\-]+[/\\])+[A-Za-z0-9_.\-]+"
    r"|(?<![A-Za-z0-9_])[A-Za-z0-9_\-]+\.(?:py|md|json|jsonl|txt|ya?ml|toml|ini|cfg|js|jsx|ts|tsx|"
    r"mjs|cjs|html|css|scss|sh|ps1|bat|c|h|cc|cpp|hpp|rs|go|java|kt|sql|csv|lock|whl|exe|png|svg)")


def estimate_tokens(text: str) -> int:
    """与 harness/models.py 的 estimate_tokens 同一条公式。"""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def item_text(item: Any) -> str:
    """条目在请求里占的字符序列：字符串原样，对象按紧凑 JSON。"""
    if isinstance(item, str):
        return item
    return json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class Entry:
    index: int
    kind: str
    role: str | None
    text: str
    tokens: int
    step_id: int
    source: str | None = None
    sections: tuple[tuple[str, str], ...] = ()
    call_id: str | None = None
    tool: str | None = None
    ok: bool | None = None
    paths: tuple[str, ...] = ()
    meta: dict[str, Any] = field(default_factory=dict)
    # 原始条目：视图按原样回放时要用它，`verify` 才能核对逐字节一致
    raw: dict[str, Any] | None = None

    def to_message(self) -> dict[str, Any]:
        """回到请求体里的条目形状。折叠过的条目按占位改写，配对关系保持不变。"""
        if self.raw is not None and not (self.meta or {}).get("collapsed"):
            return self.raw
        if self.kind == "tool":
            return {"role": "tool", "tool_call_id": self.call_id, "content": self.text}
        if self.kind == "folded":
            return {"role": "user", "content": self.text}
        if self.raw is not None:
            return {**self.raw, "content": self.text}
        return {"role": self.role or "user", "content": self.text}

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index, "kind": self.kind, "role": self.role, "tokens": self.tokens,
            "step_id": self.step_id, "source": self.source, "call_id": self.call_id,
            "tool": self.tool, "ok": self.ok, "paths": list(self.paths),
            "sections": [name for name, _ in self.sections],
        }


def split_sections(text: str) -> tuple[tuple[str, str], ...]:
    """把部门材料按 `[source]` 切开，返回 (来源, 正文) 序列。"""
    matches = list(SECTION.finditer(text))
    if not matches:
        return ()
    sections: list[tuple[str, str]] = []
    if matches[0].start() > 0:
        sections.append(("_preamble", text[:matches[0].start()]))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end():end]
        sections.append((match.group(1), body))
    return tuple(sections)


def referenced_paths(text: str) -> tuple[str, ...]:
    """条目里出现的、看起来是文件路径的记号（去重后按出现顺序）。"""
    seen: dict[str, None] = {}
    for match in PATH_TOKEN.finditer(text):
        token = match.group(0).replace("\\", "/")
        if len(token) < 4:
            continue
        seen.setdefault(token, None)
    return tuple(seen)


def normalize_request(body: dict[str, Any], step_id: int) -> list[Entry]:
    """把协议请求体拆成条目序列。

    支持两种协议形状：chat_completions 的 `messages`，responses 的 `input`。
    tools 不在条目里，单独处理（见 view.py 的 tools 预算）。
    """
    raw = body.get("messages")
    if raw is None:
        raw = body.get("input")
    if raw is None:
        raise ValueError("请求体既没有 messages 也没有 input")
    entries: list[Entry] = []
    for index, item in enumerate(raw):
        if isinstance(item, str):
            item = {"role": "user", "content": item, "type": "message"}
        if not isinstance(item, dict):
            entries.append(Entry(index=index, kind="other", role=None,
                                 text=item_text(item), tokens=estimate_tokens(item_text(item)),
                                 step_id=step_id))
            continue
        entries.append(replace(_entry_from_item(index, item, step_id), raw=item))
    # 工具结果在 chat 协议里不带工具名与调用参数：按 call_id 回到同一步的调用条目上取
    names: dict[str, str | None] = {}
    arguments: dict[str, Any] = {}
    for entry in entries:
        if entry.kind != "call":
            continue
        for call in (entry.meta.get("calls") or []):
            if call.get("call_id"):
                names.setdefault(call["call_id"], call.get("tool"))
                arguments.setdefault(call["call_id"], call.get("arguments"))
        if entry.call_id:
            names.setdefault(entry.call_id, entry.tool)
            arguments.setdefault(entry.call_id, entry.meta.get("arguments"))
    if names:
        updated = []
        for entry in entries:
            if entry.kind != "tool" or entry.call_id not in names:
                updated.append(entry)
                continue
            meta = dict(entry.meta)
            meta["arguments"] = arguments.get(entry.call_id)
            meta["path"] = _argument_path(meta["arguments"])
            updated.append(Entry(**{**entry.__dict__, "tool": entry.tool or names[entry.call_id],
                                    "meta": meta}))
        entries = updated
    return entries


def _argument_path(arguments: Any) -> str | None:
    """工具调用参数里的路径：read_file、read_range、edit_range 等都用 path。"""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except (json.JSONDecodeError, TypeError):
            return None
    if isinstance(arguments, dict):
        for key in ("path", "file", "filename"):
            value = arguments.get(key)
            if isinstance(value, str) and value:
                return value.replace("\\", "/")
    return None


def _entry_from_item(index: int, item: dict[str, Any], step_id: int) -> Entry:
    kind = item.get("type")
    role = item.get("role")
    if kind in ("function_call", "custom_tool_call"):
        text = item_text(item)
        return Entry(index=index, kind="call", role="assistant", text=text,
                     tokens=estimate_tokens(text), step_id=step_id,
                     call_id=str(item.get("call_id") or item.get("id") or "") or None,
                     tool=item.get("name"), meta={"arguments": item.get("arguments")})
    if kind in ("function_call_output", "custom_tool_call_output"):
        text = item_text(item)
        return Entry(index=index, kind="tool", role="tool", text=text,
                     tokens=estimate_tokens(text), step_id=step_id,
                     call_id=str(item.get("call_id") or "") or None,
                     paths=referenced_paths(text), meta={"output": item.get("output")})
    if kind == "reasoning":
        text = item_text(item)
        return Entry(index=index, kind="reasoning", role="assistant", text=text,
                     tokens=estimate_tokens(text), step_id=step_id)
    if role == "developer" or role == "system":
        text = item.get("content")
        text = text if isinstance(text, str) else item_text(text)
        sections = split_sections(text)
        return Entry(index=index, kind="pinned", role=role, text=text,
                     tokens=sum(estimate_tokens(body) for _, body in sections) or estimate_tokens(text),
                     step_id=step_id, sections=sections,
                     source=sections[0][0] if sections else None)
    if role == "user":
        text = item.get("content")
        text = text if isinstance(text, str) else item_text(text)
        return Entry(index=index, kind="input", role="user", text=text,
                     tokens=estimate_tokens(text), step_id=step_id,
                     paths=referenced_paths(text), meta={"label": _label(text)})
    if role == "assistant":
        content = item.get("content")
        calls = item.get("tool_calls") or []
        if calls:
            text = item_text(calls)
            details = [{"call_id": str((call or {}).get("id") or ""),
                        "tool": ((call or {}).get("function") or {}).get("name"),
                        "arguments": ((call or {}).get("function") or {}).get("arguments")}
                       for call in calls]
            first = details[0] if details else {"call_id": "", "tool": None, "arguments": None}
            return Entry(index=index, kind="call", role="assistant", text=text,
                         tokens=estimate_tokens(text), step_id=step_id,
                         call_id=first["call_id"] or None, tool=first["tool"],
                         meta={"arguments": first["arguments"], "calls": details})
        text = content if isinstance(content, str) else item_text(content)
        return Entry(index=index, kind="message", role="assistant", text=text,
                     tokens=estimate_tokens(text), step_id=step_id,
                     paths=referenced_paths(text))
    if role == "tool":
        text = item.get("content")
        text = text if isinstance(text, str) else item_text(text)
        return Entry(index=index, kind="tool", role="tool", text=text,
                     tokens=estimate_tokens(text), step_id=step_id,
                     call_id=str(item.get("tool_call_id") or "") or None,
                     paths=referenced_paths(text),
                     ok=_ok_of(text))
    text = item_text(item)
    return Entry(index=index, kind="other", role=role, text=text,
                 tokens=estimate_tokens(text), step_id=step_id)


def _label(text: str) -> str:
    match = SECTION.match(text)
    return match.group(1) if match else ("notify" if text.startswith(("用户追加", "产品要求", "新的交付", "产品记录")) else "")


def _ok_of(text: str) -> bool | None:
    """工具结果里的 ok 字段：`{"ok": false, ...}` 视为失败。"""
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(parsed, dict):
        value = parsed.get("ok")
        if isinstance(value, bool):
            return value
        if "error" in parsed:
            return parsed.get("error") in (None, "", False)
    return None


def tokens_of(entries: Iterable[Entry]) -> int:
    return sum(entry.tokens for entry in entries)
