from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

# 选择层保存的三项：模型访问定义引用、请求档位与部门 Prompt。项目部门设置只写入覆盖的项，
# 没有写入的项使用部门默认；部门 Prompt 没有写入时使用内置默认 Prompt（设计说明第 5.2 节）。
# 每一项都可以为空，三项一起保存、一个版本。

# 选择来源：提供模型访问定义的那一层（设计说明第 5.3 节）。角色两层由 #63 加入
DEPARTMENT_DEFAULT_SOURCE = "department_default"
PROJECT_DEPARTMENT_SETTING_SOURCE = "project_department_setting"

@dataclass(frozen=True)
class ModelSelection:
    # 一层保存的模型选择：模型访问定义引用与请求档位都可以为空。
    # `provider_id` 与 `model_id` 一起写入或一起为空（选择「跟随部门默认」清除本项目的模型选择），
    # `department_prompt` 为空表示这一层没有写入部门 Prompt
    provider_id: str | None = None
    model_id: str | None = None
    requested_tier: str | None = None
    department_prompt: str | None = None

    def writes_model(self) -> bool:
        return bool(self.model_id)

    def writes_tier(self) -> bool:
        return self.requested_tier is not None

    def writes_prompt(self) -> bool:
        return self.department_prompt is not None

    def event_payload(self) -> dict[str, Any]:
        # 写入项目事件的三项：只含写入了的项。模型两项一起写入；请求档位与部门 Prompt 各自单独写入。
        # 全部没有写入时为空（保存以后该部门跟随部门默认与内置默认 Prompt）
        payload: dict[str, Any] = {}
        if self.model_id is not None:
            payload["provider_id"] = self.provider_id
            payload["model_id"] = self.model_id
        if self.requested_tier is not None:
            payload["requested_tier"] = self.requested_tier
        if self.department_prompt is not None:
            payload["department_prompt"] = self.department_prompt
        return payload

    @classmethod
    def from_event(cls, raw: Mapping[str, Any]) -> ModelSelection:
        return cls(
            provider_id=_text(raw.get("provider_id")),
            model_id=_text(raw.get("model_id")),
            requested_tier=_text(raw.get("requested_tier")),
            department_prompt=_text(raw.get("department_prompt")),
        )

    def read_view(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "requested_tier": self.requested_tier,
            "department_prompt": self.department_prompt,
        }

@dataclass(frozen=True)
class SelectionResolution:
    # 一次模型请求的合并结果：模型访问定义引用、请求档位、选择来源与部门 Prompt。
    # 模型访问定义与请求档位分别按「项目部门设置、部门默认」的顺序取得第一个写入了的项；
    # 都没有时 resolved 为假。选择来源是提供模型访问定义的那一层。
    resolved: bool
    provider_id: str | None
    model_id: str | None
    requested_tier: str | None
    selection_source: str
    department_prompt: str | None

def merge_selection(
    project: ModelSelection | None,
    department: ModelSelection | None,
) -> SelectionResolution:
    # 选择合并是一个没有副作用的规则（设计说明第 5.3 节）：流程编排的新建检查与应用层的
    # 生效模型查询使用同一个规则。项目为 None 表示没有项目层（命令行与测试的运行）。
    source = PROJECT_DEPARTMENT_SETTING_SOURCE if _chosen_for_model(project) else DEPARTMENT_DEFAULT_SOURCE
    chosen = project if _chosen_for_model(project) else department
    model_id = None if chosen is None else chosen.model_id
    provider_id = None if chosen is None else chosen.provider_id
    tier = _first_tier(project, department)
    prompt = None if project is None else project.department_prompt
    return SelectionResolution(
        resolved=bool(model_id),
        provider_id=provider_id,
        model_id=model_id,
        requested_tier=tier,
        selection_source=source,
        department_prompt=prompt,
    )

def _chosen_for_model(project: ModelSelection | None) -> bool:
    return project is not None and project.writes_model()

def _first_tier(project: ModelSelection | None, department: ModelSelection | None) -> str | None:
    # 请求档位按与模型访问定义相同的顺序取得第一个写入了的项；都没有时为空（由 Provider 按模型默认档位）
    for selection in (project, department):
        if selection is not None and selection.writes_tier():
            return selection.requested_tier
    return None

def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None
