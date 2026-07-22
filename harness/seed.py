"""Copy a safe visible seed into an empty agent workspace."""

from __future__ import annotations

import os
import shutil
import stat

from harness.workspace import _is_link_or_junction, _require_real_directory


def seed_workspace(seed_dir: str, dest_dir: str) -> list[str]:
    """Copy regular seed files into an existing, empty real directory."""
    source_root = _require_real_directory(seed_dir, "seed source", _is_link_or_junction)
    destination_root = _require_real_directory(dest_dir, "seed destination", _is_link_or_junction)
    if os.path.samefile(source_root, destination_root):
        raise ValueError("seed root overlap: source and destination are the same")
    try:
        common_root = os.path.commonpath((source_root, destination_root))
    except ValueError:
        common_root = None
    if common_root in (source_root, destination_root):
        raise ValueError("seed root overlap: source and destination must not contain one another")
    with os.scandir(destination_root) as entries:
        if next(entries, None) is not None:
            raise ValueError(f"seed destination must be empty: {dest_dir}")

    copied: list[str] = []
    for dirpath, dirnames, filenames in os.walk(source_root, followlinks=False):
        for dirname in dirnames:
            source_directory = os.path.join(dirpath, dirname)
            if _is_link_or_junction(source_directory):
                raise ValueError(f"seed directory link is not allowed: {source_directory}")
            if not stat.S_ISDIR(os.lstat(source_directory).st_mode):
                raise ValueError(f"seed special directory is not allowed: {source_directory}")
        dirnames.sort()
        for filename in sorted(filenames):
            source = os.path.join(dirpath, filename)
            if _is_link_or_junction(source):
                raise ValueError(f"seed file link is not allowed: {source}")
            if not stat.S_ISREG(os.lstat(source).st_mode):
                raise ValueError(f"seed special file is not allowed: {source}")

            relative = os.path.relpath(source, source_root)
            target = os.path.join(destination_root, relative)
            os.makedirs(os.path.dirname(target) or destination_root, exist_ok=True)
            shutil.copy2(source, target)
            if _is_link_or_junction(target) or not stat.S_ISREG(os.lstat(target).st_mode):
                raise ValueError(f"seed target is not a regular file: {target}")
            copied.append(relative.replace(os.sep, "/"))
    return sorted(copied)
