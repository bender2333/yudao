# 工具定义：各部门可以使用的工具、主机工具与环境工具的分类、提交类工具对应的提案种类、登记命令的校验，
# 以及请求中提供给模型的工具定义。主机工具由步骤驱动执行，环境工具的动作由执行环境（environment.py）执行。

from __future__ import annotations

import re
from typing import Any

CHECK_TIMEOUT_SEC = 30
CHECK_OUTPUT_LIMIT = 4000

# kind：主机工具（host）由控制核心执行，现在只有提交类工具；环境工具（environment）的每次调用是一个动作，
# 经过工具许可以后在执行环境中执行，action 是动作类别（读取、写入、检查、登记的本地命令）
TOOL_DEFS = {
    "read_file": {"kind": "environment", "action": "read", "departments": ("product", "engineering", "quality")},
    "list_files": {"kind": "environment", "action": "read", "departments": ("product", "engineering", "quality")},
    "search": {"kind": "environment", "action": "read", "departments": ("product", "engineering", "quality")},
    "read_range": {"kind": "environment", "action": "read", "departments": ("product", "engineering", "quality")},
    "write_file": {"kind": "environment", "action": "write", "departments": ("engineering",)},
    "edit_range": {"kind": "environment", "action": "write", "departments": ("engineering",)},
    "delete_file": {"kind": "environment", "action": "write", "departments": ("engineering",)},
    "move_file": {"kind": "environment", "action": "write", "departments": ("engineering",)},
    "run_check": {"kind": "environment", "action": "check", "departments": ("product", "engineering", "quality")},
    "run_command": {"kind": "environment", "action": "command", "departments": ("engineering",)},
    "submit_product_spec": {"kind": "host", "departments": ("product",)},
    "submit_product_decision": {"kind": "host", "departments": ("product",)},
    "submit_request": {"kind": "host", "departments": ("product", "engineering", "quality")},
    "submit_response": {"kind": "host", "departments": ("product", "engineering", "quality")},
    "submit_guidance_response": {"kind": "host", "departments": ("product", "engineering", "quality")},
    "submit_plan": {"kind": "host", "departments": ("engineering",)},
    "submit_delivery": {"kind": "host", "departments": ("engineering",)},
    "submit_review": {"kind": "host", "departments": ("quality",)},
}

SUBMIT_KINDS = {
    "submit_product_spec": "product_spec",
    "submit_product_decision": "product_decision",
    "submit_request": "collaboration_request",
    "submit_response": "collaboration_response",
    "submit_guidance_response": "department_guidance_response",
    "submit_plan": "engineering_plan",
    "submit_delivery": "delivery_spec",
    "submit_review": "qa_review",
}

# 登记命令名只允许简单标识，避免路径与 shell 元字符进入注册表
_COMMAND_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
# 超时上限 10 分钟：登记命令是受信构建/测试入口，不是常驻服务
COMMAND_TIMEOUT_MAX_SEC = 600


def validate_registered_command(name: str, config: dict[str, Any]) -> dict[str, Any]:
    # 校验一条项目登记命令，返回冻结用的规范形态；任一非法直接报错
    if not isinstance(name, str) or not _COMMAND_NAME_PATTERN.fullmatch(name):
        raise ValueError("command name must match [A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
    if not isinstance(config, dict):
        raise ValueError(f"registered command {name} must be an object")
    argv = config.get("argv")
    if not isinstance(argv, list) or not argv or any(not isinstance(item, str) or not item for item in argv):
        raise ValueError(f"registered command {name} requires a non-empty argv list of strings")
    extra_args = config.get("args", [])
    if not isinstance(extra_args, list) or any(not isinstance(item, str) or not item for item in extra_args):
        raise ValueError(f"registered command {name} allowlist args must be a list of non-empty strings")
    timeout_sec = config.get("timeout_sec", CHECK_TIMEOUT_SEC)
    if type(timeout_sec) is not int or not 1 <= timeout_sec <= COMMAND_TIMEOUT_MAX_SEC:
        raise ValueError(f"registered command {name} timeout_sec must be an integer in 1..{COMMAND_TIMEOUT_MAX_SEC}")
    output_limit = config.get("output_limit", CHECK_OUTPUT_LIMIT)
    if type(output_limit) is not int or output_limit < 1:
        raise ValueError(f"registered command {name} output_limit must be an integer >= 1")
    return {"argv": list(argv), "args": list(extra_args), "timeout_sec": timeout_sec, "output_limit": output_limit}


def normalize_registered_commands(registry: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    # 冻结注册表逐条校验并规范化；空注册表表示本轮没有可用命令
    if registry is None:
        return {}
    if not isinstance(registry, dict):
        raise ValueError("registered_commands must be an object")
    return {name: validate_registered_command(name, config) for name, config in registry.items()}


def tools_for(department: str) -> list[str]:
    return [name for name, spec in TOOL_DEFS.items() if department in spec["departments"]]


def has_tool(department: str, name: str) -> bool:
    spec = TOOL_DEFS.get(name)
    return bool(spec and department in spec["departments"])


def tool_definitions(tool_names: list[str]) -> list[dict[str, Any]]:
    return [dict(TOOL_SCHEMAS[name]) for name in tool_names if name in TOOL_SCHEMAS]


def _object_schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def _string_list_schema(description: str) -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}, "description": description}


TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "read_file": {
        "name": "read_file",
        "label": "read_file",
        "description": "Return the entire content of one public workspace file as a single UTF-8 string, without line numbers or truncation. Files that are not valid UTF-8 are rejected. Paths under .checks are host-private. Use read_range for large files, or when you need line numbers and the content_hash that edit_range checks.",
        "parameters": _object_schema({"path": {"type": "string", "description": "Workspace-relative file path"}}, ["path"]),
        "loadMode": "essential",
    },
    "list_files": {
        "name": "list_files",
        "label": "list_files",
        "description": "List every file in the public workspace tree, recursively, as workspace-relative paths. prefix filters by plain string prefix on those paths: \"src/\" keeps only the src directory, while \"src\" also keeps paths such as \"src2/a.py\". Paths under .checks are never listed.",
        "parameters": _object_schema({"prefix": {"type": "string", "description": "Optional string prefix on workspace-relative paths; end it with / to limit the list to one directory"}}),
        "loadMode": "essential",
    },
    "search": {
        "name": "search",
        "label": "search",
        "description": "Search public workspace files with a Python re regex. Returns path, 1-based line and snippet per match with the snapshot digest. Large results are truncated with next_cursor.",
        "parameters": _object_schema(
            {
                "pattern": {"type": "string", "description": "Python re regex searched per line"},
                "path": {"type": ["string", "null"], "description": "Optional file or directory scope within the public tree"},
                "max_results": {"type": ["integer", "null"], "description": "Maximum matches per page"},
                "cursor": {"type": ["string", "null"], "description": "Continuation cursor from a truncated search"},
            },
            ["pattern"],
        ),
        "loadMode": "essential",
    },
    "read_range": {
        "name": "read_range",
        "label": "read_range",
        "description": "Read a line range of one public workspace file. Returns path, start_line, end_line, total_lines, the snapshot digest and the file content_hash. Truncated output carries next_cursor.",
        "parameters": _object_schema(
            {
                "path": {"type": "string", "description": "Workspace-relative file path"},
                "start_line": {"type": "integer", "description": "First line to read, 1-based"},
                "end_line": {"type": ["integer", "null"], "description": "Last line to read, inclusive; omit for end of file"},
                "cursor": {"type": ["string", "null"], "description": "Continuation cursor from a truncated read"},
            },
            ["path", "start_line"],
        ),
        "loadMode": "essential",
    },
    "write_file": {
        "name": "write_file",
        "label": "write_file",
        "description": "Create one public workspace file or replace its entire content with UTF-8 text; missing parent directories are created. Engineering only. Requires an accepted engineering plan for the current effective contract, and the path must be inside that plan's scope; otherwise the call is rejected and nothing is written. Paths under .checks are host-private. Use edit_range to change part of an existing file.",
        "parameters": _object_schema(
            {
                "path": {"type": "string", "description": "Workspace-relative file path"},
                "content": {"type": "string", "description": "Full file contents"},
            },
            ["path", "content"],
        ),
        "loadMode": "essential",
    },
    "edit_range": {
        "name": "edit_range",
        "label": "edit_range",
        "description": "Replace an exact original line span inside one public workspace file. Engineering only. The span must equal expected_text exactly, expected_text must occur exactly once in the file, and expected_digest (the read_range file content_hash) must still match when given; otherwise the edit is rejected and the file is left unchanged. Requires an accepted engineering plan for the current effective contract, and the path must be inside that plan's scope.",
        "parameters": _object_schema(
            {
                "path": {"type": "string", "description": "Workspace-relative file path"},
                "start_line": {"type": "integer", "description": "First line to replace, 1-based"},
                "end_line": {"type": "integer", "description": "Last line to replace, inclusive"},
                "expected_text": {"type": "string", "description": "Exact original lines previously read, joined by newline without a trailing newline"},
                "new_text": {"type": "string", "description": "Replacement text for the span, lines joined by newline"},
                "expected_digest": {"type": ["string", "null"], "description": "File content_hash observed when the span was read; omit to skip the digest check"},
            },
            ["path", "start_line", "end_line", "expected_text", "new_text"],
        ),
        "loadMode": "essential",
    },
    "delete_file": {        "name": "delete_file",
        "label": "delete_file",
        "description": "Delete one existing regular workspace file within the effective engineering plan. Engineering only; requires a reason. Directories and links are rejected.",
        "parameters": _object_schema(
            {"path": {"type": "string"}, "reason": {"type": "string", "minLength": 1}},
            ["path", "reason"],
        ),
        "loadMode": "essential",
    },
    "move_file": {
        "name": "move_file",
        "label": "move_file",
        "description": "Move one existing regular workspace file without overwriting. Both paths must be in the effective engineering plan. Engineering only; requires a reason. Directories and links are rejected.",
        "parameters": _object_schema(
            {"source": {"type": "string"}, "destination": {"type": "string"},
             "reason": {"type": "string", "minLength": 1}},
            ["source", "destination", "reason"],
        ),
        "loadMode": "essential",
    },
    "run_check": {
        "name": "run_check",
        "label": "run_check",
        "description": "Host-executes a check in the workspace and records exit_code, summary, and snapshot hash. Do not self-report exit_code. argv example: [\"python\", \"src/echo.py\", \"hello\"].",
        "parameters": _object_schema(
            {
                "name": {"type": "string", "description": "Check name, e.g. smoke"},
                "argv": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Argument vector executed by the host, e.g. [\"python\", \"src/echo.py\", \"hello\"]",
                },
            },
            ["name", "argv"],
        ),
        "loadMode": "essential",
    },
    "run_command": {
        "name": "run_command",
        "label": "run_command",
        "description": "Engineering-only: run one project-registered command in the run workspace with a stripped environment, time limit, output limit, and process-tree cleanup. Only the registered name and allowlisted extra args are accepted. The host-observed exit status is the evidence; a self-reported exit_code is never read. run_command results are action receipts and cannot be listed in submit_delivery check_names; run the checks a delivery needs with run_check.",
        "parameters": _object_schema(
            {
                "name": {"type": "string", "description": "Registered command name frozen for this run"},
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Extra arguments; every item must be in the registered allowlist",
                },
            },
            ["name"],
        ),
        "loadMode": "essential",
    },
    "submit_product_spec": {
        "name": "submit_product_spec",
        "label": "submit_product_spec",
        "description": "Submit a ProductSpec. Required: goal, requirements, acceptance_criteria.",
        "parameters": _object_schema(
            {
                "goal": {"type": "string"},
                "requirements": _string_list_schema("Must contain at least one item"),
                "acceptance_criteria": _string_list_schema("Must contain at least one item"),
                "boundaries": _string_list_schema("Optional"),
                "constraints": _string_list_schema("Optional"),
                "fatal_conditions": _string_list_schema("Optional"),
                "non_goals": _string_list_schema("Optional"),
                "change_record": {
                    **_object_schema(
                        {
                            "changed": _string_list_schema("Requirements added or changed in this revision"),
                            "retained": _string_list_schema("Requirements explicitly preserved"),
                            "retired": _string_list_schema("Requirements explicitly removed"),
                            "rationale": {"type": "string", "minLength": 1},
                        },
                        ["changed", "retained", "retired", "rationale"],
                    ),
                    "description": "Required when replacing a ProductSpec. Submit the complete new requirements and explain changed, retained, and retired behavior. A complete ProductSpec processes user input; a response or product decision does not. Omit on the first spec.",
                },
                "decision_changes": {
                    "type": "array",
                    "items": _object_schema({
                        "decision_hash": {"type": "string"},
                        "disposition": {"type": "string", "enum": ["retain", "integrate", "retire"]},
                        "rationale": {"type": "string"},
                    }, ["decision_hash", "disposition", "rationale"]),
                    "description": "When replacing a spec, explicitly retain, integrate, or retire every effective product decision. Empty for the first spec.",
                },
            },
            ["goal", "requirements", "acceptance_criteria"],
        ),
        "loadMode": "essential",
    },
    "submit_product_decision": {
        "name": "submit_product_decision",
        "label": "submit_product_decision",
        "description": "Publish an explicit product requirement decision with its rationale. This changes the effective contract. A consultation response alone does not change product requirements.",
        "parameters": _object_schema(
            {"statement": {"type": "string"}, "rationale": {"type": "string"}},
            ["statement", "rationale"],
        ),
        "loadMode": "essential",
    },
    "submit_request": {
        "name": "submit_request",
        "label": "submit_request",
        "description": "Ask another department for consultation or a concrete action. The recipient responds before the requester resumes. Only one request may be pending; consultation does not authorize delivery changes.",
        "parameters": _object_schema(
            {
                "recipient": {"type": "string", "enum": ["product", "engineering", "quality"]},
                "request_type": {"type": "string", "enum": ["consultation", "action"]},
                "question": {"type": "string"},
                "background": {"type": "string"},
                "expected_result": {"type": "string"},
                "action": {"type": ["string", "null"], "enum": [None, "inspect", "check", "revise_requirements", "revise_delivery"]},
            },
            ["recipient", "request_type", "question", "background", "expected_result", "action"],
        ),
        "loadMode": "essential",
    },
    "submit_response": {
        "name": "submit_response",
        "label": "submit_response",
        "description": "Respond to the pending request addressed to your department. For completed actions, first produce normal accepted artifacts or host checks and cite their actual event IDs. Do not invent evidence or use a response as a product decision.",
        "parameters": _object_schema(
            {
                "request_id": {"type": "string"},
                "status": {"type": "string", "enum": ["answered", "completed", "declined", "needs_work"]},
                "text": {"type": "string"},
                "result_event_ids": _string_list_schema("Actual accepted result or host tool event IDs for this request"),
            },
            ["request_id", "status", "text", "result_event_ids"],
        ),
        "loadMode": "essential",
    },
    "submit_guidance_response": {
        "name": "submit_guidance_response",
        "label": "submit_guidance_response",
        "description": "Respond to one persisted department guidance item. Use explained when the handling is an explanation, no change is required, or this department cannot apply it. Use completed only when host-verified actions after this guidance was adopted are listed in guidance_results; the host binds those results and result_event_ids cannot enlarge that set. Empty, rejected, failed, or earlier-unrelated results cannot complete an action. This response does not change the contract, plan, files, or QA result by itself.",
        "parameters": _object_schema(
            {
                "guidance_id": {"type": "string"},
                "status": {"type": "string", "enum": ["explained", "completed", "declined", "needs_work"]},
                "text": {"type": "string"},
                "result_event_ids": _string_list_schema("Optional. completed must be a subset of guidance_results; the host binds those results. explained, declined, and needs_work do not require results."),
            },
            ["guidance_id", "status", "text", "result_event_ids"],
        ),
        "loadMode": "essential",
    },
    "submit_plan": {
        "name": "submit_plan",
        "label": "submit_plan",
        "description": "Submit an engineering plan before changing delivery files. The host binds it to the current effective contract. Plan adjustments require a reason; product requirements must be decided by product.",
        "parameters": _object_schema(
            {
                "objective": {"type": "string"},
                "scope": _string_list_schema("Relative files or directories ending with /; . means the entire public workspace"),
                "tasks": {
                    "type": "array",
                    "items": _object_schema(
                        {
                            "title": {"type": "string"},
                            "outputs": _string_list_schema("Observable outputs of this task"),
                            "verification": {"type": "string", "description": "How to verify these outputs"},
                        },
                        ["title", "outputs", "verification"],
                    ),
                    "description": "Non-empty tasks in execution order",
                },
                "refactoring": _string_list_schema("Necessary structural changes, or an empty list"),
                "assumptions": {
                    "type": "array",
                    "items": _object_schema(
                        {"decision": {"type": "string"}, "basis": {"type": "string"}},
                        ["decision", "basis"],
                    ),
                    "description": "Professional defaults and their basis; do not present defaults as user statements",
                },
                "reason": {"type": "string", "description": "Reason for adjusting an existing plan; may be empty for the first plan"},
            },
            ["objective", "scope", "tasks", "refactoring", "assumptions", "reason"],
        ),
        "loadMode": "essential",
    },
    "submit_delivery": {
        "name": "submit_delivery",
        "label": "submit_delivery",
        "description": "Submit a DeliverySpec after writing files and running checks. Every name in check_names must be a name you passed to run_check in this activation on the current workspace; receipts from earlier activations are not reused, and if any file changes after a check, call run_check again before submitting. run_command results are action receipts and are not accepted as delivery check receipts. A name without a matching run_check receipt rejects the delivery.",
        "parameters": _object_schema(
            {
                "summary": {"type": "string"},
                "files": _string_list_schema("Workspace-relative files included in the delivery"),
                "check_names": _string_list_schema("Names passed to run_check in this activation on the current workspace; run_command results do not count"),
                "known_risks": _string_list_schema("Optional"),
            },
            ["summary", "files", "check_names"],
        ),
        "loadMode": "essential",
    },
    "submit_review": {
        "name": "submit_review",
        "label": "submit_review",
        "description": "Submit a QAReview. release requires quality-run host receipts with exit_code 0 on the current snapshot. Engineering receipts are not accepted as QA evidence. checks are check names.",
        "parameters": _object_schema(
            {
                "verdict": {"type": "string", "enum": ["rework_product", "rework_engineering", "release"]},
                "rationale": {"type": "string"},
                "checks": {"type": "array", "items": {"type": "string"}, "description": "Quality check names run via run_check"},
                "defects": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "severity": {"type": "string", "enum": ["blocker", "major", "minor"]},
                            "summary": {"type": "string"},
                        },
                        "required": ["severity", "summary"],
                    },
                },
            },
            ["verdict", "rationale", "checks"],
        ),
        "loadMode": "essential",
    },
}
