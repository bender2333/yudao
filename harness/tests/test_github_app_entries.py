# GitHub App 入口转发参数的验收（工单 #526）：scripts/github-app/ 的 gh.exe 与 git.exe
# 把参数原样交给真正的 gh 与 git。
#
# 工单验收逐条对应：
#   1. 含 | & ^ ( ) % ! 引号、空格、中文、结尾反斜杠的参数与空参数，经入口到达真 git 时与原样相同：
#      直接启动（gh 调用 git 的方式）、cmd、Git bash 三种调用方式，两个变量设置与不设置两种状态；
#      真 git 收到的参数取自它自己的 trace2 记录；
#   2. 同样的字符经入口到达真 gh：gh config set 写进隔离的配置目录，读回核对；
#   3. 真 gh 经入口调用 git：分支名带特殊字符时，gh 生成的正则与分支名原样到达真 git，
#      进程链上真 gh 的下一级是入口 git.exe；
#   4. 提交的 gh.exe 与 git.exe 与 make_entries.py 生成的逐字节相同。
#
# 全程真实的 gh、git 与入口，不用假程序。设置变量的状态用令牌缓存里有效期充足的令牌，
# 入口不访问 GitHub；gh 的网络请求经代理指向本机一个关闭的端口。

import importlib.util
import json
import os
import shlex
import subprocess
import time
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = REPO_ROOT / "scripts" / "github-app"
APP_ID = "12345"

# 每一项都带空格：list2cmdline 只给带空格的参数加引号，加了引号 cmd 才不解释 | & ^ ( )。
# YUDAO_UNSET 在测试环境里没有定义，cmd 原样保留 %YUDAO_UNSET%
ARGUMENTS = [
    "a|b & c^d (e)f",
    "%YUDAO_UNSET% 100% !x!",
    "说 \"引号\" '单引号'",
    "空 格 中文",
    "末尾 \\",
    "",
]
GH_VALUE = " ".join(ARGUMENTS[:-1])
# 合法的 git 分支名不能含 ^ 与空格，其余特殊字符都放进来
BRANCH = "a|b&c(d)%e'f\"g!中文"
SHELLS = ("direct", "cmd", "bash")

def _environment(tmp_path: Path, *, configured: bool) -> dict[str, str]:
    environment = {**os.environ, "PYTHONIOENCODING": "utf-8",
                   "PATH": str(APP_DIR) + os.pathsep + os.environ["PATH"],
                   "GIT_TRACE2_EVENT": str(tmp_path / "trace2.json")}
    # 两个 MSYS 变量关掉 Git bash 的路径转换，去掉以后与平常打开的 Git bash 相同
    for name in ("YUDAO_GH_APP_ID", "YUDAO_GH_APP_KEY_FILE", "YUDAO_UNSET",
                 "MSYS_NO_PATHCONV", "MSYS2_ARG_CONV_EXCL"):
        environment.pop(name, None)
    if configured:
        environment.update(_configured(tmp_path))
    return environment

def _configured(tmp_path: Path) -> dict[str, str]:
    # 现场生成私钥；缓存里放一个一小时后过期的令牌，入口直接复用，不换新
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = tmp_path / "key.pem"
    key.write_bytes(rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    local = tmp_path / "localappdata"
    cache = local / "yudao" / f"github-app-token-{APP_ID}.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({"token": "ghs_cached_for_entries",
                                 "expires_at_epoch": int(time.time()) + 3600}), encoding="utf-8")
    return {"YUDAO_GH_APP_ID": APP_ID, "YUDAO_GH_APP_KEY_FILE": str(key), "LOCALAPPDATA": str(local)}

def _git_bash() -> Path:
    # Git for Windows 的 bash：git --exec-path 是 <安装目录>/mingw64/libexec/git-core。
    # 用 usr/bin 下的 bash：bin/bash.exe 会把 Git 自己的目录加到 PATH 最前面；
    # PATH 上的 bash 可能是 System32 下的 WSL
    exec_path = subprocess.run(["git", "--exec-path"], capture_output=True, text=True,
                               check=True).stdout.strip()
    return Path(exec_path).parents[2] / "usr" / "bin" / "bash.exe"

def _run(shell: str, program: str, arguments: list[str], environment: dict[str, str],
         cwd: Path) -> subprocess.CompletedProcess:
    if shell == "direct":
        command = [str(APP_DIR / f"{program}.exe"), *arguments]
    elif shell == "cmd":
        line = subprocess.list2cmdline([program, *arguments])
        command = f'cmd /d /v:off /s /c "{line}"'
    else:
        # 命令写进脚本文件，参数按 POSIX shell 的规则加引号，与在 Git bash 里输入的相同
        script = cwd / f"run-{program}.sh"
        script.write_text(shlex.join([program, *arguments]) + "\n", encoding="utf-8", newline="\n")
        command = [str(_git_bash()), script.as_posix()]
    return subprocess.run(command, env=environment, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120)

def _git_processes(trace: Path) -> list[dict]:
    # 每个真 git 进程一条：收到的参数、退出码与 Windows 上的进程链（由近到远的程序名）
    processes: dict[str, dict] = {}
    for line in trace.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        process = processes.setdefault(event["sid"], {})
        if event["event"] == "start":
            process["argv"] = event["argv"][1:]
        elif event["event"] == "exit":
            process["code"] = event["code"]
        elif event["event"] == "data_json" and event.get("key") == "windows/ancestry":
            process["ancestry"] = event["value"]
    return [process for process in processes.values() if "argv" in process]

@pytest.mark.parametrize("configured", [False, True], ids=["plain", "app"])
@pytest.mark.parametrize("shell", SHELLS)
def test_git_receives_the_arguments_unchanged(tmp_path, shell, configured):
    # 验收 1：真 git 的 trace2 记录里的参数与传入的完全相同
    environment = _environment(tmp_path, configured=configured)
    result = _run(shell, "git", ["rev-parse", "--sq-quote", *ARGUMENTS], environment, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    processes = _git_processes(tmp_path / "trace2.json")
    assert [process["argv"] for process in processes] == [["rev-parse", "--sq-quote", *ARGUMENTS]]

@pytest.mark.parametrize("configured", [False, True], ids=["plain", "app"])
@pytest.mark.parametrize("shell", SHELLS)
def test_gh_receives_the_arguments_unchanged(tmp_path, shell, configured):
    # 验收 2：真 gh 把收到的值写进隔离的配置目录，文件里的值与传入的完全相同，读回的输出也相同
    environment = {**_environment(tmp_path, configured=configured),
                   "GH_CONFIG_DIR": str(tmp_path / "gh-config"), "GH_NO_UPDATE_NOTIFIER": "1"}
    written = _run(shell, "gh", ["config", "set", "yudao_probe", GH_VALUE], environment, tmp_path)
    assert written.returncode == 0, written.stdout + written.stderr
    stored = yaml.safe_load((tmp_path / "gh-config" / "config.yml").read_text(encoding="utf-8"))
    assert stored["yudao_probe"] == GH_VALUE
    read = _run(shell, "gh", ["config", "get", "yudao_probe"], environment, tmp_path)
    assert read.returncode == 0, read.stdout + read.stderr
    assert read.stdout == GH_VALUE + "\n"

def test_gh_calls_git_through_the_entry_with_the_arguments_unchanged(tmp_path):
    # 验收 3：#526 的现场。gh pr status 先用 git 查当前分支的配置，正则里有 | ( ) 与转义的分支名；
    # 网络请求在这之后，指向关闭的端口直接失败
    repo = tmp_path / "repo"
    real_git = ["git", "-C", str(repo)]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for arguments in (["symbolic-ref", "HEAD", f"refs/heads/{BRANCH}"],
                      ["remote", "add", "origin", "https://github.com/bender2333/yudao.git"],
                      ["config", f"branch.{BRANCH}.remote", "origin"],
                      ["config", f"branch.{BRANCH}.merge", f"refs/heads/{BRANCH}"]):
        subprocess.run([*real_git, *arguments], check=True)
    environment = {**_environment(tmp_path, configured=True),
                   "GH_CONFIG_DIR": str(tmp_path / "gh-config"), "GH_NO_UPDATE_NOTIFIER": "1",
                   "GH_PROMPT_DISABLED": "1", "HTTPS_PROXY": "http://127.0.0.1:1"}
    for name in ("NO_PROXY", "no_proxy"):
        environment.pop(name, None)
    _run("direct", "gh", ["pr", "status"], environment, repo)

    processes = _git_processes(tmp_path / "trace2.json")
    regexp = [process for process in processes
              if process["argv"][:2] == ["config", "--get-regexp"]
              and process["argv"][2].startswith("^branch")]
    assert len(regexp) == 1, processes
    assert regexp[0]["argv"][2].endswith(r"\.(remote|merge|pushremote|gh-merge-base)$")
    # 退出码 0 说明正则完整到达并且匹配上了这个分支的配置
    assert regexp[0]["code"] == 0
    push = [process for process in processes if process["argv"][:2] == ["rev-parse", "--symbolic-full-name"]]
    assert [process["argv"] for process in push] == [
        ["rev-parse", "--symbolic-full-name", f"{BRANCH}@{{push}}"]]
    for process in processes:
        ancestry = process["ancestry"]
        assert ancestry[ancestry.index("gh.exe") - 1] == "git.exe", ancestry

def test_committed_entries_match_the_generator(tmp_path, monkeypatch):
    # 验收 4：重新生成的入口与提交的逐字节相同。make_entries 会设置 SOURCE_DATE_EPOCH，
    # 先经 monkeypatch 设置一次，测试结束后恢复原状
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "0")
    spec = importlib.util.spec_from_file_location("make_entries", APP_DIR / "make_entries.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.make_entries(tmp_path)
    for name in ("gh.exe", "git.exe"):
        assert (tmp_path / name).read_bytes() == (APP_DIR / name).read_bytes(), name
