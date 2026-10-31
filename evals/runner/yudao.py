"""Yudao 运行器：只经 HTTP 接口驱动 Yudao，只从导出的事件日志观察它。

评测场景设计第 7 节：运行器只把起点与公开部分交给被测方；不导入 `harness` 的任何
模块，同一套工具因此可以评测不同版本的 Yudao。凭据只从环境变量读（被测模型的地址
与 Key 在用户环境变量 `YUDAO_EVAL_BASE_URL`、`YUDAO_EVAL_API_KEY` 中），不写进代码、
事件、日志与提交。

一次运行：新建每次运行独立的起点文件夹（只含题目提供的数据文件）、建立项目并把它作为
起始文件夹交给被测的 Yudao、三个部门的项目部门设置使用被测模型、运行器不登记命令、
以用户原始意图提交需求原文加接口约定、等待结束；到时间上限时经 `work_item.cancel`
结束并标记超时；运行结束以后经 `run.export` 导出事件日志，取最后一次封存的交付交给
评分器，并在导出的事件日志中查找材料目录的路径（找到时这次运行作废）。
"""

import base64
import contextlib
import importlib.util
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import material_integrity
import model_service

# 一次评测运行的场景（评测场景设计第 2 节）：场景 3 从较长的 PRD 新建项目，场景 2 接入已有仓库。
# 入口按 `--scenario` 设一次；测试用 `scenario()` 临时切换，结束后恢复
SCENARIO_2 = "scenario-2"
SCENARIO_3 = "scenario-3"
SCENARIOS = (SCENARIO_2, SCENARIO_3)
SCENARIO = SCENARIO_3

# 场景 3 的运行模型在三个部门都使用同一条连接与同一个访问定义（评测场景设计第 3 节）
PROVIDER_ID = "yudao-eval"
MODEL_DEFINITION_ID = "yudao-eval-model"
PROTOCOL = "chat_completions"
# 场景 3 交给 Yudao 的起点：只有题目提供的数据文件（第 3 节「输入」）
START_FILES = ("subway_data.json",)
# 场景 2 的起点是检出好的上游仓库，经 `project.onboard` 接入；建档的那个事项的种类（接入已有项目设计说明第 3.3 节）
ONBOARDING_SOURCE_NAME = "upstream"
INITIAL_PRD_KIND = "initial_prd"
CONFIRM_OPTION = "confirm"
TERMINAL_STATUSES = ("done", "paused", "failed")
# 建档事项还在执行、或者在等用户确认初始 PRD 时的状态（接入已有项目设计说明第 3.4 节）
ONBOARDING_RUNNING_STATUSES = ("in_progress", "not_started", "awaiting_initial_prd")
# 目录文档里的模型 id 与被测模型名是同一个字符串，按 #88 由用户提供的模型决定
POLL_INTERVAL_SECONDS = 3.0
STARTUP_TIMEOUT_SECONDS = 180.0


def set_scenario(name):
    """切换当前场景：入口按 `--scenario` 设一次，测试用 `scenario()` 临时切换。"""
    global SCENARIO
    if name not in SCENARIOS:
        raise ValueError("unknown scenario: " + str(name))
    SCENARIO = name
    return SCENARIO


@contextlib.contextmanager
def scenario(name):
    """在指定场景下运行一段代码，结束后恢复原来的场景（一次运行与测试都用它）。"""
    previous = SCENARIO
    set_scenario(name)
    try:
        yield name
    finally:
        set_scenario(previous)


_SCENARIO_MODULES = {}


def scenario_module():
    """当前场景的运行器专用部分：材料目录、评分输入与上游仓库地址由它给出。

    两边的运行器共用同一个 `scenarioN` 模块（评测场景设计第 7 节），场景 2 与场景 3
    的评分输入与上游地址都在里面。按文件路径加载：场景 2 的运行器模块与评分器的模块
    同名（`runner/scenario2.py` 与 `scorer/scenario2.py`），同一个进程里先导入的那个
    会占住 `scenario2` 这个名字，按模块名查找会拿到评分器。
    """
    if SCENARIO not in _SCENARIO_MODULES:
        name = SCENARIO.replace("-", "")
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name + ".py")
        spec = importlib.util.spec_from_file_location("yudao_" + name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _SCENARIO_MODULES[SCENARIO] = module
    return _SCENARIO_MODULES[SCENARIO]


def material_version():
    """当前场景的材料版本（材料 manifest 的 `material_version`，第 6 节）。"""
    with open(os.path.join(materials_dir(), "manifest.json"), encoding="utf-8") as handle:
        return json.load(handle).get("material_version")


def scenario_base():
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                                        "scenarios", SCENARIO))


def materials_dir():
    return os.path.join(scenario_base(), "materials")


def start_dir():
    return os.path.join(materials_dir(), "start", "files")


def fresh_start_dir(runs_root, run_id):
    """每次运行新建的起点文件夹：只含题目提供的数据文件，放在运行目录之外。

    运行目录是这次运行的数据目录（`data_dir_for`），起点文件夹与它并列；仓库内的路径
    与已经存在的文件夹都拒绝，与数据目录同一条规矩（第 3 节「隔离」）。
    """
    path = os.path.abspath(os.path.join(runs_root, run_id, "start"))
    repo_root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    if _is_inside(path, repo_root):
        raise ValueError("Yudao starting folder must be outside the Yudao repository: " + path)
    if os.path.exists(path):
        raise ValueError("Yudao starting folder already exists: " + path)
    os.makedirs(path)
    for name in START_FILES:
        shutil.copy2(os.path.join(start_dir(), name), os.path.join(path, name))
    return path


def hidden_dirs():
    """隐藏部分：运行目录与事件日志里不能出现的材料目录。"""
    base = os.path.dirname(materials_dir())
    return {
        "materials": os.path.join(base, "materials"),
        "checks": os.path.join(base, "checks"),
        "reference": os.path.join(base, "reference"),
        "files": os.path.join(base, "files"),
    }


def source_install_command():
    """场景 2 评分副本建立环境用的命令：材料 manifest 的 `runtime.install`（第 2.2 节）。"""
    with open(os.path.join(materials_dir(), "manifest.json"), encoding="utf-8") as handle:
        return str(json.load(handle)["runtime"]["install"])


def prepare_source_dir(runs_root, run_id, *, repo_url=None, commit=None, install_command=None):
    """场景 2 的起点：在运行目录之外检出任务上游仓库的基准提交（第 3 节「输入」「隔离」）。

    检出方式沿用 OpenCode 一侧的 `scenario2.fill_run_dir`：按材料里的基准提交号从
    上游检出，再用仓库自己的锁文件建立 Python 3.13 环境。两处不同：`.git` 保留，
    快照要记下 git 提交（接入已有项目设计说明第 4.6 节）；不放需求原文，评测材料
    不进入被接入的目录。远端地址检出以后去掉，工作区里不留回到上游的入口。

    `repo_url`、`commit`、`install_command` 只由测试给出：用测试里建的本地小仓库
    代替上游，不联网。
    """
    path = os.path.abspath(os.path.join(runs_root, run_id, "source"))
    repo_root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    if _is_inside(path, repo_root):
        raise ValueError("the onboarded repository must be outside the Yudao repository: " + path)
    if os.path.exists(path):
        raise ValueError("the onboarded repository already exists: " + path)
    os.makedirs(path)
    url = repo_url or scenario_module().UPSTREAM_URL
    target = commit or scenario_module().base_commit()
    _git(["init", "--quiet"], path)
    _git(["remote", "add", "origin", url], path)
    fetched = _git(["fetch", "--quiet", "--depth", "1", "origin", target], path, check=False)
    if fetched.returncode != 0:
        raise RuntimeError("cannot fetch base commit " + str(target) + ": "
                           + (fetched.stderr or fetched.stdout))
    _git(["checkout", "--quiet", "FETCH_HEAD"], path)
    _git(["remote", "remove", "origin"], path)
    install_environment(path, install_command)
    return path


def _git(arguments, cwd, check=True):
    return subprocess.run(["git"] + arguments, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=check)


def install_environment(repo_dir, install_command=None):
    """按材料的 `runtime.install` 在检出好的仓库里建立运行环境（需要联网，第 2.2 节）。

    测试给出空串时跳过：本地小仓库没有锁文件，也不为它建立环境。
    """
    command = source_install_command() if install_command is None else install_command
    if not command:
        return None
    completed = subprocess.run(shlex.split(command), cwd=repo_dir, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        raise RuntimeError("cannot build the environment: " + (completed.stderr or completed.stdout))
    return completed


# 场景 3 的任务上游仓库（PRDBench）。运行器在导出的事件日志里查找对它的访问，
# 与材料目录的路径使用同一条作废处理（评测场景设计第 3 节「联网」）。
UPSTREAM_REPOSITORY = "AGI-Eval-Official/PRDBench"
UPSTREAM_URLS = ("https://github.com/" + UPSTREAM_REPOSITORY,)


def upstream_urls():
    """当前场景的任务上游仓库地址：导出的事件日志里出现时这次运行作废（第 3 节「联网」）。

    场景 2 的上游是 `openai/openai-agents-python`（`scenario2.UPSTREAM_URL`），
    场景 3 的是 PRDBench；两边都在各自的 `scenarioN` 模块里，与 OpenCode 一侧同一份。
    """
    return tuple(scenario_module().upstream_urls())


def requirement_text():
    """交给 Yudao 的用户原始意图（评测场景设计第 3 节「输入」）。

    场景 3 是需求原文加接口约定：两边的输入是同一份，全文写在这条原文里，工作区里
    没有这两个文件，工程不需要去读它们；起点文件（`subway_data.json`）由运行器经
    起始文件夹带入，事项文字里不另写起点文件的说明。场景 2 是需求原文一件：已有的
    代码由 `project.onboard` 接入，事项只提交这次要加的功能。
    """
    if SCENARIO == SCENARIO_2:
        return _read(os.path.join(materials_dir(), "requirement.md"))
    prd = _read(os.path.join(materials_dir(), "prd.md"))
    agreement = _read(os.path.join(materials_dir(), "interface-agreement.md"))
    return (
        "按下面的需求原文与接口约定实现这份程序。两份全文都写在下面，工作区里没有"
        "这两个文件，不需要去读取它们。代码放在工作区的 `src/` 下，模块名、构造参数、"
        "属性名、命令入口、输入输出格式与导出版面都按接口约定。\n\n"
        "## 需求原文\n\n" + prd + "\n\n## 接口约定\n\n" + agreement
    )


def _scenario_python():
    """场景 3 的运行环境是 uv 管理的 Python 3.13（评测场景设计第 3 节）。"""
    found = subprocess.run(["uv", "python", "find", "3.13"],
                           capture_output=True, encoding="utf-8", errors="replace")
    path = (found.stdout or "").strip()
    if found.returncode != 0 or not path:
        raise RuntimeError("uv cannot provide Python 3.13")
    return path


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


# HTTP 接口（只用标准库，不引入新的第三方依赖）

class YudaoClient:
    """Yudao 接口层的最小客户端：命令、查询与停止。"""

    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")

    def command(self, name, body):
        payload = dict(body)
        payload.setdefault("command_id", str(uuid.uuid4()))
        request = urllib.request.Request(
            self.base_url + "/api/commands/" + name,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        return self._send(request, name)

    def query(self, name, params=None):
        url = self.base_url + "/api/queries/" + name
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return self._send(urllib.request.Request(url, method="GET"), name)

    def _send(self, request, name):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", "replace")
            raise YudaoRejected(name, error.code, body) from None

    def wait_ready(self, timeout_seconds=STARTUP_TIMEOUT_SECONDS):
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(self.base_url + "/api/capabilities", timeout=10) as response:
                    return json.loads(response.read().decode("utf-8"))
            except (urllib.error.URLError, OSError, socket.timeout):
                time.sleep(1.0)
        raise RuntimeError("Yudao did not become ready within " + str(timeout_seconds) + " seconds")

    def stop(self):
        try:
            urllib.request.urlopen(
                urllib.request.Request(self.base_url + "/api/system/stop", data=b"",
                                       headers={"Content-Type": "application/json"}, method="POST"),
                timeout=30)
        except (urllib.error.HTTPError, urllib.error.URLError, OSError):
            pass


class YudaoRejected(Exception):
    """命令被拒绝（409）或接口返回错误。"""

    def __init__(self, name, status, body):
        super().__init__(name + " rejected with HTTP " + str(status) + ": " + body[:400])
        self.name = name
        self.status = status
        self.body = body


# ---------------------------------------------------------------------------
# 服务进程：数据目录在 Yudao 仓库之外

def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def data_dir_for(runs_root, run_id):
    """被测 Yudao 的数据目录：每次运行新建，必须在仓库之外（第 3 节「隔离」）。"""
    path = os.path.abspath(os.path.join(runs_root, run_id, "data"))
    repo_root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    if _is_inside(path, repo_root):
        raise ValueError("Yudao data directory must be outside the Yudao repository: " + path)
    os.makedirs(path, exist_ok=True)
    return path


def start_service(data_dir, port, python_executable=None):
    """在被测的数据目录上启动 Yudao 服务，返回进程对象与接口地址。

    `--no-browser`：运行器不需要在控制主机上打开页面，评测运行与测试都按无界面启动。
    `--no-fetch`：关闭取回，这个实例的部门没有 `fetch_url` 与 `read_external_source`
    （网络与 MCP 设计说明第 5.1、12.4 节、评测场景设计说明第 3 节「两边都不联网」）。
    """
    command = [python_executable or sys.executable, "-m", "harness", "api",
               "--data-dir", data_dir, "--port", str(port), "--no-browser", "--no-fetch"]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               stdin=subprocess.DEVNULL)
    return process, YudaoClient("http://127.0.0.1:" + str(port))


def stop_service(process, timeout_seconds=60):
    """结束服务进程及其子进程，并收回它的输出（记下进程号，只结束自己启动的进程）。"""
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
        else:
            process.terminate()
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
    return _decode(stdout), _decode(stderr)


def _decode(data):
    return data.decode("utf-8", errors="replace") if data else ""


def _is_inside(path, parent):
    path = os.path.normcase(os.path.abspath(path))
    parent = os.path.normcase(os.path.abspath(parent))
    return path == parent or path.startswith(parent + os.sep)


# ---------------------------------------------------------------------------
# 一次运行

def model_service_url():
    base_url = (os.environ.get(model_service.MODEL_SERVICE_BASE_URL_ENV) or "").strip()
    if not base_url:
        raise RuntimeError("the model service address is not in "
                           + model_service.MODEL_SERVICE_BASE_URL_ENV)
    if not (os.environ.get(model_service.MODEL_SERVICE_API_KEY_ENV) or "").strip():
        raise RuntimeError("the model service credential is not in "
                           + model_service.MODEL_SERVICE_API_KEY_ENV)
    return base_url.rstrip("/")


def model_definition(model_name, limits):
    """写进目录文档的模型访问定义：容量取模型服务报告的值或运行器参数（第 3 节）。"""
    return {
        "id": MODEL_DEFINITION_ID, "provider_id": PROVIDER_ID, "model": model_name, "protocol": PROTOCOL,
        "context_window": limits["context_window"],
        "max_output_tokens": limits["max_output_tokens"],
        "accepts_required_tool_call": True,
        "input_modalities": ["text", "image"], "reasoning_levels": [],
        "default_reasoning_level": None, "reasoning_mode": "",
    }


def register_model(client, model_name, limits):
    """把被测模型写入目录文档，经模型测试准入，并让三个部门的默认绑定都指向它。

    部门默认绑定（`catalog.department_defaults.save`）是新建事项的前提：事项要求三个
    部门都能解析到一个可用的模型，只有项目部门设置还不够。
    """
    document = client.query("catalog.document")["data"]
    providers = [item for item in document["providers"] if item["id"] != PROVIDER_ID]
    models = [item for item in document["models"] if item["id"] != MODEL_DEFINITION_ID]
    providers.append({
        "id": PROVIDER_ID, "name": "Yudao eval",
        "base_url": model_service_url(), "credential_ref": model_service.MODEL_SERVICE_API_KEY_ENV,
        "timeout_sec": 600.0, "preset_id": "", "models_url": "",
    })
    models.append(model_definition(model_name, limits))
    client.command("catalog.document.save",
                   {"base_version": document["revision"],
                    "document": {"providers": providers, "models": models, "bindings": {}}})
    admission = _admit_model(client)
    client.command("catalog.department_defaults.save", {
        "base_version": client.query("catalog.document")["data"]["revision"],
        "bindings": {department: {"provider_id": PROVIDER_ID, "model_id": MODEL_DEFINITION_ID,
                                  "requested_tier": None}
                     for department in ("product", "engineering", "quality")}})
    return admission


def create_project(client, name, goal, initial_directory=None):
    """新建项目；`initial_directory` 是这次运行的起点文件夹（评测场景设计第 3 节「输入」）。"""
    created = client.command("project.create", {"name": name, "goal": goal,
                                                "initial_directory": initial_directory})
    return created["refs"]["project_id"]


def save_department_settings(client, project_id):
    """三个部门的项目部门设置都使用被测模型（第 3 节「模型」一行）。"""
    settings = client.query("project.settings", {"project_id": project_id})["data"]["departments"]
    reminders = {}
    for department in ("product", "engineering", "quality"):
        accepted = client.command("department_settings.save",
                                  {"base_version": settings[department]["version"],
                                   "project_id": project_id, "department": department,
                                   "provider_id": PROVIDER_ID, "model_id": MODEL_DEFINITION_ID})
        reminders[department] = list((accepted.get("refs") or {}).get("reminders") or [])
    return reminders


def submit_requirement(client, project_id, text):
    """以用户原始意图提交需求原文加接口约定（评测场景设计第 3 节「输入」）。"""
    created = client.command("work_item.create", {"project_id": project_id, "text": text})
    return created["refs"]["work_item_id"], created["refs"]["run_id"]


# ---------------------------------------------------------------------------
# 场景 2 的建档：接入已有仓库、确认初始 PRD（接入已有项目设计说明第 3、4 节）

def onboard_project(client, name, goal, source_path):
    """接入已有项目：新建项目、登记源目录、采集快照、开始建档事项（第 3.1 节）。

    返回项目、建档事项与建档 run 三个编号：建档的导出按 run 取，与事项的导出分开。
    """
    created = client.command("project.onboard", {"name": name, "goal": goal,
                                                 "source_name": ONBOARDING_SOURCE_NAME,
                                                 "source_path": source_path})
    refs = created["refs"]
    return refs["project_id"], refs["work_item_id"], refs["run_id"]


def initial_prd_decision(client, project_id):
    """这个项目的初始 PRD 决定请求；还没有出现时为 None。

    请求写在项目流中，`decisions.list` 同时返回项目流与 run 流中的请求（第 3.2 节）。
    """
    listed = client.query("decisions.list", {"project_id": project_id,
                                             "kind": INITIAL_PRD_KIND})["data"]["decisions"]
    return listed[0] if listed else None


def onboarding_status(client, project_id, work_item_id):
    """建档事项的状态：`running_statuses` 里的是还在建档，`awaiting_initial_prd` 是等确认。"""
    card = work_item_status(client, project_id, work_item_id)
    return None if card is None else str(card.get("status") or "")


def wait_for_initial_prd(client, project_id, work_item_id, timeout_seconds):
    """等建档跑完并出现初始 PRD 的确认请求，返回这个请求（第 4.7 节）。

    建档只回答一次确认：请求出现时它就是这次等待的结果。建档在出请求之前停下时
    抛 RuntimeError，运行器把它写成这次运行的作废原因。
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        decision = initial_prd_decision(client, project_id)
        if decision is not None:
            return decision
        status = onboarding_status(client, project_id, work_item_id)
        if status not in ONBOARDING_RUNNING_STATUSES:
            raise RuntimeError("建档没有给出初始 PRD 的确认请求，建档事项停在 " + (status or "未知状态"))
        time.sleep(POLL_INTERVAL_SECONDS)
    raise RuntimeError("建档在 " + str(timeout_seconds) + " 秒内没有给出初始 PRD 的确认请求")


def wait_for_confirmation(client, project_id, timeout_seconds):
    """等运行之外的回答：人在浏览器的决定卡片里确认初始 PRD（`--wait-prd-confirmation`）。

    回答由人和运行器以外的一方提交，运行器只轮询决定请求的状态；到时限仍没有被
    回答时抛 RuntimeError，运行器把这次运行作废并写明原因。
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        decision = initial_prd_decision(client, project_id)
        if decision is not None and decision["status"] == "answered":
            return decision
        time.sleep(POLL_INTERVAL_SECONDS)
    raise RuntimeError("初始 PRD 的确认在 " + str(timeout_seconds) + " 秒内没有被回答")


def answer_initial_prd(client, decision):
    """经 `decision.answer` 确认初始 PRD：基准版本是请求的版本（第 3.2 节）。"""
    return client.command("decision.answer", {"base_version": decision["version"],
                                              "decision_id": decision["decision_id"],
                                              "option": CONFIRM_OPTION})


def work_item_status(client, project_id, work_item_id):
    overview = client.query("project.overview", {"project_id": project_id, "work_item": work_item_id})
    cards = overview["data"]["work_items"]
    return cards[0] if cards else None


def wait_for_end(client, project_id, work_item_id, limit_seconds):
    """等待事项结束；到时间上限时经 `work_item.cancel` 结束并标记超时（第 3 节「时间上限」）。"""
    deadline = time.monotonic() + limit_seconds
    while True:
        card = work_item_status(client, project_id, work_item_id)
        if card is None:
            raise RuntimeError("the work item disappeared from project.overview")
        if card["status"] not in ("in_progress", "not_started", "queued"):
            return card, False
        if time.monotonic() >= deadline:
            _cancel(client, work_item_id)
            return wait_settled(client, project_id, work_item_id), True
        time.sleep(POLL_INTERVAL_SECONDS)


def _admit_model(client):
    """模型测试：请求真正发一次，被测模型没有响应就没有准入（#86 准入记录单独返回）。"""
    revision = client.query("catalog.document")["data"]["revision"]
    client.command("catalog.model.test",
                   {"base_version": revision, "provider_id": PROVIDER_ID,
                    "model_id": MODEL_DEFINITION_ID})
    deadline = time.monotonic() + 300.0
    while time.monotonic() < deadline:
        for admission in client.query("catalog")["data"]["admissions"]:
            if admission["model_id"] != MODEL_DEFINITION_ID:
                continue
            # 准入记录可能来自以前那次测试：作废的记录不算这次模型测试的结果
            if admission.get("stale"):
                raise RuntimeError("the model test recorded a stale admission")
            if not admission["admitted"]:
                raise RuntimeError("the model test did not admit the model under test")
            # 服务返回的模型名由服务决定（网关可能换成一个具体的模型）；报告记录它实际服务的名字
            return admission
        time.sleep(1.0)
    raise RuntimeError("the model test did not finish within 300 seconds")


def _cancel(client, work_item_id):
    try:
        client.command("work_item.cancel", {"work_item_id": work_item_id})
    except YudaoRejected as rejected:
        # 事项在轮询与取消之间自己结束：这不是超时路径上的失败
        if '"run_terminal"' not in rejected.body and "run_terminal" not in rejected.body:
            raise


def wait_settled(client, project_id, work_item_id, timeout_seconds=300.0):
    """等待结束事件写入以后读一次事项状态（终态事件先于任务表摘除）。"""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        card = work_item_status(client, project_id, work_item_id)
        if card is not None and card["status"] not in ("in_progress", "not_started", "queued"):
            return card
        time.sleep(POLL_INTERVAL_SECONDS)
    raise RuntimeError("the work item did not settle after being cancelled")


def export_run(client, run_id):
    """经 `run.export` 导出事件日志（指标、过程检查点与交付都从它算）。"""
    return client.query("run.export", {"run_id": run_id})["data"]


def last_archived_delivery(export):
    """最后一次封存的交付：它的 `delivery_accepted` 事件是封存的交付树。"""
    deliveries = [event for event in export["events"] if event["type"] == "delivery_accepted"]
    return deliveries[-1] if deliveries else None


def quality_released(export):
    """质检是否已经放行：最后一次质检提交为 `release`（设计说明第 5.1 节）。"""
    reviews = [event for event in export["events"] if event["type"] == "qa_submitted"]
    return bool(reviews) and reviews[-1]["payload"].get("verdict") == "release"


def fetch_delivery(client, delivery_event, target_dir):
    """把封存的交付树逐个文件取回到评分目录（`delivery.file` 只读封存内容）。"""
    if os.path.exists(target_dir):
        shutil.rmtree(target_dir)
    os.makedirs(target_dir)
    payload = delivery_event["payload"]
    written = []
    for path in payload["files"]:
        fetched = client.query("delivery.file",
                               {"event_id": delivery_event["event_id"], "path": path})["data"]
        destination = os.path.join(target_dir, *path.split("/"))
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        if fetched["content"] is not None:
            _write_bytes(destination, fetched["content"].encode("utf-8"))
        else:
            _write_bytes(destination, base64.b64decode(fetched["base64"]))
        written.append(path)
    return written


def _write_bytes(path, data):
    with open(path, "wb") as handle:
        handle.write(data)


def material_path_hits(text, extra_dirs=None):
    """在导出的事件日志中查找材料目录的路径：找到时这次运行作废（第 3 节「隔离」）。

    匹配完整路径（含目录名），父目录前缀太短，日志里正常的片段会误判。日志是
    JSON 文本，Windows 路径的反斜杠在载荷里写成两个，因此每条路径按原样、正斜杠
    与 JSON 转义三种写法各匹配一次。
    """
    hits = []
    searched = dict(hidden_dirs())
    if extra_dirs:
        searched.update(extra_dirs)
    lowered = text.lower()
    for label, path in searched.items():
        for candidate in _path_variants(path):
            if candidate.lower() in lowered:
                hits.append({"part": label, "path": candidate})
    return hits


def _path_variants(path):
    absolute = os.path.abspath(path)
    forward = absolute.replace("\\", "/")
    return sorted({absolute, forward,
                   json.dumps(absolute)[1:-1], json.dumps(forward)[1:-1]})


def describe_hits(hits):
    return "、".join(sorted({hit["part"] for hit in hits}))


def digest_reasons(base):
    """材料摘要与材料版本记录比较：不同时这次运行作废（第 3 节「隔离」）。

    摘要算在场景目录的材料原件上，不算评分目录里的副本：评分目录紧接在运行
    之后从原件复制，两者相同，而真正要防的是被测方在运行途中改掉仓库里的原件。
    要核对哪几项由当前场景的 `SCORING_INPUTS` 给出（与 OpenCode 一侧同一份）。
    """
    return material_integrity.digest_reasons(base, set(scenario_module().SCORING_INPUTS))


def upstream_hits(text):
    """在导出的事件日志中查找对任务上游仓库的访问：找到时这次运行作废。"""
    return material_integrity.upstream_hits(text, upstream_urls())


def void_reasons(text):
    """一次运行的全部作废原因：材料路径、材料摘要、上游仓库的访问。

    三项都写进报告，报告逐条列出；任一项非空，这次运行不计分。
    """
    reasons = []
    hits = material_path_hits(text)
    if hits:
        reasons.append("事件日志导出中出现材料目录的路径：" + describe_hits(hits))
    reasons.extend(digest_reasons(scenario_base()))
    urls = upstream_hits(text)
    if urls:
        reasons.append("事件日志导出中出现对上游仓库的访问："
                       + material_integrity.describe_urls(urls))
    return reasons


def yudao_commit(repo_root=None):
    """被测 Yudao 的提交号（报告第 6 节：结果记录 Yudao 提交号）。"""
    root = repo_root or os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    result = subprocess.run(["git", "-C", root, "rev-parse", "--short", "HEAD"],
                            capture_output=True, encoding="utf-8", errors="replace")
    return (result.stdout or "").strip() or "unknown"
