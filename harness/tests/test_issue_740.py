# 工单 #740：服务端按 422 拒绝一条命令时，响应体里带一句中文说明。
#
# 早先只有 pydantic 的字段错误明细（机器看），页面上拿不到一句能看懂的话，
# 于是页面上只多出一个空的错误框（用户使用记录 U89）。这一张核对三件事：
# 字段错误明细没有变（机器读的那一份仍然是原来的样子）、中文说明写明了是哪个字段与要求是什么、
# 说明里不出现字段路径与英文机器短语。

import uuid

from harness.adapters.fake import FakeAdapter
from harness.app.application import DEFAULT_REGISTRY, Application
from harness.app.contracts import API_VERSION
from harness.app.registry import Registry
from harness.runtime import LoopSystem
from harness.tests.api_helpers import running_api


class _Opened:
    # 服务生命周期中建立的应用层
    def __init__(self, data_dir, registry: Registry = DEFAULT_REGISTRY) -> None:
        self.data_dir = data_dir
        self.registry = registry
        self.applications: list[Application] = []

    def __call__(self) -> Application:
        application = Application(LoopSystem.for_testing(self.data_dir, FakeAdapter([])), registry=self.registry)
        self.applications.append(application)
        return application


def _post(client, name, body):
    return client.post(f"/api/commands/{name}", json={"command_id": str(uuid.uuid4()), **body})


def test_an_empty_department_prompt_is_refused_with_a_readable_chinese_note(data_dir):
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        response = _post(client, "department_settings.save", {
            "base_version": 0, "project_id": "proj_1", "department": "quality", "department_prompt": "",
        })
        assert response.status_code == 422, response.text
        body = response.json()
        # 机器读的那一份没有变：字段错误明细仍在，字段位置仍在里面
        assert body["detail"], body
        assert body["detail"][0]["loc"] == ["body", "department_prompt"]
        # 页面看的那一份：一句中文，写明是哪个字段、要求是什么
        note = body["error"]
        assert note == "这次请求被拒绝：「部门 Prompt」不能为空，请修改以后再提交。", note
        # 说明里不出现字段路径与英文机器短语
        assert "department_prompt" not in note
        assert "string_too_short" not in note
        assert "String should have" not in note
        assert opened.applications[-1].system.store.end_position() == 0


def test_an_empty_goal_is_refused_with_the_field_it_names(data_dir):
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        response = _post(client, "project.create", {"name": "文本工具", "goal": ""})
        assert response.status_code == 422, response.text
        note = response.json()["error"]
        assert note == "这次请求被拒绝：「长期目标」不能为空，请修改以后再提交。", note
        assert "goal" not in note


def test_a_blank_field_and_an_unknown_field_are_both_refused_with_a_readable_note(data_dir):
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        # 只有空白的文字：合同的空白检查拒绝它
        blank = _post(client, "project.create", {"name": "  ", "goal": "目标"})
        assert blank.status_code == 422, blank.text
        assert "不能只有空白字符" in blank.json()["error"], blank.json()["error"]
        # 合同以外的字段：服务端不认识的字段不写字段名，只写「多填了一项」
        unknown = _post(client, "project.create", {"name": "文本工具", "goal": "目标", "owner": "someone"})
        assert unknown.status_code == 422, unknown.text
        note = unknown.json()["error"]
        assert "多填了一项服务端不认识的填写内容" in note, note
        assert "owner" not in note


def test_a_rejected_command_still_answers_409_with_the_reason_and_its_message(data_dir):
    # 应用层的拒绝不受这一处影响：409 的响应体仍然是 Rejected
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        created = _post(client, "project.create", {"name": "文本工具", "goal": "目标"})
        assert created.status_code == 200, created.text
        project_id = created.json()["refs"]["project_id"]
        stale = _post(client, "project.rename", {"base_version": 0, "project_id": project_id, "name": "新名字"})
        assert stale.status_code == 409, stale.text
        assert stale.json()["reason"] == "stale_base"
        assert stale.json()["message"]


def test_the_capability_list_still_reports_the_same_interface_version(data_dir):
    # 这一处只改 422 的响应体，接口版本不变
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        assert client.get("/api/capabilities").json()["deployment"]["api_version"] == API_VERSION
