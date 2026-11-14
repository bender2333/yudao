# 随包分发的进程外运维技能模块层测试（docs/design/external-ops-agent.md「随包运维技能」「三条改动通道与失败处理」「验收」）。

from __future__ import annotations

import io
import json
import re
import shlex
import types
from pathlib import Path
from typing import Annotated, Any, Union, get_args, get_origin

import pytest
import yaml
from markdown_it import MarkdownIt
from pydantic import TypeAdapter

from harness.__main__ import build_parser
from harness.__main__ import main as cli_main
from harness.app.application import DEFAULT_REGISTRY
from harness.app.catalog_queries import CatalogProvider
from harness.app.contracts import (
    EVENT_TYPES,
    REJECTION_REASONS,
    Accepted,
    Capabilities,
    CommandRequest,
    Deployment,
    EventEnvelope,
    Rejected,
    Snapshot,
    StreamCapability,
)
from harness.app.event_stream import StreamResync
from harness.app.payloads import APPLICATION_EVENT_OWNER
from harness.definitions import DEFAULT_FORM, DEFINITIONS, DEFINITIONS_DIR
from harness.kernel_events import SKELETON_EVENTS, application_event_types
from harness.ops_skill import SKILL_FILENAME, install_skill, read_skill_text
from harness.runtime import FORM_REGISTRY
from harness.streams import DECLARED_EVENT_TYPES


def _invoke_skill(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = cli_main(argv, stdin=io.StringIO(""), stdout=stdout, stderr=stderr, environ={})
    return code, stdout.getvalue(), stderr.getvalue()


def _is_placeholder(raw_value: str) -> bool:
    stripped = raw_value.strip()
    return stripped.startswith("<") and stripped.endswith(">")


def _classify_field_types(annotation: Any) -> tuple[bool, bool, bool]:
    # 返回 (允许字符串, 允许非字符串标量或容器, 允许空值)
    origin = get_origin(annotation)
    if origin is Annotated:
        return _classify_field_types(get_args(annotation)[0])
    if origin in (Union, types.UnionType):
        allows_str = False
        allows_non_str = False
        allows_none = False
        for member in get_args(annotation):
            sub_str, sub_non_str, sub_none = _classify_field_types(member)
            allows_str = allows_str or sub_str
            allows_non_str = allows_non_str or sub_non_str
            allows_none = allows_none or sub_none
        return allows_str, allows_non_str, allows_none
    if annotation is Any:
        return True, True, True
    if annotation is type(None):
        return False, False, True
    if str(origin).endswith("Literal"):
        values = get_args(annotation)
        allows_str = any(isinstance(v, str) for v in values)
        allows_non_str = any(v is not None and not isinstance(v, str) for v in values)
        allows_none = any(v is None for v in values)
        return allows_str, allows_non_str, allows_none
    if annotation is str:
        return True, False, False
    return False, True, False


def _assert_command_param_flag(command_name: str, key: str, annotation: Any, param_kind: str) -> None:
    allows_str, allows_non_str, allows_none = _classify_field_types(annotation)
    if allows_str and not allows_non_str and not allows_none:
        assert param_kind == "string", f"命令 {command_name} 的纯字符串字段 {key!r} 必须使用 --string-param"
    if allows_non_str and not allows_str:
        assert param_kind == "json", f"命令 {command_name} 的非字符串字段 {key!r} 必须使用 --param"


def _parse_cli_param_value(raw_value: str, param_kind: str) -> Any:
    if param_kind == "string":
        return raw_value
    try:
        return json.loads(raw_value)
    except json.JSONDecodeError:
        return raw_value


def _validate_skill_contracts(skill_text: str) -> None:
    registered_commands = DEFAULT_REGISTRY.commands
    registered_queries = DEFAULT_REGISTRY.queries
    registered_names = set(registered_commands) | set(registered_queries)
    registered_decisions = set(DEFAULT_REGISTRY.decisions)
    registered_rejections = set(REJECTION_REASONS)
    command_rejection_reasons = {
        reason for cmd_name in registered_commands for reason in DEFAULT_REGISTRY.reasons(cmd_name)
    }

    registered_events = set(EVENT_TYPES)
    assert registered_events == set(DECLARED_EVENT_TYPES)
    default_app_events = {
        kind for kind, owner in application_event_types().items() if owner == APPLICATION_EVENT_OWNER
    }
    assert registered_events == (SKELETON_EVENTS | default_app_events)

    built_in_forms = set(FORM_REGISTRY)
    disk_forms = {DEFAULT_FORM} | {p.name for p in (DEFINITIONS_DIR / "forms").iterdir() if p.is_dir()}
    assert built_in_forms == disk_forms

    registered_parameters = {name for name, rule in DEFINITIONS.rules.items() if rule.kind == "parameter"}

    cli_parser = build_parser()
    valid_subcommands: set[str] = set()
    for action in cli_parser._actions:
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict):
            valid_subcommands.update(choices)

    capabilities_fields = set(Capabilities.model_fields)
    capabilities_dotted = {f"deployment.{k}" for k in Deployment.model_fields} | {
        f"stream.{k}" for k in StreamCapability.model_fields
    }
    resync_reasons = set(get_args(StreamResync.model_fields["reason"].annotation))
    envelope_snake_fields = (
        set(CommandRequest.model_fields)
        | set(Accepted.model_fields)
        | set(Rejected.model_fields)
        | set(Snapshot.model_fields)
        | set(EventEnvelope.model_fields)
        | set(StreamResync.model_fields)
        | set(CatalogProvider.model_fields)
        | capabilities_fields
        | resync_reasons
        | {"refresh_on"}
    )

    parts = skill_text.split("---\n", 2)
    assert len(parts) == 3
    tokens = MarkdownIt().parse(parts[2])
    fences = [tok for tok in tokens if tok.type == "fence"]
    assert fences

    checked_commands = 0
    checked_queries = 0
    checked_events = 0
    checked_forms = 0

    for fence in fences:
        pending_comments: list[str] = []
        for raw_line in fence.content.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#"):
                pending_comments.append(line)
                for dotted in re.findall(r"\b[a-z][a-z0-9_]*\.[a-z][a-z0-9_.]*\b", line):
                    assert dotted in registered_names, f"代码块注释出现未登记名称: {dotted}"
                continue

            argv = shlex.split(line)
            assert argv and argv[0] == "yudao", f"未知命令入口: {line}"
            try:
                args = cli_parser.parse_args(argv[1:])
            except SystemExit as exc:
                raise AssertionError(f"命令行示例解析失败: {line}") from exc

            if args.command == "command":
                checked_commands += 1
                assert args.target_name in registered_commands, f"未知命令名: {args.target_name}"
                cmd_def = registered_commands[args.target_name]
                fields = cmd_def.request.model_fields

                if args.payload_stdin:
                    for field_ref in re.findall(r"\b[a-z][a-z0-9_]*_[a-z0-9_]*\b", "\n".join(pending_comments)):
                        assert field_ref in fields, f"命令 {args.target_name} 标准输入说明出现未知字段: {field_ref}"

                if args.json_payload is not None:
                    if _is_placeholder(args.json_payload):
                        for field_ref in re.findall(r"\b[a-z][a-z0-9_]*\b", args.json_payload):
                            if field_ref != "json":
                                assert field_ref in fields, f"命令 {args.target_name} JSON 示例出现未知字段: {field_ref}"
                    else:
                        payload_obj = json.loads(args.json_payload)
                        assert isinstance(payload_obj, dict)
                        assert set(payload_obj) <= set(fields)

                supplied_keys: set[str] = set()
                for param_kind, raw_item in args.command_params or []:
                    assert "=" in raw_item, f"命令参数缺少 '=': {raw_item}"
                    key, raw_val = raw_item.split("=", 1)
                    assert key in fields and key != "command_id", f"命令 {args.target_name} 存在未知参数键: {key}"
                    supplied_keys.add(key)
                    _assert_command_param_flag(args.target_name, key, fields[key].annotation, param_kind)

                    if not _is_placeholder(raw_val):
                        if key == "form":
                            checked_forms += 1
                            assert raw_val in built_in_forms, f"未知内置形态标识: {raw_val}"
                        if args.target_name in {"parameter.set", "parameter.withdraw"} and key == "name":
                            assert raw_val in registered_parameters, f"未知运行参数名: {raw_val}"
                        parsed_val = _parse_cli_param_value(raw_val, param_kind)
                        TypeAdapter(fields[key].annotation).validate_python(parsed_val)

                if not args.payload_stdin and args.json_payload is None:
                    required_keys = {k for k, f in fields.items() if f.is_required() and k != "command_id"}
                    missing_keys = sorted(required_keys - supplied_keys)
                    assert not missing_keys, f"命令 {args.target_name} 缺少必填参数键: {missing_keys}"

            elif args.command == "query":
                checked_queries += 1
                assert args.target_name in registered_queries, f"未知查询名: {args.target_name}"
                if args.target_name == "forms.list":
                    comment_forms = re.findall(r"\b[a-z][a-z0-9_]*\b", "\n".join(pending_comments))
                    assert comment_forms, "forms.list 示例注释缺少内置形态标识"
                    for form_id in comment_forms:
                        checked_forms += 1
                        assert form_id in built_in_forms, f"未知内置形态标识: {form_id}"

                qry_def = registered_queries[args.target_name]
                if args.at_position is not None:
                    assert qry_def.replayable, f"查询 {args.target_name} 不支持按位置回放"
                if qry_def.request is None:
                    assert not args.query_params and args.json_payload is None, (
                        f"无参查询 {args.target_name} 不接受查询参数"
                    )
                else:
                    qfields = qry_def.request.model_fields
                    supplied_qkeys: set[str] = set()
                    for raw_item in args.query_params or []:
                        assert "=" in raw_item, f"查询参数缺少 '=': {raw_item}"
                        key, raw_val = raw_item.split("=", 1)
                        assert key in qfields, f"查询 {args.target_name} 存在未知参数键: {key}"
                        supplied_qkeys.add(key)
                        if not _is_placeholder(raw_val):
                            field_ann = qfields[key].annotation
                            candidate: Any = [raw_val] if get_origin(field_ann) is list else raw_val
                            TypeAdapter(field_ann).validate_python(candidate)
                    if args.json_payload is None:
                        missing_qkeys = sorted(k for k, f in qfields.items() if f.is_required() and k not in supplied_qkeys)
                        assert not missing_qkeys, f"查询 {args.target_name} 缺少必填参数键: {missing_qkeys}"

            elif args.command == "describe":
                assert args.target_name in registered_names, f"未知自省目标名: {args.target_name}"

            elif args.command == "events":
                assert args.after_position is not None, "events 示例必须显式传入 --after"
                for event_type in [*(args.event_types or []), *(args.until_types or [])]:
                    checked_events += 1
                    assert event_type in registered_events, f"未知事件种类: {event_type}"

            pending_comments = []

    checked_rejections = 0
    for tok in tokens:
        if tok.type != "inline" or not tok.children:
            continue
        inline_spans = [child.content for child in tok.children if child.type == "code_inline"]

        if "yudao capabilities" in inline_spans and "deployment.log_id" in inline_spans:
            for span in inline_spans:
                if re.fullmatch(r"[a-z][a-z0-9_]*", span) and span != "capabilities":
                    assert span in capabilities_fields, f"能力清单说明出现未知顶层字段: {span}"

        if "409" in inline_spans:
            rejection_candidates = [
                span
                for span in inline_spans
                if re.fullmatch(r"[a-z][a-z0-9_]*_[a-z0-9_]*", span)
                and span not in {"base_version", *Rejected.model_fields}
            ]
            assert rejection_candidates, "业务拒绝说明缺少拒绝原因标识"
            for reason in rejection_candidates:
                checked_rejections += 1
                assert reason in registered_rejections and reason in command_rejection_reasons, f"未知拒绝原因: {reason}"

        for span in inline_spans:
            if span.startswith("yudao "):
                parts_cmd = span.split()
                assert parts_cmd[1] in valid_subcommands, f"未知命令行子命令: {parts_cmd[1]}"
                if len(parts_cmd) >= 3 and parts_cmd[1] in {"command", "query", "describe"}:
                    target = parts_cmd[2]
                    if not target.startswith(("<", "[", "-")):
                        if parts_cmd[1] == "command":
                            assert target in registered_commands, f"未知命令名: {target}"
                        elif parts_cmd[1] == "query":
                            assert target in registered_queries, f"未知查询名: {target}"
                        else:
                            assert target in registered_names, f"未知自省目标名: {target}"
            elif re.fullmatch(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_.]*", span):
                assert span in registered_names or span in capabilities_dotted, f"未知点分合同标识: {span}"
            elif re.fullmatch(r"[a-z][a-z0-9_]*_[a-z0-9_]*", span):
                known_snake = (
                    registered_rejections
                    | registered_decisions
                    | registered_events
                    | built_in_forms
                    | registered_parameters
                    | envelope_snake_fields
                )
                assert span in known_snake, f"未知合同符号: {span}"

    assert checked_commands > 0
    assert checked_queries > 0
    assert checked_events > 0
    assert checked_forms > 0
    assert checked_rejections > 0


def test_skill_show_outputs_complete_yaml_frontmatter_and_operational_protocols(tmp_path: Path) -> None:
    # 守 R2/R3：yudao skill show 原样输出带 YAML 头的完整技能文档，覆盖基准版本、凭据隔离、三条改动通道、决定请求用户拍板与常见运维序列，且不接触数据目录
    unused_data_dir = tmp_path / "untouched-data-dir"
    code, out, err = _invoke_skill(["--data-dir", str(unused_data_dir), "skill", "show"])
    assert code == 0, err
    assert err == ""
    assert not unused_data_dir.exists()
    assert out == read_skill_text()

    assert out.startswith("---\n")
    parts = out.split("---\n", 2)
    assert len(parts) == 3
    frontmatter = yaml.safe_load(parts[1])
    assert isinstance(frontmatter, dict)
    assert frontmatter["name"] == "yudao-ops"
    assert isinstance(frontmatter.get("description"), str) and frontmatter["description"].strip()

    body = parts[2]
    # 1. 先读取后修改与基准版本规程及全部退出码
    for token in (
        "capabilities",
        "describe",
        "query",
        "command",
        "events",
        "base_version",
        "--command-id",
        "退出码 `0`",
        "退出码 `1`",
        "退出码 `2`",
        "退出码 `3`",
        "退出码 `4`",
        "退出码 `5`",
    ):
        assert token in body, token

    # 2. 凭据安全与隔离规程
    for token in (".env", "--stdin", "--token-stdin", "YUDAO_TOKEN", "credential.set", "catalog.connect"):
        assert token in body, token

    # 3. 三条改动通道分流规程
    for token in (
        "第一条通道：数据定义与参数命令",
        "第二条通道：隔离动作与外部工具",
        "第三条通道：修改 Yudao 自身代码",
        "organization.adopt",
        "parameter.set",
        "parameter.withdraw",
        "tool_server.probe",
        "mcp_servers.save",
        "kernel_modification",
        "runtime.start_drain",
        "release-check",
    ):
        assert token in body, token

    # 4. 决定请求用户拍板确认规程与常见运维序列
    for token in ("decisions.list", "decision.answer", "只有在用户明确给出具体选择之后", "常见运维操作序列"):
        assert token in body, token


def test_skill_install_creates_parent_directories_and_enforces_overwrite_guard(tmp_path: Path) -> None:
    # 守 R2/R3：yudao skill install 自动建立缺失父目录并写入 SKILL.md；已存在时未传 --force 返回退出码 1 并保留原文件，传 --force 正常覆盖
    target_dir = tmp_path / "external-agent" / "skills" / "yudao-ops"
    expected_file = target_dir / SKILL_FILENAME

    code_new, out_new, err_new = _invoke_skill(["skill", "install", str(target_dir)])
    assert code_new == 0, err_new
    assert err_new == ""
    assert Path(out_new.strip()) == expected_file
    assert expected_file.is_file()
    assert expected_file.read_text(encoding="utf-8") == read_skill_text()

    sentinel_text = "用户本地改过的旧版技能内容\n"
    expected_file.write_text(sentinel_text, encoding="utf-8")

    code_refused, out_refused, err_refused = _invoke_skill(["skill", "install", str(target_dir)])
    assert code_refused == 1
    assert out_refused == ""
    assert "--force" in err_refused
    assert expected_file.read_text(encoding="utf-8") == sentinel_text

    code_forced, out_forced, err_forced = _invoke_skill(["skill", "install", str(target_dir), "--force"])
    assert code_forced == 0, err_forced
    assert err_forced == ""
    assert Path(out_forced.strip()) == expected_file
    assert expected_file.read_text(encoding="utf-8") == read_skill_text()

    # 函数入口同样遵守覆盖守卫
    direct_dir = tmp_path / "direct-install"
    written = install_skill(direct_dir)
    assert written == direct_dir / SKILL_FILENAME
    try:
        install_skill(direct_dir, force=False)
    except FileExistsError:
        pass
    else:
        raise AssertionError("install_skill without force must raise FileExistsError when SKILL.md exists")


def test_skill_references_match_registered_contracts_events_and_forms() -> None:
    # 守 R2：随包 SKILL.md 中的命令名、查询名、参数键与类型选项、拒绝原因、事件种类及内置形态标识与注册表及定义目录一致
    skill_text = read_skill_text()
    _validate_skill_contracts(skill_text)

    negative_mutations = (
        ("yudao command decision.answer", "yudao command decision.nonexistent_command"),
        ("yudao query forms.list", "yudao query forms.nonexistent_query"),
        ("--string-param option=", "--string-param nonexistent_field="),
        ("--param base_version=<version> --string-param decision_id=", "--string-param decision_id="),
        ("--string-param name=run_time_limit_sec", "--param name=run_time_limit_sec"),
        ("`stale_base`", "`nonexistent_rejection_reason`"),
        ("--type catalog_test_finished", "--type catalog_nonexistent_event"),
        ("three_departments", "nonexistent_builtin_form"),
        ("form=single_role_direct", "form=nonexistent_builtin_form"),
    )
    for original, mutated in negative_mutations:
        assert original in skill_text, original
        with pytest.raises(AssertionError):
            _validate_skill_contracts(skill_text.replace(original, mutated, 1))

