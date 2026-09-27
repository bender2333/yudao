# 带版本的定义（ADR-0014）：随系统发布的 JSON 数据文件，放在本目录。
# 导入本模块时读取并校验全部定义文件：标准库解析 JSON（重复的键不合法），pydantic 类型校验每个文件的结构，
# 任何一项不合法都抛出 DefinitionError，写明文件与字段，导入本模块的程序因此无法启动。
# 定义的版本是全部定义文件内容的摘要：每个文件解析以后按原来的键顺序写成紧凑的 JSON，只改格式不改变版本。
# 运行中任何代码都不修改定义：类型不可改写，可变的结构交回副本；项目部门设置中的 Prompt 与模型属于设置，不在这里。

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

DEFINITIONS_DIR = Path(__file__).parent


class DefinitionError(ValueError):
    # 定义不合法：每一项是（文件、字段、原因）
    def __init__(self, issues: list[tuple[str, str, str]]) -> None:
        self.issues = tuple(issues)
        super().__init__("定义不合法：\n" + "\n".join(
            f"  {file} {field}：{message}" for file, field, message in self.issues))


class _Definition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Limits(_Definition):
    # 运行时间上限（秒）：达到时运行失败（time_limit）
    run_time_limit_sec: int = Field(gt=0)
    # 部门激活次数上限：达到时运行暂停（max_cycles）
    max_cycles: int = Field(gt=0)
    # 一次激活的模型步数上限，重试同样计入：达到时运行暂停（model_steps_exhausted）
    max_model_steps: int = Field(gt=0)
    # 一次模型调用的最多尝试次数，与重试的初始间隔、最大间隔（秒）
    max_provider_attempts: int = Field(gt=0)
    retry_initial_delay_sec: float = Field(gt=0)
    retry_max_delay_sec: float = Field(gt=0)
    # 连续没有调用工具的回复最多追加说明的次数，再出现一次运行暂停（no_tool_call）
    tool_call_required_limit: int = Field(gt=0)
    # 检查的时限（秒），也是登记命令没有写明时限时的默认值
    check_timeout_sec: int = Field(gt=0)
    # 一次工具结果的输出上限（字符），也是登记命令没有写明输出上限时的默认值
    tool_output_limit: int = Field(gt=0)
    # 登记命令时限的最大值（秒）
    command_timeout_max_sec: int = Field(gt=0)


class Definitions(_Definition):
    version: str
    limits: Limits


# 定义文件与它在 Definitions 中的字段、类型
_FILES: dict[str, tuple[str, type[BaseModel]]] = {
    "limits.json": ("limits", Limits),
}


class _DuplicateKey(ValueError):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _ in pairs]
    for key in keys:
        if keys.count(key) > 1:
            raise _DuplicateKey(key)
    return dict(pairs)


def _location(loc: tuple[Any, ...]) -> str:
    text = ""
    for part in loc:
        text += f"[{part}]" if isinstance(part, int) else (f".{part}" if text else str(part))
    return text or "（整个文件）"


def load_definitions(directory: Path = DEFINITIONS_DIR) -> Definitions:
    # 读取并校验 directory 中的全部定义文件；不合法时抛出 DefinitionError
    issues: list[tuple[str, str, str]] = []
    contents: dict[str, Any] = {}
    parts: dict[str, BaseModel] = {}
    for file, (field, model) in _FILES.items():
        path = directory / file
        if not path.is_file():
            issues.append((file, "（整个文件）", "定义文件不存在"))
            continue
        text = path.read_text(encoding="utf-8")
        try:
            contents[file] = json.loads(text, object_pairs_hook=_unique_keys)
        except json.JSONDecodeError as exc:
            issues.append((file, f"第 {exc.lineno} 行第 {exc.colno} 列", f"不是合法的 JSON：{exc.msg}"))
            continue
        except _DuplicateKey as exc:
            issues.append((file, exc.key, "重复的键"))
            continue
        try:
            parts[field] = model.model_validate_json(text)
        except ValidationError as exc:
            issues.extend((file, _location(error["loc"]), error["msg"]) for error in exc.errors())
    if issues:
        raise DefinitionError(issues)
    return Definitions(version=_version(contents), **parts)


def _version(contents: dict[str, Any]) -> str:
    canonical = json.dumps({file: contents[file] for file in sorted(contents)},
                           ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


DEFINITIONS = load_definitions()
