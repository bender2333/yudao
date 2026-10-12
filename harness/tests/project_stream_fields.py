# 项目流字段清单的核对与写入（ADR-0019、#241，工单 #126）。
# 项目流的事件种类与字段登记在 harness/tests/project_stream_fields.json 中：删除事件种类、删除字段、
# 改变字段类型或删除取值固定字段（const/enum）的已登记取值时测试失败；增加种类、字段或扩大取值集合时
# 写明旧事件中的缺省含义（取值扩大不算新字段，不需要写缺省含义）。清单只覆盖项目流的事件种类，run 流
# 跟随应用版本，不登记在清单中。清单记三类内容：fields（每个事件种类的字段与类型，取值固定的字段把
# 取值集合记在中括号里）、baseline（首次登记时的字段集合）、added_defaults（baseline 之后新增的字段
# 与它在旧事件中的缺省含义）。
# 写入（--write-project-stream-fields）只允许往清单中添加新的事件种类、字段或扩大取值固定字段的取值
# 集合：与已登记的清单比较后，发现删除事件种类、删除字段、改变字段类型或删除已登记取值时拒绝写入并
# 写明是哪个种类、哪个字段以及变化（删除取值时写明被删除的取值）。基线 baseline 是只读的，写入不会
# 改动它；清单连同 baseline 与 added_defaults 一起提交在仓库里，没有整份重建的路径，文件丢失时从
# git 历史恢复。

import json
import re
from pathlib import Path

from pydantic import TypeAdapter

from harness.app.payloads import PAYLOADS
from harness.streams import PROJECT_EVENT_TYPES

MANIFEST = Path(__file__).parent / "project_stream_fields.json"

# 取值固定的字段（const/enum）渲染为 "const string[v1]"、"enum string[v1, v2]"（可空加 "?"）：
# 取值集合记在中括号里，const 与 enum 只是取值数量的叫法，取值从一个扩大为多个时按新增处理（#241）
_FIXED_VALUES = re.compile(r"^(?:const|enum) (\w+)\[(.*)\](\??)$")

def parse_fixed_values(rendered: str) -> tuple[str, frozenset[str]] | None:
    # 解析取值固定的字段：返回（不含取值的类型标识，取值集合）；不是取值固定的字段时返回 None
    match = _FIXED_VALUES.match(rendered)
    if not match:
        return None
    basetype, raw_values, nullable = match.groups()
    values = frozenset(v.strip() for v in raw_values.split(",") if v.strip())
    return f"{basetype}{nullable}", values

def _resolve(schema: dict, defs: dict) -> dict:
    while "$ref" in schema:
        schema = defs[schema["$ref"].split("/")[-1]]
    return schema

def _render(schema: dict, defs: dict) -> str:
    # 字段类型在清单中的写法：基础类型、可空（?）、数组（array[元素]）、对象、枚举与常量；
    # 枚举与常量把取值集合记在中括号里（#241），取值按字符串排序后固定顺序
    schema = _resolve(schema, defs)
    for key in ("anyOf", "oneOf"):
        if key in schema:
            parts: list[str] = []
            nullable = False
            for sub in schema[key]:
                sub = _resolve(sub, defs)
                if sub.get("type") == "null":
                    nullable = True
                    continue
                parts.append(_render(sub, defs))
            return " | ".join(sorted(set(parts))) + ("?" if nullable else "")
    if "const" in schema or "enum" in schema:
        values = [schema["const"]] if "const" in schema else list(schema["enum"])
        tag = "const" if "const" in schema else "enum"
        basetype = schema.get("type") or "string"
        rendered_values = ", ".join(str(value) for value in sorted(values, key=str))
        return f"{tag} {basetype}[{rendered_values}]"
    if schema.get("type") == "array":
        return "array[" + _render(schema.get("items", {}), defs) + "]"
    if schema.get("type") == "object":
        return "object"
    return schema.get("type", "any")

def _merge(value: str, other: str) -> str:
    # 同一个字段在联合的两个成员里都有时的写法：取值固定且基础类型相同则合并取值集合，否则按类型取并集
    left, right = parse_fixed_values(value), parse_fixed_values(other)
    if left is not None and right is not None and left[0] == right[0]:
        return f"enum {left[0]}[{', '.join(sorted(left[1] | right[1]))}]"
    return " | ".join(sorted({value, other}))

def live_fields() -> dict[str, dict[str, str]]:
    # 合同类型中项目流每个事件种类的字段与类型。一个事件种类的载荷是以某字段区分的联合时（项目决定请求按
    # kind 区分，工单 #136、#354），登记的字段是各成员字段的并集：Project 流只增加字段，联合的每个成员
    # 各自只携带自己的那一组字段
    fields: dict[str, dict[str, str]] = {}
    for kind in sorted(PROJECT_EVENT_TYPES):
        schema = TypeAdapter(PAYLOADS[kind]).json_schema()
        defs = schema.pop("$defs", {})
        members = [_resolve(sub, defs) for sub in schema.get("anyOf", ())]
        rendered: dict[str, str] = {}
        for properties in [schema, *members]:
            for name, sub in properties.get("properties", {}).items():
                value = _render(sub, defs)
                rendered[name] = value if name not in rendered else _merge(rendered[name], value)
        fields[kind] = rendered
    return fields

class ManifestWriteRejected(ValueError):
    # 写入清单时发现删除事件种类、删除字段或改变字段类型：只允许添加，其他一律拒绝
    pass

def merge_additions(registered: dict[str, dict[str, str]], live: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    # 把合同类型中新增的事件种类与字段并入已登记的清单；与登记内容比较后，删除种类、删除字段或改变字段
    # 类型都拒绝写入，并写明是哪个种类、哪个字段以及变化（ADR-0019：项目流只增加字段或事件种类）；
    # 取值固定的字段（const/enum）取值集合扩大算新增，删除取值当作改变字段类型拒绝并写明被删除的取值（#241）
    removed_kinds = sorted(kind for kind in registered if kind not in live)
    removed_fields: dict[str, list[str]] = {}
    retyped: dict[str, list[str]] = {}
    for kind, declared_fields in registered.items():
        live_kind = live.get(kind)
        if live_kind is None:
            continue
        gone = sorted(name for name in declared_fields if name not in live_kind)
        if gone:
            removed_fields[kind] = gone
        changed = sorted(_describe_change(name, declared, live_kind[name])
                         for name, declared in declared_fields.items()
                         if name in live_kind and not same_type(declared, live_kind[name]))
        if changed:
            retyped[kind] = changed
    if removed_kinds or removed_fields or retyped:
        reasons = []
        if removed_kinds:
            reasons.append("删除事件种类：" + "、".join(removed_kinds))
        if removed_fields:
            reasons.append("删除字段：" + "；".join(f"{kind}.{name}"
                                             for kind, names in sorted(removed_fields.items()) for name in names))
        if retyped:
            reasons.append("改变字段类型：" + "；".join(f"{kind}.{change}"
                                                for kind, changes in sorted(retyped.items()) for change in changes))
        raise ManifestWriteRejected(
            "项目流字段清单只允许添加新的事件种类与字段，拒绝写入。" + "。".join(reasons)
            + "。需要删除种类、删除字段或改变类型时，由架构师按 ADR-0019 处理。")
    merged = {kind: dict(registered[kind]) for kind in registered}
    for kind, live_kind in live.items():
        if kind not in merged:
            merged[kind] = dict(live_kind)
        else:
            for name, declared in live_kind.items():
                merged[kind].setdefault(name, declared)
                if name in registered.get(kind, {}) and merged[kind][name] != declared:
                    merged[kind][name] = declared
    return merged

def _is_value_expansion(declared: str, live: str) -> bool:
    # declared（已登记）与 live（合同类型当前值）都是取值固定的字段，且 live 的取值集合包含 declared
    # 的全部取值（基础类型不变）时算新增，不算改变字段类型；不是取值固定的字段，或取值集合变小/基础类型
    # 改变时返回 False（按改变字段类型拒绝）
    declared_parsed = parse_fixed_values(declared)
    live_parsed = parse_fixed_values(live)
    if declared_parsed is None or live_parsed is None:
        return False
    declared_basetype, declared_values = declared_parsed
    live_basetype, live_values = live_parsed
    return declared_basetype == live_basetype and declared_values <= live_values

def same_type(declared: str, live: str) -> bool:
    # declared 与 live 是否算同一类型：字符串完全相等，或 declared 是 live 的取值子集（取值扩大，#241）
    return declared == live or _is_value_expansion(declared, live)

def _describe_change(name: str, declared: str, live: str) -> str:
    # 拒绝原因里每个字段一行：取值固定的字段取值集合变小时写明被删除的取值，其他情形写明旧类型与新类型
    declared_parsed = parse_fixed_values(declared)
    live_parsed = parse_fixed_values(live)
    if declared_parsed is not None and live_parsed is not None:
        declared_basetype, declared_values = declared_parsed
        live_basetype, live_values = live_parsed
        if declared_basetype == live_basetype:
            removed_values = sorted(declared_values - live_values)
            if removed_values:
                return f"{name}: 删除取值 {', '.join(removed_values)}（{declared} -> {live}）"
    return f"{name}: {declared} -> {live}"

def load_manifest() -> dict:
    # 清单是随仓库提交的文件，没有整份重建的路径：文件缺失时直接报错并说明从 git 历史恢复
    if not MANIFEST.is_file():
        raise FileNotFoundError(
            f"项目流字段清单 {MANIFEST} 不存在：这个文件连同 baseline 与 added_defaults 一起提交在仓库里，"
            "从 git 历史恢复它；--write-project-stream-fields 只添加新的种类与字段，不重建清单")
    return json.loads(MANIFEST.read_text(encoding="utf-8"))

def write_manifest(document: dict) -> None:
    MANIFEST.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")

def apply_rewrite() -> dict:
    # --write-project-stream-fields 的处理：只往 fields 中添加新的种类与字段；
    # baseline 与 added_defaults 原样保留，baseline 是只读的
    document = load_manifest()
    document["fields"] = merge_additions(document["fields"], live_fields())
    write_manifest(document)
    return document
