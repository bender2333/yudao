# 模型能力表的只读访问（模型管理设计说明第 4.1 节）。
# 能力表是带版本的定义（definitions/model_capabilities.json），由发布前运行的提取脚本从 models.dev
# 生成快照，运行时不从远端刷新（ADR-0003）。本模块只提供读取：整张表的 revision、快照日期与来源，
# 以及按服务方案与上游模型 ID 查询一条能力记录。预填以外的运行路径（准入、建议能力的提醒）
# 只使用模型访问定义中的值，不读取这里。

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping

from ..definitions import DEFINITIONS, ModelCapability

_TABLE = DEFINITIONS.model_capabilities
CAPABILITY_TABLE_REVISION = _TABLE.revision
CAPABILITY_TABLE_SNAPSHOT_DATE = _TABLE.snapshot_date
CAPABILITY_TABLE_SOURCE = _TABLE.source

# 服务方案 ID → {上游模型 ID → 一条能力记录}；没有条目的服务方案（自定义、未收录）查不到
_INDEX: Mapping[str, Mapping[str, ModelCapability]] = MappingProxyType({
    preset_id: MappingProxyType({entry.model: entry for entry in entries})
    for preset_id, entries in _TABLE.presets.items()
})


def table_public() -> dict[str, Any]:
    # 整张表的公开信息：revision、快照日期与来源，以及每个预置服务方案的条目
    # （查询 catalog 交回，界面显示；条目含上游模型 ID 与第 4.1 节字段）
    return {
        "revision": CAPABILITY_TABLE_REVISION,
        "snapshot_date": CAPABILITY_TABLE_SNAPSHOT_DATE,
        "source": CAPABILITY_TABLE_SOURCE,
        "presets": {
            preset_id: [
                {
                    "model": entry.model,
                    "protocol": entry.protocol,
                    "input_modalities": list(entry.input_modalities),
                    "output_modalities": list(entry.output_modalities),
                    "context_window": entry.context_window,
                    "max_output_tokens": entry.max_output_tokens,
                    "tool_call": entry.tool_call,
                    "reasoning": entry.reasoning,
                }
                for entry in entries
            ]
            for preset_id, entries in _TABLE.presets.items()
        },
    }


def entries(preset_id: str) -> tuple[ModelCapability, ...]:
    # 一个服务方案的全部条目（按上游模型 ID 排序）；没有条目时为空
    index = _INDEX.get(str(preset_id))
    if not index:
        return ()
    return tuple(index[model] for model in sorted(index))


def capability(preset_id: str, model: str) -> ModelCapability | None:
    # 按服务方案与上游模型 ID 查一条能力记录；自定义服务方案与未收录的模型返回 None
    index = _INDEX.get(str(preset_id))
    return None if index is None else index.get(str(model))
