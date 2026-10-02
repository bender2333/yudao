# 端到端测试使用的后端：真实运行的接口层、应用层与控制核心，模型回答由 FakeAdapter 脚本给出。
# 不是测试替身：事件日志、工件、工作区都是真实实现（工单 #79 的验收要求）。
#
# 用法：python client/tests/e2e/backend.py --port 0
# 输出一行 JSON：{"port": <端口>, "data_dir": <数据目录>}
# 进程收到 SIGTERM 或标准输入关闭时退出。

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
from harness.adapters.fake import FakeAdapter, FakeTurn  # noqa: E402
from harness.api.app import create_app  # noqa: E402
from harness.app.application import Application  # noqa: E402
from harness.app.contracts import Accepted  # noqa: E402
from harness.app.project_commands import ProjectCreate  # noqa: E402
from harness.app.project_and_work_item_commands import (  # noqa: E402
    CommandRegistrationSave,
    DepartmentSettingsSave,
    MaterialRecord,
    WorkItemCreate,
)
from harness.models import Usage  # noqa: E402
from harness.proposals import delivery_turn, plan_turn, product_spec, review_turn  # noqa: E402
from harness.runtime import LoopSystem  # noqa: E402

UNAVAILABLE = "Missing configuration: provider credential"


def script():
    # 第一个事项：正常走完一轮三部门（产品 → 工程 → 质检放行），供项目列表与看板显示
    return [
        product_spec(),
        plan_turn(),
        delivery_turn(),
        review_turn("release", "checks passed on the current snapshot"),
        # 第二个项目：产品提交规格以后，工程部门的请求被提供方报告为不可用，
        # run 停在这次请求之前并发出 model_unavailable 的决定请求（供托盘与待你决定的验收）
        FakeTurn(proposal=product_spec(), usage=Usage(input_tokens=100, output_tokens=20)),
        ProviderError(UNAVAILABLE, reason="provider_unavailable"),
        # 回答「继续执行」以后再次遇到不可用：发出第二个决定请求，供「窗口关闭后有新的决定请求」的验收
        ProviderError(UNAVAILABLE, reason="provider_unavailable"),
        # 再次回答「继续执行」以后走完剩下的三部门：端到端测试核对一个事项的全过程随事件流完成
        plan_turn(),
        delivery_turn(),
        review_turn("release", "checks passed on the current snapshot"),
        # 第三个项目：预置时没有事项。执行槽位空出来以后，端到端测试在界面上提交需求并开始事项，
        # 这四轮让第二个事项的全过程也在浏览器里随事件流走完
        product_spec(),
        plan_turn(),
        delivery_turn(),
        review_turn("release", "checks passed on the current snapshot"),
    ]


async def seed(application: Application, system: LoopSystem) -> None:
    created = await application.command(
        "project.create", ProjectCreate(command_id=str(uuid.uuid4()), name="示例项目", goal="实现一个回声工具"),
        actor="user:local")
    project_id = created.refs.project_id
    # 项目设置页需要真实的行：登记一条命令、写入一个部门 Prompt、记录一条项目材料
    await accept(application, "command_registration.save", CommandRegistrationSave(
        command_id=str(uuid.uuid4()), project_id=project_id, name="smoke",
        argv=["python", "-c", "raise SystemExit(0)"], args=["--verbose"],
        timeout_sec=30, output_limit=4096, base_version=0))
    await accept(application, "department_settings.save", DepartmentSettingsSave(
        command_id=str(uuid.uuid4()), project_id=project_id, department="product",
        department_prompt="产品部门先写目标与验收标准，范围以外的要求先问用户。", base_version=0))
    await accept(application, "material.record", MaterialRecord(
        command_id=str(uuid.uuid4()), project_id=project_id,
        text="回声工具要能在终端里逐行回显输入。", department="product"))
    item = await application.command(
        "work_item.create", WorkItemCreate(command_id=str(uuid.uuid4()), project_id=project_id, text="实现回声工具"),
        actor="user:local")
    task = system.orchestrator.work_item_execution(item.refs.run_id)
    if task is not None:
        await task
    # 第二个项目：第二个事项停在模型不可用，留下一个等待回答的决定请求
    created = await application.command(
        "project.create", ProjectCreate(command_id=str(uuid.uuid4()), name="文本工具", goal="逐行处理文本"),
        actor="user:local")
    blocked_project = created.refs.project_id
    item = await application.command(
        "work_item.create", WorkItemCreate(command_id=str(uuid.uuid4()), project_id=blocked_project, text="实现逐行处理"),
        actor="user:local")
    task = system.orchestrator.work_item_execution(item.refs.run_id)
    if task is not None:
        await task
    # 第三个项目：只建档、不建事项。端到端测试在界面上提交需求开始事项，
    # 由事件流把第二个事项的全过程（产品 → 工程 → 质检 → 采纳）走完
    await application.command(
        "project.create", ProjectCreate(command_id=str(uuid.uuid4()), name="实时项目", goal="在界面上走完一个事项"),
        actor="user:local")


async def accept(application: Application, name: str, request) -> None:
    # 预置数据必须是真实被服务端接受的结果：被拒绝时立即失败，不在客户端一侧兜底
    result = await application.command(name, request, actor="user:local")
    if not isinstance(result, Accepted):
        raise AssertionError(f"预置 {name} 被拒绝：{result.reason} {result.message}")


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
    # 端到端测试核对「接口版本不同时只显示更新页」：让服务报告一个不同的接口版本，
    # 就像一个已经升级或尚未升级的部署那样（真实 HTTP 响应，不改动被测代码）
    parser.add_argument("--api-version", type=int, default=None)
    args = parser.parse_args()

    import tempfile

    data_dir = Path(args.data_dir) if args.data_dir else Path(tempfile.mkdtemp(prefix="yudao-e2e-"))
    system = LoopSystem.for_testing(data_dir, FakeAdapter(script()))
    application = VersionedApplication(system)
    if args.api_version is not None:
        application.reported_api_version = args.api_version

    api = create_app(lambda: application, access="local")

    config = uvicorn.Config(api, host="127.0.0.1", port=args.port, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        if not thread.is_alive():
            raise RuntimeError("接口层在启动过程中结束")

    asyncio.run(seed(application, system))

    port = server.servers[0].sockets[0].getsockname()[1]
    print(json.dumps({"port": port, "data_dir": str(data_dir)}), flush=True)

    # 标准输入关闭时退出（由 Playwright 的 fixture 控制生命周期）
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
