# R2、R3：通过真实 HTTP、SQLite 与公开目录合同核对候选测试（docs/design/model-management.md「模型访问定义与准入」中「候选测试」）。
# 六条验收标准各一个用例；上游是测试内启动的真实本机 HTTP 服务，不使用替身。
from __future__ import annotations

import json
import threading
import time
import uuid

from harness.app.application import Application
from harness.models import CatalogEventType
from harness.tests.api_helpers import running_api
from harness.tests.protocol_helpers import ScriptedProvider, model_test_responder, send_reply
from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC

SECRET = "candidate-test-key-do-not-publish"

# 目录状态的等待窗口：一条用例里最多连等几次目录状态，每次取集中的等待上限的五分之一
# （harness/tests/wait_limits.py），仍在集成层给每条用例的上限之内。
CATALOG_WAIT_SEC = WAIT_FOR_HOST_WORK_SEC / 5


class Opened:
    def __init__(self, root):
        self.data_dir = root / "data"
        self.config = root / "providers.json"
        self.dotenv = root / ".env"
        self.applications = []

    def __call__(self):
        application = Application.open(self.data_dir, provider_config=self.config, dotenv=self.dotenv)
        self.applications.append(application)
        return application

    @property
    def application(self):
        return self.applications[-1]


def catalog(client):
    response = client.get("/api/queries/catalog")
    assert response.status_code == 200, response.text
    return response.json()["data"]


def command(client, operation, **values):
    return client.post(f"/api/commands/{operation}", json={"command_id": str(uuid.uuid4()), **values})


def responder(models):
    # 本机上游：GET 交回模型列表，POST 按模型测试的四个步骤回放完整回复（chat_completions）
    def respond(_provider, handler):
        if handler.body is None:
            send_reply(handler, 200, "application/json", json.dumps({"data": models}).encode())
            return
        status, content_type, chunks = model_test_responder(
            handler.body, protocol="chat_completions", actual_model=handler.body["model"])
        send_reply(handler, status, content_type, b"".join(chunks))
    return respond


def connect(client, upstream):
    response = command(client, "catalog.connect", base_version=catalog(client)["revision"],
                       base_url=upstream.base + "/v1", api_key=SECRET)
    assert response.status_code == 200, response.text
    provider_id = response.json()["refs"]["provider_id"]
    wait_catalog(client, lambda data: data["providers"][0]["latest_candidates"] is not None)
    return provider_id


def candidate_test(data, provider_id, model):
    # 目录查询里这个候选的测试状态与结果；没有测试过时为空
    provider = next(item for item in data["providers"] if item["id"] == provider_id)
    latest = provider["latest_candidates"] or {}
    candidate = next((item for item in latest.get("candidates", ()) if item["id"] == model), None)
    return None if candidate is None else candidate.get("test")


def wait_catalog(client, predicate):
    deadline = time.monotonic() + CATALOG_WAIT_SEC
    while time.monotonic() < deadline:
        data = catalog(client)
        if predicate(data):
            return data
        time.sleep(0.01)
    raise AssertionError("等待目录状态超时：" + json.dumps(catalog(client), ensure_ascii=False))


def wait_candidate_test(client, provider_id, model, predicate):
    return wait_catalog(client, lambda data: predicate(candidate_test(data, provider_id, model)))


def wait_event(opened, predicate, *, after=0):
    arrived = threading.Event()
    found = []

    def receive(events):
        for event in events:
            if event.position > after and predicate(event):
                found.append(event)
                arrived.set()

    store = opened.application.system.store
    unsubscribe = store.subscribe(receive)
    try:
        receive(store.read(after, limit=10000))
        assert arrived.wait(30), "等待目录结果事件超时"
        return found[-1]
    finally:
        unsubscribe()


def test_a_passing_candidate_test_saves_no_definition_admission_or_selection(tmp_path):
    # 验收 1：通过以后目录里没有新定义、没有准入记录，bindings 与已有选择与测试前完全相同；
    # 结果里有用时、实际返回的模型与是否接受要求调用工具。
    upstream = ScriptedProvider([responder([
        {"id": "maker/ready", "limit": {"context": 128000, "output": 8192}}
    ])] * 8)
    opened = Opened(tmp_path)
    try:
        with running_api(opened) as client:
            provider_id = connect(client, upstream)
            before = catalog(client)
            assert before["models"] == [] and before["admissions"] == [] and before["bindings"] == {}
            started = command(client, "catalog.candidate.test", base_version=before["revision"],
                              provider_id=provider_id, model="maker/ready")
            assert started.status_code == 200, started.text
            position = opened.application.system.store.end_position()
            data = wait_candidate_test(client, provider_id, "maker/ready",
                                       lambda test: test is not None and test["status"] == "passed")
            test = candidate_test(data, provider_id, "maker/ready")
            assert test["elapsed_ms"] >= 0 and test["actual_model"] == "maker/ready"
            assert test["accepts_required_tool_call"] is True
            assert test["failure_group"] is None and test["failure_step"] is None and test["error"] is None
            after = catalog(client)
            assert after["models"] == [] and after["admissions"] == [] and after["bindings"] == {}
            assert after["selections"] == []
            finished = wait_event(opened, lambda event: event.type == CatalogEventType.CATALOG_TEST_FINISHED
                                  and event.payload["kind"] == "candidate", after=position)
            assert finished.payload["ok"] is True and finished.payload["admitted"] is None
            assert finished.payload["provider_id"] == provider_id
            assert finished.payload["model_id"] == "maker/ready"
            assert finished.payload["actual_model"] == "maker/ready"
            assert SECRET not in json.dumps([event.payload for event in
                                             opened.application.system.store.read(0, limit=10000)])
    finally:
        upstream.close()


def test_a_failed_candidate_test_names_the_group_step_and_hides_401_and_403_bodies(tmp_path):
    # 验收 2：未通过时写明哪一组、哪一步与原因；401 与 403 只写状态码与含义，响应里查不到 Key。
    exposed = "untrusted-credential-echo " + SECRET

    def text_instead_of_tool(_provider, handler):
        body = {**handler.body, "tools": []}
        status, content_type, chunks = model_test_responder(
            body, protocol="chat_completions", actual_model=handler.body["model"])
        send_reply(handler, status, content_type, b"".join(chunks))

    def rejected(status):
        def respond(_provider, handler):
            send_reply(handler, status, "application/json",
                       json.dumps({"error": {"message": exposed}}).encode())
        return respond

    models = [{"id": "maker/ready", "limit": {"context": 128000, "output": 8192}}]
    upstream = ScriptedProvider([responder(models), responder(models), text_instead_of_tool,
                                 rejected(401), rejected(403)])
    opened = Opened(tmp_path)
    try:
        with running_api(opened) as client:
            provider_id = connect(client, upstream)

            def start():
                response = command(client, "catalog.candidate.test", base_version=catalog(client)["revision"],
                                   provider_id=provider_id, model="maker/ready")
                assert response.status_code == 200, response.text

            start()
            data = wait_candidate_test(client, provider_id, "maker/ready",
                                       lambda test: test is not None and test["status"] == "failed")
            tool = candidate_test(data, provider_id, "maker/ready")
            assert tool["failure_group"] == "tool_round_trip" and tool["failure_step"] == "tool_call"
            assert "工具往返" in tool["error"] and "模型没有调用测试工具" in tool["error"]

            start()
            data = wait_candidate_test(client, provider_id, "maker/ready",
                                       lambda test: test is not None and test["status"] == "failed")
            unauthorized = candidate_test(data, provider_id, "maker/ready")
            assert unauthorized["failure_group"] == "minimal_qa"
            assert unauthorized["failure_step"] == "request"
            assert "HTTP 401" in unauthorized["error"] and "凭据无效" in unauthorized["error"]
            assert exposed not in json.dumps(data, ensure_ascii=False)
            assert SECRET not in json.dumps(data, ensure_ascii=False)

            start()
            data = wait_candidate_test(client, provider_id, "maker/ready",
                                       lambda test: test is not None and test["status"] == "failed")
            forbidden = candidate_test(data, provider_id, "maker/ready")
            assert forbidden["failure_group"] == "minimal_qa"
            assert "HTTP 403" in forbidden["error"] and "没有访问权限" in forbidden["error"]
            dumped = json.dumps(data, ensure_ascii=False) + json.dumps(
                [event.payload for event in opened.application.system.store.read(0, limit=10000)],
                ensure_ascii=False)
            assert exposed not in dumped and SECRET not in dumped
            assert data["models"] == [] and data["admissions"] == [] and data["bindings"] == {}
    finally:
        upstream.close()


def test_candidate_tests_and_model_tests_share_one_concurrency_limit(tmp_path):
    # 验收 3：候选测试与选用后的模型测试合起来不超过同时测试的上限，多的是「等待测试」；
    # 上限改成 1 与 8 时同样成立。
    names = ["candidate-a", "candidate-b", "selected-c"]
    releases = {name: threading.Event() for name in names}
    entered: set[str] = set()
    condition = threading.Condition()
    normal = responder([{"id": name, "limit": {"context": 32000, "output": 2048}} for name in names])

    def gated(provider, handler):
        # 每次测试的第一组请求停在这里：名额给了哪些测试、谁还在等待，由真实请求的到达决定
        if handler.body is not None and not handler.body.get("tools"):
            name = handler.body["model"]
            with condition:
                entered.add(name)
                condition.notify_all()
            assert releases[name].wait(30), "等待候选测试名额放行"
        normal(provider, handler)

    upstream = ScriptedProvider([responder([{"id": name, "limit": {"context": 32000, "output": 2048}}
                                            for name in names]), *[gated] * 40])
    opened = Opened(tmp_path)
    try:
        with running_api(opened) as client:
            provider_id = connect(client, upstream)
            changed = command(client, "parameter.set", name="provider.model_test_max_concurrent", value=1,
                              reason="核对候选测试与选用测试共用一个名额", modified_by="candidate-test")
            assert changed.status_code == 200, changed.text
            for name in names:
                if name == names[-1]:
                    response = command(client, "catalog.model.select", base_version=catalog(client)["revision"],
                                       provider_id=provider_id, model=name)
                else:
                    response = command(client, "catalog.candidate.test", base_version=catalog(client)["revision"],
                                       provider_id=provider_id, model=name)
                assert response.status_code == 200, response.text
            with condition:
                assert condition.wait_for(lambda: len(entered) == 1, timeout=30)
            data = catalog(client)
            states = [candidate_test(data, provider_id, name)["status"] for name in names[:-1]]
            states += [row["status"] for row in data["selections"]]
            assert sorted(states) == ["testing", "waiting", "waiting"]
            raised = command(client, "parameter.set", name="provider.model_test_max_concurrent", value=8,
                             reason="核对上界：等待的候选测试与选用测试一起开始", modified_by="candidate-test")
            assert raised.status_code == 200, raised.text
            with condition:
                assert condition.wait_for(lambda: len(entered) == 3, timeout=30)
            data = catalog(client)
            states = [candidate_test(data, provider_id, name)["status"] for name in names[:-1]]
            states += [row["status"] for row in data["selections"]]
            assert states == ["testing", "testing", "testing"]
            for release in releases.values():
                release.set()
            data = wait_catalog(client, lambda data: all(
                (candidate_test(data, provider_id, name) or {}).get("status") == "passed"
                for name in names[:-1]) and any(row["admitted"] for row in data["admissions"])
                and not data["selections"])
            assert any(row["model"] == names[-1] and row["admitted"] for row in data["admissions"])
    finally:
        for release in releases.values():
            release.set()
        upstream.close()


def test_candidate_test_results_stay_in_the_query_until_the_model_list_is_fetched_again(tmp_path):
    # 验收 4：结果在重复查询时仍在，重新获取该连接的模型列表以后清除；服务重启以后不要求保留。
    upstream = ScriptedProvider([responder([
        {"id": "maker/ready", "limit": {"context": 128000, "output": 8192}}
    ])] * 8)
    opened = Opened(tmp_path)
    try:
        with running_api(opened) as client:
            provider_id = connect(client, upstream)
            response = command(client, "catalog.candidate.test", base_version=catalog(client)["revision"],
                               provider_id=provider_id, model="maker/ready")
            assert response.status_code == 200, response.text
            wait_candidate_test(client, provider_id, "maker/ready",
                                lambda test: test is not None and test["status"] == "passed")
            first = candidate_test(catalog(client), provider_id, "maker/ready")
            second = candidate_test(catalog(client), provider_id, "maker/ready")
            assert first == second and first["status"] == "passed"
            refreshed = command(client, "catalog.candidates.collect", base_version=catalog(client)["revision"],
                                provider_id=provider_id)
            assert refreshed.status_code == 200, refreshed.text
            wait_catalog(client, lambda data: candidate_test(data, provider_id, "maker/ready") is None)
        # 服务重启以后候选连数据本身都不保留（设计说明：候选测试的状态与结果只在服务进程里）
        with running_api(opened) as client:
            restarted = catalog(client)
            assert restarted["providers"][0]["latest_candidates"] is None
            assert restarted["models"] == [] and restarted["admissions"] == []
    finally:
        upstream.close()


def test_unknown_capacity_and_non_text_candidates_are_rejected_without_a_request(tmp_path):
    # 验收 5：容量未知的候选被拒绝，原因写明缺哪一项；输出不是文本的候选同样被拒绝。
    upstream = ScriptedProvider([responder([
        {"id": "unknown"},
        {"id": "picture", "modalities": {"output": ["image"]}},
    ])])
    opened = Opened(tmp_path)
    try:
        with running_api(opened) as client:
            provider_id = connect(client, upstream)
            unknown = command(client, "catalog.candidate.test", base_version=catalog(client)["revision"],
                              provider_id=provider_id, model="unknown")
            assert unknown.status_code == 409, unknown.text
            assert unknown.json()["reason"] == "not_allowed"
            assert "容量未知" in unknown.json()["message"]
            assert "窗口" in unknown.json()["message"] and "输出上限" in unknown.json()["message"]
            picture = command(client, "catalog.candidate.test", base_version=catalog(client)["revision"],
                              provider_id=provider_id, model="picture")
            assert picture.status_code == 409, picture.text
            assert picture.json()["reason"] == "not_allowed"
            assert "不适用" in picture.json()["message"]
            absent = command(client, "catalog.candidate.test", base_version=catalog(client)["revision"],
                             provider_id=provider_id, model="not-in-list")
            assert absent.status_code == 409, absent.text
            assert absent.json()["reason"] == "not_found"
            data = catalog(client)
            assert data["models"] == [] and data["admissions"] == [] and data["bindings"] == {}
            assert candidate_test(data, provider_id, "unknown") is None
            assert candidate_test(data, provider_id, "picture") is None
            # 被拒绝的测试没有向上游发出任何模型请求（只有获取模型列表的那一次 GET）
            assert upstream.requests == [None]
    finally:
        upstream.close()


def test_selecting_after_a_candidate_test_sends_the_two_groups_again_and_enables_with_sources(tmp_path):
    # 验收 6：测试通过以后选用该候选，上游再次收到两组请求，最终已启用，来源详情完整。
    upstream = ScriptedProvider([responder([
        {"id": "maker/ready", "limit": {"context": 128000, "output": 8192},
         "modalities": {"input": ["text", "image"], "output": ["text"]}}
    ])] * 10)
    opened = Opened(tmp_path)
    try:
        with running_api(opened) as client:
            provider_id = connect(client, upstream)
            tested = command(client, "catalog.candidate.test", base_version=catalog(client)["revision"],
                             provider_id=provider_id, model="maker/ready")
            assert tested.status_code == 200, tested.text
            wait_candidate_test(client, provider_id, "maker/ready",
                                lambda test: test is not None and test["status"] == "passed")
            requests_after_candidate_test = len(upstream.requests)
            assert requests_after_candidate_test == 4  # 一次列表 GET 与两组请求的三次 POST
            selected = command(client, "catalog.model.select", base_version=catalog(client)["revision"],
                               provider_id=provider_id, model="maker/ready")
            assert selected.status_code == 200, selected.text
            data = wait_catalog(client, lambda data: any(row["admitted"] for row in data["admissions"]))
            assert len(upstream.requests) == requests_after_candidate_test + 3
            [model] = data["models"]
            assert model["model"] == "maker/ready"
            assert model["context_window"] == 128000 and model["max_output_tokens"] == 8192
            assert model["input_modalities"] == ["text", "image"]
            sources = {name: detail["source"] for name, detail in model["source_details"].items()}
            assert set(sources) == {"protocol", "context_window", "max_output_tokens", "input_modalities",
                                    "output_modalities", "applicable", "reasoning"}
            assert sources["protocol"] == "default"
            assert sources["context_window"] == "models_url"
            assert sources["max_output_tokens"] == "models_url"
            assert sources["input_modalities"] == "models_url"
            assert sources["output_modalities"] == "models_url"
            assert model["accepts_required_tool_call"] is True
            [admission] = data["admissions"]
            assert admission["admitted"] is True and admission["admitted_model"] == "maker/ready"
            assert data["bindings"] == {
                department: {"provider_id": provider_id, "model_id": model["id"], "requested_tier": None}
                for department in ("product", "engineering", "quality")}
            assert data["selections"] == []
    finally:
        upstream.close()
