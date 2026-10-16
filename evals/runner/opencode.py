"""OpenCode 运行器：在 Yudao 仓库之外新建运行目录并运行一次 OpenCode。

每次运行独立建立 git 仓库，OpenCode 才把交付写入运行目录（没有版本控制的目录
会被当成全局目录，交付落到系统临时目录）。运行目录只含材料起点，不含隐藏检查、
条目表与参考实现。起点、消息与隐藏目录随场景不同，由 runner/scenario3.py 与
runner/scenario2.py 提供，本模块的其余部分对所有场景通用。

工具取回与搜索（webfetch、websearch）在运行配置中关闭；运行结束以后运行器检查
JSON 输出里有没有这两类工具的调用。
"""

import json
import os
import shutil
import subprocess
import time
import material_integrity

SCENARIO_MODULE = "scenario3"
NETWORK_TOOLS = ("webfetch", "websearch")
MODEL_SERVICE_BASE_URL_ENV = "YUDAO_EVAL_BASE_URL"
MODEL_SERVICE_API_KEY_ENV = "YUDAO_EVAL_API_KEY"


def scenario(name=None):
    """载入场景模块：起点、消息与隐藏目录随场景不同，其余部分是通用的。"""
    import importlib
    return importlib.import_module(name or SCENARIO_MODULE)


def write_run_config(run_dir, model, model_id):
    """写运行配置：关闭取回与搜索工具，模型服务由环境变量给出。

    被测模型由用户提供（评测场景设计第 3 节），凭据只留在环境变量里，
    配置里用 {env:...} 引用，不写进运行目录与仓库。
    """
    config_dir = os.path.join(run_dir, ".opencode-config")
    os.makedirs(config_dir, exist_ok=True)
    config = {
        "$schema": "https://opencode.ai/config.json",
        "model": model,
        "permission": {
            "bash": "allow",
            "edit": "allow",
            "webfetch": "deny",
            "websearch": "deny",
        },
        "provider": {
            "yudao-eval": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Yudao eval",
                "options": {
                    "baseURL": "{env:" + MODEL_SERVICE_BASE_URL_ENV + "}",
                    "apiKey": "{env:" + MODEL_SERVICE_API_KEY_ENV + "}",
                },
                "models": {model_id: {"name": model_id}},
            }
        },
    }
    path = os.path.join(config_dir, "opencode.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2)
    return path


def create_run_dir(runs_root, run_id, model, model_id, scenario_name=None):
    """在 Yudao 仓库之外新建运行目录，由场景模块填入起点。"""
    scenario_module = scenario(scenario_name)
    run_dir = os.path.abspath(os.path.join(runs_root, run_id))
    if os.path.exists(run_dir):
        raise ValueError("run directory already exists: " + run_dir)
    repo_root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    if _is_inside(run_dir, repo_root):
        raise ValueError("run directory must be outside the Yudao repository: " + run_dir)
    os.makedirs(run_dir)
    scenario_module.fill_run_dir(run_dir)
    # 没有版本控制的目录被 OpenCode 当成全局目录，交付会落到系统临时目录。
    subprocess.run(["git", "init", "--quiet"], cwd=run_dir, check=True,
                   capture_output=True)
    write_run_config(run_dir, model, model_id)
    return run_dir


def _is_inside(path, parent):
    path = os.path.normcase(os.path.abspath(path))
    parent = os.path.normcase(os.path.abspath(parent))
    return path == parent or path.startswith(parent + os.sep)


def build_command(run_dir, model, opencode_command="opencode", scenario_name=None):
    """`opencode run` 的命令行：默认 agent、JSON 事件流、消息带材料附件。"""
    scenario_module = scenario(scenario_name)
    executable = shutil.which(opencode_command)
    if executable is None:
        raise FileNotFoundError("opencode is not on PATH: " + opencode_command)
    command = [executable, "run", "--pure", "--dir", run_dir, "--format", "json",
               "--model", model, scenario_module.message()]
    for path in scenario_module.message_files(run_dir):
        command += ["-f", path]
    return command


def run_opencode(run_dir, model, limit_seconds, opencode_command="opencode", scenario_name=None):
    """在运行目录中运行 `opencode run`，到时间上限结束。

    返回运行器的原始结果：退出状态、是否超时、输出文本与耗时。
    """
    command = build_command(run_dir, model, opencode_command, scenario_name)
    env = dict(os.environ)
    env["OPENCODE_CONFIG_DIR"] = os.path.join(run_dir, ".opencode-config")
    started = time.monotonic()
    process = subprocess.Popen(command, cwd=run_dir, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=limit_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate(process)
        stdout, stderr = process.communicate()
    elapsed = time.monotonic() - started
    return {
        "returncode": process.returncode,
        "timed_out": timed_out,
        "stdout": _decode(stdout),
        "stderr": _decode(stderr),
        "elapsed_seconds": elapsed,
        "command": command,
    }


def _decode(data):
    """OpenCode 的事件输出是 UTF-8，错误信息按 Windows 控制台代码页给出。"""
    if not data:
        return ""
    return data.decode("utf-8", errors="replace")


def _terminate(process):
    """结束运行器自己启动的进程及其子进程（超时路径）。"""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       capture_output=True)
    else:
        process.terminate()
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()


def parse_events(stdout_text):
    """解析 `--format json` 的事件流，忽略无法解析的行。"""
    events = []
    for line in stdout_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def tool_calls(events):
    """JSON 输出里记录的工具调用：[(tool_name, 状态, 输出文本)]。"""
    calls = []
    for event in events:
        if event.get("type") != "tool_use":
            continue
        part = event.get("part") or {}
        if part.get("type") != "tool":
            continue
        state = part.get("state") or {}
        calls.append({
            "tool": part.get("tool", ""),
            "status": state.get("status", ""),
            "output": state.get("output", "") or "",
            "input": state.get("input") or {},
        })
    return calls


def network_tool_calls(calls):
    return [call for call in calls if call["tool"] in NETWORK_TOOLS]


def material_path_hits(text, scenario_name=None, extra_dirs=None):
    """在 JSON 输出中查找材料目录的路径：找到时这次运行作废。

    匹配完整路径（含目录名），父目录前缀太短，输出里正常的片段会误判。
    """
    hits = []
    searched = dict(scenario(scenario_name).hidden_dirs())
    if extra_dirs:
        searched.update(extra_dirs)
    lowered = text.lower()
    for label, path in searched.items():
        for candidate in _path_variants(path):
            if candidate.lower() in lowered:
                hits.append({"part": label, "path": candidate})
    return hits

def upstream_hits(text, scenario_name=None):
    """在 JSON 输出中查找对任务上游仓库的访问：找到时这次运行作废（第 3 节「联网」）。"""
    urls = scenario(scenario_name).upstream_urls()
    return material_integrity.upstream_hits(text, urls)


def digest_reasons(base, scenario_name=None):
    """场景材料的摘要与材料版本记录比较：不同时这次运行作废（第 3 节「隔离」）。"""
    return material_integrity.digest_reasons(
        base, set(scenario(scenario_name).SCORING_INPUTS) | {"reference"})


def _path_variants(path):
    """同一目录在 Windows 上可能写成反斜杠或正斜杠，两种都算命中。"""
    absolute = os.path.abspath(path)
    return sorted({absolute, absolute.replace("\\", "/")})