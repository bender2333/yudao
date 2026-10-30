"""文件 Artifact Store。大对象按内容哈希落盘，路径不进入内容哈希。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Iterable

from .kernel_events import json_dumps, utc_now
from .models import ArtifactRef, hash_bytes

# 外部来源工件（网络取回与 MCP 设计说明第 9 节）：取回的正文与 MCP 的结果按行保存成工件，
# 来源字段写在与正文同一个目录的 `<摘要>.source.json` 中；正文仍按内容哈希落盘，
# 摘要值因此与工件引用里的 content_hash 相同
EXTERNAL_SOURCE_KIND = "external_source"
_EXTERNAL_SOURCE_META = ".source.json"


@dataclass(frozen=True)
class ExternalSource:
    # 一个外部来源工件：来源（地址，或服务器名称与工具名）、最终地址、状态码、内容类型、
    # 摘要值、取得时间与正文（换行统一成 \n，行号从 1 起）
    source: str
    content_hash: str
    fetched_at: str
    text: str
    final_url: str | None = None
    status_code: int | None = None
    content_type: str | None = None

    @property
    def total_lines(self) -> int:
        return len(self.text.splitlines())


class ArtifactStore:
    def __init__(self, root: str | Path, *, read_only: bool = False) -> None:
        self.root = Path(root)
        self.read_only = read_only
        if not read_only:
            self.root.mkdir(parents=True, exist_ok=True)

    def put(self, run_id: str, kind: str, data: str | bytes, *, media_type: str = "text/plain") -> ArtifactRef:
        raw = data.encode("utf-8") if isinstance(data, str) else data
        digest = hash_bytes(raw)
        digest_body = digest.split(":", 1)[1]
        rel = Path(run_id) / digest_body[:2] / digest_body
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(raw)
        return ArtifactRef(kind=kind, content_hash=digest, path=rel.as_posix(), media_type=media_type)

    def put_stream(
        self,
        run_id: str,
        kind: str,
        chunks: Iterable[bytes],
        *,
        media_type: str = "application/octet-stream",
    ) -> ArtifactRef:
        """Persist an iterable without materializing the complete artifact in memory."""

        run_root = self.root / run_id
        run_root.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=run_root, prefix=".stream-", delete=False) as temporary:
                temporary_path = Path(temporary.name)
                for chunk in chunks:
                    if not isinstance(chunk, (bytes, bytearray, memoryview)):
                        raise TypeError("artifact stream chunks must be bytes")
                    raw = bytes(chunk)
                    digest.update(raw)
                    temporary.write(raw)
                temporary.flush()
            digest_value = digest.hexdigest()
            relative = Path(run_id) / digest_value[:2] / digest_value
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                os.replace(temporary_path, path)
            else:
                temporary_path.unlink(missing_ok=True)
        except Exception:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise
        return ArtifactRef(
            kind=kind,
            content_hash="sha256:" + digest_value,
            path=relative.as_posix(),
            media_type=media_type,
        )

    def get(self, ref: ArtifactRef | str) -> bytes:
        if isinstance(ref, ArtifactRef):
            path = self.root / ref.path
        else:
            matches = list(self.root.glob(f"*/{ref.split(':', 1)[-1][:2]}/{ref.split(':', 1)[-1]}"))
            if not matches:
                raise FileNotFoundError(ref)
            path = matches[0]
        return path.read_bytes()

    def get_text(self, ref: ArtifactRef | str) -> str:
        return self.get(ref).decode("utf-8")

    def get_for_run(self, run_id: str, ref: ArtifactRef) -> bytes:
        if not isinstance(run_id, str) or run_id in {"", ".", ".."} or Path(run_id).name != run_id:
            raise ValueError("invalid artifact run id")
        if not isinstance(ref.content_hash, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", ref.content_hash):
            raise ValueError("invalid artifact content hash")
        digest = ref.content_hash.split(":", 1)[1]
        relative = Path(run_id) / digest[:2] / digest
        if ref.path != relative.as_posix():
            raise ValueError("artifact reference does not belong to this run")
        path = self.root.resolve() / relative
        if path.resolve() != path:
            raise ValueError("artifact path resolves outside its recorded location")
        raw = path.read_bytes()
        if hash_bytes(raw) != ref.content_hash:
            raise ValueError("artifact content hash mismatch")
        return raw

    # ---- 外部来源工件（网络取回与 MCP 设计说明第 9 节） ----

    def put_external_source(self, run_id: str, text: str, *, source: str,
                            final_url: str | None = None, status_code: int | None = None,
                            content_type: str | None = None, fetched_at: str | None = None) -> ArtifactRef:
        # 存一份外部来源：正文的换行统一成 \n 以后按行保存（行号从 1 起），来源字段写在同一个目录。
        # 同一份正文再存一次时保留第一次写下的来源字段：正文相同，读出来的内容也不变
        if not isinstance(text, str):
            raise TypeError("external source text must be a string")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("an external source requires a non-empty source")
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        ref = self.put(run_id, EXTERNAL_SOURCE_KIND, normalized, media_type=content_type or "text/plain")
        meta_path = self._external_source_meta(ref)
        if not meta_path.exists():
            meta_path.parent.mkdir(parents=True, exist_ok=True)
            meta_path.write_text(json_dumps({
                "source": source,
                "final_url": final_url,
                "status_code": status_code,
                "content_type": content_type,
                "content_hash": ref.content_hash,
                "fetched_at": fetched_at or utc_now(),
            }), encoding="utf-8")
        return ref

    def external_source(self, run_id: str, content_hash: str) -> ExternalSource:
        # 读一份外部来源：正文按工件引用的摘要核对，来源字段取自同一个目录的记录。
        # 不是外部来源工件、工件不在这个 run 里或正文被改动过时直接报错
        if not isinstance(content_hash, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", content_hash):
            raise ValueError("invalid external source id")
        digest = content_hash.split(":", 1)[1]
        ref = ArtifactRef(kind=EXTERNAL_SOURCE_KIND, content_hash=content_hash,
                          path=(Path(run_id) / digest[:2] / digest).as_posix())
        raw = self.get_for_run(run_id, ref)
        meta_path = self._external_source_meta(ref)
        if not meta_path.is_file():
            raise FileNotFoundError(f"not an external source artifact: {content_hash}")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return ExternalSource(
            source=str(meta["source"]),
            content_hash=content_hash,
            fetched_at=str(meta["fetched_at"]),
            text=raw.decode("utf-8"),
            final_url=meta.get("final_url"),
            status_code=meta.get("status_code"),
            content_type=meta.get("content_type"),
        )

    def _external_source_meta(self, ref: ArtifactRef) -> Path:
        return self.root / (ref.path + _EXTERNAL_SOURCE_META)
