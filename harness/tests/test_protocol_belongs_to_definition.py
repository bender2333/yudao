# 调用协议属于模型访问定义的验收（ADR-0033，工单 #382）。
# 同一份连接下的多个访问定义可以各用一种协议，请求基址按访问定义的协议取：
# 内置服务方案取预置表中该协议的请求基址，自定义服务取连接的地址；
# 改动协议只让它自己的准入作废，改动连接地址让该连接下全部定义作废。
# 全部检查经测试内启动的真实 HTTP 服务，不使用桩替身。

from __future__ import annotations

from harness.providers import CatalogValidationError, CredentialChain, ProviderFacade
from harness.providers.presets import preset_base_url
from harness.tests.protocol_helpers import (
    chat_responder,
    invoke,
    messages_responder,
    model_call,
    responses_responder,
    serve,
)

HI = model_call([{"role": "user", "content": "hi"}], max_output_tokens=1024,
                session_id="run-1:engineering", attempt_id="a1")

# 自定义服务：一份连接不带服务方案，地址由连接自己给出
def _custom_document(*definitions):
    return {
        "providers": [{"id": "local", "name": "Local", "base_url": "http://127.0.0.1:9/v1",
                       "credential_ref": "LOCAL_KEY", "timeout_sec": 30.0}],
        "models": [{"id": model_id, "provider_id": "local", "model": "upstream-x",
                    "protocol": protocol, "context_window": 32000, "max_output_tokens": 2048}
                   for model_id, protocol in definitions],
        "bindings": {},
    }

def _facade(document, **overrides):
    facade = ProviderFacade(credentials=CredentialChain(overrides={"LOCAL_KEY": "local-secret"}, use_env=False))
    facade.store_document(document)
    for ref, secret in overrides.items():
        facade.set_credential_override(ref, secret)
    return facade

def _target(facade, model_id):
    return facade.resolve_snapshot(
        [{"key": model_id, "provider_id": "local", "model_id": model_id}]).target(model_id)

def test_two_protocols_under_one_connection_reach_their_own_paths_and_headers():
    # 同一份连接下的两条定义：Chat Completions 发往 /chat/completions 带 Bearer，
    # Anthropic Messages 发往 /v1/messages 带 x-api-key
    server, capture, base = serve(lambda body: messages_responder(body)
                                  if any("/messages" in path for path in capture.paths[-1:])
                                  else chat_responder(body))
    try:
        document = _custom_document(("m-chat", "chat_completions"), ("m-msg", "messages"))
        document["providers"][0]["base_url"] = base
        facade = _facade(document)
        invoke(facade, _target(facade, "m-chat"), HI)
        invoke(facade, _target(facade, "m-msg"), HI)
    finally:
        server.shutdown()
        server.server_close()
    assert [path.split("?")[0] for path in capture.paths] == ["/chat/completions", "/v1/messages"]
    assert capture.headers[0]["authorization"] == "Bearer local-secret"
    assert capture.headers[0].get("x-api-key") is None
    assert capture.headers[1]["x-api-key"] == "local-secret"
    assert capture.headers[1].get("authorization") is None

def test_a_preset_connection_takes_the_base_url_of_the_definition_protocol():
    # 内置服务方案：请求基址取预置表中该协议的基址，不是连接的地址
    server, capture, base = serve(responses_responder)
    try:
        facade = _facade({
            "providers": [{"id": "go", "name": "Go", "base_url": base,
                           "credential_ref": "LOCAL_KEY", "timeout_sec": 30.0,
                           "preset_id": "opencode-go"}],
            "models": [{"id": "m-responses", "provider_id": "go", "model": "upstream-x",
                        "protocol": "responses", "context_window": 32000, "max_output_tokens": 2048}],
            "bindings": {},
        })
        target = facade.resolve_snapshot(
            [{"key": "m-responses", "provider_id": "go", "model_id": "m-responses"}]).target("m-responses")
        assert target.base_url == preset_base_url("opencode-go", "responses")
        assert target.base_url != base
    finally:
        server.shutdown()
        server.server_close()
    assert capture.requests == []

def test_a_custom_connection_uses_its_own_address_for_every_protocol():
    # 自定义服务没有预置基址：三种协议的请求基址都是连接的地址
    for protocol in ("responses", "chat_completions", "messages"):
        facade = _facade(_custom_document(("m1", protocol)))
        target = _target(facade, "m1")
        assert target.base_url == "http://127.0.0.1:9/v1"
        assert target.protocol == protocol

def test_changing_one_definition_protocol_stales_only_that_definition():
    # 改一条定义的协议：只有它回到候选，同一连接下的其他定义保持已准入
    facade = _facade(_custom_document(("m-chat", "chat_completions"), ("m-msg", "messages")))
    facade.record_admission("local", "m-chat", admitted_model="upstream-x")
    facade.record_admission("local", "m-msg", admitted_model="upstream-x")
    assert [row["admitted"] for row in facade.model_admissions()] == [True, True]

    revision = facade.catalog_revision()
    facade.save_provider_entry(
        {"id": "local", "name": "Local", "base_url": "http://127.0.0.1:9/v1",
         "credential_ref": "LOCAL_KEY", "timeout_sec": 30.0},
        [{"id": "m-chat", "model": "upstream-x", "protocol": "responses",
          "context_window": 32000, "max_output_tokens": 2048},
         {"id": "m-msg", "model": "upstream-x", "protocol": "messages",
          "context_window": 32000, "max_output_tokens": 2048}],
    )
    rows = {row["model_id"]: row for row in facade.model_admissions()}
    assert rows["m-chat"]["admitted"] is False
    assert rows["m-chat"]["stale"] is True
    assert rows["m-msg"]["admitted"] is True
    assert rows["m-chat"]["protocol"] == "responses"
    assert facade.catalog_revision() > revision

    # catalog.change_impact 只算受影响的定义，应用层读同一份计算
    impacted = facade.impacted_definitions({
        "providers": facade.to_document()["providers"],
        "models": [{**item, "protocol": "responses"} for item in facade.to_document()["models"]
                   if item["id"] == "m-chat"],
    })
    assert impacted == [{"model_id": "m-chat", "provider_id": "local"}]

def test_changing_the_connection_address_stales_every_definition_under_it():
    # 改连接的地址：该连接下全部定义回到候选；另一份连接下的定义不受影响
    facade = _facade(_custom_document(("m-chat", "chat_completions"), ("m-msg", "messages")))
    facade.store_document({
        "providers": facade.to_document()["providers"] + [
            {"id": "other", "name": "Other", "base_url": "http://127.0.0.1:10/v1",
             "credential_ref": "LOCAL_KEY", "timeout_sec": 30.0}],
        "models": facade.to_document()["models"] + [
            {"id": "m-other", "provider_id": "other", "model": "upstream-y",
             "protocol": "chat_completions", "context_window": 32000, "max_output_tokens": 2048}],
        "bindings": {},
    })
    for model_id, provider_id in (("m-chat", "local"), ("m-msg", "local"), ("m-other", "other")):
        facade.record_admission(provider_id, model_id, admitted_model="upstream-x")

    facade.save_provider_entry(
        {"id": "local", "name": "Local", "base_url": "http://127.0.0.1:11/v1",
         "credential_ref": "LOCAL_KEY", "timeout_sec": 30.0},
        [{"id": "m-chat", "model": "upstream-x", "protocol": "chat_completions",
          "context_window": 32000, "max_output_tokens": 2048},
         {"id": "m-msg", "model": "upstream-x", "protocol": "messages",
          "context_window": 32000, "max_output_tokens": 2048}],
    )
    rows = {row["model_id"]: row for row in facade.model_admissions()}
    assert rows["m-chat"]["admitted"] is False
    assert rows["m-msg"]["admitted"] is False
    assert rows["m-other"]["admitted"] is True

def test_admission_records_carry_the_protocol_of_the_definition():
    # 准入记录写入访问定义的协议；改这条定义的协议以后记录作废（第 4.4 节）
    facade = _facade(_custom_document(("m-chat", "chat_completions")))
    facade.record_admission("local", "m-chat", admitted_model="upstream-x")
    rows = facade.model_admissions()
    assert rows[0]["protocol"] == "chat_completions"
    assert rows[0]["admitted"] is True

    facade.save_provider_entry(
        {"id": "local", "name": "Local", "base_url": "http://127.0.0.1:9/v1",
         "credential_ref": "LOCAL_KEY", "timeout_sec": 30.0},
        [{"id": "m-chat", "model": "upstream-x", "protocol": "messages",
          "context_window": 32000, "max_output_tokens": 2048}],
    )
    rows = facade.model_admissions()
    assert rows[0]["protocol"] == "messages"
    assert rows[0]["admitted"] is False
    assert rows[0]["stale"] is True

def test_a_connection_that_declares_a_protocol_is_rejected_naming_where():
    # 连接上出现协议字段：读取以错误结束并写明位置，不迁移也不补默认值
    facade = ProviderFacade(credentials=CredentialChain(use_env=False))
    try:
        facade.store_document({
            "providers": [{"id": "local", "name": "Local", "protocol": "responses",
                           "base_url": "http://127.0.0.1:9/v1", "credential_ref": "LOCAL_KEY"}],
            "models": [{"id": "m1", "provider_id": "local", "model": "upstream-x",
                        "protocol": "responses", "context_window": 32000, "max_output_tokens": 2048}],
            "bindings": {},
        })
    except CatalogValidationError as exc:
        issues = [(issue.location, issue.message) for issue in exc.issues]
    else:
        raise AssertionError("连接上带协议的目录应被拒绝")
    assert ("providers[0].protocol", "连接不再声明调用协议，请在每个模型访问定义上声明") in issues

def test_a_definition_without_a_protocol_is_rejected_naming_where():
    # 访问定义缺少协议：读取以错误结束并写明位置
    facade = ProviderFacade(credentials=CredentialChain(use_env=False))
    try:
        facade.store_document({
            "providers": [{"id": "local", "name": "Local",
                           "base_url": "http://127.0.0.1:9/v1", "credential_ref": "LOCAL_KEY"}],
            "models": [{"id": "m1", "provider_id": "local", "model": "upstream-x",
                        "context_window": 32000, "max_output_tokens": 2048}],
            "bindings": {},
        })
    except CatalogValidationError as exc:
        issues = [(issue.location, issue.message) for issue in exc.issues]
    else:
        raise AssertionError("缺少协议的访问定义应被拒绝")
    assert any(location.startswith("models[0]") and location.endswith("protocol")
               for location, _message in issues)

def test_a_definition_with_an_unsupported_protocol_is_rejected_naming_where():
    # 协议取值不在三种协议与 fake 之内：写明位置
    facade = ProviderFacade(credentials=CredentialChain(use_env=False))
    try:
        facade.store_document(_custom_document(("m1", "grpc")))
    except CatalogValidationError as exc:
        issues = [(issue.location, issue.message) for issue in exc.issues]
    else:
        raise AssertionError("协议不受支持的访问定义应被拒绝")
    assert ("models[0].protocol", "协议不受支持") in issues

def test_the_connection_has_no_protocol_in_the_catalog_view():
    # 目录视图里的连接不带协议，协议在每一条访问定义上
    facade = _facade(_custom_document(("m-chat", "chat_completions"), ("m-msg", "messages")))
    view = facade.providers_view()
    assert "protocol" not in view["providers"][0]
    assert [item["protocol"] for item in view["models"]] == ["chat_completions", "messages"]
    assert set(facade.to_document()["providers"][0]) == {
        "id", "name", "base_url", "credential_ref", "timeout_sec", "preset_id", "models_url"}

def test_a_fake_definition_is_rejected_when_started_normally():
    # fake 只在测试或演示方式启动的系统中可用：正常启动时写明是哪一条定义
    facade = ProviderFacade(credentials=CredentialChain(use_env=False), startup_mode="normal")
    try:
        facade.store_document(_custom_document(("m-fake", "fake")))
    except CatalogValidationError as exc:
        issues = [(issue.location, issue.message) for issue in exc.issues]
    else:
        raise AssertionError("正常启动的系统中 fake 协议的访问定义应被拒绝")
    assert issues == [("models.m-fake.protocol", "正常启动的系统不允许 fake 协议的模型访问定义，"
                                                 "fake 只在测试或演示方式下可用")]

