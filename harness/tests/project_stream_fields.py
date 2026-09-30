# 项目流字段清单的核对与写入（ADR-0019，工单 #126）。
# 项目流的事件种类与字段登记在 harness/tests/project_stream_fields.json 中：删除事件种类、删除字段或改变字段
# 类型时测试失败；增加种类或字段时写明旧事件中的缺省含义。清单只覆盖项目流的事件种类，run 流跟随应用版本，
# 不登记在清单中。清单记三类内容：fields（每个事件种类的字段与类型）、baseline（首次登记时的字段集合）、
# added_defaults（baseline 之后新增的字段与它在旧事件中的缺省含义）。
# 写入（--write-project-stream-fields）只允许往清单中添加新的事件种类与字段：与已登记的清单比较后，
# 发现删除事件种类、删除字段或改变字段类型时拒绝写入并写明是哪个种类、哪个字段以及变化。基线 baseline
# 是只读的，写入不会改动它；清单连同 baseline 与 added_defaults 一起提交在仓库里，没有整份重建的路径，
# 文件丢失时从 git 历史恢复。

import json
from pathlib import Path

from pydantic import TypeAdapter

from harness.app.payloads import PAYLOADS
from harness.streams import PROJECT_EVENT_TYPES

MANIFEST = Path(__file__).parent / "project_stream_fields.json"

def _resolve(schema: dict, defs: dict) -> dict:
    while "$ref" in schema:
        schema = defs[schema["$ref"].split("/")[-1]]
    return schema

def _render(schema: dict, defs: dict) -> str:
    # 字段类型在清单中的写法：基础类型、可空（?）、数组（array[元素]）、对象、枚举与常量
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
        return ("const " if "const" in schema else "enum ") + (schema.get("type") or "string")
    if schema.get("type") == "array":
        return "array[" + _render(schema.get("items", {}), defs) + "]"
    if schema.get("type") == "object":
        return "object"
    return schema.get("type", "any")

def live_fields() -> dict[str, dict[str, str]]:
    # 合同类型中项目流每个事件种类的字段与类型
    fields: dict[str, dict[str, str]] = {}
    for kind in sorted(PROJECT_EVENT_TYPES):
        schema = TypeAdapter(PAYLOADS[kind]).json_schema()
        defs = schema.pop("$defs", {})
        fields[kind] = {name: _render(sub, defs) for name, sub in schema.get("properties", {}).items()}
    return fields

class ManifestWriteRejected(ValueError):
    # 写入清单时发现删除事件种类、删除字段或改变字段类型：只允许添加，其他一律拒绝
    pass

def merge_additions(registered: dict[str, dict[str, str]], live: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    # 把合同类型中新增的事件种类与字段并入已登记的清单；与登记内容比较后，删除种类、删除字段或改变字段
    # 类型都拒绝写入，并写明是哪个种类、哪个字段以及变化（ADR-0019：项目流只增加字段或事件种类）
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
        changed = sorted(f"{name}: {declared} -> {live_kind[name]}"
                         for name, declared in declared_fields.items()
                         if name in live_kind and live_kind[name] != declared)
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
    return merged

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
