# 模型能力表的提取脚本（模型管理设计说明第 4.1 节）。
# 发布前运行：读取 models.dev 的 api.json，收录全部服务商与设计规定的模型字段，
# 写出 harness/definitions/model_capabilities.json，随 Yudao 新版本发布；运行时不从远端刷新。
#
# 用法：
#   uv run python scripts/generate_model_capabilities.py                      # 从 https://models.dev/api.json 取数
#   uv run python scripts/generate_model_capabilities.py --input 文件 --date 2026-10-30 --out 输出文件
#
# --input 给出本地文件时不发出网络请求（测试与离线复现使用）；--date 固定快照日期，缺省为当天；
# --revision 固定表的 revision，缺省为「快照日期.1」。
# 同一输入、同一日期与同一 revision 生成的内容逐字节稳定；表里记录来源文件的 SHA-256。

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PRESETS_PATH = REPO_ROOT / "harness" / "definitions" / "service_presets.json"
OUTPUT_PATH = REPO_ROOT / "harness" / "definitions" / "model_capabilities.json"
DEFAULT_SOURCE_URL = "https://models.dev/api.json"

# 接入包映射表（设计说明第 4.1 节）：登记的单位是接入包，每一行登记为三种协议之一，
# 或者登记为「没有对应的协议」（None）。登记为某种协议的行，依据写在 NPM_EVIDENCE 里：
# 官方源码发出这种协议的请求（请求路径、认证方式与请求体），依据是仓库、提交与文件位置。
# 没有这样的依据就登记为没有对应的协议；映射表里没有的接入包使脚本以错误结束。
NPM_PROTOCOLS: dict[str, str | None] = {
    # --- 登记为某种协议 ---
    "@ai-sdk/openai": "responses",
    "@ai-sdk/anthropic": "messages",
    "@ai-sdk/openai-compatible": "chat_completions",
    "@openrouter/ai-sdk-provider": "chat_completions",
    "@ai-sdk/azure": "responses",
    "@ai-sdk/amazon-bedrock/mantle": "chat_completions",
    "@ai-sdk/cerebras": "chat_completions",
    "@ai-sdk/deepinfra": "chat_completions",
    "@ai-sdk/google-vertex/anthropic": "messages",
    "@ai-sdk/groq": "chat_completions",
    "@ai-sdk/mistral": "chat_completions",
    "@ai-sdk/togetherai": "chat_completions",
    "@ai-sdk/xai": "responses",
    "@ai-sdk/alibaba": "chat_completions",
    "@aihubmix/ai-sdk-provider": "chat_completions",
    "@jerome-benoit/sap-ai-provider-v2": "responses",
    "@qvac/ai-sdk-provider": "chat_completions",
    "@saladtechnologies-oss/ai-sdk-provider": "chat_completions",
    "gitlab-ai-provider": "chat_completions",
    "merge-gateway-ai-sdk-provider": "chat_completions",
    "venice-ai-sdk-provider": "chat_completions",
    # --- 没有对应的协议（模型照常收录，协议为空）---
    "@ai-sdk/amazon-bedrock": None,
    "@ai-sdk/cohere": None,
    "@ai-sdk/gateway": None,
    "@ai-sdk/google": None,
    "@ai-sdk/google-vertex": None,
    "@ai-sdk/perplexity": None,
    "ai-gateway-provider": None,
    "watsonx-ai-provider": None,
}

# 登记为某种协议的接入包的依据：官方源码的仓库、提交与文件位置。
NPM_EVIDENCE: dict[str, str] = {
    "@ai-sdk/openai":
        "vercel/ai@5107fa3c98857df791317c88089a850665eb6304 "
        "packages/openai/src/responses/openai-responses-language-model.ts:850（path: '/responses'）",
    "@ai-sdk/anthropic":
        "vercel/ai@5107fa3c98857df791317c88089a850665eb6304 "
        "packages/anthropic/src/anthropic-language-model.ts:1195（${baseURL}/messages，anthropic-version 请求头）",
    "@ai-sdk/openai-compatible":
        "vercel/ai@5107fa3c98857df791317c88089a850665eb6304 "
        "packages/openai-compatible/src/chat/openai-compatible-chat-language-model.ts:378-379"
        "（path: '/chat/completions'，Bearer 认证，OpenAI 格式的请求体）",
    "@openrouter/ai-sdk-provider":
        "OpenRouterTeam/ai-sdk-provider@0d2e6922091b77b71cc44e81eba69ed5fbd92f0f "
        "src/chat/index.ts:301（path: '/chat/completions'）",
    "@ai-sdk/azure":
        "vercel/ai@5107fa3c98857df791317c88089a850665eb6304 "
        "packages/azure/src/azure-openai-provider.ts:440-446,546（默认 languageModel 是 OpenAIResponsesLanguageModel，"
        "请求路径 /responses 见 packages/openai/src/responses/openai-responses-language-model.ts:850）",
    "@ai-sdk/amazon-bedrock/mantle":
        "vercel/ai@5107fa3c98857df791317c88089a850665eb6304 "
        "packages/amazon-bedrock/src/mantle/bedrock-mantle-provider.ts:262-266（默认 languageModel 用 OpenAIChatLanguageModel，"
        "请求路径 /chat/completions 见 packages/openai/src/chat/openai-chat-language-model.ts:424）",
    "@ai-sdk/cerebras":
        "vercel/ai@5107fa3c98857df791317c88089a850665eb6304 "
        "packages/cerebras/src/cerebras-chat-language-model.ts:36（继承 OpenAICompatibleChatLanguageModel）",
    "@ai-sdk/deepinfra":
        "vercel/ai@5107fa3c98857df791317c88089a850665eb6304 "
        "packages/deepinfra/src/deepinfra-chat-language-model.ts:22（继承 OpenAICompatibleChatLanguageModel）",
    "@ai-sdk/google-vertex/anthropic":
        "vercel/ai@5107fa3c98857df791317c88089a850665eb6304 "
        "packages/google-vertex/src/anthropic/google-vertex-anthropic-provider.ts:223-237"
        "（AnthropicMessagesLanguageModel，anthropic_version: 'vertex-2023-10-16'，请求体是 Anthropic Messages 的格式）",
    "@ai-sdk/groq":
        "vercel/ai@5107fa3c98857df791317c88089a850665eb6304 "
        "packages/groq/src/groq-chat-language-model.ts:310-311（path: '/chat/completions'）",
    "@ai-sdk/mistral":
        "vercel/ai@5107fa3c98857df791317c88089a850665eb6304 "
        "packages/mistral/src/mistral-chat-language-model.ts:271（${baseURL}/chat/completions）",
    "@ai-sdk/togetherai":
        "vercel/ai@5107fa3c98857df791317c88089a850665eb6304 "
        "packages/togetherai/src/togetherai-provider.ts:161-167（用 OpenAICompatibleChatLanguageModel）",
    "@ai-sdk/xai":
        "vercel/ai@5107fa3c98857df791317c88089a850665eb6304 "
        "packages/xai/src/responses/xai-responses-language-model.ts:418（${baseURL}/responses）",
    "@ai-sdk/alibaba":
        "vercel/ai@5107fa3c98857df791317c88089a850665eb6304 "
        "packages/alibaba/src/alibaba-chat-language-model.ts:230（${baseURL}/chat/completions）",
    "@aihubmix/ai-sdk-provider":
        "AIhubmix/ai-sdk-provider@86fbd7c2dcdd2b8c1bc276bb979d1509e784021c "
        "src/aihubmix-provider.ts:283-286（默认 languageModel 用 OpenAICompatibleChatLanguageModel；"
        "claude- 前缀的模型走 Anthropic Messages、gemini- 前缀的模型走 generateContent）",
    "@jerome-benoit/sap-ai-provider-v2":
        "jerome-benoit/sap-ai-provider@d6e826a0eca162c821dacef4066ab604c9b7eee0 "
        "src/responses-http-transport.ts:67,152（${deploymentPath}/responses，POST 的 JSON 请求体）",
    "@qvac/ai-sdk-provider":
        "tetherto/qvac@74abd6a5b7e59b48f0de8c1a11b33d63751d00a4 "
        "packages/ai-sdk-provider/src/provider.ts:41（用 OpenAI 兼容的 chatModel）",
    "@saladtechnologies-oss/ai-sdk-provider":
        "saladtechnologies/ai-sdk-provider@d82b5e12aba77f4e1e335cd3e69b162f14a19eea "
        "src/salad-cloud-chat-language-model.ts:81（${baseURL}/chat/completions）",
    "gitlab-ai-provider":
        "gitlab.com/vglafirov/gitlab-ai-provider@671aea4d32e344b883396becdde77dd365911d11 "
        "src/gitlab-provider.ts:601,659（默认 languageModel 是 GitLabOpenAILanguageModel）；"
        "src/gitlab-openai-language-model.ts:1,83-89（用 OpenAI SDK 的 Chat Completions）",
    "merge-gateway-ai-sdk-provider":
        "merge-api/merge-gateway-ai-sdk-provider@8242796d9a8feb0ddceccb62ffef8b1294c11bef "
        "src/chat/index.ts:196（path: '/chat/completions'）",
    "venice-ai-sdk-provider":
        "dpuyosa/venice-ai-sdk-provider@245da5978c3546b3f3032d50ab8ed2cbb779ec9a "
        "src/venice-chat-language-model.ts:227（path: '/chat/completions'）",
}

# 这些官方服务商的 models.dev 记录没有 api；其他服务商缺少时保持空串。
OFFICIAL_API_URLS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "google": "https://generativelanguage.googleapis.com/v1beta",
}


def load_models_dev(source_url: str, input_path: Path | None) -> tuple[dict[str, Any], str]:
    # 取数与来源文件的 SHA-256：给出本地文件时读文件，给出地址时读网络内容，两处都记哈希。
    if input_path is not None:
        payload = input_path.read_bytes()
        return json.loads(payload.decode("utf-8")), hashlib.sha256(payload).hexdigest()
    import urllib.request

    request = urllib.request.Request(source_url, headers={"User-Agent": "Yudao-Loop-System/0.1"})
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = response.read()
    return json.loads(payload.decode("utf-8")), hashlib.sha256(payload).hexdigest()


def declared_npm(entry: dict[str, Any]) -> str:
    # 模型单独声明的 provider.npm；没有字符串声明时由调用方取服务商接入包。
    provider = entry.get("provider")
    npm = provider.get("npm") if isinstance(provider, dict) else None
    return npm.strip() if isinstance(npm, str) else ""


def extract_model(entry: dict[str, Any], model_id: str, npm: str, model_npm: str) -> dict[str, Any]:
    # 一条模型记录：models.dev 中 modalities 可以缺少，缺少时不记录输入方式与输出方式；
    # limit 缺少或取值非法时对应的容量字段为 null；工具调用与推理按布尔取值记录。
    # 协议取自这个模型生效的接入包（模型自己声明的优先，否则取服务商的）；
    # 接入包没有对应的协议时协议为空，容量与输入方式照常记录。
    capability: dict[str, Any] = {"model": model_id, "protocol": NPM_PROTOCOLS[npm]}
    if model_npm:
        capability["npm"] = model_npm
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


def check_evidence() -> None:
    # 登记为某种协议的接入包都要有依据；依据缺失是登记表的错误，不是快照的问题。
    missing = sorted(name for name, protocol in NPM_PROTOCOLS.items() if protocol is not None and not NPM_EVIDENCE.get(name))
    if missing:
        raise ValueError("接入包映射表里登记为某种协议的行缺少依据：" + "、".join(missing))
    unknown = sorted(set(NPM_EVIDENCE) - set(NPM_PROTOCOLS))
    if unknown:
        raise ValueError("依据里有映射表没有的接入包：" + "、".join(unknown))


def build_table(presets: list[dict[str, Any]], models_dev: dict[str, Any],
                revision: str, snapshot_date: str, source: str,
                source_sha256: str = "") -> dict[str, Any]:
    check_evidence()
    providers: dict[str, dict[str, Any]] = {}
    unknown: list[str] = []
    for provider_id, provider in sorted(models_dev.items()):
        if not isinstance(provider, dict) or not isinstance(provider.get("models"), dict):
            raise ValueError(f"models.dev 的服务商 {provider_id} 缺少模型对象")
        npm = provider.get("npm") or ""
        if npm not in NPM_PROTOCOLS:
            unknown.append(f"{provider_id}（服务商接入包 {npm or '缺少接入包'}）")
        entries = provider["models"]
        models: list[dict[str, Any]] = []
        for model_id, entry in sorted(entries.items()):
            if not isinstance(entry, dict):
                raise ValueError(f"models.dev 的 {provider_id}/{model_id} 不是模型对象")
            model_npm = declared_npm(entry)
            effective = model_npm or npm
            if effective not in NPM_PROTOCOLS:
                unknown.append(f"{provider_id}/{model_id}（模型接入包 {effective or '缺少接入包'}）")
                continue
            models.append(extract_model(entry, model_id, effective, model_npm))
        if npm in NPM_PROTOCOLS:
            providers[provider_id] = {
                "api": provider.get("api") or OFFICIAL_API_URLS.get(provider_id, ""),
                "npm": npm,
                "models": models,
            }
    if unknown:
        raise ValueError("models.dev 的接入包不在协议映射表里（服务商/模型）：\n  " + "\n  ".join(unknown))
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
        raise ValueError("models.dev 中找不到预置服务方案：" + "、".join(missing))
    return {
        "version": 2,
        "providers": providers,
        "presets": table_presets,
        "revision": revision,
        "snapshot_date": snapshot_date,
        "source": source,
        "source_sha256": source_sha256,
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
    models_dev, source_sha256 = load_models_dev(args.source_url, args.input)
    snapshot_date = args.date or date.today().isoformat()
    revision = args.revision or f"{snapshot_date}.1"
    source = args.source_url if args.input is None else f"{args.source_url}（本地文件 {args.input.name}）"
    try:
        table = build_table(presets, models_dev, revision, snapshot_date, source, source_sha256)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    payload = json.dumps(table, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    args.out.write_text(payload, encoding="utf-8", newline="\n")
    count = sum(len(provider["models"]) for provider in table["providers"].values())
    without_protocol = sum(1 for provider in table["providers"].values()
                            for entry in provider["models"] if entry["protocol"] is None)
    print(f"写出 {args.out}：revision {revision}，快照日期 {snapshot_date}，"
          f"{len(table['providers'])} 个服务商、{count} 个模型（其中协议为空 {without_protocol} 个）、"
          f"{args.out.stat().st_size} 字节；来源 SHA-256 {source_sha256}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
