"""Yudao-owned OMP launch isolation: overlay, system prompt, and capture evidence.

Delivery-directory files cannot supply --config or --system-prompt. The model
provider/model stay user-selected; this module does not pick a fallback provider.
User profile and auth stay in place. OMP still appends its own environment/footer,
so the sent system prompt is not byte-identical to the department manifest.

Local capture evidence is access-policy verification against a stub, not proof
that a production request body was captured.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..context import AssembledContext
from .base import InvokeRequest


CONTEXT_DISCOVERY_PROVIDERS = (
    "agents-md",
    "claude-md",
    "native",
    "agents",
    "codex",
    "claude",
    "gemini",
    "github",
    "opencode",
)

ISOLATION_FLAGS = (
    "--no-tools",
    "--no-lsp",
    "--no-session",
    "--no-extensions",
    "--no-skills",
    "--no-rules",
    "--no-title",
)

HOST_OWNED_FLAGS = ("--config", "--system-prompt", "--append-system-prompt")
UNVERIFIABLE_FLAGS = ("--add-dir", "--append-system-prompt")

POLICY_ID = "overlay-disabled-9-discovery-providers+host-system-prompt+isolation-flags"
CAPTURE_SCHEMA = "yudao-omp-isolation-capture/v2"
CAPTURE_SEMANTIC = "access_policy_verification"


def isolation_overlay_path() -> Path:
    path = Path(__file__).resolve().parent / "omp_isolation.yml"
    if not path.is_file():
        raise FileNotFoundError(f"missing Yudao OMP isolation overlay: {path}")
    return path


def overlay_sha256() -> str:
    return sha256_file(isolation_overlay_path())


def capture_evidence_path() -> Path:
    return Path(__file__).resolve().parents[2] / ".tmp" / "omp_isolation_capture.json"


def describe_launch_policy() -> dict[str, Any]:
    overlay = isolation_overlay_path()
    return {
        "policy_id": POLICY_ID,
        "flags": list(ISOLATION_FLAGS),
        "overlay": {
            "path": str(overlay),
            "sha256": overlay_sha256(),
            "controlled_by": "yudao",
            "disabled_providers": list(CONTEXT_DISCOVERY_PROVIDERS),
            "enabled_providers": [],
            "include_workspace_tree": False,
        },
        "system_prompt": {
            "controlled_by": "yudao",
            "origin": "assembled_department_context",
            "overridable_by_delivery_files": False,
        },
        "profile": "retain_user_profile",
        "omp_generated": ["environment", "footer"],
        "byte_identical_to_manifest": False,
        "provider_fallback": False,
    }


def describe_prompt_sources(
    context: AssembledContext,
    *,
    overlay_path: Path,
    system_prompt_path: Path,
) -> dict[str, Any]:
    injected = [
        {"source": item.source, "version": item.version, "digest": item.digest}
        for item in context.manifest.injected
    ]
    excluded = [{"source": item.source, "reason": item.reason} for item in context.manifest.excluded]
    prompt_bytes = context.prompt_text.encode("utf-8")
    return {
        "host_system_prompt": {
            "controlled_by": "yudao",
            "path": str(system_prompt_path),
            "origin": "assembled_department_context",
            "department": context.department,
            "manifest_digest": context.manifest.digest,
            "injected": injected,
            "excluded": excluded,
            "byte_count": len(prompt_bytes),
            "sha256": sha256_bytes(prompt_bytes),
        },
        "host_overlay": {
            "controlled_by": "yudao",
            "path": str(overlay_path),
            "sha256": sha256_file(overlay_path),
            "disabled_providers": list(CONTEXT_DISCOVERY_PROVIDERS),
            "enabled_providers": [],
            "include_workspace_tree": False,
        },
        "omp_generated": [
            {
                "section": "environment",
                "origin": "omp_project_footer",
                "note": "OMP workstation/environment block is still appended",
            },
            {
                "section": "footer",
                "origin": "omp_project_footer",
                "note": "OMP critical/instructions footer is still appended",
            },
        ],
        "byte_identical_to_manifest": False,
        "note": "sent system prompt includes OMP environment/footer and is not only the department manifest bytes",
    }


def strip_host_owned_flags(command: list[str]) -> list[str]:
    """Drop --config/--system-prompt supplied by user args or delivery paths."""
    kept: list[str] = []
    skip_value = False
    for token in command:
        if skip_value:
            skip_value = False
            continue
        name, separator, _value = token.partition("=")
        if name in HOST_OWNED_FLAGS:
            if not separator:
                skip_value = True
            continue
        kept.append(token)
    return kept


def apply_host_launch_args(
    command: list[str],
    *,
    provider: str | None,
    model: str | None,
    system_prompt_path: str | Path,
) -> list[str]:
    command = strip_host_owned_flags(list(command))
    if provider and "--provider" not in command:
        command.extend(["--provider", provider])
    if model and "--model" not in command:
        command.extend(["--model", model])
    for flag in ISOLATION_FLAGS:
        if flag not in command:
            command.append(flag)
    overlay = isolation_overlay_path()
    command.extend(["--config", str(overlay), "--system-prompt", str(Path(system_prompt_path))])
    return command


def assert_host_controlled_paths(workspace_root: str | Path, overlay_path: Path, system_prompt_path: Path) -> None:
    workspace = Path(workspace_root).resolve()
    overlay = overlay_path.resolve()
    prompt = system_prompt_path.resolve()
    if overlay == workspace or workspace in overlay.parents:
        raise RuntimeError("OMP isolation overlay must not come from the delivery workspace")
    if prompt == workspace or workspace in prompt.parents:
        raise RuntimeError("OMP system prompt must not be written into the delivery workspace")


def unverifiable_reasons(command: list[str]) -> list[str]:
    reasons: list[str] = []
    overlay = str(isolation_overlay_path())
    config_values = _flag_values(command, "--config")
    prompt_values = _flag_values(command, "--system-prompt")
    if config_values != [overlay]:
        reasons.append("host overlay is not the sole --config value")
    if len(prompt_values) != 1:
        reasons.append("host system prompt is not the sole --system-prompt value")
    for flag in ISOLATION_FLAGS:
        if flag not in command:
            reasons.append(f"missing isolation flag {flag}")
    if any(token == "--tools" or token.startswith("--tools=") for token in command):
        reasons.append("builtin --tools would replace Yudao host tools")
    if "--" in command:
        reasons.append("end-of-options can prevent host isolation flags from applying")
    for flag in UNVERIFIABLE_FLAGS:
        if flag in command or any(token.startswith(f"{flag}=") for token in command):
            reasons.append(f"unverified context source flag {flag}")
    return reasons


def build_launch_diagnostics(
    request: InvokeRequest,
    command: list[str],
    isolation: IsolationFiles,
) -> dict[str, Any]:
    reasons = unverifiable_reasons(command)
    retained = _env_get(isolation.env, "PI_CODING_AGENT_DIR")
    return {
        "kind": "host_launch_diagnostics",
        "run_id": request.run_id,
        "session_id": request.session_id,
        "activation_id": request.activation_id,
        "context_digest": request.context.manifest.digest,
        "policy_id": POLICY_ID,
        "flags": list(ISOLATION_FLAGS),
        "overlay_sha256": overlay_sha256(),
        "disabled_providers": list(CONTEXT_DISCOVERY_PROVIDERS),
        "runtime": runtime_identity(command),
        "launch_args_sha256": launch_args_sha256(command),
        "process_started": False,
        "profile_retained": True,
        "retained_profile": retained,
        "verifiable": not reasons,
        "unverifiable_reasons": reasons,
        "prompt_sources": isolation.prompt_sources,
        "omp_generated": ["environment", "footer"],
        "byte_identical_to_manifest": False,
        "provider_fallback": False,
    }


def runtime_identity(command: list[str]) -> dict[str, Any]:
    files: list[dict[str, str]] = []
    for index, token in enumerate(command):
        if token.startswith("-"):
            break
        path = Path(shutil.which(token) or token) if index == 0 else Path(token)
        if path.is_file():
            resolved = path.resolve()
            files.append({"path": str(resolved), "sha256": sha256_file(resolved)})
    return {"files": files}


def launch_args_sha256(command: list[str]) -> str:
    # Model, profile, and per-activation prompt paths vary without changing discovery policy.
    ignored = {"--provider", "--model", "--profile"}
    normalized: list[str] = []
    index = 1
    while index < len(command) and not command[index].startswith("-"):
        if not Path(command[index]).is_file():
            normalized.append(command[index])
        index += 1
    while index < len(command):
        token = command[index]
        name, separator, _ = token.partition("=")
        if name in ignored or name in {"--config", "--system-prompt"}:
            if name not in ignored:
                normalized.append(name)
            index += 1 if separator else 2
            continue
        normalized.append(token)
        index += 1
    return sha256_bytes(json.dumps(normalized, separators=(",", ":")).encode("utf-8"))


def runtime_sha256s(record: dict[str, Any]) -> list[str]:
    runtime = record.get("runtime") or {}
    files = runtime.get("files") if isinstance(runtime, dict) else None
    if not isinstance(files, list):
        return []
    return [str(item.get("sha256")) for item in files if isinstance(item, dict) and item.get("sha256")]


@dataclass
class IsolationFiles:
    root: Path
    overlay_path: Path
    system_prompt_path: Path
    env: dict[str, str]
    prompt_sources: dict[str, Any]
    retained_profile: str | None


def prepare_invocation_isolation(
    env: dict[str, str],
    context: AssembledContext,
    workspace_root: str | Path,
) -> IsolationFiles:
    root = Path(tempfile.mkdtemp(prefix="yudao-omp-host-"))
    try:
        system_prompt_path = root / "system-prompt.txt"
        system_prompt_path.write_text(context.prompt_text, encoding="utf-8")
        overlay_path = isolation_overlay_path()
        assert_host_controlled_paths(workspace_root, overlay_path, system_prompt_path)
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise
    spawn_env = dict(env)
    return IsolationFiles(
        root=root,
        overlay_path=overlay_path,
        system_prompt_path=system_prompt_path,
        env=spawn_env,
        prompt_sources=describe_prompt_sources(
            context,
            overlay_path=overlay_path,
            system_prompt_path=system_prompt_path,
        ),
        retained_profile=_env_get(spawn_env, "PI_CODING_AGENT_DIR"),
    )


def cleanup_isolation(files: IsolationFiles | None) -> None:
    if files is None:
        return
    shutil.rmtree(files.root, ignore_errors=True)


def evaluate_capture(launch_records: list[dict[str, Any]]) -> dict[str, Any]:
    if not launch_records:
        return _unverified(["没有该 run 的实际 OMP 启动诊断"])
    if any(record.get("process_started") is not True for record in launch_records):
        return _unverified(["缺少实际 OMP 进程启动记录"])
    if any(not record.get("verifiable", False) for record in launch_records):
        reasons = []
        for record in launch_records:
            reasons.extend(str(item) for item in (record.get("unverifiable_reasons") or []))
        return _unverified(["实际启动含不可验证的发现/提示来源组合", *reasons] or ["实际启动不可验证"])
    path = capture_evidence_path()
    if not path.is_file():
        return _unverified(["缺少与当前 OMP 启动策略对应的本地请求捕获验证依据"])
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _unverified(["请求捕获证据文件不可读"])
    if not isinstance(data, dict):
        return _unverified(["请求捕获证据文件格式无效"])
    if data.get("schema") != CAPTURE_SCHEMA:
        return _unverified(["捕获证据格式未知或过旧，不能继续标记验证通过"])
    if data.get("semantic") != CAPTURE_SEMANTIC:
        return _unverified(["捕获证据语义不是接入策略验证"])
    if data.get("canaries_present") is not False:
        return _unverified(["缺少明确的 canary 排除证明"])
    if data.get("host_tools_registered") is not True or data.get("custom_prompt_in_system") is not True:
        return _unverified(["缺少宿主工具注册或系统提示来源证明"])
    if data.get("host_tools_roundtrip") is not True:
        return _unverified(["缺少 host tools 往返证明"])
    if not isinstance(data.get("request_count"), int) or data["request_count"] < 2:
        return _unverified(["缺少工具返回后的第二次请求捕获"])
    if data.get("verified") is not True:
        return _unverified(["捕获证据未通过"])
    expected_overlay = overlay_sha256()
    expected_flags = list(ISOLATION_FLAGS)
    hashes = data.get("runtime_sha256")
    if not isinstance(hashes, list) or not hashes or any(not _valid_sha256(value) for value in hashes):
        return _unverified(["捕获证据缺少有效 runtime 指纹"])
    capture_runtime = hashes
    if data.get("policy_id") != POLICY_ID or not _valid_sha256(data.get("launch_args_sha256")):
        return _unverified(["捕获证据缺少已知策略或启动参数指纹"])
    for record in launch_records:
        if record.get("policy_id") != data.get("policy_id"):
            return _unverified(["实际启动策略与捕获证据的 policy_id 不一致"], evidence=str(path))
        if record.get("overlay_sha256") != data.get("overlay_sha256") or record.get("overlay_sha256") != expected_overlay:
            return _unverified(["实际启动 overlay 与捕获证据不一致"], evidence=str(path))
        if record.get("flags") != data.get("flags") or record.get("flags") != expected_flags:
            return _unverified(["实际启动隔离开关与捕获证据不一致"], evidence=str(path))
        if runtime_sha256s(record) != capture_runtime:
            return _unverified(["实际启动 runtime 与捕获证据不一致"], evidence=str(path))
        if record.get("launch_args_sha256") != data.get("launch_args_sha256"):
            return _unverified(["实际启动参数与捕获证据不一致"], evidence=str(path))
    notes = [str(note) for note in data.get("notes", [])] if isinstance(data.get("notes"), list) else []
    notes.append("本地 stub 接入策略验证，不是该生产请求正文捕获")
    return {
        "status": "verified",
        "semantic": CAPTURE_SEMANTIC,
        "evidence": data.get("test") or str(path),
        "canaries_present": False,
        "host_tools_registered": data.get("host_tools_registered"),
        "host_tools_roundtrip": True,
        "system_bytes": data.get("system_bytes"),
        "input_bytes": data.get("input_bytes"),
        "request_bytes": data.get("request_bytes"),
        "overlay_sha256": data.get("overlay_sha256"),
        "runtime_sha256": list(capture_runtime),
        "notes": notes,
    }


def write_capture_evidence(payload: dict[str, Any]) -> Path:
    path = capture_evidence_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "schema": CAPTURE_SCHEMA,
        "semantic": CAPTURE_SEMANTIC,
        **payload,
    }
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _flag_values(command: list[str], flag: str) -> list[str]:
    values: list[str] = []
    pending = False
    for token in command:
        if pending:
            values.append(token)
            pending = False
            continue
        name, separator, value = token.partition("=")
        if name != flag:
            continue
        if separator:
            values.append(value)
        else:
            pending = True
    return values


def _env_get(env: dict[str, str], key: str) -> str | None:
    if key in env:
        return env[key]
    wanted = key.upper()
    for name, value in env.items():
        if name.upper() == wanted:
            return value
    return None


def _unverified(notes: list[str], *, evidence: str | None = None) -> dict[str, Any]:
    return {
        "status": "unverified",
        "semantic": CAPTURE_SEMANTIC,
        "evidence": evidence,
        "notes": notes,
    }
