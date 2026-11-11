import json
import time
import uuid

from harness.watched_outputs import has_new_work
from harness.adapters.base import ProviderError
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.app.application import DEFAULT_REGISTRY, Application
from harness.demo import demo_script
from harness.direct import SINGLE_ROLE_DIRECT
from harness.models import EventType, ProjectEventType, Usage
from harness.projection import project_run
from harness.proposals import product_spec
from harness.runtime import LoopSystem
from harness.tests.api_helpers import catalog_model, catalog_provider, running_api
from harness.tests.protocol_helpers import serve, stub_stream
from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC
from harness.tests.helpers import quality_turns

# 项目与事项的命令（应用层与接口层 docs/design/app-and-interface.md「命令」、「执行与结算的归属」，工单 #74）：真实启动 FastAPI 应用（uvicorn），
# 经 HTTP 提交命令、读取查询；控制核心在服务生命周期中建立，事件日志是真实的 SQLite 文件，
# 事项的执行由流程编排在接口进程的事件循环中作为任务运行，run 结束时由流程编排结算。


UNAVAILABLE = "Missing configuration: provider credential"


def _blocked_script():
    # 产品提交规格以后，工程部门的请求被提供方报告为不可用：run 停在这次请求之前（ENGINEERING，未终态）
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    return {
        "product": [FakeTurn(proposal=product_spec(), usage=Usage(input_tokens=100, output_tokens=20))],
        "engineering": [ProviderError(UNAVAILABLE, reason="provider_unavailable")],
        "quality": quality_turns("release", "checks passed on the current snapshot"),
    }


class _Opened:
    # 服务生命周期中建立的应用层；测试经它直接读取事件日志核对结果
    def __init__(self, data_dir, adapter=None, registry=DEFAULT_REGISTRY) -> None:
        self.data_dir = data_dir
        self.adapter = FakeAdapter([]) if adapter is None else adapter
        self.registry = registry
        self.applications: list[Application] = []

    def __call__(self) -> Application:
        system = LoopSystem.for_testing(self.data_dir, self.adapter)
        application = Application(system, registry=self.registry)
        self.applications.append(application)
        return application

    @property
    def store(self):
        return self.applications[-1].system.store

    @property
    def system(self) -> LoopSystem:
        return self.applications[-1].system


def _post(client, command: str, **body):
    return client.post(f"/api/commands/{command}", json={"command_id": str(uuid.uuid4()), **body})


def _wait_for(predicate, timeout=WAIT_FOR_HOST_WORK_SEC):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_project_modification_commands_and_stale_base(data_dir):
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        created = _post(client, "project.create", name="测试项目", goal="验证命令")
        assert created.status_code == 200
        project_id = created.json()["refs"]["project_id"]

        # 重命名：基准版本过期时返回 409、stale_base 与当前版本
        rename_stale = client.post("/api/commands/project.rename", json={
            "command_id": str(uuid.uuid4()), "base_version": 999, "project_id": project_id, "name": "新名字"})
        assert rename_stale.status_code == 409
        assert rename_stale.json()["reason"] == "stale_base"
        assert rename_stale.json()["current_version"] == 1

        renamed = client.post("/api/commands/project.rename", json={
            "command_id": str(uuid.uuid4()), "base_version": 1, "project_id": project_id, "name": "新名字"})
        assert renamed.status_code == 200

        # 置顶
        pin_stale = client.post("/api/commands/project.pin", json={
            "command_id": str(uuid.uuid4()), "base_version": 1, "project_id": project_id, "pinned": True})
        assert pin_stale.status_code == 409 and pin_stale.json()["reason"] == "stale_base"
        assert pin_stale.json()["current_version"] == 2

        pinned = client.post("/api/commands/project.pin", json={
            "command_id": str(uuid.uuid4()), "base_version": 2, "project_id": project_id, "pinned": True})
        assert pinned.status_code == 200

        # 归档
        archived = client.post("/api/commands/project.archive", json={
            "command_id": str(uuid.uuid4()), "base_version": 3, "project_id": project_id})
        assert archived.status_code == 200

        # 归档后拒绝新建事项与记录原文，原因是 project_archived
        rejected_work = _post(client, "work_item.create", project_id=project_id, text="新事项")
        assert rejected_work.status_code == 409 and rejected_work.json()["reason"] == "project_archived"
        rejected_mat = _post(client, "material.record", project_id=project_id, text="材料")
        assert rejected_mat.status_code == 409 and rejected_mat.json()["reason"] == "project_archived"

        # 恢复
        restored = client.post("/api/commands/project.restore", json={
            "command_id": str(uuid.uuid4()), "base_version": 4, "project_id": project_id})
        assert restored.status_code == 200
        assert not opened.system.projects.projection(project_id).archived


def test_source_directory_save_and_project_settings(data_dir):
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        created = _post(client, "project.create", name="代码项目", goal="测试源目录")
        project_id = created.json()["refs"]["project_id"]

        # 初次登记源目录，基准版本为 0；基准版本不符时返回 stale_base 与当前版本 0
        stale = client.post("/api/commands/source_directory.save", json={
            "command_id": str(uuid.uuid4()), "base_version": 1, "project_id": project_id,
            "name": "src", "path": "C:/repo/src"})
        assert stale.status_code == 409 and stale.json()["reason"] == "stale_base"
        assert stale.json()["current_version"] == 0

        saved = client.post("/api/commands/source_directory.save", json={
            "command_id": str(uuid.uuid4()), "base_version": 0, "project_id": project_id,
            "name": "src", "path": "C:/repo/src"})
        assert saved.status_code == 200

        # 再次登记同一个名称，基准版本为 1
        again = client.post("/api/commands/source_directory.save", json={
            "command_id": str(uuid.uuid4()), "base_version": 0, "project_id": project_id,
            "name": "src", "path": "C:/repo/other"})
        assert again.status_code == 409 and again.json()["current_version"] == 1

        updated = client.post("/api/commands/source_directory.save", json={
            "command_id": str(uuid.uuid4()), "base_version": 1, "project_id": project_id,
            "name": "src", "path": "C:/repo/other"})
        assert updated.status_code == 200

        # project.settings 返回登记的源目录与版本
        settings = client.get(f"/api/queries/project.settings?project_id={project_id}")
        assert settings.status_code == 200
        directories = settings.json()["data"]["source_directories"]
        assert directories["src"] == {"name": "src", "path": "C:/repo/other", "version": 2, "writeback_enabled": False, "remote": "", "target_branch": "", "check_commands": [], "credential_ref": None}


def test_department_settings_save(data_dir):
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        created = _post(client, "project.create", name="设置项目", goal="验证设置")
        project_id = created.json()["refs"]["project_id"]

        # department_settings.save：基准版本是部门设置的版本，初次为 0
        prompt_stale = client.post("/api/commands/department_settings.save", json={
            "command_id": str(uuid.uuid4()), "base_version": 99, "project_id": project_id,
            "department": "product", "department_prompt": "产品原则"})
        assert prompt_stale.status_code == 409 and prompt_stale.json()["reason"] == "stale_base"
        assert prompt_stale.json()["current_version"] == 0

        prompt_ok = client.post("/api/commands/department_settings.save", json={
            "command_id": str(uuid.uuid4()), "base_version": 0, "project_id": project_id,
            "department": "product", "department_prompt": "产品原则"})
        assert prompt_ok.status_code == 200


def test_work_item_append_input_accepts_changed_version_and_deduplicates(data_dir):
    opened = _Opened(data_dir, adapter=FakeAdapter(_blocked_script()))
    with running_api(opened) as client:
        created = _post(client, "project.create", name="输入测试", goal="测试追加输入")
        project_id = created.json()["refs"]["project_id"]

        item_res = _post(client, "work_item.create", project_id=project_id, text="第一步需求")
        assert item_res.status_code == 200, item_res.text
        work_item_id = item_res.json()["refs"]["work_item_id"]
        run_id = item_res.json()["refs"]["run_id"]

        # 事项在执行：等待运行停在请求之前
        assert _wait_for(lambda: has_new_work(project_run(opened.store, run_id), "engineering"))

        # 事项在执行时新建事项被拒绝，原因 busy
        busy = _post(client, "work_item.create", project_id=project_id, text="第二个事项")
        assert busy.status_code == 409 and busy.json()["reason"] == "busy"

        # 追加需求：基准版本与当前不同也被接受，事件记录依据的版本
        command_id = str(uuid.uuid4())
        append_res = client.post("/api/commands/work_item.append_input", json={
            "command_id": command_id, "base_version": 999, "work_item_id": work_item_id, "text": "追加新说明"})
        assert append_res.status_code == 200, append_res.text

        # 同一 command_id 重试只产生一条输入
        repeat_res = client.post("/api/commands/work_item.append_input", json={
            "command_id": command_id, "base_version": 999, "work_item_id": work_item_id, "text": "追加新说明"})
        assert repeat_res.status_code == 200 and repeat_res.json()["duplicate"] is True

        inputs = [event for event in opened.store.list_events(run_id)
                  if event.type == EventType.USER_INPUT_RECEIVED]
        # 新建事项的初始输入写在 run_created 中；追加需求写入一条 user_input_received
        assert len(inputs) == 1
        assert inputs[0].payload["text"] == "追加新说明"
        assert inputs[0].payload["base_version"] == 999


def test_guidance_send_accepts_changed_version(data_dir):
    opened = _Opened(data_dir, adapter=FakeAdapter(_blocked_script()))
    with running_api(opened) as client:
        created = _post(client, "project.create", name="指导测试", goal="测试部门指导")
        project_id = created.json()["refs"]["project_id"]
        item_res = _post(client, "work_item.create", project_id=project_id, text="带指导的事项")
        work_item_id = item_res.json()["refs"]["work_item_id"]
        run_id = item_res.json()["refs"]["run_id"]
        assert _wait_for(lambda: has_new_work(project_run(opened.store, run_id), "engineering"))

        sent = client.post("/api/commands/guidance.send", json={
            "command_id": str(uuid.uuid4()), "base_version": 999, "work_item_id": work_item_id,
            "department": "product", "text": "先给出验收标准"})
        assert sent.status_code == 200, sent.text
        guidance = [event for event in opened.store.list_events(run_id)
                    if event.type == EventType.DEPARTMENT_GUIDANCE_RECEIVED]
        assert [event.payload["text"] for event in guidance] == ["先给出验收标准"]
        assert guidance[0].payload["base_version"] == 999


def test_work_item_cancel_stops_run_and_rejects_after_terminal(data_dir):
    opened = _Opened(data_dir, adapter=FakeAdapter(_blocked_script()))
    with running_api(opened) as client:
        created = _post(client, "project.create", name="取消测试", goal="测试取消事项")
        project_id = created.json()["refs"]["project_id"]
        item_res = _post(client, "work_item.create", project_id=project_id, text="要取消的事项")
        work_item_id = item_res.json()["refs"]["work_item_id"]
        run_id = item_res.json()["refs"]["run_id"]
        assert _wait_for(lambda: has_new_work(project_run(opened.store, run_id), "engineering"))

        cancel_res = client.post("/api/commands/work_item.cancel", json={
            "command_id": str(uuid.uuid4()), "base_version": 999, "work_item_id": work_item_id})
        assert cancel_res.status_code == 200, cancel_res.text
        projection = project_run(opened.store, run_id)
        assert (projection.status, projection.stop_reason) == ("failed", "cancelled")

        # 已终结的事项再次取消返回 run_terminal
        again = client.post("/api/commands/work_item.cancel", json={
            "command_id": str(uuid.uuid4()), "base_version": 999, "work_item_id": work_item_id})
        assert again.status_code == 409 and again.json()["reason"] == "run_terminal"


def test_work_item_execution_runs_in_loop_and_settles_on_completion(data_dir):
    opened = _Opened(data_dir, adapter=FakeAdapter(demo_script()))
    with running_api(opened) as client:
        created = _post(client, "project.create", name="完整执行", goal="验证自动结算")
        project_id = created.json()["refs"]["project_id"]
        item_res = _post(client, "work_item.create", project_id=project_id, text="构建 CLI 工具")
        assert item_res.status_code == 200, item_res.text
        run_id = item_res.json()["refs"]["run_id"]

        # 事项在接口进程的事件循环中作为任务运行；run 结束时由流程编排结算（采纳）
        assert _wait_for(lambda: any(
            event.type == ProjectEventType.DELIVERABLE_ADOPTED
            for event in opened.store.list_project_events(project_id)))
        adopted = [event for event in opened.store.list_project_events(project_id)
                   if event.type == ProjectEventType.DELIVERABLE_ADOPTED]
        assert len(adopted) == 1 and adopted[0].payload["run_id"] == run_id
        assert project_run(opened.store, run_id).status == "done"


def test_startup_settles_pending_and_query_does_not_settle(data_dir):
    # run 达到 DONE、进程在结算前退出；重启服务时由流程编排补做结算
    system = LoopSystem.for_testing(data_dir, FakeAdapter(demo_script()))
    project_id = system.projects.register("中断测试", "验证启动时补结算")
    work_item_id, run_id = system.projects.start_work_item(project_id, "构建 CLI 工具")
    system.run_until_stop(run_id)
    assert project_run(system.store, run_id).status == "done"
    before = [event.type for event in system.store.list_project_events(project_id)]
    assert ProjectEventType.DELIVERABLE_ADOPTED not in before
    system.close()

    opened = _Opened(data_dir, adapter=FakeAdapter([]))
    with running_api(opened) as client:
        # 启动时已经补做结算一次
        settled = [event.type for event in opened.store.list_project_events(project_id)]
        assert settled.count(ProjectEventType.DELIVERABLE_ADOPTED) == 1
        # 查询不结算：读取项目概览不追加事件
        position = opened.store.end_position()
        overview = client.get(f"/api/queries/project.overview?project_id={project_id}")
        assert overview.status_code == 200
        assert opened.store.end_position() == position


class _ChosenDepartments:
    # 真实目录文件与真实 .env：只有给定的部门选了模型；模型回答由测试内启动的本机服务按 Responses 协议给出。
    # 就绪检查这一段在假适配器下整段跳过，所以这里不用假适配器（工单 #1700）
    def __init__(self, tmp_path, base_url: str, *, departments: tuple[str, ...]) -> None:
        self.data_dir = tmp_path / "data"
        self.config = tmp_path / "providers.json"
        self.dotenv = tmp_path / ".env"
        self.base_url = base_url
        self.departments = departments
        self.applications: list[Application] = []

    def __call__(self) -> Application:
        document = {
            "providers": [catalog_provider("provider-a", self.base_url, "KEY_A")],
            "models": [catalog_model("model-a", "provider-a", "upstream-a")],
            "bindings": {department: {"provider_id": "provider-a", "model_id": "model-a"}
                         for department in self.departments},
        }
        self.config.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        self.dotenv.write_text("KEY_A=issue1700-key-a\n", encoding="utf-8")
        application = Application.open(self.data_dir, provider_config=self.config, dotenv=self.dotenv)
        self.applications.append(application)
        return application

    @property
    def system(self) -> LoopSystem:
        return self.applications[-1].system

    def admit(self) -> None:
        self.system.facade.record_admission("provider-a", "model-a", admitted_model="upstream-a")


def _wait_task(system, run_id: str) -> None:
    deadline = time.monotonic() + WAIT_FOR_HOST_WORK_SEC
    while time.monotonic() < deadline:
        task = system.orchestrator.work_item_execution(run_id)
        if task is None or task.done():
            return
        time.sleep(0.02)
    raise AssertionError(f"事项 {run_id} 没有停下来")


def _settle(client, system, refs: dict) -> None:
    # 让这个事项停在这里：还在进行时取消，已经结束就不再取消；随后等执行任务结束，留出执行槽位
    if project_run(system.store, refs["run_id"]).status not in ("done", "failed"):
        cancelled = _post(client, "work_item.cancel", base_version=0, work_item_id=refs["work_item_id"])
        assert cancelled.status_code == 200, cancelled.text
    _wait_task(system, refs["run_id"])


def test_readiness_for_a_new_work_item_only_checks_the_item_organization(tmp_path):
    # 工单 #1700（形态与核验角色设计说明「形态随事项冻结」）：新建事项前的模型就绪只看这件事项要冻结的那份
    # 组织里的职能。只给工程选了模型时，「工程」的项目能新建事项；默认形态的项目被拒绝，说明写明是哪个职能
    server, _capture, base_url = serve(lambda _body: (200, "text/event-stream", [stub_stream()]))
    try:
        opened = _ChosenDepartments(tmp_path, base_url, departments=("engineering",))
        with running_api(opened) as client:
            opened.admit()
            single = _post(client, "project.create", name="工程形态", goal="只给工程选模型",
                           form=SINGLE_ROLE_DIRECT)
            assert single.status_code == 200, single.text
            single_project = single.json()["refs"]["project_id"]
            started = _post(client, "work_item.create", project_id=single_project, text="工程的事项")
            assert started.status_code == 200, started.text
            _settle(client, opened.system, started.json()["refs"])

            default = _post(client, "project.create", name="默认形态", goal="三个职能都要模型")
            assert default.status_code == 200, default.text
            default_project = default.json()["refs"]["project_id"]
            rejected = _post(client, "work_item.create", project_id=default_project, text="默认形态的事项")
            assert rejected.status_code == 409, rejected.text
            assert rejected.json()["reason"] == "provider_unavailable"
            message = rejected.json()["message"]
            # 说明写明是哪个职能没有可用的模型，不只写「不可用」
            assert "产品" in message and "质检" in message, message
            assert "工程部门还没有选择模型" not in message, message

            # 新建事项时临时选「工程」：按工程这一份组织的职能核对，能开始
            temporary = _post(client, "work_item.create", project_id=default_project, text="临时选工程",
                              form=SINGLE_ROLE_DIRECT)
            assert temporary.status_code == 200, temporary.text
            _settle(client, opened.system, temporary.json()["refs"])
    finally:
        server.shutdown()
        server.server_close()
