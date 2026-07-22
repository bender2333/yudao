"""Atomic, deterministic run artifact writers."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path


from .workspace import _is_link_or_junction


def _prepare_new_path(path: Path) -> None:
    if not isinstance(path, Path):
        raise TypeError("path must be a Path")
    absolute = Path(os.path.abspath(path))
    for parent in reversed(absolute.parents):
        if not os.path.lexists(parent):
            parent.mkdir()
        if _is_link_or_junction(parent) or not stat.S_ISDIR(parent.lstat().st_mode):
            raise ValueError(f"artifact parent must be a real directory: {parent}")
    for candidate in (path, path.with_name(path.name + ".tmp")):
        if os.path.lexists(candidate):
            raise FileExistsError(candidate)


def _commit_temp(temp: Path, target: Path) -> None:
    try:
        os.link(temp, target)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def write_json_atomic(path: Path, value: object) -> None:
    _prepare_new_path(path)
    temp = path.with_name(path.name + ".tmp")
    try:
        with temp.open("x", encoding="utf-8", newline="\n") as file:
            json.dump(value, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        _commit_temp(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _write_jsonl_atomic(path: Path, rows) -> None:
    _prepare_new_path(path)
    temp = path.with_name(path.name + ".tmp")
    try:
        with temp.open("x", encoding="utf-8", newline="\n") as file:
            for row in rows:
                file.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            file.flush()
            os.fsync(file.fileno())
        _commit_temp(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


class EventWriter:
    def __init__(self, path: Path):
        _prepare_new_path(path)
        self._file = path.open("x", encoding="utf-8", newline="\n")
        self._seq = 0
        self._closed = False

    def append(self, event: dict) -> None:
        if self._closed:
            raise ValueError("event writer is closed")
        if type(event) is not dict:
            raise TypeError("event must be a dict")
        candidate = self._seq + 1
        line = json.dumps({**event, "seq": candidate}, ensure_ascii=False, separators=(",", ":")) + "\n"
        self._file.write(line)
        self._file.flush()
        self._seq = candidate

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._file.flush()
            os.fsync(self._file.fileno())
        finally:
            self._file.close()
