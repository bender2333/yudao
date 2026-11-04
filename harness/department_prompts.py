# 部门 Prompt 原文的工件。内置默认 Prompt 在定义中（definitions/roles.json），项目部门设置中的 Prompt 属于设置

from __future__ import annotations

from typing import Any

from .artifacts import ArtifactStore
from .definitions import DEFINITIONS
from .materials import save_text_material
from .models import ArtifactRef


def save_department_prompt(artifacts: ArtifactStore, run_id: str, department: str, text: str,
                           definitions: Any | None = None) -> ArtifactRef:
    # 部门清单按写这份 Prompt 的那份定义核对（工单 #1509）：事项层是它冻结的那一份，项目层是项目现在的形态；
    # 没有交时读进程加载的那一份
    definition = DEFINITIONS if definitions is None else definitions
    if department not in definition.departments:
        raise ValueError("unknown prompt department")
    return save_text_material(artifacts, run_id, "department_prompt", text)
