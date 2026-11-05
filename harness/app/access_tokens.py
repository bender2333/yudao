# 访问令牌（应用层与接口层设计说明第 6.3 节）：局域网访问方式的凭据。
# 服务只保存令牌的 SHA-256 摘要、名称与建立时间，令牌本身不落盘；撤销只记下时间，撤销以后立即失效。
# 令牌管理只在服务所在机器的命令行进行，不提供命令。

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from pathlib import Path

# 数据目录中的令牌文件（第 6.3 节）
FILE_NAME = "access-tokens.json"
# 256 位随机令牌：secrets.token_hex 给出的十六进制串（第 6.3 节）
TOKEN_BYTES = 32


@dataclass(frozen=True)
class AccessToken:
    # 一条令牌记录：名称、摘要、建立时间与撤销时间。撤销以后 revoked_at 不是 None
    name: str
    digest: str
    created_at: str
    revoked_at: str | None


class TokenNameTaken(Exception):
    # 名称已经被另一条有效令牌占用：建立同名的令牌会被拒绝
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


class UnknownToken(Exception):
    # 名称没有对应的令牌记录
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


class AccessTokenStore:
    # 数据目录中的令牌文件：读取、建立、撤销与校验。文件不存在的目录按没有令牌处理。
    # 每次校验都重新读文件，撤销因此立即生效，也不需要进程内缓存失效的机制
    def __init__(self, data_dir: str | Path) -> None:
        self.path = Path(data_dir).absolute().resolve() / FILE_NAME

    def list(self) -> tuple[AccessToken, ...]:
        return tuple(AccessToken(**record) for record in self._records())

    def create(self, name: str, *, now: str) -> tuple[AccessToken, str]:
        # 建立一条令牌，返回记录与只显示一次的令牌明文
        records = self._records()
        if any(record["name"] == name and record["revoked_at"] is None for record in records):
            raise TokenNameTaken(name)
        token = secrets.token_hex(TOKEN_BYTES)
        entry = AccessToken(name=name, digest=digest(token), created_at=now, revoked_at=None)
        self._write(records + [_as_record(entry)])
        return entry, token

    def revoke(self, name: str, *, now: str) -> AccessToken:
        # 撤销：记下撤销时间。名称没有对应记录时报错，已经撤销过的再撤销同样报错
        records = self._records()
        for index, record in enumerate(records):
            if record["name"] != name or record["revoked_at"] is not None:
                continue
            entry = AccessToken(name=name, digest=record["digest"], created_at=record["created_at"],
                                revoked_at=now)
            records[index] = _as_record(entry)
            self._write(records)
            return entry
        raise UnknownToken(name)

    def name_of(self, token: str) -> str | None:
        # 按令牌明文求出令牌名称；明文不匹配任何有效令牌时返回 None（认证失败返回 401，不附原因）
        candidate = digest(token)
        for record in self._records():
            if record["revoked_at"] is not None:
                continue
            if hmac.compare_digest(record["digest"], candidate):
                return str(record["name"])
        return None

    def _records(self) -> list[dict[str, object]]:
        if not self.path.is_file():
            return []
        document = json.loads(self.path.read_text(encoding="utf-8"))
        return [dict(record) for record in document["tokens"]]

    def _write(self, records: list[dict[str, object]]) -> None:
        # 先写临时文件再替换：服务进程被中断时不留下半个令牌文件
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps({"tokens": records}, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
        temporary.replace(self.path)


def digest(token: str) -> str:
    # 令牌的 SHA-256 摘要（第 6.3 节）：服务只保存摘要，令牌本身不落盘
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _as_record(entry: AccessToken) -> dict[str, object]:
    return {"name": entry.name, "digest": entry.digest, "created_at": entry.created_at,
            "revoked_at": entry.revoked_at}
