"""场景 1 评分器：在评分目录中启动交付并由界面智能体执行用例。

交付是按 WebGen-Bench 000080 要求实现的待办清单应用。评分器启动交付服务，
将端口通过环境变量 PORT 传入，在服务就绪后由界面智能体在浏览器中按可见内容
执行 8 条用例并截图留存，按通过（1）、部分通过（0.5）、不通过（0）记分；
找不到对应元素或入口时记为「没有做」（not_done，0）。
若交付目录为空或无法启动，全部用例直接记为「没有做」。

界面智能体模型固定为 ag/gemini-3.8-flash-high，评分器版本为 scorer-1@1，
材料版本为 scenario-1@1。
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

SCENARIO = "scenario-1"
MATERIAL_VERSION = "scenario-1@1"
SCORER_VERSION = "scorer-1@1"
DEFAULT_MODEL = "ag/gemini-3.8-flash-high"
STARTUP_TIMEOUT = 15.0

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKS_DIR = os.path.join(HERE, "..", "scenarios", SCENARIO, "checks")
MATERIALS_DIR = os.path.join(HERE, "..", "scenarios", SCENARIO, "materials")


def find_free_port():
    """动态获取一个可用的本机端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_server(url, timeout=STARTUP_TIMEOUT, proc=None):
    """轮询直到服务能够响应 HTTP 请求。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc and proc.poll() is not None:
            return False
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "YudaoScorer/1.0"})
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status in (200, 301, 302, 304, 404):
                    return True
        except (urllib.error.HTTPError, urllib.error.URLError, ConnectionError, OSError):
            pass
        time.sleep(0.3)
    return False


def stop_process(proc):
    """结束服务进程树。"""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       capture_output=True)
    else:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def load_cases(checks_dir):
    """加载 8 条测试用例。"""
    cases_path = os.path.join(checks_dir, "cases.json")
    with open(cases_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_requirements(table_path):
    """加载需求条目表。"""
    with open(table_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        return data.get("requirements", [])


def aggregate(records, requirements, model=DEFAULT_MODEL, startup_error=None):
    """计算完成度、正确性与需求得分。"""
    requirement_map = {}
    for req in requirements:
        requirement_map[req["id"]] = [c for c in records if c.get("requirement_id") == req["id"]]

    requirement_scores = {}
    for req_id, req_checks in requirement_map.items():
        if not req_checks:
            requirement_scores[req_id] = 0.0
        else:
            requirement_scores[req_id] = sum(c["score"] for c in req_checks) / len(req_checks)

    completion = sum(requirement_scores.values()) / len(requirement_scores) if requirement_scores else 0.0

    attempted = [c for c in records if c["status"] != "not_done"]
    correctness = sum(c["score"] for c in attempted) / len(attempted) if attempted else 0.0

    not_done = [c["id"] for c in records if c["status"] == "not_done"]
    wrong = [c["id"] for c in records if c["status"] == "wrong"]

    return {
        "scenario": SCENARIO,
        "material_version": MATERIAL_VERSION,
        "scorer_version": SCORER_VERSION,
        "ui_agent_model": model,
        "completion": completion,
        "correctness": correctness,
        "not_done_count": len(not_done),
        "wrong_count": len(wrong),
        "not_done": not_done,
        "wrong": wrong,
        "requirements": requirement_scores,
        "checks": records,
        "startup_error": startup_error,
    }


def determine_start_command(delivery_dir):
    """按约定推断启动交付的命令。"""
    if not os.path.isdir(delivery_dir):
        return None

    package_json = os.path.join(delivery_dir, "package.json")
    if os.path.isfile(package_json):
        try:
            with open(package_json, "r", encoding="utf-8") as f:
                pkg = json.load(f)
            scripts = pkg.get("scripts", {})
            if "dev" in scripts:
                return ["npm", "run", "dev"]
            elif "start" in scripts:
                return ["npm", "run", "start"]
            else:
                return ["npm", "start"]
        except Exception:
            return ["npm", "start"]

    if os.path.isfile(os.path.join(delivery_dir, "server.js")):
        return ["node", "server.js"]
    if os.path.isfile(os.path.join(delivery_dir, "index.js")):
        return ["node", "index.js"]
    if os.path.isfile(os.path.join(delivery_dir, "index.html")):
        code = ("const http=require('http'),fs=require('fs');"
                "const port=process.env.PORT||3000;"
                "http.createServer((q,s)=>{fs.readFile('index.html',(e,d)=>{s.writeHead(200,{'Content-Type':'text/html'});s.end(d)})}).listen(port);")
        return ["node", "-e", code]

    return None


def score(delivery_dir, checks_dir=CHECKS_DIR, table_path=None, work_dir=None, model=DEFAULT_MODEL):
    """在交付上运行 8 条用例并返回评分结果。"""
    delivery_dir = os.path.abspath(delivery_dir)
    checks_dir = os.path.abspath(checks_dir)
    table_path = os.path.abspath(table_path or os.path.join(MATERIALS_DIR, "requirement-table.json"))
    work_dir = os.path.abspath(work_dir or os.path.join(os.path.dirname(delivery_dir), "_work"))
    screenshots_dir = os.path.join(work_dir, "screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)

    cases = load_cases(checks_dir)
    requirements = load_requirements(table_path)

    # 1. 检查交付是否为空或不存在启动入口
    cmd = determine_start_command(delivery_dir)
    if cmd is None:
        records = [{
            "id": c["id"],
            "requirement_id": c.get("requirement_id"),
            "name": c.get("name"),
            "score": 0.0,
            "status": "not_done",
            "verdict": "NOT_DONE",
            "reason": "Empty delivery directory or no web entry point found",
            "screenshots": []
        } for c in cases]
        return aggregate(records, requirements, model=model,
                         startup_error="Empty delivery directory or no web entry point found")

    # 2. 分配端口并启动服务
    port = find_free_port()
    env = dict(os.environ)
    env["PORT"] = str(port)

    # Windows 上 npm 需要通过 shell 执行
    use_shell = (os.name == "nt" and cmd[0] == "npm")
    proc = subprocess.Popen(
        cmd if not use_shell else " ".join(cmd),
        cwd=delivery_dir,
        env=env,
        shell=use_shell,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    base_url = f"http://127.0.0.1:{port}/"
    ready = wait_for_server(base_url, timeout=STARTUP_TIMEOUT, proc=proc)

    if not ready:
        stop_process(proc)
        err = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
        startup_err = f"Failed to start delivery server (exit code: {proc.poll()}). {err}".strip()
        records = [{
            "id": c["id"],
            "requirement_id": c.get("requirement_id"),
            "name": c.get("name"),
            "score": 0.0,
            "status": "not_done",
            "verdict": "NOT_DONE",
            "reason": startup_err,
            "screenshots": []
        } for c in cases]
        return aggregate(records, requirements, model=model, startup_error=startup_err)

    try:
        from ui_agent import run_ui_eval
        records = run_ui_eval(base_url, cases, screenshots_dir, model=model)
    finally:
        stop_process(proc)

    return aggregate(records, requirements, model=model)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Scenario 1 scorer")
    parser.add_argument("--delivery", required=True, help="交付目录")
    parser.add_argument("--checks", default=CHECKS_DIR, help="隐藏检查目录")
    parser.add_argument("--table", help="需求条目表路径")
    parser.add_argument("--result", help="输出机器可读结果路径")
    parser.add_argument("--work-dir", help="工作与截图目录")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="界面智能体模型名")
    args = parser.parse_args(argv)

    table_path = args.table or os.path.join(MATERIALS_DIR, "requirement-table.json")
    result = score(args.delivery, args.checks, table_path, args.work_dir, model=args.model)
    text = json.dumps(result, ensure_ascii=False, indent=2)

    if args.result:
        os.makedirs(os.path.dirname(os.path.abspath(args.result)), exist_ok=True)
        with open(args.result, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
