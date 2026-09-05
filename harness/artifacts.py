"""文件 Artifact Store。大对象按内容哈希落盘，路径不进入内容哈希。"""

from __future__ import annotations

from pathlib import Path

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
