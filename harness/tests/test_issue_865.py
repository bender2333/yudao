# 工单 #865：保存部门设置时，内容与现值完全相同，服务端不再返回 500。
#
# 原因：部门设置的保存已经判断过「内容没有变化」（harness/projects.py），这时不追加任何事件；
# 命令被接受以后，接受结果里的提醒按这个命令追加的事件推导，原来直接取最后一条事件，
# 事件列表为空时抛 IndexError，接口层回 500。
#
# 用例真实启动 FastAPI 应用，经 HTTP 提交命令、读取查询：事件日志与目录文件都是真实实现。

import json
import uuid

from harness.app.application import Application
from harness.models import ProjectEventType
from harness.tests.api_helpers import running_api

SECRET = "catalog-secret-key-1"
REF = "CATALOG_KEY"
UPSTREAM_BASE = "http://127.0.0.1:9/v1"


def _provider(provider_id="p1"):
    return {"id": provider_id, "name": provider_id, "base_url": UPSTREAM_BASE,
            "credential_ref": REF, "timeout_sec": 20.0, "preset_id": "", "models_url": ""}


def _model(model_id="m1"):
    # 模型访问定义：输入方式只有文本，给质检部门用时缺图像输入（设计说明第 5.6 节）
    return {"id": model_id, "model": "model-x", "protocol": "responses",
            "context_window": 32000, "max_output_tokens": 2048}


class _Opened:
    # 服务生命周期中建立的应用层；目录文件与 .env 是真实文件，测试经它读取事件日志核对结果
    def __init__(self, tmp_path) -> None:
        self.data_dir = tmp_path / "data"
        self.config = tmp_path / "providers.json"
        self.dotenv = tmp_path / ".env"
        self.dotenv.write_text(f"{REF}={SECRET}\n", encoding="utf-8")
        self.config.write_text(json.dumps({
            "providers": [_provider()],
            "models": [{**_model(), "provider_id": "p1"}],
            "bindings": {},
        }), encoding="utf-8")
        self.applications: list[Application] = []

    def __call__(self) -> Application:
        application = Application.open(self.data_dir, provider_config=self.config, dotenv=self.dotenv)
        self.applications.append(application)
        return application

    @property
    def application(self) -> Application:
        return self.applications[-1]

    @property
    def store(self):
        return self.application.system.store


def _post(client, command, **body):
    return client.post(f"/api/commands/{command}", json={"command_id": str(uuid.uuid4()), **body})


def _settings_events(store, project_id):
    return [event for event in store.list_project_events(project_id)
            if event.type == ProjectEventType.DEPARTMENT_SETTINGS_CONFIGURED]


def _department_setting(client, project_id, department):
    response = client.get(f"/api/queries/project.settings?project_id={project_id}")
    assert response.status_code == 200, response.text
    return response.json()["data"]["departments"][department]


def test_saving_unchanged_department_settings_is_accepted(tmp_path):
    opened = _Opened(tmp_path)
    with running_api(opened) as client:
        created = _post(client, "project.create", name="设置项目", goal="验证没有改动的保存")
        assert created.status_code == 200, created.text
        project_id = created.json()["refs"]["project_id"]

        # 第一次保存：写入部门 Prompt，版本变成 1
        first = _post(client, "department_settings.save", base_version=0, project_id=project_id,
                      department="product", department_prompt="产品原则")
        assert first.status_code == 200, first.text
        assert first.json()["refs"]["reminders"] == []
        assert _department_setting(client, project_id, "product")["version"] == 1

        # 内容与现值完全相同：按「没有改动」接受，不再返回 500（工单 #865）
        same = _post(client, "department_settings.save", base_version=1, project_id=project_id,
                     department="product", department_prompt="产品原则")
        assert same.status_code == 200, same.text
        assert same.json()["refs"]["reminders"] == []
        assert same.json()["duplicate"] is False

        # 设置没有变化：版本不变，事件流里也没有多出一条
        assert _department_setting(client, project_id, "product")["version"] == 1
        assert len(_settings_events(opened.store, project_id)) == 1

        # 同一个命令身份再提交一次（内容相同）：仍然接受，标记为重复
        command_id = str(uuid.uuid4())
        body = {"command_id": command_id, "base_version": 1, "project_id": project_id,
                "department": "product", "department_prompt": "产品原则"}
        again = client.post("/api/commands/department_settings.save", json=body)
        assert again.status_code == 200, again.text
        repeat = client.post("/api/commands/department_settings.save", json=body)
        assert repeat.status_code == 200, repeat.text
        assert repeat.json()["duplicate"] is True
        assert repeat.json()["refs"]["reminders"] == []
        assert len(_settings_events(opened.store, project_id)) == 1

        # 内容有变化时照常保存：版本加一，接受结果里带回这次算出的建议能力提醒
        opened.application.system.facade.record_admission("p1", "m1", admitted_model="model-x")
        changed = _post(client, "department_settings.save", base_version=0, project_id=project_id,
                        department="quality", provider_id="p1", model_id="m1")
        assert changed.status_code == 200, changed.text
        reminders = changed.json()["refs"]["reminders"]
        assert len(reminders) == 1 and "图像输入" in reminders[0], reminders
        assert _department_setting(client, project_id, "quality")["version"] == 1
        assert len(_settings_events(opened.store, project_id)) == 2
