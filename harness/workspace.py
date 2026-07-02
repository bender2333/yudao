"""Workspace: the directory the agent operates in, plus a meta/products area."""

from __future__ import annotations

import os


class Workspace:
    def __init__(self, root: str):
        self.dir = os.path.realpath(root)
        os.makedirs(self.dir, exist_ok=True)
        self._meta_dir = os.path.join(self.dir, ".harness")
        os.makedirs(self._meta_dir, exist_ok=True)

    def write_meta(self, name: str, text: str) -> None:
        """Write a product/metadata file under root/.harness/ (not a deliverable)."""
        path = os.path.join(self._meta_dir, name)
        os.makedirs(os.path.dirname(path) or self._meta_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def snapshot_files(self) -> dict[str, int]:
        """Return {relative_path: byte_size} for deliverable files.

        Excludes the .harness/ meta area.
        """
        result: dict[str, int] = {}
        for dirpath, dirnames, filenames in os.walk(self.dir):
            # skip the meta area
            if ".harness" in dirnames:
                dirnames.remove(".harness")
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, self.dir).replace(os.sep, "/")
                try:
                    result[rel] = os.path.getsize(full)
                except OSError:
                    result[rel] = -1
        return result
