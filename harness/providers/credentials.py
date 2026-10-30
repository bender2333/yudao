from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


# .env 的键名规则：字母、数字与下划线，不以数字开头（工单 #1158）
DOTENV_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DOTENV_KEY_RULE = "字母、数字与下划线，不以数字开头"


# 内存中的凭据材料，secret 与 version 均不进入 repr/比较/导出
@dataclass(frozen=True)
class CredentialMaterial:
    secret: str = field(repr=False, compare=False)
    version: str | None = field(default=None, repr=False, compare=False)


def is_dotenv_key(value: str) -> bool:
    # 这段文字能不能当 .env 的键名
    return bool(DOTENV_KEY_PATTERN.fullmatch(str(value)))


def suggested_dotenv_key(ref: str) -> str:
    # 给不合规的引用举一个合规的写法：字母数字以外换成下划线，转大写；
    # 开头是数字或什么都不剩时补上 KEY_ 前缀
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", str(ref).strip()).strip("_").upper()
    suggested = f"KEY_{cleaned}" if cleaned == "" or cleaned[0].isdigit() else cleaned
    return suggested or "PROVIDER_KEY"


def connection_credential_ref(provider_id: str) -> str:
    # 一步连接按连接 ID 生成引用，非字母开头时使用 HOST_ 前缀（设计说明第 4.2 节）。
    reference = re.sub(r"[^A-Za-z0-9]", "_", provider_id).upper() + "_KEY"
    return reference if reference[0] in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" else "HOST_" + reference


def dotenv_key_problem(ref: str) -> str | None:
    # 引用不能写进 .env 时的说明：写明规则并举一个合规的写法；可以用时返回空。
    # 保存之前按它拒绝，文件与内存都不动：Yudao 不写出自己读不回的 .env（工单 #1158）
    key = str(ref).strip()
    if is_dotenv_key(key):
        return None
    return (f"凭据引用 {key or '（空）'} 不能写进 .env：.env 的键名只用{DOTENV_KEY_RULE}，"
            f"例如 {suggested_dotenv_key(key)}")


def parse_dotenv_text(text: str) -> dict[str, str]:
    # 最小兼容解析：空行与 # 注释跳过，可选 export 前缀，KEY=VALUE 单行形状，
    # 值两侧成对单双引号剥离。不支持多行值、转义序列、行内注释剥离、命令替换等
    # 语法；遇到不支持或畸形的行直接报错，不静默误读。不写 os.environ。
    result: dict[str, str] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            raise ValueError(f".env 第 {line_number} 行不是 KEY=VALUE 形状")
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not is_dotenv_key(key):
            raise ValueError(f".env 第 {line_number} 行键名非法：{key}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        result[key] = value
    return result


def load_dotenv_dict(path: str | Path) -> dict[str, str]:
    # 独立 .env 字典来源，文件缺失即该源为空，不抛错
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return {}
    return parse_dotenv_text(text)


class CredentialChain:
    # 查找顺序：内存覆盖 > 进程环境 > 独立 .env 字典；只读环境，不写 os.environ
    def __init__(
        self,
        overrides: Mapping[str, str | CredentialMaterial] | None = None,
        dotenv_dict: Mapping[str, str | CredentialMaterial] | None = None,
        *,
        use_env: bool = True,
    ) -> None:
        self._overrides: dict[str, CredentialMaterial] = {}
        self._dotenv: dict[str, CredentialMaterial] = {}
        self._use_env = bool(use_env)
        if overrides:
            for ref, value in overrides.items():
                self.set_override(ref, value)
        if dotenv_dict:
            for ref, value in dotenv_dict.items():
                self._dotenv[str(ref)] = _coerce_material(value, source="dotenv")

    def set_override(self, ref: str, value: str | CredentialMaterial) -> None:
        self._overrides[str(ref)] = _coerce_material(value, source="override")

    def clear_override(self, ref: str) -> bool:
        return self._overrides.pop(str(ref), None) is not None

    def load_dotenv_file(self, path: str | Path) -> int:
        # 显式载入独立 .env 文件，结果并入 dotenv 源
        data = load_dotenv_dict(path)
        for ref, value in data.items():
            self._dotenv[ref] = _coerce_material(value, source="dotenv")
        return len(data)

    def replace_dotenv_dict(self, data: Mapping[str, str | CredentialMaterial]) -> None:
        # 整体替换 dotenv 源，用于文件轮询与外部删除感知，不碰内存覆盖与进程环境
        replaced: dict[str, CredentialMaterial] = {}
        for ref, value in data.items():
            replaced[str(ref)] = _coerce_material(value, source="dotenv")
        self._dotenv = replaced

    def clear_dotenv(self) -> None:
        # .env 文件被删除时清除整个文件源值，不从缓存复活已删除密钥
        self._dotenv = {}

    def remove_dotenv_value(self, ref: str) -> bool:
        # 移除单个文件源值，返回是否确实存在
        return self._dotenv.pop(str(ref), None) is not None

    def has_persisted(self, ref: str) -> bool:
        material = self._dotenv.get(str(ref))
        return material is not None and bool(material.secret.strip())

    def resolve(self, ref: str) -> CredentialMaterial | None:
        key = str(ref)
        material = self._overrides.get(key)
        if material is not None and material.secret.strip():
            return material
        if self._use_env:
            env_value = os.environ.get(key)
            if env_value is not None and env_value.strip():
                return CredentialMaterial(secret=env_value, version="env")
        material = self._dotenv.get(key)
        if material is not None and material.secret.strip():
            return material
        return None

    def describe(self, ref: str) -> dict[str, object]:
        # 脱敏描述，只返回是否就绪与来源，不返回 secret 与 version
        key = str(ref)
        override = self._overrides.get(key)
        has_override = override is not None and bool(override.secret.strip())
        env_value = os.environ.get(key) if self._use_env else None
        has_env = env_value is not None and bool(env_value.strip())
        dotenv_material = self._dotenv.get(key)
        has_dotenv = dotenv_material is not None and bool(dotenv_material.secret.strip())
        if has_override:
            source = "override"
        elif has_env:
            source = "env"
        elif has_dotenv:
            source = "dotenv"
        else:
            source = "missing"
        return {
            "ref": key,
            "configured": source != "missing",
            "source": source,
            "has_override": has_override,
        }


def _coerce_material(value: str | CredentialMaterial, *, source: str) -> CredentialMaterial:
    if isinstance(value, CredentialMaterial):
        return value
    return CredentialMaterial(secret=str(value), version=source)
