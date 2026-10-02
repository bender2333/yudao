# 端到端测试使用的后端：真实运行的接口层、应用层与控制核心，模型回答由 FakeAdapter 脚本给出。
# 不是测试替身：事件日志、工件、工作区都是真实实现（工单 #79 的验收要求）。
#
# 两种用法：
#   1. python client/tests/e2e/backend.py --port 0：测试自己启动，端口由系统分配，
#      输出一行 JSON {"port": <端口>, "data_dir": <数据目录>}，标准输入关闭时退出。
#   2. python client/tests/e2e/backend.py api：作为 `yudao api` 命令运行（工单 #207）：
#      客户端在 PATH 中找到 yudao 命令以后启动 `yudao api`，本脚本收到 api 这个子命令，
#      监听默认端口，接受本机停止请求，收到以后进程退出。Provider 由 FakeAdapter 提供，
#      因此空的数据目录就能创建事项。
#
# 数据目录由 --data-dir 给出；不给出时用临时目录（fixture）或命令行的默认数据目录（api）。

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import threading
import uuid
from pathlib import Path

import uvicorn

# 让脚本可以导入仓库中的 harness（控制主机项目环境安装的就是它）
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from harness.adapters.base import ProviderError  # noqa: E402
from harness.adapters.fake import FakeAdapter  # noqa: E402
from harness.api.app import create_app  # noqa: E402
from harness.app.application import Application  # noqa: E402
from harness.app.project_commands import ProjectCreate  # noqa: E402
from harness.app.project_queries import ProjectsList  # noqa: E402
from harness.app.project_and_work_item_commands import WorkItemCreate  # noqa: E402
from harness.data_directory import default_data_dir  # noqa: E402
from harness.proposals import product_spec  # noqa: E402
from harness.runtime import LoopSystem  # noqa: E402

UNAVAILABLE = "Missing configuration: provider credential"


def script():
    # 一个事项：产品部门提交规格以后，工程部门的请求被提供方报告为不可用，
    # run 停在这次请求之前并发出 model_unavailable 的决定请求（供托盘与待你决定的验收）
    return [
        product_spec(),
        ProviderError(UNAVAILABLE, reason="provider_unavailable"),
    ]


async def seed(application: Application, system: LoopSystem) -> None:
    # 一个项目、一个事项：产品部门提交规格以后，工程部门的请求被提供方报告为不可用，run 停在这次
    # 请求之前并发出 model_unavailable 的决定请求。这个 run 没有进终态，system.status 的
    # running_runs 因此大于 0（工单 #207 的停止确认与「正在运行的事项」验收用它）。
    # 只有一个执行槽位（orchestrator 3.4A），预置一个事项就够；不再预置第二个避免执行槽位竞争
    created = await application.command(
        "project.create", ProjectCreate(command_id=str(uuid.uuid4()), name="示例项目", goal="实现一个回声工具"),
        actor="user:local")
    project_id = created.refs.project_id
    item = await application.command(
        "work_item.create", WorkItemCreate(command_id=str(uuid.uuid4()), project_id=project_id, text="实现回声工具"),
        actor="user:local")
    task = system.orchestrator.work_item_execution(item.refs.run_id)
    if task is not None:
        await task


class VersionedApplication(Application):
    # 让能力清单报告一个不同的接口版本：像一个接口版本不同的部署那样（不改动被测代码或接口层）
    reported_api_version: int | None = None

    def capabilities(self, contract_digest: str, *, access):
        capabilities = super().capabilities(contract_digest, access=access)
        if self.reported_api_version is not None:
            return capabilities.model_copy(
                update={"deployment": capabilities.deployment.model_copy(
                    update={"api_version": self.reported_api_version})})
        return capabilities


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--data-dir", default=None)
    # `yudao api --access lan --host 0.0.0.0`：客户端打开「允许局域网访问」时带的参数（工单 #207）。
    # 与真正的命令行一致：访问方式是启动参数，局域网监听任意地址，本机只监听回环
    parser.add_argument("--access", choices=("local", "lan"), default="local")
    parser.add_argument("--host", default="127.0.0.1")
    # 端到端测试核对「接口版本不同时只显示更新页」：让服务报告一个不同的接口版本，
    # 就像一个已经升级或尚未升级的部署那样（真实 HTTP 响应，不改动被测代码）
    parser.add_argument("--api-version", type=int, default=None)
    # api：以 `yudao api` 命令的方式运行（工单 #207）。命令行的替身把收到的参数原样交给本脚本，
    # 因此这里接到的子命令与真正的 yudao 命令一致；端口固定为客户端连接的本机端口，
    # 接受本机停止请求并在收到以后退出，与 harness.api.server 的行为一致
    parser.add_argument("mode", nargs="?", default="fixture", choices=("fixture", "api"))
    args = parser.parse_args()

    if args.mode == "api":
        # 作为 `yudao api` 运行：不带 --data-dir 时用命令行的默认数据目录（客户端只运行 yudao api，
        # 默认数据目录由 LOCALAPPDATA 算出，端到端测试把它指到自己的临时目录）
        data_dir = Path(args.data_dir) if args.data_dir else default_data_dir()
        # `yudao api` 的默认端口是 8765（客户端连接的本机地址），没有明确给端口时用它
        port = args.port if args.port else 8765
    else:
        import tempfile
        data_dir = Path(args.data_dir) if args.data_dir else Path(tempfile.mkdtemp(prefix="yudao-e2e-"))
        port = args.port
    system = LoopSystem.for_testing(data_dir, FakeAdapter(script()))
    application = VersionedApplication(system)
    if args.api_version is not None:
        application.reported_api_version = args.api_version

    # 本机停止请求：请求到达时让 uvicorn 优雅退出（harness/api/server.py 的 _request_stop）
    server = uvicorn.Server(uvicorn.Config(
        lambda: create_app(lambda: application, access=args.access,
                            on_stop=lambda: setattr(server, "should_exit", True)),
        host=args.host, port=port,
        log_level="warning", lifespan="on", timeout_graceful_shutdown=3.0))

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        if not thread.is_alive():
            raise RuntimeError("接口层在启动过程中结束")

    port = server.servers[0].sockets[0].getsockname()[1]
    if args.mode == "api":
        # 客户端按能力清单判断服务是否可用：先报就绪再预置事项（预置事项要跑几轮 FakeAdapter 的调用）
        print(json.dumps({"port": port, "data_dir": str(data_dir)}), flush=True)
        # 数据目录里已经有项目时不再预置：客户端「重新启动服务」会在同一个数据目录上再启动一次
        # （工单 #207 的验收），重复预置会让 work_item.create 被拒绝。真正的 `yudao api` 也不预置数据
        if not application.query("projects.list", ProjectsList(include_archived=True)).data.projects:
            asyncio.run(seed(application, system))
        # 进程一直服务到收到本机停止请求（数据目录的进程锁随退出释放）
        thread.join()
        return 0

    asyncio.run(seed(application, system))
    print(json.dumps({"port": port, "data_dir": str(data_dir)}), flush=True)
    # fixture 模式：标准输入关闭时退出（由 Playwright 的 fixture 控制生命周期）
    try:
        sys.stdin.read()
    except KeyboardInterrupt:
        pass
    finally:
        server.should_exit = True
        thread.join(10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
