"""Copy seed files into a freshly created agent workspace."""

from __future__ import annotations

import os
import shutil


def seed_workspace(seed_dir: str, dest_dir: str) -> list[str]:
    """Copy all files under seed_dir into dest_dir (merge). Returns relative paths."""
    if not seed_dir or not os.path.isdir(seed_dir):
        raise FileNotFoundError(f"seed_dir not found: {seed_dir}")
    dest_root = os.path.realpath(dest_dir)
    os.makedirs(dest_root, exist_ok=True)
    copied: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(seed_dir):
        rel_dir = os.path.relpath(dirpath, seed_dir)
        for name in filenames:
            src = os.path.join(dirpath, name)
            if rel_dir in (".", ""):
                rel = name.replace("\\", "/")
                out = os.path.join(dest_root, name)
            else:
                rel = os.path.join(rel_dir, name).replace("\\", "/")
                out = os.path.join(dest_root, rel_dir, name)
            os.makedirs(os.path.dirname(out) or dest_root, exist_ok=True)
            shutil.copy2(src, out)
            copied.append(rel.replace("\\", "/"))
    return sorted(copied)
