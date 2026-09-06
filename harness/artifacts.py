"""文件 Artifact Store。大对象按内容哈希落盘，路径不进入内容哈希。"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from collections.abc import Iterable

from .models import ArtifactRef, hash_bytes


class ArtifactStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
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
