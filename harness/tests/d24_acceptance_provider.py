# 真实 Provider 验收的共享装配（工单 #96）：连接、模型访问定义、真实 HTTP 上游的调用目标。
# 只被验收测试文件导入，不进入产品代码。

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from harness.providers.credentials import CredentialChain
from harness.providers.facade import ProviderFacade

# 三种协议在 9router 上的请求基址与凭据都来自用户环境变量；Key 不进入代码、事件与日志
BASE_URL_ENV = "YUDAO_EVAL_BASE_URL"
API_KEY_ENV = "YUDAO_EVAL_API_KEY"


def eval_base_url() -> str:
    value = os.environ.get(BASE_URL_ENV, "").strip()
    if not value:
        raise RuntimeError(f"缺少环境变量 {BASE_URL_ENV}")
    return value.rstrip("/")


def eval_api_key() -> str:
    value = os.environ.get(API_KEY_ENV, "").strip()
    if not value:
        raise RuntimeError(f"缺少环境变量 {API_KEY_ENV}")
    return value


# 三个模型：连接测试、模型测试与 Messages 工具往返用 Claude；推理内容核对与回放用 DeepSeek
CLAUDE_MODEL = "ag/claude-opus-4-6-thinking"
DEEPSEEK_MODEL = "cbcn/deepseek-v4.1-flash"

# 三种协议各自的连接 ID、模型定义 ID 与推理参数方式
PROTOCOLS = ("responses", "chat_completions", "messages")


def protocol_reasoning_mode(protocol: str) -> str:
    # Responses 与 Chat Completions 用 effort；Anthropic Messages 用 adaptive（设计说明第 7.4 节）
    return "adaptive" if protocol == "messages" else "effort"


def connection_document(protocol: str, *, base_url: str | None = None) -> dict[str, Any]:
    # 一份连接只声明一种协议（ADR-0004）；三种协议共用同一个 9router 地址与凭据引用
    url = base_url if base_url is not None else eval_base_url()
    return {
        "id": f"eval-{protocol}",
        "name": f"9router {protocol}",
        "protocol": protocol,
        "base_url": url,
        "credential_ref": "YUDAO_EVAL_API_KEY",
        "timeout_sec": 120.0,
        "models_url": f"{url}/models",
    }


def claude_definition(protocol: str) -> dict[str, Any]:
    # Claude 的三种协议都能正常回复；Messages 的工具往返也用它。容量取自上游模型列表
    return {
        "id": f"claude-{protocol}",
        "provider_id": f"eval-{protocol}",
        "model": CLAUDE_MODEL,
        "context_window": 200_000,
        "max_output_tokens": 8_192,
        "input_modalities": ["text"],
        "reasoning_levels": ["low", "medium", "high"],
        "default_reasoning_level": "medium",
        "reasoning_mode": protocol_reasoning_mode(protocol),
    }


def deepseek_definition(protocol: str) -> dict[str, Any]:
    # DeepSeek V4.1 Flash 在三种协议上都返回推理内容；用它核对实际发送的推理参数与上游返回的推理内容
    return {
        "id": f"deepseek-{protocol}",
        "provider_id": f"eval-{protocol}",
        "model": DEEPSEEK_MODEL,
        "context_window": 1_000_000,
        "max_output_tokens": 16_384,
        "input_modalities": ["text"],
        "reasoning_levels": ["low", "medium", "high"],
        "default_reasoning_level": "medium",
        "reasoning_mode": protocol_reasoning_mode(protocol),
    }


def build_facade(protocol: str, *, startup_mode: str = "normal") -> ProviderFacade:
    # 每个协议一份连接、两份定义（Claude 与 DeepSeek）；凭据从进程环境读取，不写入文件
    facade = ProviderFacade(
        credentials=CredentialChain(overrides={}, use_env=True),
        startup_mode=startup_mode,
    )
    facade.store_document({
        "providers": [connection_document(protocol)],
        "models": [claude_definition(protocol), deepseek_definition(protocol)],
        "bindings": {},
    })
    return facade


def configure_paths(facade: ProviderFacade, data_dir: Path) -> None:
    # 目录文件与准入文件落在验收数据目录内；目录文件本身不含凭据
    data_dir.mkdir(parents=True, exist_ok=True)
    facade.configure_paths(data_dir / "providers.json", None)
    facade.persist_document(data_dir / "providers.json")


def build_system_facade(data_dir: Path):
    # 建三种协议各一份连接与两份定义，完成连接测试与模型测试写入准入，部门默认绑定 Messages 上的 Claude。
    # 返回 (LoopSystem, ProviderFacade)，供真实事项运行使用
    from harness.runtime import LoopSystem

    facade = ProviderFacade(credentials=CredentialChain(overrides={}, use_env=True), startup_mode="normal")
    providers = [connection_document(p) for p in PROTOCOLS]
    models = [claude_definition(p) for p in PROTOCOLS] + [deepseek_definition(p) for p in PROTOCOLS]
    facade.store_document({"providers": providers, "models": models, "bindings": {}})
    facade.configure_paths(data_dir / "providers.json", None)
    facade.persist_document(data_dir / "providers.json")
    for protocol in PROTOCOLS:
        facade.test_connection({"key": f"claude-{protocol}", "provider_id": f"eval-{protocol}",
                                "model_id": f"claude-{protocol}"})
        facade.model_test(f"eval-{protocol}", f"claude-{protocol}")
        facade.model_test(f"eval-{protocol}", f"deepseek-{protocol}")
    facade.save_bindings({department: {"provider_id": "eval-messages", "model_id": "claude-messages",
                                       "requested_tier": "high"}
                          for department in ("product", "engineering", "quality")})
    facade.persist_document(data_dir / "providers.json")
    system = LoopSystem(data_dir, facade=facade, resume_on_startup=False)
    return system, facade
