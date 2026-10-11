"""D22 启动与 Provider 热生效自动验收测试。
覆盖 docs/requirements/startup-provider-reload.md 第 3-5 节的本地行为，
全部使用 tmp_path 隔离，不访问网络，不调用真实模型。
"""
from __future__ import annotations

import json
import time

import pytest

from harness.app.application import Application
from harness.models import EventType
from harness.providers import (
    CredentialChain,
    ProviderFacade,
)
from harness.runtime import LoopSystem
from harness.tests.api_helpers import running_api


# ---------------------------------------------------------------------------
# 辅助构造器
# ---------------------------------------------------------------------------

def _fake_doc() -> dict:
    """包含一个 fake 协议 Provider、一个模型和三部门绑定的有效文档。"""
    return {
        "providers": [
            {"id": "pf", "name": "测试服务"},
        ],
        "models": [
            {
                "id": "mf",
                "provider_id": "pf",
                "model": "fake-model",
                "protocol": "fake",
                "context_window": 8000,
                "max_output_tokens": 512,
            },
        ],
        "bindings": {
            "product": {"provider_id": "pf", "model_id": "mf"},
            "engineering": {"provider_id": "pf", "model_id": "mf"},
            "quality": {"provider_id": "pf", "model_id": "mf"},
        },
    }


def _fake_catalog_only() -> dict:
    """只有目录和模型，没有绑定。"""
    return {
        "providers": [
            {"id": "pf", "name": "测试服务"},
        ],
        "models": [
            {
                "id": "mf",
                "provider_id": "pf",
                "model": "fake-model",
                "protocol": "fake",
                "context_window": 8000,
                "max_output_tokens": 512,
            },
        ],
    }


def _fake_provider_entry() -> dict:
    """单个 Provider 结构条目，无 credential_ref。"""
    return {"id": "pf", "name": "测试服务"}


def _write_json(path, data) -> None:
    """以与 persist_document 一致的字节格式写 JSON：UTF-8, \n 换行。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_bytes(payload.encode("utf-8"))


def _write_text(path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


# ---------------------------------------------------------------------------
# 1. 无配置启动
# ---------------------------------------------------------------------------

def test_no_config_start(tmp_path):
    """指向不存在的 providers.json 和 .env -> provider_status 可用为 False，
    原因 provider_config_missing；config_status 报告路径与空态，无异常。"""
    missing_config = tmp_path / "nonexistent" / "providers.json"
    missing_dotenv = tmp_path / "nonexistent" / ".env"

    facade = ProviderFacade(startup_mode="test", credentials=CredentialChain(use_env=False))
    facade.configure_paths(missing_config, missing_dotenv)
    facade.reload()

    system = LoopSystem(tmp_path / "data", facade=facade)

    # provider_status: 无配置 -> 不可用
    status = system.provider_status()
    assert status["available"] is False
    assert status["reason"] == "provider_config_missing"

    # config_status: 路径已记录，reload 报告目录文件不存在，reload_error 为空
    cfg = facade.config_status()
    assert cfg["config_path"] == str(missing_config)
    assert cfg["config_state"] in ("empty", "missing", "deleted")
    assert cfg["reload_error"] is None


# ---------------------------------------------------------------------------
# 2. CLI 默认命令
# ---------------------------------------------------------------------------

def test_cli_default_command(tmp_path):
    # 不写子命令时启动新接口（应用层与接口层设计说明第 7.3、7.4 节）：默认端口 8765，
    # 没有 serve 子命令；服务以空态启动，system.status 返回 Provider 不可用与默认的模型目录路径
    from harness.__main__ import build_parser

    parser = build_parser()
    assert parser.parse_args([]).port == 8765
    assert parser.parse_args([]).command is None
    with pytest.raises(SystemExit):
        parser.parse_args(["serve"])

    data_dir = tmp_path / "data"
    with running_api(lambda: Application.open(data_dir, provider_config=data_dir / "providers.json",
                                              dotenv=data_dir / ".env")) as client:
        status = client.get("/api/queries/system.status").json()["data"]
    assert status["provider"]["available"] is False
    assert status["catalog"]["reload_error"] is None
    assert (data_dir / "events.sqlite").is_file()


_ABSENT_KEY = "YUDAO_STARTUP_ABSENT_KEY"


def _startup_config(state: str):
    if state == "missing":
        return None
    if state == "invalid_json":
        return "{ not json"
    if state == "empty_catalog":
        return {"providers": [], "models": [], "bindings": {}}
    if state == "unbound":
        # 目录有内容但没有部门绑定；fake 协议在正常启动被拒绝（工单 #86），这里用真实协议
        return {
            "providers": [{"id": "p1", "name": "P1",
                           "base_url": "https://example.com/v1",
                           "credential_ref": _ABSENT_KEY, "timeout_sec": 60}],
            "models": [{"id": "m1", "provider_id": "p1", "model": "m",
                        "protocol": "responses",
                        "context_window": 8000, "max_output_tokens": 512}],
            "bindings": {},
        }
    return {
        "providers": [{"id": "p1", "name": "P1",
                       "base_url": "https://example.com/v1",
                       "credential_ref": _ABSENT_KEY, "timeout_sec": 60}],
        "models": [{"id": "m1", "provider_id": "p1", "model": "m",
                    "protocol": "responses",
                    "context_window": 8000, "max_output_tokens": 512}],
        "bindings": {department: {"provider_id": "p1", "model_id": "m1"}
                     for department in ("product", "engineering", "quality")},
    }


@pytest.mark.parametrize("state", ["missing", "invalid_json", "empty_catalog", "unbound", "missing_key"])
def test_service_starts_in_every_unready_state_and_blocks_the_first_request(tmp_path, monkeypatch, state):
    # 模型目录文件缺少、JSON 损坏、目录为空、没有绑定、缺少凭据：服务照常启动，system.status 与 catalog
    # 返回 Provider 不可用；创建事项不再解析调用目标（#45），第一次请求解析失败时进入待恢复，运行不是失败结束。
    # 凭据文件默认在数据目录内（设计说明第 3.4 节）
    from harness.projection import saved_decisions

    monkeypatch.delenv(_ABSENT_KEY, raising=False)
    config_path = tmp_path / "providers.json"
    content = _startup_config(state)
    if isinstance(content, str):
        _write_text(config_path, content)
    elif content is not None:
        _write_json(config_path, content)

    data_dir = tmp_path / "data"
    application = Application.open(data_dir, provider_config=config_path, dotenv=data_dir / ".env")
    system = application.system
    with running_api(lambda: application) as client:
        status = client.get("/api/queries/system.status").json()["data"]
        catalog = client.get("/api/queries/catalog").json()["data"]
        assert status["provider"]["available"] is False
        assert isinstance(catalog["providers"], list)
        status_view = system.facade.config_status()
        assert status_view["dotenv_path"] == str((data_dir / ".env").resolve())
        if state == "invalid_json":
            assert status_view["reload_error"]
            assert status["catalog"]["reload_error"]
        else:
            assert status_view["reload_error"] is None
        if state == "missing_key":
            assert _ABSENT_KEY in status_view["message"]
        run_id = system.create_run("create without a ready provider")
        assert system.list_run_ids() == [run_id]
        blocked = system.run_until_stop(run_id)
        assert (blocked.outcome, blocked.stop_reason) == ("running", None)
        _position, decisions = saved_decisions(system.store, statuses=("open",))
        assert [decision.request["kind"] for decision in decisions] == ["model_unavailable"]
        assert not any(event.type == EventType.MODEL_REQUESTED for event in system.store.list_events(run_id))


# ---------------------------------------------------------------------------
# 3. 结构合法的部分保存
# ---------------------------------------------------------------------------

def test_structural_partial_save(tmp_path):
    """save_provider_entry 保存结构合法的 Provider（无 credential、无 model）-> 发布成功；
    describe_readiness available False 且含定位 issues；落盘可重新加载且非敏感内容一致。"""
    facade = ProviderFacade(startup_mode="test", credentials=CredentialChain(use_env=False))
    # 保存结构条目，不传 models_raw
    rev = facade.save_provider_entry(_fake_provider_entry())
    assert rev >= 1

    # 就绪检查：缺绑定 -> 不可用
    readiness = facade.describe_readiness()
    assert readiness["available"] is False
    assert readiness["issues"]  # 有定位 issue

    # 持久化文档并重新加载
    doc_path = tmp_path / "providers.json"
    facade.persist_document(doc_path)

    loaded = json.loads(doc_path.read_text(encoding="utf-8"))
    assert loaded["providers"][0]["id"] == "pf"
    assert loaded["providers"][0]["name"] == "测试服务"
    assert "credential_ref" not in loaded["providers"][0] or loaded["providers"][0].get("credential_ref", "") == ""

    # 验证已持久化的文档能被全新 facade 加载且结构一致
    facade2 = ProviderFacade(startup_mode="test", credentials=CredentialChain(use_env=False))
    facade2.load_document(doc_path)
    doc2 = facade2.to_document()
    assert doc2["providers"] == loaded["providers"]


# ---------------------------------------------------------------------------
# 4. 新任务修订与冻结快照不变性
# ---------------------------------------------------------------------------

def test_frozen_snapshot_immutability(tmp_path):
    """resolve_departments 返回的快照 public_dict 在后续 save_bindings 推进修订后不变。"""
    facade = ProviderFacade(startup_mode="test", credentials=CredentialChain(use_env=False))

    # 先写入目录与模型（fake 协议无需凭据）
    facade.store(_fake_catalog_only())

    # 绑定并发布第一个版本
    facade.save_bindings({
        "product": {"provider_id": "pf", "model_id": "mf"},
        "engineering": {"provider_id": "pf", "model_id": "mf"},
        "quality": {"provider_id": "pf", "model_id": "mf"},
    })
    rev_before = facade.revision

    # 取得冻结快照，捕获其公开字典
    snapshot = facade.resolve_departments()
    snapshot_public = snapshot.public_dict()

    # 快照中目标与当前目录一致
    assert snapshot.target("product").provider_id == "pf"
    assert snapshot.target("product").model_id == "mf"

    # 推进新修订：新增一个模型并重新绑定到新模型
    facade.save_model({
        "id": "mf2", "provider_id": "pf", "model": "fake-model-2",
        "protocol": "fake",
        "context_window": 4000, "max_output_tokens": 256,
    })
    facade.save_bindings({
        "product": {"provider_id": "pf", "model_id": "mf2"},
        "engineering": {"provider_id": "pf", "model_id": "mf2"},
        "quality": {"provider_id": "pf", "model_id": "mf2"},
    })

    # 冻结快照仍然持有旧值（公共字典与修订不随后续发布改变）
    assert snapshot.public_dict() == snapshot_public
    assert snapshot.target("product").model_id == "mf"

    # 新快照反映新状态
    new_snapshot = facade.resolve_departments()
    assert new_snapshot.target("product").model_id == "mf2"


# ---------------------------------------------------------------------------
# 5. 外部损坏编辑
# ---------------------------------------------------------------------------

def test_corrupt_external_edit(tmp_path):
    """有效文档加载后，外部覆写为非法 JSON -> reload ok=False，保留上一版本；
    修复后 reload ok=True 且错误清除。"""
    config_path = tmp_path / "providers.json"
    facade = ProviderFacade(startup_mode="test", credentials=CredentialChain(use_env=False))
    facade.configure_paths(config_path)

    # 写入有效文档并加载
    _write_json(config_path, _fake_doc())
    facade.load_document(config_path)
    valid_rev = facade.revision
    assert valid_rev >= 1

    # 外部损坏
    _write_text(config_path, "{invalid json!!!")
    result = facade.reload()
    assert result["ok"] is False
    assert facade.config_status()["reload_error"] is not None
    # 保留上一有效版本
    assert facade.revision == valid_rev
    readiness = facade.describe_readiness()
    assert readiness["available"] is True  # 旧版本仍可用

    # 修复文件
    _write_json(config_path, _fake_doc())
    result2 = facade.reload()
    assert result2["ok"] is True
    assert facade.config_status()["reload_error"] is None
    assert facade.revision > valid_rev
    assert facade.describe_readiness()["available"] is True


# ---------------------------------------------------------------------------
# 6. 明确删除配置文件
# ---------------------------------------------------------------------------

def test_clear_withdraw(tmp_path):
    """删除 providers.json -> reload config_state=deleted，目录与部门默认一起清空，readiness 不可用；
    重建有效空文档 -> reload 发布。"""
    config_path = tmp_path / "providers.json"
    facade = ProviderFacade(startup_mode="test", credentials=CredentialChain(use_env=False))
    facade.configure_paths(config_path)

    # 写入有效文档并加载
    _write_json(config_path, _fake_doc())
    facade.load_document(config_path)
    saved_rev = facade.revision

    # 删除文件：目录与部门默认一起清空，config_state 记为 deleted（设计说明第 4.7 节）
    config_path.unlink()
    result = facade.reload()
    assert result["ok"] is True  # 删除不是损坏，reload_error 为 None
    assert facade.config_status()["config_state"] == "deleted"
    assert facade.get_bindings() == {} and facade.to_document()["models"] == []
    readiness = facade.describe_readiness()
    assert readiness["available"] is False
    assert readiness["reason"] == "provider_config_missing"

    # 重建有效文档
    _write_json(config_path, _fake_doc())
    result2 = facade.reload()
    assert result2["ok"] is True
    assert facade.config_status()["config_state"] in ("loaded", "empty")
    assert facade.revision > saved_rev


def test_save_after_delete_refreshes_the_config_state_to_loaded(tmp_path):
    # 工单 #301：文件删除以后保存成功，配置状态刷新为已加载，不再停留删除
    config_path = tmp_path / "providers.json"
    facade = ProviderFacade(startup_mode="test", credentials=CredentialChain(use_env=False))
    facade.configure_paths(config_path)
    _write_json(config_path, _fake_doc())
    facade.load_document(config_path)
    config_path.unlink()
    assert facade.reload()["ok"] is True
    assert facade.config_status()["config_state"] == "deleted"
    previous = facade.to_document()
    facade.save_provider_entry({"id": "pf", "name": "测试服务"})
    assert facade.persist_catalog(previous) is None
    assert facade.config_status()["config_state"] == "loaded"


def test_memory_save_without_config_path_refreshes_the_config_state_to_loaded():
    # 工单 #301：没有配置文件路径时保存只改内存，配置状态同样按内存重算为已加载
    facade = ProviderFacade(startup_mode="test", credentials=CredentialChain(use_env=False))
    facade.store_document(_fake_doc())
    assert facade.config_status()["config_state"] == "loaded"


# ---------------------------------------------------------------------------
# 7. 同尺寸改写检测（内容哈希，非 mtime/size）
# ---------------------------------------------------------------------------

def test_same_size_rewrite(tmp_path):
    """不同 JSON 内容但完全相同字节数 -> reload 必须检测变化并发布。"""
    config_path = tmp_path / "providers.json"
    facade = ProviderFacade(startup_mode="test", credentials=CredentialChain(use_env=False))
    facade.configure_paths(config_path)

    doc_a = _fake_doc()
    _write_json(config_path, doc_a)
    facade.load_document(config_path)
    rev_a = facade.revision
    raw_a = config_path.read_bytes()

    # 构造不同内容但相同字节数的文档 B：替换等长中文名（4 个汉字 = 12 字节 UTF-8）
    doc_b = json.loads(json.dumps(doc_a))
    doc_b["providers"][0]["name"] = "一二三四"
    raw_b = (json.dumps(doc_b, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    assert len(raw_b) == len(raw_a), (
        f"无法构造同尺寸文档：A={len(raw_a)} B={len(raw_b)}"
    )
    assert raw_b != raw_a

    config_path.write_bytes(raw_b)
    result = facade.reload()
    assert result["ok"] is True
    assert facade.revision > rev_a
    # 验证新内容已生效
    doc = facade.to_document()
    assert doc["providers"][0]["name"] == "一二三四"


# ---------------------------------------------------------------------------
# 8. 文件轮询监视器
# ---------------------------------------------------------------------------

def test_watcher_detects_external_write(tmp_path):
    """facade.start_watching(interval_sec=0.05) 后写入新文档 -> 轮询约 3 秒内
    检测到修订变化；stop_watching 后线程停止。"""
    config_path = tmp_path / "providers.json"
    facade = ProviderFacade(startup_mode="test", credentials=CredentialChain(use_env=False))
    facade.configure_paths(config_path)

    # 初始加载
    _write_json(config_path, _fake_catalog_only())
    facade.load_document(config_path)
    initial_rev = facade.revision

    # 启动监视：监视线程没有启动回调，用截止时限内轮询等待它已经运行
    facade.start_watching(interval_sec=0.05)
    deadline = time.monotonic() + 3.0
    while not facade.config_status()["watching"]:
        assert time.monotonic() < deadline, "监视线程没有启动"
        time.sleep(0.01)

    # 外部写入新有效文档；写入发生在监视已经运行之后，修订变化由下面的轮询确认
    _write_json(config_path, _fake_doc())

    # 轮询等待修订变化
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if facade.revision > initial_rev:
            break
        time.sleep(0.05)
    assert facade.revision > initial_rev, "监视器未在 3 秒内检测到文件变化"
    cfg_status = facade.config_status()
    assert cfg_status["config_state"] in ("loaded", "empty")
    assert cfg_status["reload_error"] is None

    # 停止并确认线程终止
    facade.stop_watching()
    cfg = facade.config_status()
    assert cfg["watching"] is False


# ---------------------------------------------------------------------------
# 9. 凭据来源链
# ---------------------------------------------------------------------------

def test_credentials_chain(tmp_path, monkeypatch):
    """覆盖 -> .env -> 删除 .env -> 移除后不复活 -> 持久化与移除 -> 失败时抛异常。"""
    # 清理环境变量，防止干扰
    monkeypatch.delenv("TEST_CRED_SECRET", raising=False)
    monkeypatch.delenv("TEST_DOTENV_KEY", raising=False)

    config_path = tmp_path / "providers.json"
    dotenv_path = tmp_path / ".env"

    facade = ProviderFacade(startup_mode="test", credentials=CredentialChain(use_env=False))
    facade.configure_paths(config_path, dotenv_path)
    _write_json(config_path, {
        "providers": [
            {"id": "p1", "name": "P1",
             "credential_ref": "TEST_CRED_SECRET",
             "base_url": "https://example.com/v1", "timeout_sec": 60},
        ],
        "models": [
            {"id": "m1", "provider_id": "p1", "model": "m",
             "protocol": "responses",
             "context_window": 8000, "max_output_tokens": 512},
        ],
        "bindings": {
            "product": {"provider_id": "p1", "model_id": "m1"},
            "engineering": {"provider_id": "p1", "model_id": "m1"},
            "quality": {"provider_id": "p1", "model_id": "m1"},
        },
    })
    facade.load_document(config_path)

    # (a) 设置内存覆盖 -> describe source=override, has_override=True
    facade.set_credential_override("TEST_CRED_SECRET", "override-secret-123")
    desc = facade.providers_view()["providers"][0]["credential"]
    assert desc["source"] == "override"
    assert desc["has_override"] is True
    assert desc["configured"] is True

    # (b) 写入 .env，清除覆盖 -> 回退到 dotenv
    _write_text(dotenv_path, "TEST_CRED_SECRET=dotenv-secret-456\n")
    facade.clear_credential_override("TEST_CRED_SECRET")
    facade.reload()
    desc2 = facade.providers_view()["providers"][0]["credential"]
    assert desc2["source"] == "dotenv"
    assert desc2["has_override"] is False
    assert desc2["configured"] is True

    # (c) 删除 .env 文件 -> 重新加载 -> 来源变为 missing，不复活缓存
    dotenv_path.unlink()
    facade.reload()
    desc3 = facade.providers_view()["providers"][0]["credential"]
    assert desc3["source"] == "missing"
    assert desc3["configured"] is False

    # (d) save_dotenv_value 持久化 -> .env 文件和内存均更新
    dotenv_path2 = tmp_path / ".env2"
    result = facade.save_dotenv_value(dotenv_path2, "TEST_DOTENV_KEY", "new-secret-789")
    assert result["configured"] is True
    assert result["source"] == "dotenv"
    assert dotenv_path2.exists()
    env_content = dotenv_path2.read_text(encoding="utf-8")
    assert "TEST_DOTENV_KEY" in env_content

    # (e) remove_dotenv_value 移除
    result2 = facade.remove_dotenv_value(dotenv_path2, "TEST_DOTENV_KEY")
    assert result2["removed"] is True
    assert result2["configured"] is False
    env_content2 = dotenv_path2.read_text(encoding="utf-8")
    assert "TEST_DOTENV_KEY" not in env_content2

    # (f) save_dotenv_value 目标路径是目录 -> 抛异常，不报成功
    dir_path = tmp_path / "a_directory"
    dir_path.mkdir()
    with pytest.raises(OSError):
        facade.save_dotenv_value(dir_path, "KEY", "value")


# ---------------------------------------------------------------------------
# 10. 密钥卫生
# ---------------------------------------------------------------------------

def test_secret_hygiene(tmp_path, monkeypatch):
    """全部操作完成后，序列化输出与落盘文件中不含任何测试密钥明文。"""
    # 清理环境变量，防止泄漏进 use_env=False 的 describe 检查
    monkeypatch.delenv("SECRET_REF", raising=False)
    monkeypatch.delenv("ANOTHER_KEY", raising=False)

    secret_values = [
        "override-secret-123",
        "env-leaked-key-xyz",
        "dotenv-persisted-abc",
    ]

    config_path = tmp_path / "providers.json"
    dotenv_path = tmp_path / ".env"

    facade = ProviderFacade(startup_mode="test", credentials=CredentialChain(use_env=False))
    facade.configure_paths(config_path, dotenv_path)
    _write_json(config_path, {
        "providers": [
            {"id": "p1", "name": "P1",
             "credential_ref": "SECRET_REF",
             "base_url": "https://example.com/v1", "timeout_sec": 60},
        ],
        "models": [
            {"id": "m1", "provider_id": "p1", "model": "m",
             "protocol": "responses",
             "context_window": 8000, "max_output_tokens": 512},
        ],
        "bindings": {
            "product": {"provider_id": "p1", "model_id": "m1"},
            "engineering": {"provider_id": "p1", "model_id": "m1"},
            "quality": {"provider_id": "p1", "model_id": "m1"},
        },
    })
    facade.load_document(config_path)

    # 注入各种密钥来源
    facade.set_credential_override("SECRET_REF", secret_values[0])
    facade.save_dotenv_value(dotenv_path, "ANOTHER_KEY", secret_values[2])
    facade.set_credential_override("ANOTHER_KEY", secret_values[1])

    # 持久化文档
    facade.persist_document(config_path)

    # 采集全部序列化输出
    public_json = json.dumps(facade.public_view(), ensure_ascii=False)
    doc_json = json.dumps(facade.to_document(), ensure_ascii=False)
    cfg_json = json.dumps(facade.config_status(), ensure_ascii=False)
    file_content = config_path.read_bytes().decode("utf-8")

    combined = public_json + doc_json + cfg_json + file_content

    for secret in secret_values:
        assert secret not in combined, (
            f"密钥 {secret!r} 出现在序列化输出或落盘文件中，存在泄漏"
        )
