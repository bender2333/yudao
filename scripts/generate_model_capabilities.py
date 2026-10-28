# 模型能力表的提取脚本（模型管理设计说明第 4.1 节）。
# 发布前运行：读取 models.dev 的 api.json，只收录服务方案预置表中服务方案的模型，
# 每个模型保留上游模型 ID、输入方式、输出方式、上下文窗口、输出上限、是否支持工具调用与是否支持推理，
# 写出 harness/definitions/model_capabilities.json，随 Yudao 新版本发布；运行时不从远端刷新。
#
# 用法：
#   uv run python scripts/generate_model_capabilities.py                      # 从 https://models.dev/api.json 取数
#   uv run python scripts/generate_model_capabilities.py --input 文件 --date 2026-10-02 --out 输出文件
#
# --input 给出本地文件时不发出网络请求（测试与离线复现使用）；--date 固定快照日期，缺省为当天；
# --revision 固定表的 revision，缺省按「预置表 revision 的日期.序号」编到快照日期上。
# 同一输入、同一日期与同一 revision 生成的内容逐字节稳定。

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PRESETS_PATH = REPO_ROOT / "harness" / "definitions" / "service_presets.json"
OUTPUT_PATH = REPO_ROOT / "harness" / "definitions" / "model_capabilities.json"
DEFAULT_SOURCE_URL = "https://models.dev/api.json"

# models.dev 中每个模型的 provider.npm 与调用协议的对应（设计说明第 4.1 节）：
# 模型没有单独声明 provider.npm 时记录服务方案的默认协议；这三种以外的取值由提取脚本报告
NPM_PROTOCOLS: dict[str, str] = {
    "@ai-sdk/openai": "responses",
    "@ai-sdk/anthropic": "messages",
    "@ai-sdk/openai-compatible": "chat_completions",
}


def load_models_dev(source_url: str, input_path: Path | None) -> dict[str, Any]:
    if input_path is not None:
        return json.loads(input_path.read_text(encoding="utf-8"))
    import urllib.request

    request = urllib.request.Request(source_url, headers={"User-Agent": "Yudao-Loop-System/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def declared_npm(entry: dict[str, Any]) -> str:
    # 模型单独声明的 provider.npm；没有声明或取值不是字符串时返回空串，由调用方改用服务方案的默认协议
    provider = entry.get("provider")
    npm = provider.get("npm") if isinstance(provider, dict) else None
    return npm.strip() if isinstance(npm, str) else ""


def extract_model(entry: dict[str, Any], model_id: str, default_protocol: str) -> dict[str, Any]:
    # 一条模型记录：models.dev 中 modalities 可以缺少，缺少时不记录输入方式与输出方式；
    # limit 缺少或取值非法时对应的容量字段为 null；工具调用与推理按布尔取值记录；
    # 协议按 provider.npm 映射，模型没有单独声明时取服务方案的默认协议
    capability: dict[str, Any] = {"model": model_id,
                                  "protocol": NPM_PROTOCOLS.get(declared_npm(entry), default_protocol)}
    modalities = entry.get("modalities")
    if isinstance(modalities, dict):
        for field in ("input", "output"):
            values = modalities.get(field)
            if isinstance(values, list) and all(isinstance(item, str) for item in values):
                capability[f"{field}_modalities"] = sorted(values)
    limits = entry.get("limit")
    context = limits.get("context") if isinstance(limits, dict) else None
    output = limits.get("output") if isinstance(limits, dict) else None
    capability["context_window"] = context if isinstance(context, int) and not isinstance(context, bool) else None
    capability["max_output_tokens"] = output if isinstance(output, int) and not isinstance(output, bool) else None
    capability["tool_call"] = bool(entry.get("tool_call"))
    capability["reasoning"] = bool(entry.get("reasoning"))
    return capability


def build_table(presets: list[dict[str, Any]], models_dev: dict[str, Any],
                revision: str, snapshot_date: str, source: str) -> dict[str, Any]:
    # 只收录预置表中填写了 models_dev_id 的服务方案（设计说明第 4.1 节「范围」）；
    # 「自定义」不使用预置表，在能力表中没有条目
    table_presets: dict[str, list[dict[str, Any]]] = {}
    missing: list[str] = []
    unknown: list[str] = []
    for preset in presets:
        models_dev_id = str(preset.get("models_dev_id") or "")
        if not models_dev_id:
            continue
        provider = models_dev.get(models_dev_id)
        if not isinstance(provider, dict) or not isinstance(provider.get("models"), dict) \
                or not provider["models"]:
            missing.append(f"{preset['id']} → {models_dev_id}")
            continue
        entries = provider["models"]
        default_protocol = str(preset["default_protocol"])
        for key in sorted(entries):
            if not isinstance(entries[key], dict):
                continue
            npm = declared_npm(entries[key])
            if npm and npm not in NPM_PROTOCOLS:
                unknown.append(f"{preset['id']}/{key}（{npm}）")
        table_presets[preset["id"]] = [extract_model(entries[key], key, default_protocol)
                                       for key in sorted(entries) if isinstance(entries[key], dict)]
    if missing:
        raise ValueError("models.dev 中找不到预置服务方案：" + "、".join(missing))
    if unknown:
        # 遇到三种取值以外的 provider.npm 时以错误结束并列出这些模型，由更新快照的人决定
        raise ValueError("models.dev 的 provider.npm 不在协议映射中：\n  " + "\n  ".join(unknown))
    return {
        "presets": table_presets,
        "revision": revision,
        "snapshot_date": snapshot_date,
        "source": source,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从 models.dev 生成模型能力表快照")
    parser.add_argument("--input", type=Path, default=None,
                        help="本地 models.dev api.json 文件；给出时不发出网络请求")
    parser.add_argument("--source-url", default=DEFAULT_SOURCE_URL, help="models.dev 数据地址")
    parser.add_argument("--date", default=None, help="快照日期（YYYY-MM-DD），缺省为当天")
    parser.add_argument("--revision", default=None, help="表的 revision，缺省为「快照日期.1」")
    parser.add_argument("--out", type=Path, default=OUTPUT_PATH, help="写出的定义文件")
    args = parser.parse_args(argv)

    presets_doc = json.loads(PRESETS_PATH.read_text(encoding="utf-8"))
    presets = presets_doc.get("presets", [])
    models_dev = load_models_dev(args.source_url, args.input)
    snapshot_date = args.date or date.today().isoformat()
    revision = args.revision or f"{snapshot_date}.1"
    source = args.source_url if args.input is None else f"{args.source_url}（本地文件 {args.input.name}）"
    table = build_table(presets, models_dev, revision, snapshot_date, source)
    payload = json.dumps(table, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    args.out.write_text(payload, encoding="utf-8", newline="\n")
    counts = ", ".join(f"{key} {len(value)} 个模型" for key, value in sorted(table["presets"].items()))
    print(f"写出 {args.out}：revision {revision}，快照日期 {snapshot_date}，{counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
