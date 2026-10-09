# 访问令牌（应用层与接口层设计说明第 6.3 节）：真实运行局域网访问方式的接口，
# 经 HTTP 检查令牌要求、提出者、撤销后的即时失效与明文不出现的位置。
# 令牌文件与命令行都用真实的实现，不使用替身。

import socket
import uuid

import pytest

from harness.__main__ import main
from harness.adapters.fake import FakeAdapter
from harness.app.access_tokens import AccessTokenStore, TokenNameTaken, UnknownToken, digest
from harness.app.application import Application
from harness.models import utc_now
from harness.runtime import LoopSystem
from harness.tests.api_helpers import running_api


class _Opened:
    # 与 test_access.py 相同的打开方式：真实建立控制核心，模型回答由 FakeAdapter 给出
    def __init__(self, data_dir) -> None:
        self.data_dir = data_dir
        self.applications: list[Application] = []

    def __call__(self) -> Application:
        application = Application(LoopSystem.for_testing(self.data_dir, FakeAdapter([])))
        self.applications.append(application)
        return application


def _lan_address() -> str:
    for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
        address = info[4][0]
        if not address.startswith("127."):
            return address
    return "127.0.0.1"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _lan(opened, data_dir, **options):
    # 局域网访问方式的真实服务：监听本机所有地址，经局域网地址连接（第 6.2、6.3 节）
    return running_api(opened, access="lan", host="0.0.0.0", connect=_lan_address(),
                       data_dir=data_dir, **options)


def _pages(root):
    # 一份 Vite 构建结构的页面文件：入口页面
    root.mkdir()
    (root / "index.html").write_text("<!doctype html><title>Yudao</title>", encoding="utf-8")
    return root


def test_only_the_digest_of_a_token_is_kept(data_dir):
    # 服务只保存摘要、名称与时间：令牌本身不落盘，明文不出现在令牌文件里
    _entry, token = AccessTokenStore(data_dir).create("客厅的电脑", now=utc_now())
    written = (data_dir / "access-tokens.json").read_text(encoding="utf-8")
    assert token not in written
    assert digest(token) in written


def test_a_token_is_accepted_once_per_name_and_lists_its_time(data_dir):
    # 建立、列表与同名拒绝：列表给出名称与建立时间，令牌明文只在建立时显示一次
    store = AccessTokenStore(data_dir)
    assert store.list() == ()
    entry, token = store.create("客厅的电脑", now="2026-10-08T10:00:00+00:00")
    assert store.list() == (entry,)
    assert store.name_of(token) == "客厅的电脑"
    with pytest.raises(TokenNameTaken):
        store.create("客厅的电脑", now="2026-10-08T10:00:00+00:00")


def test_a_revoked_token_stops_working_at_once(data_dir):
    # 撤销以后立即失效；撤销后的名称可以重新建立，旧的令牌仍然无效
    store = AccessTokenStore(data_dir)
    _entry, token = store.create("客厅的电脑", now=utc_now())
    store.revoke("客厅的电脑", now="2026-10-08T11:00:00+00:00")
    assert store.name_of(token) is None
    assert store.list()[0].revoked_at == "2026-10-08T11:00:00+00:00"
    _second, token2 = store.create("客厅的电脑", now="2026-10-08T12:00:00+00:00")
    assert store.name_of(token2) == "客厅的电脑"
    assert store.name_of(token) is None
    with pytest.raises(UnknownToken):
        store.revoke("书房", now=utc_now())


def test_an_unknown_token_is_not_accepted(data_dir):
    # 明文与任何有效令牌都不匹配时拒绝：长度不同、内容不同都不通过
    store = AccessTokenStore(data_dir)
    _entry, token = store.create("客厅的电脑", now=utc_now())
    assert store.name_of("0" * 64) is None
    assert store.name_of(token[:-1]) is None


def test_the_command_line_creates_lists_and_revokes_tokens(tmp_path, capsys):
    # 命令行只在服务所在机器建立、列出与撤销令牌（第 6.3 节）：令牌明文只写一次，
    # 服务运行时也能撤销，因此不取数据目录的进程锁
    data_dir = tmp_path / "data"
    assert main(["token", "create", "--name", "客厅的电脑", "--data-dir", str(data_dir)]) == 0
    created = capsys.readouterr()
    token = created.out.strip()
    assert len(token) == 64
    assert token not in created.err

    assert main(["token", "list", "--data-dir", str(data_dir)]) == 0
    listed = capsys.readouterr().out.strip().split("\t")
    assert listed[0] == "客厅的电脑" and listed[2] == "有效" and listed[1] != ""

    assert main(["token", "create", "--name", "客厅的电脑", "--data-dir", str(data_dir)]) == 1
    assert "已经存在" in capsys.readouterr().err

    assert main(["token", "revoke", "客厅的电脑", "--data-dir", str(data_dir)]) == 0
    capsys.readouterr()
    assert main(["token", "list", "--data-dir", str(data_dir)]) == 0
    assert capsys.readouterr().out.strip().split("\t")[2] == "已撤销"
    assert main(["token", "revoke", "客厅的电脑", "--data-dir", str(data_dir)]) == 1
    assert "没有名为" in capsys.readouterr().err
    assert AccessTokenStore(data_dir).name_of(token) is None


def test_lan_access_requires_a_token_for_every_interface_path(data_dir, tmp_path):
    # 局域网访问方式：页面文件不需要令牌，其余全部路径（能力清单、OpenAPI、查询、命令、事件流）
    # 没有令牌都返回 401 且不附原因，无效令牌与格式不对的请求头同样被拒绝；有效令牌照常
    opened = _Opened(data_dir)
    _entry, token = AccessTokenStore(data_dir).create("客厅的电脑", now=utc_now())
    with _lan(opened, data_dir, pages=_pages(tmp_path / "pages")) as client:
        page = client.get("/")
        denied = {
            "capabilities": client.get("/api/capabilities"),
            "openapi": client.get("/openapi.json"),
            "query": client.get("/api/queries/system.status"),
            "command": client.post("/api/commands/project.create",
                                   json={"command_id": str(uuid.uuid4()), "name": "无令牌", "goal": "整理需求"}),
            "events": client.get("/api/events?after=999999"),
        }
        invalid = client.get("/api/queries/system.status", headers=_bearer("0" * 64))
        no_scheme = client.get("/api/queries/system.status", headers={"Authorization": token})
        allowed = client.get("/api/queries/system.status", headers=_bearer(token))
        openapi_allowed = client.get("/openapi.json", headers=_bearer(token))
    assert page.status_code == 200
    assert all(response.status_code == 401 and response.content == b"" for response in denied.values())
    assert invalid.status_code == 401 and invalid.content == b""
    assert no_scheme.status_code == 401
    assert allowed.status_code == 200
    assert openapi_allowed.status_code == 200


def test_local_access_needs_no_token(data_dir):
    # 本机访问方式不需要令牌，提出者保持 user:local（第 6.2 节）
    opened = _Opened(data_dir)
    AccessTokenStore(data_dir).create("客厅的电脑", now=utc_now())
    with running_api(opened, data_dir=data_dir) as client:
        status = client.get("/api/queries/system.status")
        accepted = client.post("/api/commands/project.create",
                               json={"command_id": str(uuid.uuid4()), "name": "本机项目", "goal": "整理需求"})
        events = opened.applications[0].system.store.list_project_events(
            accepted.json()["refs"]["project_id"])
    assert status.status_code == 200
    assert [event.actor for event in events] == ["user:local"]


def test_the_actor_is_the_token_name_and_the_token_stays_out_of_events(data_dir):
    # 提出者是 user:<令牌名称>；令牌明文不出现在事件与事件流的请求地址里（第 6.3 节）
    opened = _Opened(data_dir)
    _entry, token = AccessTokenStore(data_dir).create("客厅的电脑", now=utc_now())
    with _lan(opened, data_dir) as client:
        accepted = client.post("/api/commands/project.create",
                               json={"command_id": str(uuid.uuid4()), "name": "接入已有项目", "goal": "整理需求"},
                               headers=_bearer(token))
        stream = client.get("/api/events?after=999999", headers=_bearer(token))
        project_id = accepted.json()["refs"]["project_id"]
        events = opened.applications[0].system.store.list_project_events(project_id)
    assert accepted.status_code == 200
    assert [event.actor for event in events] == ["user:客厅的电脑"]
    # 令牌只经请求头送出，事件流的地址与事件内容里都没有它
    assert token not in str(stream.url)
    assert token not in str(events)
    assert "event: resync" in stream.text


def test_revoking_a_token_takes_effect_on_a_running_service(data_dir):
    # 撤销以后运行中的服务立即拒绝它：令牌文件由令牌目录改写，服务每次校验都重新读
    opened = _Opened(data_dir)
    _entry, token = AccessTokenStore(data_dir).create("客厅的电脑", now=utc_now())
    with _lan(opened, data_dir) as client:
        before = client.get("/api/queries/system.status", headers=_bearer(token))
        AccessTokenStore(data_dir).revoke("客厅的电脑", now=utc_now())
        after = client.get("/api/queries/system.status", headers=_bearer(token))
    assert before.status_code == 200
    assert after.status_code == 401 and after.content == b""