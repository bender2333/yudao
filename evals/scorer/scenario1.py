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
UI_AGENT_MODEL = "ag/gemini-3.8-flash-high"
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


def aggregate(records, requirements, startup_error=None):
    """计算完成度、正确性与需求得分。"""
    req_ids = [r["id"] if isinstance(r, dict) else r for r in requirements]

    requirement_checks = {rid: [] for rid in req_ids}
    for c in records:
        rid = c.get("requirement") or c.get("requirement_id")
        if rid in requirement_checks:
            requirement_checks[rid].append(c)

    requirement_scores = {}
    for rid in req_ids:
        items = requirement_checks[rid]
        passed = sum(1 for item in items if item["status"] == "pass")
        req_score = sum(item["score"] for item in items) / len(items) if items else 0.0
        requirement_scores[rid] = {
            "passed": passed,
            "total": len(items),
            "score": req_score,
        }

    completion = sum(item["score"] for item in requirement_scores.values()) / len(requirement_scores) if requirement_scores else 0.0

    attempted = [c for c in records if c["status"] != "not_done"]
    correctness = sum(c["score"] for c in attempted) / len(attempted) if attempted else 0.0

    not_done = [c["id"] for c in records if c["status"] == "not_done"]
    wrong = [c["id"] for c in records if c["status"] == "wrong"]

    return {
        "scenario": SCENARIO,
        "material_version": MATERIAL_VERSION,
        "scorer_version": SCORER_VERSION,
        "ui_agent_model": UI_AGENT_MODEL,
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

def _read_last_lines(file_path, count=10):
    """读取文件末尾若干行。"""
    if not os.path.exists(file_path):
        return ""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            return "".join(lines[-count:])
    except Exception:
        return ""


def prepare_and_start_server(delivery_dir, work_dir, port):
    """按接口约定准备依赖并启动服务进程。返回 (proc, log_file, error_message)。"""
    if not os.path.isdir(delivery_dir):
        return None, None, "Empty delivery directory or not a directory"

    log_path = os.path.join(work_dir, "server.log")
    log_file = open(log_path, "a", encoding="utf-8", errors="replace")

    package_json_path = os.path.join(delivery_dir, "package.json")
    cmd = None

    if os.path.isfile(package_json_path):
        try:
            with open(package_json_path, "r", encoding="utf-8") as f:
                pkg = json.load(f)
        except Exception as exc:
            log_file.close()
            return None, None, f"Failed to parse package.json: {exc}"

        # 运行 npm install
        log_file.write(f"=== Running npm install in {delivery_dir} ===\n")
        log_file.flush()
        use_shell = (os.name == "nt")
        install_cmd = "npm install --no-package-lock" if use_shell else ["npm", "install", "--no-package-lock"]
        try:
            res = subprocess.run(
                install_cmd,
                cwd=delivery_dir,
                shell=use_shell,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                timeout=120,
            )
            if res.returncode != 0:
                log_file.close()
                last_lines = _read_last_lines(log_path, 10)
                return None, None, f"npm install failed with exit code {res.returncode}:\n{last_lines}".strip()
        except subprocess.TimeoutExpired:
            log_file.close()
            return None, None, "npm install timed out after 120 seconds"
        except Exception as exc:
            log_file.close()
            return None, None, f"Failed to execute npm install: {exc}"

        scripts = pkg.get("scripts", {})
        if "dev" in scripts:
            cmd = ["npm", "run", "dev"]
        elif "start" in scripts:
            cmd = ["npm", "run", "start"]
        elif os.path.isfile(os.path.join(delivery_dir, "server.js")):
            cmd = ["node", "server.js"]
        elif os.path.isfile(os.path.join(delivery_dir, "index.js")):
            cmd = ["node", "index.js"]
        else:
            log_file.close()
            return None, None, "No dev or start script in package.json, and neither server.js nor index.js exists"
    else:
        if os.path.isfile(os.path.join(delivery_dir, "server.js")):
            cmd = ["node", "server.js"]
        elif os.path.isfile(os.path.join(delivery_dir, "index.js")):
            cmd = ["node", "index.js"]
        else:
            log_file.close()
            return None, None, "No package.json, server.js, or index.js found in delivery directory"

    log_file.write(f"=== Starting server: {cmd} with PORT={port} ===\n")
    log_file.flush()

    env = dict(os.environ)
    env["PORT"] = str(port)
    use_shell = (os.name == "nt" and cmd[0] == "npm")

    try:
        proc = subprocess.Popen(
            cmd if not use_shell else " ".join(cmd),
            cwd=delivery_dir,
            env=env,
            shell=use_shell,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        return proc, log_file, None
    except Exception as exc:
        log_file.close()
        return None, None, f"Failed to spawn server process: {exc}"


def score(delivery_dir, checks_dir=CHECKS_DIR, table_path=None, work_dir=None):
    """在交付上运行 8 条用例并返回评分结果。"""
    delivery_dir = os.path.abspath(delivery_dir)
    checks_dir = os.path.abspath(checks_dir)
    table_path = os.path.abspath(table_path or os.path.join(MATERIALS_DIR, "requirement-table.json"))
    work_dir = os.path.abspath(work_dir or os.path.join(os.path.dirname(delivery_dir), "_work"))
    screenshots_dir = os.path.join(work_dir, "screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)

    cases = load_cases(checks_dir)
    requirements = load_requirements(table_path)

    port = find_free_port()
    proc, log_file, start_err = prepare_and_start_server(delivery_dir, work_dir, port)

    if start_err is not None:
        records = [{
            "id": c["id"],
            "requirement": c.get("requirement_id"),
            "name": c.get("name"),
            "score": 0.0,
            "status": "not_done",
            "verdict": "NOT_DONE",
            "detail": start_err,
            "screenshots": []
        } for c in cases]
        return aggregate(records, requirements, startup_error=start_err)

    base_url = f"http://127.0.0.1:{port}/"
    ready = wait_for_server(base_url, timeout=STARTUP_TIMEOUT, proc=proc)

    if not ready:
        stop_process(proc)
        log_file.close()
        last_lines = _read_last_lines(os.path.join(work_dir, "server.log"), 10)
        startup_err = f"Failed to start delivery server (exit code: {proc.poll()}).\n{last_lines}".strip()
        records = [{
            "id": c["id"],
            "requirement": c.get("requirement_id"),
            "name": c.get("name"),
            "score": 0.0,
            "status": "not_done",
            "verdict": "NOT_DONE",
            "detail": startup_err,
            "screenshots": []
        } for c in cases]
        return aggregate(records, requirements, startup_error=startup_err)

    try:
        from ui_agent import run_ui_eval
        records = run_ui_eval(base_url, cases, screenshots_dir)
    finally:
        stop_process(proc)
        log_file.close()

    return aggregate(records, requirements)
def main(argv=None):
    parser = argparse.ArgumentParser(description="Scenario 1 scorer")
    parser.add_argument("--delivery", required=True, help="交付目录")
    parser.add_argument("--checks", default=CHECKS_DIR, help="隐藏检查目录")
    parser.add_argument("--table", help="需求条目表路径")
    parser.add_argument("--result", help="输出机器可读结果路径")
    parser.add_argument("--work-dir", help="工作与截图目录")
    # 界面智能体模型固定在评分器中，不提供外部命令行选项
    args = parser.parse_args(argv)

    table_path = args.table or os.path.join(MATERIALS_DIR, "requirement-table.json")
    result = score(args.delivery, args.checks, table_path, args.work_dir)
    text = json.dumps(result, ensure_ascii=False, indent=2)

    if args.result:
        os.makedirs(os.path.dirname(os.path.abspath(args.result)), exist_ok=True)
        with open(args.result, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
