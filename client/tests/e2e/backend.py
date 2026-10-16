# 端到端测试使用的后端：真实运行的接口层、应用层与控制核心，模型回答由 FakeAdapter 脚本给出。
# 不是测试替身：事件日志、工件、工作区都是真实实现（工单 #79 的验收要求）。
#
# 用法：python client/tests/e2e/backend.py --port 0：测试自己启动，端口由系统分配，
# 输出一行 JSON {"port": <端口>, "data_dir": <数据目录>}，标准输入关闭时退出。
# 服务同时提供构建好的页面文件 client/out/renderer（npm run build:pages 的产物），
# 端到端测试用 Chromium 从服务地址打开页面。
#
# 数据目录由 --data-dir 给出；不给出时用临时目录。

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
import socket
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
from harness.app.access_tokens import AccessTokenStore  # noqa: E402
from harness.app.application import Application  # noqa: E402
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
from harness.models import Usage, json_dumps, utc_now  # noqa: E402
from harness.proposals import (  # noqa: E402
    baseline_review_turn, collaboration_request, delivery_turn, product_spec, response_turn,
    review_turn, structure_turn,
)
from harness.providers.call import ModelResponse  # noqa: E402
from harness.runtime import LoopSystem  # noqa: E402
from harness.tests.protocol_helpers import (  # noqa: E402
    chat_responder, messages_responder, preset_base_urls, responses_responder, serve,
)

UNAVAILABLE = "Missing configuration: provider credential"

# 路径守卫的端到端验收（工单 #354）：交付改动的这个路径落在运行实例的内核清单里
KERNEL_PATH = "harness/bounds.py"


def lan_address() -> str:
    # 本机的局域网地址：从另一台机器访问控制主机时用的就是它；没有时用回环
    for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
        address = info[4][0]
        if not address.startswith("127."):
            return address
    return "127.0.0.1"


def script():
    # 第一个事项：正常走完一轮三部门（产品 → 工程 → 质检放行），供项目列表与看板显示
    return [
        product_spec(),
        delivery_turn(),
        review_turn("release", "checks passed on the current snapshot"),
        # 第二个项目（交付历史）：一轮包含询问与回答、返工、放行与采纳的运行，
        # 供首页与概览的时间轴核对交接、返工、询问与回答、采纳都有关键事实（工单 #180 的验收）
        product_spec(),
        delivery_turn(),
        # 工程向产品提出询问，产品回答（collaboration_requested / collaboration_responded）
        collaboration_request("product", "How should unknown flags be handled?",
                              background="Engineering is preparing its independent delivery.",
                              expected_result="Explain the intended behavior without changing files."),
        response_turn("answered", "Print the argument as defined in the current requirement."),
        # 质检向工程提出询问，工程回答（工单 #415）：quality→engineering 因此有「咨询」与
        # 「问题反馈」两种非返工流转，与「返工」一起构成同一对部门上的三种流转
        collaboration_request("engineering", "Which acceptance line governs the rework?",
                             background="Quality is preparing its verdict on the current delivery.",
                             expected_result="Name the acceptance line to follow."),
        response_turn("answered", "Follow the acceptance line recorded in the requirement."),
        # 质检退回工程（qa_submitted 的结论为 rework_engineering，返工）
        review_turn("rework_engineering", "Missing usage text when no argument is provided.",
                    defects=[{"severity": "major", "summary": "no usage text on empty argv"}]),
        delivery_turn("added usage text"),
        # 放行（qa_submitted 的结论为 release），随后由项目采纳（deliverable_adopted）
        review_turn("release", "checks passed on the current snapshot"),
        # 第三个项目：产品提交规格以后，工程部门的请求被提供方报告为不可用，
        # run 停在这次请求之前并发出 model_unavailable 的决定请求（供顶栏待你决定的验收）
        FakeTurn(proposal=product_spec(), usage=Usage(input_tokens=100, output_tokens=20)),
        ProviderError(UNAVAILABLE, reason="provider_unavailable"),
        # 回答「继续执行」以后再次遇到不可用：发出第二个决定请求，供新的决定请求到达的验收
        ProviderError(UNAVAILABLE, reason="provider_unavailable"),
        # 再次回答「继续执行」以后走完剩下的三部门：端到端测试核对一个事项的全过程随事件流完成
        delivery_turn(),
        review_turn("release", "checks passed on the current snapshot"),
        # 第四个项目：预置时没有事项。执行槽位空出来以后，端到端测试在界面上提交需求并开始事项，
        # 这四轮让第二个事项的全过程也在浏览器里随事件流走完
        product_spec(),
        delivery_turn(),
        review_turn("release", "checks passed on the current snapshot"),
    ]


def initial_script():
    # 起始文件夹的端到端验收（工单 #323）：产品先列出工作区里的文件、再读一个起点文件夹里的文件，
    # 然后走完一轮三部门。工作区由起始文件夹的快照建成，这两次读取的输出因此在部门工作间的
    # 「动作与回执」与事件详情里给出起点文件夹里的文件。
    return [
        read_turn("list-initial", "list_files", {}),
        read_turn("read-initial", "read_file", {"path": "README.md"}),
        product_spec(),
        delivery_turn(),
        review_turn("release", "checks passed on the current snapshot"),
    ]

def room_script():
    # 部门房间的端到端验收（工单 #177）：产品的模型请求分三段流式返回，每段之间停顿；
    # 之后产品向工程发出一次询问（工程收到并回答），再走完交付与质检放行。端到端测试在请求
    # 进行中打开产品房间核对思考气泡，在交接与询问发生时核对两端的小人各说一句。
    from harness.providers.call import ModelDelta, ModelResponse, ModelStreamEvent
    from harness.adapters.fake import pending_request_id
    from harness.models import json_dumps

    def answer_turn(request_id_from_call):
        # 收到询问的一方：把回答作为 submit_response 交回
        def turn(call):
            request_id = request_id_from_call(call) if callable(request_id_from_call) else request_id_from_call
            identity = f"call-{call.activation_id}-{call.step_id}-answer"
            return ModelResponse(output=[{
                "id": identity, "call_id": identity, "type": "function_call", "name": "submit_response",
                "arguments": json_dumps({"request_id": request_id, "status": "answered",
                                         "text": "按需求里的验收条件实现即可", "result_event_ids": []}),
            }])
        return turn

    def product_stream(call):
        # 一个轮次：分三段返回流式输出。每段是一条解码后的流事件（kind="stream_event"），带 output 通道
        # 的片段（offset 为该段在通道中的起始字数），与真正的协议实现一致：attempt.live 的文字来自这些
        # 片段，事件日志里不写入片段本身；调用进行中由步骤驱动写入 model_stream_progress。
        # 片段之间的停顿由 FakeAdapter 的 stream_gap_sec 给出，让订阅方在请求进行中读到 attempt.live
        from harness.providers.call import ModelDelta
        offset = 0
        for sequence, text in enumerate(("正在阅读需求", "正在整理验收条件", "正在写出 PRD 的要点")):
            yield ModelStreamEvent(kind="stream_event", id=f"stream-{sequence}",
                                   payload={"type": "response.output_text.delta", "delta": text,
                                            "output_index": 0, "content_index": 0,
                                            "sequence_number": sequence},
                                   text=text, sequence=sequence, stage="output", source="provider_sdk",
                                   deltas=(ModelDelta(channel="output", offset=offset, text=text),))
            offset += len(text)
        return product_spec()

    return [
        # 预置的已完成事项：走完一轮，给项目留下一个已完成的事项，部门工作间默认选中它时房间照常渲染
        product_spec(),
        delivery_turn(),
        review_turn("release", "checks passed on the current snapshot"),
        # 端到端测试开始的事项：产品分三段流式请求（思考气泡），工程向质检发出一次询问
        # （传信的两端），质检回答，工程交付（交接的两端）、质检放行
        product_stream,
        # 工单 #319 第 3 项：工程先列出工作区里的文件再直接交付，房间事件流里因此有 tool_started
        # （工具类说明「现在看看有什么文件」）。盖章类的 spec_accepted、qa_started
        # 与 qa_submitted 由这一轮本身产生
        read_turn("list-workspace", "list_files", {}),
        collaboration_request("quality", "交付前需要确认哪一条验收条件"),
        answer_turn(pending_request_id),
        delivery_turn(),
        review_turn("release", "checks passed on the current snapshot"),
    ]


def onboarding_script():
    # 接入已有项目的建档脚本（工单 #137、#138）：每轮产品写出初始 PRD、工程给出结构说明、质检核验基线；
    # 三个部门各先调一次读取工具，让部门房间的「阅读已有项目」动作在事件流里真实出现。
    # 六轮供接入、重新开始建档各走一遍以外，还够一次「提出修改」的往返（第 138 号工单）
    return [turn for index in range(6) for turn in _onboarding_round(index)]


def _onboarding_round(index: int):
    requirement = f"read the project layout at step {index}"
    return [
        read_turn(f"read-{index}", "read_file", {"path": "README.md"}),
        FakeTurn(proposal=product_spec(requirements=[requirement], acceptance=["the README names the command to run"])),
        read_turn(f"search-{index}", "search", {"pattern": "print"}),
        structure_turn(requirement_locations=[{"requirement": requirement, "locations": ["src/echo.py"]}]),
        read_turn(f"range-{index}", "read_range", {"path": "src/echo.py", "start_line": 1, "end_line": 2}),
        baseline_review_turn(conclusions=[{"requirement": requirement, "status": "verified", "evidence": "smoke"}]),
    ]


def waiting_script():
    # 等待模型服务的端到端验收（工单 #375）：工程部门的第一次请求模型服务不可用，按 D17 重试
    # （model_retry_scheduled，页面据此发出「等待模型服务」的系统通知），重试这一次仍然不可用且
    # 不再重试：run 进入待恢复并发出 model_unavailable 的决定请求（页面据此发出决定请求的系统通知）
    # 这个脚本不预置项目与事项：用例在页面打开以后自己建项目并开始事项，让事件在页面开着的时候发生
    return [
        product_spec(),
        ProviderError(UNAVAILABLE, reason="provider_unavailable", retryable=True),
        ProviderError(UNAVAILABLE, reason="provider_unavailable"),
    ]


def kernel_script():
    # 路径守卫的端到端验收（工单 #354）：预置的事项交付改动了内核清单里的路径，结算因此不采纳，
    # 发出内核修改决定请求；用例在界面上核对卡片给出改动的路径与差异，批准以后交付被采纳。
    return [
        product_spec(),
        delivery_turn(summary="implemented echo CLI", files={"src/echo.py": "import sys\nprint(sys.argv[1])\n",
                                                             KERNEL_PATH: "# 交付改动的内核文件\n"}),
        review_turn("release", "checks passed on the current snapshot"),
    ]


def read_turn(identity: str, tool: str, arguments: dict):
    # 脚本里的一项可以是接收模型调用合同的函数（harness/adapters/fake.py 的 TurnFactory），
    # 函数返回带工具调用的回答；工具由原生循环真实执行
    return lambda call: ModelResponse(output=[{"id": identity, "call_id": identity, "type": "function_call",
                                               "name": tool, "arguments": json_dumps(arguments)}])


def source_directory(root: Path) -> Path:
    # 一份最小的已有项目：源目录必须是真实目录，接入命令会真的采集它的代码快照
    (root / "src").mkdir(parents=True)
    (root / "src" / "echo.py").write_text("import sys\nprint(sys.argv[1])\n", encoding="utf-8")
    (root / "README.md").write_text("# Echo\n\nPrint the given argument.\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_echo.py").write_text("def test_placeholder():\n    assert True\n", encoding="utf-8")
    return root


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

async def seed_onboarding(application: Application) -> None:
    # 建档脚本的预置（工单 #332）：只建一个空项目，不跑事项。建档轮次全部留给接入已有项目用：
    # 接入的建档 run 要走过产品、工程与质检共六次模型调用，重新开始建档再来六次，
    # 大屏用例再一轮；预置事项消耗这些轮次会让接入的建档 run 在第一次模型请求就耗尽脚本
    await application.command(
        "project.create", ProjectCreate(command_id=str(uuid.uuid4()), name="预置项目", goal="接入前的空项目"),
        actor="user:local")

async def seed_kernel(application: Application, system: LoopSystem) -> None:
    # 路径守卫的预置（工单 #354）：一个项目、一个改动内核清单路径的事项，跑完以后结算发出决定请求
    created = await application.command(
        "project.create", ProjectCreate(command_id=str(uuid.uuid4()), name="内核改动", goal="改动一个内核文件"),
        actor="user:local")
    project_id = created.refs.project_id
    item = await application.command(
        "work_item.create", WorkItemCreate(command_id=str(uuid.uuid4()), project_id=project_id, text="改动内核文件"),
        actor="user:local")
    task = system.orchestrator.work_item_execution(item.refs.run_id)
    if task is not None:
        await task

async def seed_room(application: Application, system: LoopSystem) -> str:
    # 部门房间的端到端验收（工单 #177）：建一个项目并跑完第一个事项（让部门工作间有默认选中的事项，
    # 房间照常渲染）。端到端测试随后打开房间，再经命令开始第二个事项：命令在接口进程的事件循环里
    # 启动这个 run，产品的模型请求因此在房间打开期间分三段流式返回。返回项目标识。
    created = await application.command(
        "project.create", ProjectCreate(command_id=str(uuid.uuid4()), name="房间项目", goal="观察部门房间"),
        actor="user:local")
    project_id = created.refs.project_id
    # 项目设置页与交付检查需要真实的行：登记一条 `smoke` 命令（delivery_turn 的检查要用）
    await accept(application, "command_registration.save", CommandRegistrationSave(
        command_id=str(uuid.uuid4()), project_id=project_id, name="smoke",
        argv=["python", "-c", "raise SystemExit(0)"], args=[], timeout_sec=30, output_limit=4096, base_version=0))
    item = await application.command(
        "work_item.create", WorkItemCreate(command_id=str(uuid.uuid4()), project_id=project_id, text="预置的已完成事项"),
        actor="user:local")
    task = system.orchestrator.work_item_execution(item.refs.run_id)
    if task is not None:
        await task
    return project_id

async def accept(application: Application, name: str, request) -> None:
    # 预置数据必须是真实被服务端接受的结果：被拒绝时立即失败，不在客户端一侧兜底
    result = await application.command(name, request, actor="user:local")
    if not isinstance(result, Accepted):
        raise AssertionError(f"预置 {name} 被拒绝：{result.reason} {result.message}")


def rejecting_responder(body: dict):
    # 真实返回 HTTP 401 的上游：模型测试据此显示未通过与原因（工单 #294）
    return 401, "application/json", [
        json.dumps({"error": {"message": "invalid api key", "type": "authentication_error"}}).encode("utf-8"),
    ]


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
                       *, admit_and_bind: bool = False, reject_base: str | None = None) -> None:
    # 界面上的候选、连接测试与模型测试都发真实请求，不使用测试替身
    revision = application.system.facade.catalog_revision()
    saved = await application.command("catalog.connection.save", CatalogConnectionSave(
        command_id=str(uuid.uuid4()),
        base_version=revision,
        provider=ProviderInput(
            id="opencode-go", name="OpenCode Go",
            base_url=f"{upstream_base}/v1", credential_ref="OPENCODE_GO_KEY",
            timeout_sec=30, preset_id="opencode-go", models_url=models_url,
        ),
        models=[ModelInput(
            id="glm-4.6", model="glm-4.6", protocol="responses",
            context_window=200000, max_output_tokens=32000,
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
    # 一条指向「拒绝凭据」上游的连接：模型管理页的模型测试在它上面真实失败，
    # 用来核对失败的结果写在模型行里（工单 #294）。默认不预置，避免影响其他用例的统计
    if reject_base is not None:
        rejected = await application.command("catalog.connection.save", CatalogConnectionSave(
            command_id=str(uuid.uuid4()),
            base_version=application.system.facade.catalog_revision(),
            provider=ProviderInput(
                id="rejected-go", name="拒绝的上游",
                base_url=f"{reject_base}/v1", credential_ref="REJECTED_GO_KEY",
                timeout_sec=30, models_url=models_url,
            ),
            models=[ModelInput(
                id="glm-rejected", model="glm-rejected", protocol="responses",
                context_window=200000, max_output_tokens=32000,
                capability_source="能力表", capacity_confirmed=True, input_modalities=["text"],
            )],
        ), actor="user:local")
        if isinstance(rejected, Rejected):
            raise RuntimeError(f"catalog seed rejected connection: {rejected.reason} {rejected.message}")
    # 给这条定义写准入记录并让部门默认绑定它（工单 #94）
    if not admit_and_bind:
        return
    facade.record_admission("opencode-go", "glm-4.6", admitted_model="glm-4.6")
    await accept(application, "catalog.department_defaults.save", CatalogDepartmentDefaultsSave(
        command_id=str(uuid.uuid4()), base_version=facade.catalog_revision(),
        bindings={department: BindingInput(provider_id="opencode-go", model_id="glm-4.6", requested_tier=None)
                  for department in ("product", "engineering", "quality")}))


async def clear_department_defaults(application: Application, keep: str) -> None:
    # 工单 #319 第 6 项：预置的事项跑完之后，把 --bind-departments 没有列出的部门解开。
    # 用例随后在界面上开始新事项，核对缺少部门默认时的中文提示与两个去处
    wanted = {item for item in keep.split(",") if item}
    facade = application.system.facade
    await accept(application, "catalog.department_defaults.save", CatalogDepartmentDefaultsSave(
        command_id=str(uuid.uuid4()), base_version=facade.catalog_revision(),
        bindings={department: BindingInput(provider_id="opencode-go", model_id="glm-4.6", requested_tier=None)
                  for department in wanted}))


class VersionedApplication(Application):
    # 让能力清单报告一个不同的接口版本或发布版本：像一个接口版本不同的部署、或刚升级完的服务那样
    # （不改动被测代码或接口层）。reported_release_once 只在第一次被读取时生效，
    # 用来模拟「页面连接的是一个刚升级的服务，随后读到的是同一个版本」
    reported_api_version: int | None = None
    reported_release: str | None = None
    reported_release_once: str | None = None

    def capabilities(self, contract_digest: str, *, access):
        capabilities = super().capabilities(contract_digest, access=access)
        deployment = capabilities.deployment
        if self.reported_api_version is not None:
            deployment = deployment.model_copy(update={"api_version": self.reported_api_version})
        if self.reported_release is not None:
            deployment = deployment.model_copy(update={"version": self.reported_release})
        if self.reported_release_once is not None:
            deployment = deployment.model_copy(update={"version": self.reported_release_once})
            self.reported_release_once = None
        if deployment is capabilities.deployment:
            return capabilities
        return capabilities.model_copy(update={"deployment": deployment})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--data-dir", default=None)
    # 端到端测试核对「接口版本不同」的提示：让服务报告一个不同的接口版本，
    # 就像一个已经升级或尚未升级的部署那样（真实 HTTP 响应，不改动被测代码）
    parser.add_argument("--api-version", type=int, default=None)
    # 页面与服务同出一个发布（网页界面的提供与发布设计说明第 5.1 节）：让服务报告一个与页面构建时不同的
    # 发布版本，页面据此自动重新加载，就像升级以后服务重启而浏览器里还是上一次的页面文件
    parser.add_argument("--release-version", default=None)
    # 只在第一次读取能力清单时报告这个版本：页面重新加载以后读到的是服务自己的版本，
    # 一次自动重新加载因此是可观察的（一直报告不同版本会让页面反复重新加载）
    parser.add_argument("--release-version-once", default=None)
    # 部门房间的端到端验收（工单 #177）：用流式慢模型跑一个项目，供房间在请求进行中观察
    parser.add_argument("--room", action="store_true")
    # 预置时给定义写准入并让三个部门默认绑定它：作废准入与删除引用方的用例需要真实的引用方（工单 #94）
    parser.add_argument("--admit-and-bind", action="store_true")
    # 工单 #319 第 6 项：只给这些部门默认绑定模型，其余部门保持「未设置」，
    # 用例据此核对缺少部门默认时新事项被拒绝的提示与去处。给空串表示一个部门都不绑定
    parser.add_argument("--bind-departments", default="product,engineering,quality")
    # 按工厂装配系统（工单 #319 第 6 项）：就绪检查走目录里的部门默认，
    # 目录缺哪个部门就在界面上被拒绝哪个部门；模型回答仍由同一份 FakeAdapter 脚本给出
    parser.add_argument("--catalog-driven", action="store_true")
    # 脚本选择：默认是项目列表与看板用的预置脚本；onboarding 是接入已有项目用的建档脚本（工单 #137）；
    # initial 是从想法新建带起始文件夹用的脚本（工单 #323）；waiting 是等待模型服务用的脚本（工单 #375，
    # 前一次请求按 D17 重试、后一次凭据无效进入待恢复）。它们需要的轮次与预置事项不同，因此由用例选择
    parser.add_argument("--script", choices=("default", "onboarding", "initial", "waiting", "kernel"),
                        default="default")
    # 预置一条指向「拒绝凭据」上游的连接：模型测试在它上面真实失败，
    # 用例核对失败的结果写在模型行里（工单 #294）。默认不预置，避免影响其他用例的统计
    parser.add_argument("--reject-upstream", action="store_true")
    # 局域网访问方式（工单 #348）：给出令牌名称时以局域网访问方式起服务，并在数据目录里建立一个
    # 访问令牌，把令牌明文报给测试，测试在页面上填写它
    parser.add_argument("--token-name", default=None)
    args = parser.parse_args()

    import tempfile

    # 测试内启动的真实 HTTP 上游：三种协议的推理服务与模型列表服务（工单 #93）。
    # 目录里的连接带服务方案，请求基址按访问定义的协议取自预置表（ADR-0033），
    # 因此每种协议各起一个上游，端到端的请求按协议打到不同的本机服务。
    # 「yudao api」模式不预置目录数据，但上游仍然要起：fixture 与 api 两种模式共用同一个
    # 收尾清理，api 模式的上游只在没有用例连接时空转
    upstream, _capture, upstream_base = serve(responses_responder)
    chat_upstream, _chat_capture, chat_base = serve(chat_responder)
    messages_upstream, _messages_capture, messages_base = serve(messages_responder)
    # 第二个上游：始终返回 HTTP 401，让模型测试真实失败（工单 #294）
    reject_upstream = None
    reject_base = None
    if args.reject_upstream:
        reject_upstream, _reject_capture, reject_base = serve(rejecting_responder)
    models_server = ModelsServer({"data": [
        {"id": "glm-4.6", "limit": {"context": 200000, "output": 32000}},
        {"id": "vision-model", "limit": {"context": 128000, "output": 16000}},
        # 上游模型 ID 带「/」的候选（工单 #302 走查里真实遇到的写法）：上游只给窗口不给输出上限，
        # 端到端据此核对预填的访问定义 ID 是合法写法、缺一项容量时不显示「容量已确认」
        {"id": "cbcn/deepseek-v4.1-flash", "limit": {"context": 128000}},
    ]})
    # 目录里的连接带服务方案，请求基址按访问定义的协议取自预置表（ADR-0033）：三种协议的基址
    # 分别指向各自的本机上游，端到端的真实请求打到测试内的服务。ExitStack 留在变量里，
    # 重定向在本进程内一直有效
    preset_redirect = contextlib.ExitStack()
    preset_redirect.enter_context(preset_base_urls(
        {"responses": f"{upstream_base}/v1", "chat_completions": f"{chat_base}/v1",
         "messages": f"{messages_base}/v1"}, models_url=models_server.base))
    data_dir = Path(args.data_dir) if args.data_dir else Path(tempfile.mkdtemp(prefix="yudao-e2e-"))
    port = args.port
    if args.room:
        adapter_script = room_script()
    elif args.script == "onboarding":
        adapter_script = onboarding_script()
    elif args.script == "initial":
        adapter_script = initial_script()
    elif args.script == "waiting":
        adapter_script = waiting_script()
    elif args.script == "kernel":
        adapter_script = kernel_script()
    else:
        adapter_script = script()
    if args.catalog_driven:
        # 工单 #319 第 6 项：用例要在界面上核对「缺少部门默认」的真实拒绝。
        # 就绪检查只按目录里的部门默认判断（LoopSystem.provider_status），单适配器方式直接返回
        # FakeAdapter 的可用性，因此这个模式按工厂装配：模型回答仍来自同一份脚本，目录缺哪个部门就拒绝哪个。
        # 工厂给出同一个适配器实例：每次新建会把脚本的读取位置重置到开头
        adapter = FakeAdapter(adapter_script)
        system = LoopSystem(data_dir, test_adapter_factory=lambda _department: adapter)
    else:
        system = LoopSystem.for_testing(data_dir, FakeAdapter(adapter_script, stream_gap_sec=2.5 if args.room else 0.0))
    application = VersionedApplication(system)
    if args.api_version is not None:
        application.reported_api_version = args.api_version
    if args.release_version is not None:
        application.reported_release = args.release_version
    if args.release_version_once is not None:
        application.reported_release_once = args.release_version_once

    # 页面文件来自 client/out/renderer（npm run build:pages）：页面与接口同一来源
    pages = Path(__file__).resolve().parents[2] / "out" / "renderer"
    # 局域网访问方式（工单 #348）：监听本机所有地址并按数据目录里的令牌文件校验访问令牌，
    # 令牌由 --token-name 建立后把明文报给测试，测试在页面中填写它
    access = "lan" if args.token_name is not None else "local"
    host = "0.0.0.0" if access == "lan" else "127.0.0.1"
    token = (AccessTokenStore(data_dir).create(args.token_name, now=utc_now())[1]
             if args.token_name is not None else None)
    server = uvicorn.Server(uvicorn.Config(
        lambda: create_app(lambda: application, pages=pages, access=access,
                           tokens=AccessTokenStore(data_dir)),
        host=host, port=port,
        log_level="warning", lifespan="on", timeout_graceful_shutdown=3.0))

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        if not thread.is_alive():
            raise RuntimeError("接口层在启动过程中结束")

    # 接入已有项目与起始文件夹都需要一个真实的目录：起服务前建好目录，把路径一并报给测试，
    # 测试在对话框里填这个路径走完整的流程（工单 #137、#323）
    source_dir = source_directory(Path(tempfile.mkdtemp(prefix="yudao-e2e-source-"))) if args.script in ("onboarding", "initial") else None

    # 先建示例项目与决定请求，再保存一份指向测试内上游的目录（工单 #93）。
    # 数据目录里已经有项目时不再预置（服务恢复的用例在同一个数据目录上再起一次服务），
    # 重复预置会让 work_item.create 被拒绝
    already_seeded = bool(application.query("projects.list", ProjectsList(include_archived=True)).data.projects)
    room_project = None
    # 工单 #319 第 6 项：catalog_driven 模式先用三个部门都绑定好的目录跑完预置，
    # 再把 --bind-departments 里没有的部门解开。预置的事项本身需要模型可用，
    # 用例要核对的是预置之后新事项被拒绝的那一步
    if args.catalog_driven:
        # catalog_driven 模式的就绪检查按目录里的部门默认走真实路径，目录里的连接需要凭据；
        # 预置的模型测试自己清掉了凭据，这里按界面上补凭据的做法再设一次，
        # 预置跑完以后用例要核对缺少部门默认时的拒绝，不涉及凭据
        os.environ["OPENCODE_GO_KEY"] = "seed-only-key"
        asyncio.run(seed_catalog(application, upstream_base, models_server.base,
                                 admit_and_bind=True, reject_base=reject_base))
    if not already_seeded:
        if args.room:
            room_project = asyncio.run(seed_room(application, system))
        elif args.script == "onboarding":
            asyncio.run(seed_onboarding(application))
        elif args.script == "kernel":
            asyncio.run(seed_kernel(application, system))
        elif args.script not in ("initial", "waiting"):
            # 起始文件夹的用例（工单 #323）与等待模型服务的用例（工单 #375）自己在界面上建项目并开始事项，
            # 不需要预置的项目与事项
            asyncio.run(seed(application, system))
    if args.catalog_driven:
        os.environ.pop("OPENCODE_GO_KEY", None)
        asyncio.run(clear_department_defaults(application, args.bind_departments))
    else:
        asyncio.run(seed_catalog(application, upstream_base, models_server.base,
                                 admit_and_bind=args.admit_and_bind, reject_base=reject_base))

    port = server.servers[0].sockets[0].getsockname()[1]
    # 局域网访问方式下把局域网地址与令牌明文一并报给测试（工单 #348）：
    # 测试经局域网地址打开页面，填写这个令牌
    print(json.dumps({"port": port, "data_dir": str(data_dir), "room_project": room_project,
                      "source_dir": None if source_dir is None else str(source_dir),
                      "access": access, "address": None if token is None else f"http://{lan_address()}:{port}",
                      "token": token}), flush=True)
    # 标准输入关闭时退出（由 Playwright 的 fixture 控制生命周期）
    try:
        sys.stdin.read()
    except KeyboardInterrupt:
        pass
    finally:
        server.should_exit = True
        thread.join(10)
        upstream.shutdown()
        upstream.server_close()
        chat_upstream.shutdown()
        chat_upstream.server_close()
        messages_upstream.shutdown()
        messages_upstream.server_close()
        if reject_upstream is not None:
            reject_upstream.shutdown()
            reject_upstream.server_close()
        models_server.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
