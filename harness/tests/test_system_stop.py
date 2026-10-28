# 服务的停止方式与 system.status 的字段（设计说明第 4.2、4.4 节）。
# 删除桌面客户端以后（网页界面的提供与发布设计说明第 4.2 节），停止服务就是结束这个进程（Ctrl+C）；POST /api/system/stop 不再存在，
# 接口层没有这条路由，请求应当返回 404。system.status 仍然报告发布版本号与运行中的 run。
#
# 测试使用真实的 uvicorn 服务（running_server）。

from pathlib import Path

import httpx

from harness.app.application import Application
from harness.runtime import LoopSystem
from harness.tests.api_helpers import running_server
from harness.adapters.fake import FakeAdapter

def _open(data_dir: Path):
    return Application(LoopSystem.for_testing(data_dir, FakeAdapter([])))


def test_stop_endpoint_returns_404(tmp_path):
    # 桌面客户端删除以后，POST /api/system/stop 不再存在：服务发来的请求得到 404
    data_dir = tmp_path / "data"
    with running_server(lambda: _open(data_dir)) as handle:
        response = handle.client.post("/api/system/stop")
        assert response.status_code == 404


def loopback_status(client: httpx.Client) -> dict:
    response = client.get("/api/queries/system.status")
    assert response.status_code == 200
    return response.json()


def test_system_status_carries_the_release_version_and_running_runs(tmp_path):
    # system.status 报告服务进程的发布版本号与运行中的 run 数；版本号取自 wheel 元数据，
    # 运行的是源码时为 "0+unknown"，运行的是已安装的 wheel 时为发布号
    data_dir = tmp_path / "status"
    with running_server(lambda: _open(data_dir)) as handle:
        data = loopback_status(handle.client)["data"]
        assert data["version"], "release version should be reported"
        assert data["running_runs"] == 0
