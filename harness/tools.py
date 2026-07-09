"""Tool definitions + handlers for the solo agent.

Each handler: handler(workspace_dir, **kwargs) -> str. Handlers never raise;
on error they return an "Error: ..." string for the model to read.

All file paths go through safe_path, which confines them to workspace_dir.
"""

from __future__ import annotations

import os
import subprocess

_MAX_OUTPUT = 50_000
_BASH_TIMEOUT = 120

# Dangerous substrings blocked in bash commands (spec §3 / tools.py).
_DANGEROUS = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/", "mkfs", ":(){"]


def safe_path(workspace_dir: str, rel: str) -> str:
    """Resolve rel against workspace_dir; raise ValueError if it escapes."""
    root = os.path.realpath(workspace_dir)
    target = os.path.realpath(os.path.join(root, rel))
    if target != root and not target.startswith(root + os.sep):
        raise ValueError(f"path escapes workspace: {rel}")
    return target


# ── handlers ──────────────────────────────────────────────
def read_file(workspace_dir: str, path: str, limit: int | None = None) -> str:
    try:
        p = safe_path(workspace_dir, path)
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            if limit is not None:
                lines = []
                for i, line in enumerate(f):
                    if i >= limit:
                        break
                    lines.append(line)
                return "".join(lines)
            return f.read()
    except ValueError as e:
        return f"Error: {e}"
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except OSError as e:
        return f"Error: {e}"


def write_file(workspace_dir: str, path: str, content: str) -> str:
    try:
        p = safe_path(workspace_dir, path)
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Wrote {len(content)} bytes to {path}"
    except ValueError as e:
        return f"Error: {e}"
    except OSError as e:
        return f"Error: {e}"


def edit_file(workspace_dir: str, path: str, old: str, new: str) -> str:
    try:
        p = safe_path(workspace_dir, path)
        with open(p, "r", encoding="utf-8") as f:
            content = f.read()
        count = content.count(old)
        if count == 0:
            return f"Error: old string not found in {path}"
        content = content.replace(old, new)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Edited {path} ({count} replacement(s))"
    except ValueError as e:
        return f"Error: {e}"
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except OSError as e:
        return f"Error: {e}"


def bash(workspace_dir: str, command: str) -> str:
    if any(d in command for d in _DANGEROUS):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(
            command,
            shell=True,
            cwd=workspace_dir,
            capture_output=True,
            text=True,
            timeout=_BASH_TIMEOUT,
        )
        out = (r.stdout + r.stderr).strip()
        if not out:
            return "(no output)"
        return out[:_MAX_OUTPUT]
    except subprocess.TimeoutExpired:
        return f"Error: Timeout ({_BASH_TIMEOUT}s)"
    except (FileNotFoundError, OSError) as e:
        return f"Error: {e}"


def list_dir(workspace_dir: str, path: str = ".") -> str:
    try:
        p = safe_path(workspace_dir, path)
        if not os.path.isdir(p):
            return f"Error: not a directory: {path}"
        entries = sorted(os.listdir(p))
        if not entries:
            return "(empty)"
        lines = []
        for name in entries:
            full = os.path.join(p, name)
            suffix = "/" if os.path.isdir(full) else ""
            lines.append(name + suffix)
        return "\n".join(lines)
    except ValueError as e:
        return f"Error: {e}"
    except OSError as e:
        return f"Error: {e}"


TOOL_HANDLERS = {
    "read_file": read_file,
    "write_file": write_file,
    "edit_file": edit_file,
    "bash": bash,
    "list_dir": list_dir,
}


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


TOOL_DEFS = [
    _fn(
        "read_file",
        "Read a text file in the workspace. Optionally limit to the first N lines.",
        {
            "path": {"type": "string", "description": "Path relative to workspace."},
            "limit": {"type": "integer", "description": "Max lines to read."},
        },
        ["path"],
    ),
    _fn(
        "write_file",
        "Write (create or overwrite) a file in the workspace with the given content.",
        {
            "path": {"type": "string", "description": "Path relative to workspace."},
            "content": {"type": "string", "description": "Full file content."},
        },
        ["path", "content"],
    ),
    _fn(
        "edit_file",
        "Replace all occurrences of an exact old string with a new string in a file.",
        {
            "path": {"type": "string", "description": "Path relative to workspace."},
            "old": {"type": "string", "description": "Exact text to find."},
            "new": {"type": "string", "description": "Replacement text."},
        },
        ["path", "old", "new"],
    ),
    _fn(
        "bash",
        "Run a shell command in the workspace directory. 120s timeout.",
        {"command": {"type": "string", "description": "Shell command to run."}},
        ["command"],
    ),
    _fn(
        "list_dir",
        "List entries in a workspace directory (directories end with '/').",
        {"path": {"type": "string", "description": "Directory path relative to workspace."}},
        [],
    ),
]

# Stages that must not mutate deliverables (UNDERSTAND / VERIFY / consult).
_WRITE_TOOL_NAMES = frozenset({"write_file", "edit_file"})


def tool_defs_without_writes(defs: list | None = None) -> list:
    """Return tool defs excluding write_file / edit_file (read + bash + list)."""
    src = defs if defs is not None else TOOL_DEFS
    return [t for t in src if t["function"]["name"] not in _WRITE_TOOL_NAMES]


def dispatch(name: str, args: dict, workspace_dir: str) -> str:
    """Look up and call a tool handler. Unknown tool -> Error string."""
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return f"Error: unknown tool: {name}"
    try:
        return handler(workspace_dir, **args)
    except TypeError as e:
        return f"Error: bad arguments for {name}: {e}"
