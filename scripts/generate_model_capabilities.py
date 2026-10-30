# 模型能力表的提取脚本（模型管理设计说明第 4.1 节）。
# 发布前运行：读取 models.dev 的 api.json，收录全部服务商与设计规定的模型字段，
# 写出 harness/definitions/model_capabilities.json，随 Yudao 新版本发布；运行时不从远端刷新。
#
# 用法：
#   uv run python scripts/generate_model_capabilities.py                      # 从 https://models.dev/api.json 取数
#   uv run python scripts/generate_model_capabilities.py --input 文件 --date 2026-10-02 --out 输出文件
#
# --input 给出本地文件时不发出网络请求（测试与离线复现使用）；--date 固定快照日期，缺省为当天；
# --revision 固定表的 revision，缺省为「快照日期.1」。
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
# 模型没有单独声明时使用服务商的接入包；未登记的接入包全部报告，更新者显式决定映射或排除。
NPM_PROTOCOLS: dict[str, str] = {
    "@ai-sdk/openai": "responses",
    "@ai-sdk/anthropic": "messages",
    "@ai-sdk/openai-compatible": "chat_completions",
    "@openrouter/ai-sdk-provider": "chat_completions",
}

# 这些官方服务商的 models.dev 记录没有 api；其他服务商缺少时保持空串。
OFFICIAL_API_URLS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "google": "https://generativelanguage.googleapis.com/v1beta",
}


def load_models_dev(source_url: str, input_path: Path | None) -> dict[str, Any]:
    if input_path is not None:
        return json.loads(input_path.read_text(encoding="utf-8"))
    import urllib.request

    request = urllib.request.Request(source_url, headers={"User-Agent": "Yudao-Loop-System/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def declared_npm(entry: dict[str, Any]) -> str:
    # 模型单独声明的 provider.npm；没有字符串声明时由调用方取服务商接入包。
    provider = entry.get("provider")
    npm = provider.get("npm") if isinstance(provider, dict) else None
    return npm.strip() if isinstance(npm, str) else ""


def extract_model(entry: dict[str, Any], model_id: str, default_protocol: str) -> dict[str, Any]:
    # 一条模型记录：models.dev 中 modalities 可以缺少，缺少时不记录输入方式与输出方式；
    # limit 缺少或取值非法时对应的容量字段为 null；工具调用与推理按布尔取值记录；
    # 调用方先核对全部接入包；这里保留既有函数参数，default_protocol 取自服务商接入包。
    capability: dict[str, Any] = {"model": model_id,
                                  "protocol": NPM_PROTOCOLS[declared_npm(entry)] if declared_npm(entry) else default_protocol}
    modalities = entry.get("modalities")
    if isinstance(modalities, dict):
        for field in ("input", "output"):
            values = modalities.get(field)
            if isinstance(values, list) and all(isinstance(item, str) for item in values):
                capability[f"{field}_modalities"] = sorted(values)
    limits = entry.get("limit")
    for upstream, field in (("context", "context_window"), ("output", "max_output_tokens"), ("input", "max_input_tokens")):
        value = limits.get(upstream) if isinstance(limits, dict) else None
        valid = isinstance(value, int) and not isinstance(value, bool) and value > 0
        if upstream != "input" or valid:
            capability[field] = value if valid else None
    capability["tool_call"] = bool(entry.get("tool_call"))
    capability["reasoning"] = bool(entry.get("reasoning"))
    return capability


def build_table(presets: list[dict[str, Any]], models_dev: dict[str, Any],
                revision: str, snapshot_date: str, source: str,
                *, excluded_providers: tuple[str, ...] = ()) -> dict[str, Any]:
    unexpected = sorted(set(excluded_providers) - set(models_dev))
    if unexpected:
        raise ValueError("要排除的服务商不在快照中：" + "、".join(unexpected))
    providers: dict[str, dict[str, Any]] = {}
    unknown: list[str] = []
    for provider_id, provider in sorted(models_dev.items()):
        if provider_id in excluded_providers:
            continue
        if not isinstance(provider, dict) or not isinstance(provider.get("models"), dict):
            raise ValueError(f"models.dev 的服务商 {provider_id} 缺少模型对象")
        npm = provider.get("npm", "")
        if npm not in NPM_PROTOCOLS:
            unknown.append(f"{provider_id}（{npm or '缺少接入包'}）")
        entries = provider["models"]
        provider_unknown = npm not in NPM_PROTOCOLS
        for model_id, entry in sorted(entries.items()):
            if not isinstance(entry, dict):
                raise ValueError(f"models.dev 的 {provider_id}/{model_id} 不是模型对象")
            model_npm = declared_npm(entry)
            if model_npm and model_npm not in NPM_PROTOCOLS:
                unknown.append(f"{provider_id}/{model_id}（{model_npm}）")
                provider_unknown = True
        if provider_unknown:
            continue
        providers[provider_id] = {
            "api": provider.get("api") or OFFICIAL_API_URLS.get(provider_id, ""),
            "npm": npm,
            "models": [extract_model(entries[key], key, NPM_PROTOCOLS[npm]) for key in sorted(entries)],
        }
    if unknown:
        raise ValueError("models.dev 的 provider.npm 不在协议映射中（服务商/模型）：\n  " + "\n  ".join(unknown))
    table_presets: dict[str, list[dict[str, Any]]] = {}
    missing: list[str] = []
    for preset in presets:
        provider_id = preset.get("models_dev_id")
        if not provider_id:
            continue
        provider = providers.get(provider_id)
        if provider is None or not provider["models"]:
            missing.append(f"{preset['id']} → {provider_id}")
        else:
            table_presets[preset["id"]] = provider["models"]
    if missing:
        raise ValueError("models.dev 中找不到预置服务方案（不能排除预置服务商）：" + "、".join(missing))
    return {
        "version": 2,
        "providers": providers,
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
    parser.add_argument("--exclude-provider", action="append", default=[],
                        help="显式排除的服务商，可重复；预置表所需的服务商不能排除")
    args = parser.parse_args(argv)

    presets_doc = json.loads(PRESETS_PATH.read_text(encoding="utf-8"))
    presets = presets_doc.get("presets", [])
    models_dev = load_models_dev(args.source_url, args.input)
    snapshot_date = args.date or date.today().isoformat()
    revision = args.revision or f"{snapshot_date}.1"
    source = args.source_url if args.input is None else f"{args.source_url}（本地文件 {args.input.name}）"
    try:
        table = build_table(presets, models_dev, revision, snapshot_date, source,
                            excluded_providers=tuple(args.exclude_provider))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    payload = json.dumps(table, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    args.out.write_text(payload, encoding="utf-8", newline="\n")
    count = sum(len(provider["models"]) for provider in table["providers"].values())
    print(f"写出 {args.out}：revision {revision}，快照日期 {snapshot_date}，"
          f"{len(table['providers'])} 个服务商、{count} 个模型、{args.out.stat().st_size} 字节")
    if args.exclude_provider:
        print("显式排除服务商：" + "、".join(sorted(args.exclude_provider)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
