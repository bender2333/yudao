# 项目流字段清单的核对（ADR-0019，工单 #126）。
# 项目流的事件种类与字段登记在 harness/tests/project_stream_fields.json 中：删除事件种类、删除字段或改变字段
# 类型时测试失败；增加种类或字段时写明旧事件中的缺省含义。清单只覆盖项目流的事件种类，run 流跟随应用版本，
# 不登记在清单中。清单记三类内容：fields（每个事件种类的字段与类型）、baseline（首次登记时的字段集合）、
# added_defaults（baseline 之后新增的字段与它在旧事件中的缺省含义）。

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

def load_manifest() -> dict:
    # 清单还没有建立时给出空清单：fields 与 baseline 为空、没有缺省含义说明。
    # 这时核对测试指出清单缺少全部内容，用重写选项建立第一份清单
    if not MANIFEST.is_file():
        return {"fields": {}, "baseline": {}, "added_defaults": {}}
    return json.loads(MANIFEST.read_text(encoding="utf-8"))

def write_manifest(document: dict) -> None:
    MANIFEST.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
