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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import uvicorn

# 让脚本可以导入仓库中的 harness（控制主机项目环境安装的就是它）
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from harness.adapters.base import ProviderError  # noqa: E402
from harness.adapters.fake import FakeAdapter, FakeTurn  # noqa: E402
from harness.api.app import create_app  # noqa: E402
from harness.app.application import Application  # noqa: E402
from harness.app.client_update import ReleaseAssets  # noqa: E402
from harness.app.catalog_commands import (  # noqa: E402
    BindingInput, CatalogConnectionSave, CatalogDepartmentDefaultsSave, ModelInput, ProviderInput,
)
from harness.app.contracts import Accepted, Rejected  # noqa: E402
from harness.app.project_commands import ProjectCreate  # noqa: E402
from harness.app.project_and_work_item_commands import (  # noqa: E402
    CommandRegistrationSave,
    DepartmentSettingsSave,
    MaterialRecord,
    WorkItemCreate,
)
from harness.app.project_queries import ProjectsList  # noqa: E402
from harness.data_directory import default_data_dir  # noqa: E402
from harness.models import Usage  # noqa: E402
from harness.proposals import collaboration_request, delivery_turn, plan_turn, product_spec, response_turn, review_turn  # noqa: E402
from harness.runtime import LoopSystem  # noqa: E402
from harness.tests.protocol_helpers import responses_responder, serve  # noqa: E402

UNAVAILABLE = "Missing configuration: provider credential"


def script():
    # 第一个事项：正常走完一轮三部门（产品 → 工程 → 质检放行），供项目列表与看板显示
    return [
        product_spec(),
        plan_turn(),
        delivery_turn(),
        review_turn("release", "checks passed on the current snapshot"),
        # 第二个项目（交付历史）：一轮包含询问与回答、返工、放行与采纳的运行，
        # 供首页与概览的时间轴核对交接、返工、询问与回答、采纳都有关键事实（工单 #180 的验收）
        product_spec(),
        plan_turn(),
        delivery_turn(),
        # 工程向产品提出询问，产品回答（collaboration_requested / collaboration_responded）
        collaboration_request("product", "How should unknown flags be handled?",
                              background="Engineering is preparing its independent delivery.",
                              expected_result="Explain the intended behavior without changing files."),
        response_turn("answered", "Print the argument as defined in the current requirement."),
        # 质检退回工程（qa_submitted 的结论为 rework_engineering，返工）
        review_turn("rework_engineering", "Missing usage text when no argument is provided.",
                    defects=[{"severity": "major", "summary": "no usage text on empty argv"}]),
        plan_turn(reason="Address the quality review by adding the missing usage behavior"),
        delivery_turn("added usage text"),
        # 放行（qa_submitted 的结论为 release），随后由项目采纳（deliverable_adopted）
        review_turn("release", "checks passed on the current snapshot"),
        # 第三个项目：产品提交规格以后，工程部门的请求被提供方报告为不可用，
        # run 停在这次请求之前并发出 model_unavailable 的决定请求（供托盘与待你决定的验收）
        FakeTurn(proposal=product_spec(), usage=Usage(input_tokens=100, output_tokens=20)),
        ProviderError(UNAVAILABLE, reason="provider_unavailable"),
        # 回答「继续执行」以后再次遇到不可用：发出第二个决定请求，供「窗口关闭后有新的决定请求」的验收
        ProviderError(UNAVAILABLE, reason="provider_unavailable"),
        # 再次回答「继续执行」以后走完剩下的三部门：端到端测试核对一个事项的全过程随事件流完成
        plan_turn(),
        delivery_turn(),
        review_turn("release", "checks passed on the current snapshot"),
        # 第四个项目：预置时没有事项。执行槽位空出来以后，端到端测试在界面上提交需求并开始事项，
        # 这四轮让第二个事项的全过程也在浏览器里随事件流走完
        product_spec(),
        plan_turn(),
        delivery_turn(),
        review_turn("release", "checks passed on the current snapshot"),
    ]


async def seed(application: Application, system: LoopSystem) -> None:
    # 四个项目：第一个走完一轮三部门（供项目列表与看板）；第二个（交付历史）走完一轮包含询问与回答、
    # 返工、放行与采纳（供时间轴与回放，工单 #180）；第三个的事项停在模型不可用，留下一个等待回答的
    # 决定请求，run 没有进终态，system.status 的 running_runs 因此大于 0（工单 #207 的停止确认与
    # 「正在运行的事项」验收用它）；第四个只建档，端到端测试在界面上提交需求开始事项。
    # 执行槽位一次一个事项，因此每个项目的事项在当前事项结算以后再建
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
    # 第二个项目（交付历史）：走完一轮包含询问与回答、返工、放行与采纳的事项（工单 #180 的时间轴与回放）
    created = await application.command(
        "project.create", ProjectCreate(command_id=str(uuid.uuid4()), name="交付历史", goal="回放关键事实"),
        actor="user:local")
    history_project = created.refs.project_id
    item = await application.command(
        "work_item.create", WorkItemCreate(command_id=str(uuid.uuid4()), project_id=history_project, text="实现交付历史"),
        actor="user:local")
    task = system.orchestrator.work_item_execution(item.refs.run_id)
    if task is not None:
        await task
    # 第三个项目：第二个事项停在模型不可用，留下一个等待回答的决定请求
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
    # 第四个项目：只建档、不建事项。端到端测试在界面上提交需求开始事项，
    # 由事件流把第二个事项的全过程（产品 → 工程 → 质检 → 采纳）走完
    await application.command(
        "project.create", ProjectCreate(command_id=str(uuid.uuid4()), name="实时项目", goal="在界面上走完一个事项"),
        actor="user:local")

async def accept(application: Application, name: str, request) -> None:
    # 预置数据必须是真实被服务端接受的结果：被拒绝时立即失败，不在客户端一侧兜底
    result = await application.command(name, request, actor="user:local")
    if not isinstance(result, Accepted):
        raise AssertionError(f"预置 {name} 被拒绝：{result.reason} {result.message}")


class ModelsServer:
    # 测试内启动的真实 HTTP 模型列表服务：GET /v1/models 返回 JSON，供候选采集与连接测试使用
    def __init__(self, payload):
        self.payload = payload
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                return

            def do_GET(self):
                body = json.dumps(server.payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}/v1/models"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

async def seed_catalog(application: Application, upstream_base: str, models_url: str,
                       *, admit_and_bind: bool = False) -> None:
    # 界面上的候选、连接测试与模型测试都发真实请求，不使用测试替身
    revision = application.system.facade.catalog_revision()
    saved = await application.command("catalog.connection.save", CatalogConnectionSave(
        command_id=str(uuid.uuid4()),
        base_version=revision,
        provider=ProviderInput(
            id="opencode-go", name="OpenCode Go", protocol="responses",
            base_url=f"{upstream_base}/v1", credential_ref="OPENCODE_GO_KEY",
            timeout_sec=30, preset_id="opencode-go", models_url=models_url,
        ),
        models=[ModelInput(
            id="glm-4.6", model="glm-4.6", context_window=200000, max_output_tokens=32000,
            capability_source="能力表", capacity_confirmed=True,
            accepts_required_tool_call=True, input_modalities=["text"],
            reasoning_levels=["low", "high"], default_reasoning_level="low", reasoning_mode="effort",
        )],
    ), actor="user:local")
    if isinstance(saved, Rejected):
        raise RuntimeError(f"catalog seed rejected: {saved.reason} {saved.message}")
    # 预置这个模型为已准入：部门设置弹窗的模型下拉只列出已准入定义，
    # 因此要有一条真实通过模型测试的候选（工单 #95 的验收）。测试的真实请求走同一条凭据与上游路径，
    # 这里在服务开始服务之前直接调用 Provider 模块的入口，等同于界面上的一次模型测试。
    # 准入记录与凭据来源分开保存：测试完成以后清除内存里的 Key，让界面从「凭据缺失」开始，
    # 需要凭据的用例自己按界面或命令设置（模型管理页的用例核对缺失状态）
    facade = application.system.facade
    facade.set_credential("OPENCODE_GO_KEY", "seed-only-key", persist=False)
    result = await asyncio.to_thread(facade.model_test, "opencode-go", "glm-4.6")
    if not result.get("ok"):
        raise RuntimeError(f"catalog model test rejected: {result.get('error')} {result.get('message')}")
    facade.clear_credential_override("OPENCODE_GO_KEY")
    if not admit_and_bind:
        return
    # 给这条定义写准入记录并让三个部门默认都绑定它：作废准入与删除引用方两类用例需要真实的引用方
    facade.record_admission("opencode-go", "glm-4.6", admitted_model="glm-4.6")
    await accept(application, "catalog.department_defaults.save", CatalogDepartmentDefaultsSave(
        command_id=str(uuid.uuid4()), base_version=facade.catalog_revision(),
        bindings={department: BindingInput(provider_id="opencode-go", model_id="glm-4.6", requested_tier=None)
                  for department in ("product", "engineering", "quality")}))


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
    # 更新源（设计说明第 5.1 节，工单 #208）：把发布资源目录指到这里，服务从它提供
    # /client-update/latest.yml 与安装程序。不给出时用 wheel 内的 harness/release_assets，
    # 从源码运行没有这个目录，请求返回 404（更新页的「控制主机没有提供客户端安装包」）
    parser.add_argument("--release-assets", default=None)
    # api：以 `yudao api` 命令的方式运行（工单 #207）。命令行的替身把收到的参数原样交给本脚本，
    # 因此这里接到的子命令与真正的 yudao 命令一致；端口固定为客户端连接的本机端口，
    # 接受本机停止请求并在收到以后退出，与 harness.api.server 的行为一致
    parser.add_argument("mode", nargs="?", default="fixture", choices=("fixture", "api"))
    # 预置时给定义写准入并让三个部门默认绑定它：作废准入与删除引用方的用例需要真实的引用方（工单 #94）
    parser.add_argument("--admit-and-bind", action="store_true")
    args = parser.parse_args()

    import tempfile

    # 测试内启动的真实 HTTP 上游：Responses 协议的最小推理服务与模型列表服务（工单 #93）。
    # 「yudao api」模式不预置目录数据，但上游仍然要起：fixture 与 api 两种模式共用同一个
    # 收尾清理，api 模式的上游只在没有用例连接时空转
    upstream, _capture, upstream_base = serve(responses_responder)
    models_server = ModelsServer({"data": [
        {"id": "glm-4.6", "limit": {"context": 200000, "output": 32000}},
        {"id": "vision-model", "limit": {"context": 128000, "output": 16000}},
    ]})
    if args.mode == "api":
        # 作为 `yudao api` 运行：不带 --data-dir 时用命令行的默认数据目录（客户端只运行 yudao api，
        # 默认数据目录由 LOCALAPPDATA 算出，端到端测试把它指到自己的临时目录）
        data_dir = Path(args.data_dir) if args.data_dir else default_data_dir()
        # `yudao api` 的默认端口是 8765（客户端连接的本机地址），没有明确给端口时用它
        port = args.port if args.port else 8765
    else:
        data_dir = Path(args.data_dir) if args.data_dir else Path(tempfile.mkdtemp(prefix="yudao-e2e-"))
        port = args.port
    system = LoopSystem.for_testing(data_dir, FakeAdapter(script()))
    application = VersionedApplication(system)
    if args.api_version is not None:
        application.reported_api_version = args.api_version

    # 本机停止请求：请求到达时让 uvicorn 优雅退出（harness/api/server.py 的 _request_stop）
    assets = ReleaseAssets(Path(args.release_assets)) if args.release_assets else ReleaseAssets()
    server = uvicorn.Server(uvicorn.Config(
        lambda: create_app(lambda: application, access=args.access,
                            on_stop=lambda: setattr(server, "should_exit", True),
                            release_assets=assets),
        host=args.host, port=port,
        log_level="warning", lifespan="on", timeout_graceful_shutdown=3.0))

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        if not thread.is_alive():
            raise RuntimeError("接口层在启动过程中结束")

    # 先建示例项目与决定请求，再保存一份指向测试内上游的目录（工单 #93）。
    # 数据目录里已经有项目时不再预置：客户端「重新启动服务」会在同一个数据目录上再启动一次
    # （工单 #207 的验收），重复预置会让 work_item.create 被拒绝。真正的 `yudao api` 也不预置数据
    already_seeded = bool(application.query("projects.list", ProjectsList(include_archived=True)).data.projects)
    if not already_seeded:
        asyncio.run(seed(application, system))
    asyncio.run(seed_catalog(application, upstream_base, models_server.base,
                             admit_and_bind=args.admit_and_bind))

    port = server.servers[0].sockets[0].getsockname()[1]
    print(json.dumps({"port": port, "data_dir": str(data_dir)}), flush=True)
    if args.mode == "api":
        # 进程一直服务到收到本机停止请求（数据目录的进程锁随退出释放）
        thread.join()
        return 0

    # fixture 模式：标准输入关闭时退出（由 Playwright 的 fixture 控制生命周期）
    try:
        sys.stdin.read()
    except KeyboardInterrupt:
        pass
    finally:
        server.should_exit = True
        thread.join(10)
        upstream.shutdown()
        upstream.server_close()
        models_server.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
