"""从模型输出里抽引用，作为这一步上下文的真值集合；以及这个启发式的误差。

抽三类引用（工单 #912 第 2 步：工具调用编号、文件路径、引用片段）：

- 文件路径：带扩展名或带目录分隔符的记号，例如 `src/cli.py`、`textstats.py`。
- 标识符与散列：含下划线、数字或驼峰的长标识符，以及长度 16 位以上的十六进制散列，
  例如 `content_hash`、`sha256:9e4b1b82...`。
- 引用片段：反引号包住的片段，以及引号里的长字符串（工单第六步的「引用片段」）。
- 工具调用编号：`call_...`、`toolu_...` 一类的调用编号，用于核对「这一步的调用是不是
  接在视图里已有的那次调用后面」。

误差（写在设计说明第 2 节，这里只是代码）：

1. 词面共现不等于因果。同一个记号可能同时出现在多条目里（意图、多次读取的文件内容、
   后来的输出），仅凭共现无法判断模型用的是哪一条。本工具的归属办法是把记号的贡献
   记给视图里**最早**出现它的那一条，于是后来的重复条目会被计入浪费。这一条让浪费
   偏高：被重复装进来的同一份内容按浪费计。
2. 改写与会话不算。模型可能用了某条内容但换了措辞、换算成结论，词面不重合，这一条
   会被记为浪费。这一条同样让浪费偏高。
3. 新造的记号不算漏召回。输出里第一次出现的记号（模型自己写的文件名、命令、变量名）
   不可能来自视图，把它们排除在召回分母之外；否则召回被人为压低。
4. 只看到「回答了这一步请求的输出」。输出没有写出来的依赖（例如按已有内容决定不再
   读取）不进真值集合，这一步会被记为浪费。

两条误差都指向同一方向：本测量给出的浪费是**上界**、召回是**下界**。设计说明里凡是
按浪费的数值下结论的地方都按这个方向读。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .items import Entry, estimate_tokens, item_text

IDENT = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z_][A-Za-z0-9_]{7,}(?![A-Za-z0-9_])")
HASH = re.compile(r"(?:sha256:)?[0-9a-f]{16,}")
CALL_ID = re.compile(r"\b(?:call|fc|toolu|ans|req)_[A-Za-z0-9_\-]{4,}")
QUOTED = re.compile(r"`([^`\n]{6,200})`")
PATH = re.compile(
    r"(?:[A-Za-z]:)?(?:[A-Za-z0-9_.\-]+[/\\])+[A-Za-z0-9_.\-]+"
    r"|(?<![A-Za-z0-9_])[A-Za-z0-9_\-]+\.(?:py|md|json|jsonl|txt|ya?ml|toml|ini|cfg|js|jsx|ts|tsx|"
    r"mjs|cjs|html|css|scss|sh|ps1|bat|c|h|cc|cpp|hpp|rs|go|java|kt|sql|csv|lock|whl|exe|png|svg)")


def _interesting_ident(token: str) -> bool:
    """只留不像普通英文单词的标识符：带下划线、带数字、驼峰或足够长。"""
    if "_" in token or any(char.isdigit() for char in token):
        return True
    if any(char.isupper() for char in token[1:]):
        return True
    return len(token) >= 12


# 协议字段名不是内容：它们在每一条串行化的条目里都出现，会把召回压低、把浪费抬高
PROTOCOL_WORDS = frozenset({
    "function_call", "function_call_output", "custom_tool_call", "custom_tool_call_output",
    "reasoning_content", "tool_call_id", "tool_calls", "output_index", "summary_text",
    "encrypted_content", "input_text", "output_text", "missing_response",
})

_ESCAPES = (("\\n", " "), ("\\r", " "), ("\\t", " "), ("\\\"", '"'), ("\\\\", " "))


def _clean(text: str) -> str:
    """串行化后的条目里，换行是字面的 `\\n` 两个字符；先还原成空白再抽记号。"""
    for source, target in _ESCAPES:
        text = text.replace(source, target)
    return text


def extract(text: str) -> dict[str, str]:
    """抽出 (记号 → 类型)。同一记号只记第一次的类型。"""
    text = _clean(text)
    found: dict[str, str] = {}
    for match in PATH.finditer(text):
        token = match.group(0).replace("\\", "/")
        if len(token) >= 4:
            found.setdefault(token, "path")
    for match in HASH.finditer(text):
        found.setdefault(match.group(0), "hash")
    for match in CALL_ID.finditer(text):
        found.setdefault(match.group(0), "call")
    for match in IDENT.finditer(text):
        token = match.group(0)
        if token in PROTOCOL_WORDS:
            continue
        if _interesting_ident(token):
            found.setdefault(token, "ident")
    for match in QUOTED.finditer(text):
        snippet = match.group(1).strip()
        if len(snippet) >= 8 and (_interesting_ident(snippet) or "/" in snippet or "." in snippet):
            found.setdefault(snippet, "quote")
    return found


def tokens_of_entry(entry: Entry) -> dict[str, str]:
    if entry.kind == "pinned" and entry.sections:
        merged: dict[str, str] = {}
        for _source, body in entry.sections:
            for token, kind in extract(body).items():
                merged.setdefault(token, kind)
        return merged
    return extract(entry.text)


def tokens_of_output(items: Iterable[object], tool_results: Iterable[dict]) -> dict[str, str]:
    """一步模型输出的引用集合：输出条目 + 工具调用的参数。"""
    found: dict[str, str] = {}
    for item in items:
        for token, kind in extract(item_text(item)).items():
            found.setdefault(token, kind)
    for result in tool_results:
        arguments = result.get("args")
        if arguments is not None:
            for token, kind in extract(item_text(arguments)).items():
                found.setdefault(token, kind)
    return found


@dataclass(frozen=True)
class EntryUsage:
    """一条视图条目在「此后」被用到没有。

    `referenced` 是「至少被引用到一个记号」；`used_share` 是被引用记号覆盖的字符占比，
    用来区分「整条被用上」与「只用上了其中一处」。两者都受上面第 1、2 条误差影响。
    """

    index: int
    tokens: int
    referenced: bool
    credited: tuple[str, ...]
    used_share: float

    def to_dict(self) -> dict[str, object]:
        return {"index": self.index, "tokens": self.tokens, "referenced": self.referenced,
                "credited": len(self.credited), "used_share": round(self.used_share, 4)}


def attribute(entries: list[Entry], referenced: set[str]) -> list[EntryUsage]:
    """把引用记给视图里最早持有这个记号的那一条，返回逐条的用处。"""
    credit: dict[str, int] = {}
    for entry in entries:
        for token in tokens_of_entry(entry):
            credit.setdefault(token, entry.index)
    credited: dict[int, list[str]] = {}
    for token in sorted(referenced):
        owner = credit.get(token)
        if owner is not None:
            credited.setdefault(owner, []).append(token)
    usage: list[EntryUsage] = []
    for entry in entries:
        mine = credited.get(entry.index, [])
        length = max(1, len(entry.text))
        covered = min(length, sum(len(token) for token in mine))
        usage.append(EntryUsage(index=entry.index, tokens=entry.tokens, referenced=bool(mine),
                                credited=tuple(mine), used_share=covered / length))
    return usage


def presence(entries: list[Entry]) -> set[str]:
    tokens: set[str] = set()
    for entry in entries:
        tokens.update(tokens_of_entry(entry))
    return tokens


def tokens_estimate(text: str) -> int:
    return estimate_tokens(text)
