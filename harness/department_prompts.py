# 部门 Prompt 原文的工件。内置默认 Prompt 在定义中（definitions/roles.json），项目部门设置中的 Prompt 属于设置

from __future__ import annotations

from .artifacts import ArtifactStore
from .materials import save_text_material
from .models import DEPARTMENTS, ArtifactRef


def save_department_prompt(artifacts: ArtifactStore, run_id: str, department: str, text: str) -> ArtifactRef:
    if department not in DEPARTMENTS:
        raise ValueError("unknown prompt department")
    return save_text_material(artifacts, run_id, "department_prompt", text)
