# 部门建议能力的提醒（模型管理设计说明第 5.6 节）。
# 部门定义写明本部门模型的建议能力，质检为图像输入，其他部门没有。提醒只用于提示，不阻止保存或请求。
# 判断只读模型访问定义中的输入方式，不读模型能力表（能力表只用于预填，见设计说明第 4.1 节的用途）。

from __future__ import annotations

from typing import Any, Mapping

from ..definitions import DEFINITIONS
from .store import ModelDefinition

# 缺少某项能力时的影响：按设计说明第 5.6 节抄录浏览器与 computer use 设计说明第 8.4 节的结论
_MISSING_IMPACT: Mapping[str, str] = {
    "image": "不提供 computer use，浏览器只给可访问性结构，不给截图；依赖桌面程序或外观的验收条件无法核验",
}

_CAPABILITY_NAMES: Mapping[str, str] = {
    "text": "文本输入",
    "image": "图像输入",
}

def missing_capabilities(department: str, model: ModelDefinition | Mapping[str, Any]) -> tuple[str, ...]:
    # 这个模型不具备本部门的建议能力：部门没有建议能力时没有缺少项
    suggested = DEFINITIONS.suggested_capabilities(department)
    if not suggested:
        return ()
    declared = model.input_modalities if isinstance(model, ModelDefinition) else tuple(model.get("input_modalities") or ())
    return tuple(item for item in suggested if item not in declared)

def reminder(department: str, model: ModelDefinition | Mapping[str, Any],
              model_id: str | None = None) -> str | None:
    # 一条提醒：写明部门、模型、缺少的能力与影响（设计说明第 5.6 节）。
    # 模型具备本部门的建议能力，或部门没有建议能力时没有提醒
    missing = missing_capabilities(department, model)
    if not missing:
        return None
    if model_id is None:
        model_id = model.id if isinstance(model, ModelDefinition) else str(model.get("id") or "")
    label = model_id
    declared = model.input_modalities if isinstance(model, ModelDefinition) else tuple(model.get("input_modalities") or ())
    abilities = "、".join(_CAPABILITY_NAMES.get(item, item) for item in missing)
    declared_text = "、".join(_CAPABILITY_NAMES.get(item, item) for item in declared)
    impact = "；".join(_MISSING_IMPACT.get(item, item) for item in missing)
    return f"{department} 部门的模型建议具备{abilities}，当前模型 {label} 的输入方式为 {declared_text}：{impact}"

def reminders(department: str, model: ModelDefinition | Mapping[str, Any] | None,
              model_id: str | None = None) -> list[str]:
    # 一个部门的提醒清单：没有绑定模型或模型具备建议能力时为空
    if model is None:
        return []
    return [item for item in [reminder(department, model, model_id)] if item is not None]

__all__ = ["missing_capabilities", "reminder", "reminders"]
