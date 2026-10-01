import hashlib
import json
import threading
import uuid

from harness.adapters.fake import FakeAdapter
from harness.app.application import DEFAULT_REGISTRY, Application
from harness.app.commands import Rejection
from harness.app.contracts import EVENT_TYPES, CommandRequest, Contract, NoRefs, Snapshot, Text
from harness.app.project_commands import PROJECT_CREATE
from harness.app.registry import CommandDefinition, QueryDefinition, Registry
from harness.app.system_queries import SYSTEM_STATUS
from harness.event_store import project_stream
from harness.models import CatalogEventType, EventType, ProjectEventType
from harness.runtime import LoopSystem
from harness.tests.api_helpers import running_api
from harness.write_path import NewProjectEvent

# 应用层与接口层的骨架：真实启动 FastAPI 应用（uvicorn），经 HTTP 提交命令、读取查询、能力清单与 OpenAPI；
# 控制核心在服务的生命周期中建立，事件日志是真实的 SQLite 文件，模型回答由 FakeAdapter 给出（这里不调用模型）。


class _Opened:
    # 服务生命周期中建立的应用层；测试经它直接读取事件日志核对结果
    def __init__(self, data_dir, registry: Registry = DEFAULT_REGISTRY) -> None:
        self.data_dir = data_dir
        self.registry = registry
        self.applications: list[Application] = []

    def __call__(self) -> Application:
        application = Application(LoopSystem.for_testing(self.data_dir, FakeAdapter([])), registry=self.registry)
        self.applications.append(application)
        return application

    @property
    def store(self):
        return self.applications[-1].system.store


def _create(client, command_id, name="文本工具", goal="逐行处理文本"):
    return client.post("/api/commands/project.create", json={"command_id": command_id, "name": name, "goal": goal})


def test_project_create_is_accepted_with_its_position_and_recorded_with_command_and_actor(data_dir):
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        command_id = str(uuid.uuid4())
        response = _create(client, command_id)
        assert response.status_code == 200
        body = response.json()
        project_id = body["refs"]["project_id"]
        events = opened.store.list_project_events(project_id)
        assert [event.type for event in events] == [ProjectEventType.PROJECT_REGISTERED]
        assert body == {"command_id": command_id, "position": events[0].position, "refs": {"project_id": project_id},
                        "duplicate": False}
        assert (events[0].command_id, events[0].actor) == (command_id, "user:local")
        assert (events[0].payload["name"], events[0].payload["goal"]) == ("文本工具", "逐行处理文本")
        assert opened.applications[0].system.projects.projection(project_id).name == "文本工具"


def test_a_repeated_command_identity_returns_the_original_result_and_reused_identity_is_rejected(data_dir):
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        command_id = str(uuid.uuid4())
        first = _create(client, command_id).json()
        end = opened.store.end_position()
        again = _create(client, command_id)
        assert again.status_code == 200 and again.json() == {**first, "duplicate": True}
        reused = _create(client, command_id, name="另一个项目")
        assert reused.status_code == 409
        assert reused.json() == {
            "command_id": command_id, "reason": "command_id_reused",
            "message": "这个命令身份已经用于内容不同的另一次提交，请为新的操作生成新的命令身份", "current_version": None,
        }
        # 重复与重复使用都没有写入：事件只写一次，也没有为另一个项目保存目标原文
        assert opened.store.end_position() == end
        assert opened.store.list_project_ids() == [first["refs"]["project_id"]]
        assert [path.name for path in (data_dir / "artifacts").iterdir()] == [first["refs"]["project_id"]]

        # 同一命令同时提交两次：只写入一次，两次都得到同一个位置与项目
        concurrent = str(uuid.uuid4())
        both_sent = threading.Barrier(2)
        results = []

        def submit():
            both_sent.wait(10)
            results.append(_create(client, concurrent, name="同时提交").json())

        threads = [threading.Thread(target=submit) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        assert sorted(result["duplicate"] for result in results) == [False, True]
        assert results[0]["position"] == results[1]["position"] and results[0]["refs"] == results[1]["refs"]
        assert len(opened.store.command_events(concurrent)) == 1
        assert len(opened.store.list_project_ids()) == 2


def test_system_status_returns_a_snapshot_with_its_position_and_writes_nothing(data_dir):
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        _create(client, str(uuid.uuid4()))
        store = opened.store
        streams = [project_stream(project_id) for project_id in store.list_project_ids()]
        end = store.end_position()
        saved = [store.projection(stream) for stream in streams]
        response = client.get("/api/queries/system.status")
        assert response.status_code == 200
        body = response.json()
        application = opened.applications[0]
        assert body["position"] == end
        assert body["data"]["log_id"] == store.log_id
        assert body["data"]["boot_id"] == application.boot_id
        assert body["data"]["provider"] == {"available": True, "reason": "", "message": ""}
        assert set(body["data"]["catalog"]) == {"revision", "reload_error"}
        # 查询不写入：事件日志末尾与保存的投影都不变
        assert store.end_position() == end
        assert [store.projection(stream) for stream in streams] == saved
        first_boot = body["data"]["boot_id"]
    # 服务重启：日志身份不变，本次启动的身份改变
    with running_api(opened) as client:
        status = client.get("/api/queries/system.status").json()["data"]
        assert status["log_id"] == opened.store.log_id == body["data"]["log_id"]
        assert status["boot_id"] != first_boot


def _digest(document):
    text = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _registered_paths(document, prefix):
    return {path.removeprefix(prefix) for path in document["paths"] if path.startswith(prefix)}


def test_capabilities_and_openapi_list_the_registered_queries_and_commands(data_dir):
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        capabilities = client.get("/api/capabilities").json()
        document = client.get("/openapi.json").json()
    assert capabilities["commands"] == [
        {"name": "project.create", "reasons": ["command_id_reused"]},
        {"name": "project.rename",
         "reasons": ["not_found", "stale_base", "project_archived", "command_id_reused"]},
        {"name": "project.pin",
         "reasons": ["not_found", "stale_base", "project_archived", "command_id_reused"]},
        {"name": "project.archive",
         "reasons": ["not_found", "stale_base", "work_item_in_progress", "command_id_reused"]},
        {"name": "project.restore", "reasons": ["not_found", "stale_base", "command_id_reused"]},
        {"name": "material.record",
         "reasons": ["not_found", "project_archived", "work_item_in_progress", "not_allowed",
                     "command_id_reused"]},
        {"name": "work_item.create",
         "reasons": ["not_found", "project_archived", "busy", "provider_unavailable", "command_id_reused"]},
        {"name": "work_item.append_input", "reasons": ["not_found", "run_terminal", "command_id_reused"]},
        {"name": "work_item.cancel", "reasons": ["not_found", "run_terminal", "command_id_reused"]},
        {"name": "guidance.send",
         "reasons": ["not_found", "run_terminal", "not_allowed", "command_id_reused"]},
        {"name": "department_settings.save",
         "reasons": ["not_found", "stale_base", "project_archived", "not_allowed", "command_id_reused"]},
        {"name": "command_registration.save",
         "reasons": ["not_found", "stale_base", "project_archived", "not_allowed", "command_id_reused"]},
        {"name": "source_directory.save",
         "reasons": ["not_found", "stale_base", "project_archived", "command_id_reused"]},
        {"name": "decision.answer", "reasons": ["not_found", "decision_closed", "stale_base", "option_invalid",
                                               "command_id_reused"]},
        {"name": "catalog.connection.save", "reasons": ["stale_base", "catalog_invalid", "command_id_reused"]},
        {"name": "catalog.connection.delete", "reasons": ["stale_base", "not_found", "in_use", "command_id_reused"]},
        {"name": "catalog.document.save", "reasons": ["stale_base", "catalog_invalid", "command_id_reused"]},
        {"name": "catalog.reload", "reasons": ["command_id_reused"]},
        {"name": "catalog.candidates.collect", "reasons": ["not_found", "command_id_reused"]},
        {"name": "catalog.connection.test", "reasons": ["not_found", "catalog_invalid", "command_id_reused"]},
        {"name": "catalog.model.test", "reasons": ["not_found", "command_id_reused"]},
        {"name": "catalog.department_defaults.save",
         "reasons": ["stale_base", "catalog_invalid", "command_id_reused"]},
        {"name": "credential.set", "reasons": ["stale_base", "catalog_invalid", "command_id_reused"]},
        {"name": "credential.clear_override", "reasons": ["stale_base", "command_id_reused"]},
        {"name": "credential.remove_persisted", "reasons": ["stale_base", "catalog_invalid", "command_id_reused"]},
        {"name": "runtime.start_drain", "reasons": ["not_allowed", "command_id_reused"]},
        {"name": "runtime.force_upgrade", "reasons": ["not_allowed", "command_id_reused"]},
    ]
    catalog_changed_by = ["catalog_revised", "catalog_candidates_collected", "catalog_test_finished",
                          "credential_changed"]
    assert capabilities["queries"][-2:] == [
        {"name": "catalog", "changed_by": catalog_changed_by},
        {"name": "catalog.document", "changed_by": catalog_changed_by},
    ]
    queries = capabilities["queries"]
    assert {item["name"] for item in queries} == set(DEFAULT_REGISTRY.queries) == {
        "system.status", "attempt.live", "decisions.list", "projects.list", "project.overview", "project.loop",
        "project.flow", "work_item.inputs", "event.detail", "department.workspace", "run.actions",
        "work_item.materials", "delivery.file", "project.attempts", "project.usage", "run.attempt",
        "project.settings", "run.export", "replay.check", "catalog", "catalog.document",
    }
    # 覆盖层只列出依赖的查询都已登记的：flow 与 waiting 的依赖已登记，其余依赖的查询尚未加入
    assert capabilities["overlays"] == [
        {"name": "flow", "queries": ["project.flow"]},
        {"name": "waiting", "queries": ["project.loop", "decisions.list"]},
    ]
    assert _registered_paths(document, "/api/commands/") == set(DEFAULT_REGISTRY.commands)
    assert _registered_paths(document, "/api/queries/") == set(DEFAULT_REGISTRY.queries)
    assert capabilities["decisions"] == ["model_unavailable", "definitions_changed", "unknown_action"]
    deployment = capabilities["deployment"]
    assert deployment["contract_digest"] == _digest(document)
    assert deployment["log_id"] == opened.store.log_id and deployment["boot_id"] == opened.applications[0].boot_id
    assert deployment["version"] == document["info"]["version"]
    # 事件种类：现有全部 run 事件、项目事件与目录事件，与 OpenAPI 中事件对象的联合一致
    known = {value for owner in (EventType, ProjectEventType, CatalogEventType)
             for key, value in vars(owner).items() if not key.startswith("_")}
    assert set(capabilities["event_types"]) == known == set(EVENT_TYPES)
    mapping = document["components"]["schemas"]["EventObject"]["discriminator"]["mapping"]
    assert set(mapping) == known
    assert "OutputDelta" in document["components"]["schemas"]


class _SampleRename(CommandRequest):
    # 测试登记的修改类命令：基准版本必须等于项目流的当前版本
    base_version: int
    project_id: str
    name: Text


async def _sample_rename(application, command, request):
    def decide(transaction):
        if transaction.version != request.base_version:
            raise Rejection("stale_base", "项目已经被修改，请重新读取以后再提交", current_version=transaction.version)
        transaction.append(NewProjectEvent(ProjectEventType.PROJECT_RENAMED, {"name": request.name}))

    application.system.writes.transact(project_stream(request.project_id), decide, command=command)


SAMPLE_RENAME = CommandDefinition(name="sample.rename", request=_SampleRename, refs=NoRefs, handle=_sample_rename,
                                  derive_refs=lambda _events: NoRefs(), reasons=("stale_base",))


class _SampleNameRequest(Contract):
    # 测试登记的带参数查询
    project_id: str


class _SampleName(Contract):
    name: str
    version: int


def _sample_name(application, request):
    saved = application.system.writes.read(project_stream(request.project_id))
    return Snapshot[_SampleName](position=application.system.store.end_position(),
                                 data=_SampleName(name=saved.projection.name, version=saved.version))


SAMPLE_NAME = QueryDefinition(name="sample.name", request=_SampleNameRequest, result=_SampleName,
                              handle=_sample_name, changed_by=(ProjectEventType.PROJECT_RENAMED,))
SAMPLE_REGISTRY = Registry(commands=[PROJECT_CREATE, SAMPLE_RENAME], queries=[SYSTEM_STATUS, SAMPLE_NAME])


def test_registered_commands_and_queries_get_routes_and_capabilities_and_a_base_is_checked_in_the_transaction(
        data_dir):
    opened = _Opened(data_dir, SAMPLE_REGISTRY)
    with running_api(opened, registry=SAMPLE_REGISTRY) as client:
        capabilities = client.get("/api/capabilities").json()
        document = client.get("/openapi.json").json()
        assert {"name": "sample.rename", "reasons": ["stale_base", "command_id_reused"]} in capabilities["commands"]
        assert {"name": "sample.name", "changed_by": ["project_renamed"]} in capabilities["queries"]
        assert _registered_paths(document, "/api/commands/") == {"project.create", "sample.rename"}
        assert _registered_paths(document, "/api/queries/") == {"system.status", "sample.name"}
        parameters = document["paths"]["/api/queries/sample.name"]["get"]["parameters"]
        assert [(item["name"], item["in"], item["required"]) for item in parameters] == [("project_id", "query", True)]

        project_id = _create(client, str(uuid.uuid4())).json()["refs"]["project_id"]
        store = opened.store
        stale = str(uuid.uuid4())
        rejected = client.post("/api/commands/sample.rename", json={
            "command_id": stale, "base_version": 0, "project_id": project_id, "name": "新名字"})
        assert rejected.status_code == 409
        assert rejected.json() == {"command_id": stale, "reason": "stale_base",
                                   "message": "项目已经被修改，请重新读取以后再提交", "current_version": 1}
        # 被拒绝的命令不登记：同一身份按当前版本重新提交时重新判断并被接受
        assert store.command(stale) is None
        accepted = client.post("/api/commands/sample.rename", json={
            "command_id": stale, "base_version": 1, "project_id": project_id, "name": "新名字"})
        assert accepted.status_code == 200
        assert accepted.json() == {"command_id": stale, "position": store.end_position(), "refs": {},
                                   "duplicate": False}
        assert client.get("/api/queries/sample.name", params={"project_id": project_id}).json() == {
            "position": store.end_position(), "data": {"name": "新名字", "version": 2}}
        assert client.get("/api/queries/sample.name").status_code == 422
        assert client.get("/api/queries/sample.name",
                          params={"project_id": project_id, "other": "x"}).status_code == 422


def test_requests_outside_the_contract_are_refused_and_documentation_pages_are_closed(data_dir):
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        command_id = str(uuid.uuid4())
        for body in ({"name": "项目", "goal": "目标"},
                     {"command_id": "not-a-uuid", "name": "项目", "goal": "目标"},
                     # 命令身份只接受小写的标准形式，响应与事件中原样出现
                     {"command_id": command_id.upper(), "name": "项目", "goal": "目标"},
                     {"command_id": command_id.replace("-", ""), "name": "项目", "goal": "目标"},
                     {"command_id": command_id, "name": "  ", "goal": "目标"},
                     # 控制核心按 str.strip 判断空白，分隔符等控制字符同样算空白
                     {"command_id": command_id, "name": "\u001f", "goal": "目标"},
                     {"command_id": command_id, "name": "项目", "goal": "目标", "base_version": 3},
                     {"command_id": command_id, "name": "项目", "goal": "目标", "owner": "someone"}):
            response = client.post("/api/commands/project.create", json=body)
            assert response.status_code == 422, body
            assert response.json()["detail"]
        assert opened.store.end_position() == 0
        assert client.post("/api/commands/project.unknown", json={"command_id": command_id}).status_code == 404
        assert client.get("/api/queries/project.unknown").status_code == 404
        for path in ("/docs", "/redoc", "/docs/oauth2-redirect"):
            assert client.get(path).status_code == 404
        assert client.get("/openapi.json").status_code == 200


def test_queries_for_a_missing_target_answer_404_like_the_old_read_routes(data_dir):
    # 旧路由对不存在的运行、事件与交付文件返回 404；已登记的查询在目标不存在时同样给出 404
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        for name, params in (("project.overview", {"project_id": "missing"}),
                             ("project.flow", {"project_id": "missing"}),
                             ("work_item.inputs", {"project_id": "missing", "work_item": "missing"}),
                             ("event.detail", {"event_id": "missing"}),
                             ("run.actions", {"run_id": "missing"}),
                             ("run.attempt", {"run_id": "missing", "attempt_id": "missing"}),
                             ("run.export", {"run_id": "missing"}),
                             ("delivery.file", {"event_id": "missing", "path": "missing.py"})):
            response = client.get(f"/api/queries/{name}", params=params)
            assert response.status_code == 404, (name, response.text)
            assert response.json()["error"]
        assert opened.store.end_position() == 0


def test_query_filters_outside_the_contract_are_refused_by_the_contract(data_dir):
    # 状态与部门的取值由合同限定，游标与分页大小的格式同样如此：不符合时按合同拒绝，不落到 500
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        for name, params in (("project.attempts", {"project_id": "p", "status": "bogus"}),
                             ("project.usage", {"project_id": "p", "status": "bogus"}),
                             ("project.attempts", {"project_id": "p", "department": "bogus"}),
                             ("project.usage", {"project_id": "p", "department": "bogus"}),
                             ("project.attempts", {"project_id": "p", "cursor": "not-a-cursor"}),
                             ("project.attempts", {"project_id": "p", "cursor": "1:x:2"}),
                             ("project.attempts", {"project_id": "p", "limit": 0}),
                             ("project.attempts", {"project_id": "p", "limit": 500})):
            response = client.get(f"/api/queries/{name}", params=params)
            assert response.status_code == 422, (name, params, response.text)
