"""Atomic, deterministic run artifact writers."""

from __future__ import annotations

import json
import os
from pathlib import Path


def write_json_atomic(path: Path, value: object) -> None:
    if not isinstance(path, Path):
        raise TypeError("path must be a Path")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    created = False
    try:
        with temp.open("x", encoding="utf-8", newline="\n") as file:
            created = True
            json.dump(value, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp, path)
        created = False
    finally:
        if created:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass


def _write_jsonl_atomic(path: Path, rows) -> None:
    if not isinstance(path, Path):
        raise TypeError("path must be a Path")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    created = False
    try:
        with temp.open("x", encoding="utf-8", newline="\n") as file:
            created = True
            for row in rows:
                file.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp, path)
        created = False
    finally:
        if created:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass


class EventWriter:
    def __init__(self, path: Path):
        if not isinstance(path, Path):
            raise TypeError("path must be a Path")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = path.open("x", encoding="utf-8", newline="\n")
        self._seq = 0

    def append(self, event: dict) -> None:
        if type(event) is not dict:
            raise TypeError("event must be a dict")
        self._seq += 1
        record = {**event, "seq": self._seq}
        self._file.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()
