# GitHub App 安装令牌入口的验收（工单 #513）：scripts/github-app/ 下的 gh 与 git
# 以 bender2333/yudao 上 App 安装的身份运行。
#
# 工单验收逐条对应：
#   1. 设置两个变量、入口在 PATH 最前面时，请求带上从私钥换来的安装令牌
#      —— 本地 HTTP 服务冒充 GitHub 接口，核对 JWT 头与请求路径；
#   2. 缓存令牌剩余不到 600 秒时下一次调用换新，剩余充足时不请求新令牌；
#   3. 两个变量都没有设置时原来的 gh 与 git 被调用，参数与退出码原样传递；
#   4. 私钥文件不存在时报错写明是哪个变量、哪个路径，不回退到其他身份；
#   5. 令牌与私钥的内容不出现在输出与日志中；
#   6. 新测试文件已在 harness/tests/layers.toml 登记（integration）。
#
# 全程真实子进程与真实本地 HTTP，不使用 mock：假 gh 与假 git 是 .cmd 脚本，
# 记录被调用的环境与参数；git 侧的凭证走真 git 的 credential 助手协议。

import base64
import importlib.util
import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = REPO_ROOT / "scripts" / "github-app"
MODULE_PATH = APP_DIR / "yudao_github_app.py"

APP_ID = "12345"
INSTALLATION_ID = 4242
OTHER_INSTALLATION_ID = 9999
MINTED_TOKEN = "ghs_minted_token_abc"
EXPIRES_AT = "2099-01-01T00:00:00Z"


def _env() -> dict[str, str]:
    # 运行子进程的环境：显式把输出编码设为 UTF-8（#313 的合并验证踩过 PowerShell
    # 的 surrogateescape 与 Git Bash 的 GBK，测试不依赖外部环境）
    return {**os.environ, "PYTHONIOENCODING": "utf-8"}


def _load_module():
    spec = importlib.util.spec_from_file_location("yudao_github_app", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_key(path: Path) -> Path:
    # 现场生成一把只放在临时目录里的 RSA 私钥；不进仓库、不进输出
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    return path


def _decode_jwt_part(part: str) -> dict:
    padding = "=" * (-len(part) % 4)
    return json.loads(base64.urlsafe_b64decode(part + padding))


class _FakeGitHub:
    # 冒充 GitHub App 的两个端点，记录收到的请求；端口由测试进程分配

    def __init__(self, *, installations: list[dict] | None = None):
        self.installations = installations if installations is not None else [
            {"id": INSTALLATION_ID, "account": {"login": "bender2333"}},
            {"id": OTHER_INSTALLATION_ID, "account": {"login": "someone-else"}},
        ]
        self.jwt_headers: list[dict] = []
        self.jwt_claims: list[dict] = []
        self.installation_requests: list[str] = []
        self.token_requests: list[str] = []
        self.token_count = 0
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):  # 静音：请求内容可能带令牌
                pass

            def _reply(self, payload: dict) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                authorization = self.headers.get("Authorization", "")
                if not authorization.startswith("Bearer "):
                    self.send_error(401)
                    return
                server.jwt_headers.append(_decode_jwt_part(authorization[7:].split(".")[0]))
                server.jwt_claims.append(_decode_jwt_part(authorization[7:].split(".")[1]))
                server.installation_requests.append(self.path)
                self._reply(server.installations)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0") or 0)
                if length:
                    self.rfile.read(length)
                server.token_requests.append(self.path)
                server.token_count += 1
                self._reply({"token": MINTED_TOKEN, "expires_at": EXPIRES_AT})

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self._server.server_close = self._server.server_close
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def root(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> "_FakeGitHub":
        self._thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def _configured_env(tmp_path: Path, api_root: str) -> dict[str, str]:
    # 只设本工单的两个变量与测试用的接口根、缓存目录；GITHUB_TOKEN 用假的登录态，
    # 用来核对 App 身份盖掉它
    return {
        **_env(),
        "YUDAO_GH_APP_ID": APP_ID,
        "YUDAO_GH_APP_KEY_FILE": str(tmp_path / "key.pem"),
        "YUDAO_GH_APP_API_ROOT": api_root,
        "LOCALAPPDATA": str(tmp_path / "cache"),
        "GITHUB_TOKEN": "stale_login_token",
    }


def _write_fake_gh(directory: Path) -> Path:
    # 假 gh：把 GH_TOKEN、GITHUB_TOKEN 与参数写进记录文件，返回非零退出码。
    # Windows 上用 .cmd（python 的 subprocess 能直接执行无扩展名以外的命令）；
    # 注释保持纯 ASCII，GBK 控制台会把中文当命令执行
    directory.mkdir(parents=True, exist_ok=True)
    record = directory / "record.txt"
    # >> 前必须留空格：cmd 会把紧贴的 "5>>" 当成 5 号描述符的重定向，
    # 把末尾的参数吃掉
    script = (
        "@echo off\r\n"
        f"echo GH_TOKEN=%GH_TOKEN% >> \"{record}\"\r\n"
        f"echo GITHUB_TOKEN=%GITHUB_TOKEN% >> \"{record}\"\r\n"
        f"echo ARGS=%* >> \"{record}\"\r\n"
        "exit /b 7\r\n")
    (directory / "gh.cmd").write_text(script, encoding="utf-8")
    return directory


def _read_record(directory: Path) -> dict[str, str]:
    # echo 在 >> 前留了空格，重定向符号前的一个空格会留在行尾
    lines = (directory / "record.txt").read_text(encoding="utf-8").splitlines()
    record = {}
    for line in lines:
        key, _, value = line.partition("=")
        record[key] = value.rstrip(" ")
    return record


def _front_path(*directories: Path) -> str:
    # 入口目录放在 PATH 最前面，假二进制紧跟其后；两者都要排在真 gh、真 git 之前，
    # where gh 的返回顺序按 PATH 顺序，靠后就抢不过 GitHub CLI 自带的 gh.exe
    front = os.pathsep.join(str(directory) for directory in directories)
    return front + os.pathsep + os.environ["PATH"]


@pytest.fixture
def key(tmp_path: Path) -> Path:
    return _write_key(tmp_path / "key.pem")


def test_gh_and_git_requests_carry_the_installation_token(key, tmp_path):
    # 验收 1：请求带上从私钥换来的安装令牌。本地 HTTP 接口核对 JWT 头、
    # 安装编号按仓库所有者选中、令牌请求的路径
    bin_dir = _write_fake_gh(tmp_path / "bin")
    with _FakeGitHub() as github:
        result = subprocess.run(
            [str(_python()), str(MODULE_PATH), "gh", "pr", "list", "--limit", "5"],
            env={**_configured_env(tmp_path, github.root), "PATH": _front_path(bin_dir)},
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    assert result.returncode == 7, result.stdout + result.stderr
    assert github.jwt_headers == [{"alg": "RS256", "typ": "JWT"}]
    claim = github.jwt_claims[0]
    assert claim["iss"] == APP_ID
    assert 0 < claim["exp"] - claim["iat"] <= 600
    assert github.installation_requests == ["/app/installations"]
    assert github.token_requests == [f"/app/installations/{INSTALLATION_ID}/access_tokens"]


def test_cached_token_is_reused_and_renewed_near_expiry(key, tmp_path):
    # 验收 2：剩余充足时不请求新令牌；剩余不到 600 秒时下一次调用换新
    with _FakeGitHub() as github:
        env = {**_configured_env(tmp_path, github.root)}
        first = subprocess.run([str(_python()), str(MODULE_PATH), "credential"],
                               env=env, input="protocol=https\nhost=github.com\n\n",
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=120)
        assert first.returncode == 0, first.stdout + first.stderr
        assert f"password={MINTED_TOKEN}" in first.stdout
        assert github.token_count == 1

        # 复用：第二次不再访问接口
        second = subprocess.run([str(_python()), str(MODULE_PATH), "credential"],
                                env=env, input="protocol=https\nhost=github.com\n\n",
                                capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=120)
        assert second.returncode == 0, second.stdout + second.stderr
        assert f"password={MINTED_TOKEN}" in second.stdout
        assert github.token_count == 1

        # 换新：把缓存的过期时刻改成 300 秒以后（不足 600 秒）
        cache = _cache_file(env["LOCALAPPDATA"])
        data = json.loads(cache.read_text(encoding="utf-8"))
        cache.write_text(json.dumps({**data, "expires_at_epoch": int(time.time()) + 300}),
                         encoding="utf-8")
        third = subprocess.run([str(_python()), str(MODULE_PATH), "credential"],
                               env=env, input="protocol=https\nhost=github.com\n\n",
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=120)
        assert third.returncode == 0, third.stdout + third.stderr
        assert github.token_count == 2


def test_unset_variables_pass_through_to_the_real_binaries(tmp_path):
    # 验收 3：两个变量都没有设置时调用原来的 gh 与 git，参数与退出码原样传递。
    # 假 gh 与假 git 只记录参数、返回各自的退出码。
    # 经 cmd /c 调用：Windows 上直接 CreateProcess("gh") 只搜 .exe，会跳过 .cmd 入口
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh_record = bin_dir / "gh-record.txt"
    git_record = bin_dir / "git-record.txt"
    (bin_dir / "gh.cmd").write_text(
        f"@echo off\r\necho %* >> \"{gh_record}\"\r\nexit /b 7\r\n", encoding="utf-8")
    (bin_dir / "git.cmd").write_text(
        f"@echo off\r\necho %* >> \"{git_record}\"\r\nexit /b 3\r\n", encoding="utf-8")
    path = str(APP_DIR) + os.pathsep + str(bin_dir) + os.pathsep + os.environ["PATH"]
    environment = {**_env(), "PATH": path, "YUDAO_GH_APP_ID": "",
                   "YUDAO_GH_APP_KEY_FILE": ""}
    gh = _run_shell("gh pr list --limit 5", environment)
    git = _run_shell("git push origin HEAD", environment)
    assert gh.returncode == 7
    assert git.returncode == 3
    assert gh_record.read_text(encoding="utf-8").splitlines() == ["pr list --limit 5 "]
    assert git_record.read_text(encoding="utf-8").splitlines() == ["push origin HEAD "]


def _run_shell(command: str, environment: dict, stdin: str = "") -> subprocess.CompletedProcess:
    # Windows 上经 cmd /c 运行命令：shell 的 PATH 查找带 PATHEXT，命中放在最前面的
    # .cmd 入口；Linux 与 macOS 上用 sh -c，命中同目录下无扩展名的入口。
    # stdin 直接传给子进程：cmd 的重定向不支持带引号的路径，凭据助手协议的输入
    # 由父进程写进去
    if os.name == "nt":
        return subprocess.run(["cmd", "/c", command], env=environment, input=stdin,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=120)
    return subprocess.run(["sh", "-c", command], env=environment, input=stdin,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=120)


def test_missing_key_file_names_the_variable_and_the_path(key, tmp_path):
    # 验收 4：私钥文件不存在时报错写明是哪个变量、哪个路径，不回退到其他身份
    bin_dir = tmp_path / "bin"
    _write_fake_gh(bin_dir)
    missing = tmp_path / "not-here" / "key.pem"
    env = {**_configured_env(tmp_path, "http://127.0.0.1:1"),
           "YUDAO_GH_APP_KEY_FILE": str(missing)}
    for command in ("gh --version", "git push origin HEAD"):
        result = _run_shell(command, {**env, "PATH": _front_path(APP_DIR, bin_dir)})
        assert result.returncode != 0, result.stdout + result.stderr
        assert "YUDAO_GH_APP_KEY_FILE" in result.stderr
        assert str(missing) in result.stderr
        # 不回退：假 gh 没有被调用
        assert not (bin_dir / "record.txt").exists(), "私钥缺失时回退到了原来的 gh"


def test_token_and_key_never_reach_the_output(key, tmp_path):
    # 验收 5：令牌与私钥的内容不出现在标准输出、标准错误与缓存文件里
    with _FakeGitHub() as github:
        env = {**_configured_env(tmp_path, github.root)}
        result = subprocess.run([str(_python()), str(MODULE_PATH), "credential"],
                                env=env, input="protocol=https\nhost=github.com\n\n",
                                capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        # 私钥的 PEM 内容不出现在任何一路输出里
        assert "BEGIN PRIVATE KEY" not in result.stdout + result.stderr
        # 令牌只出现在密码一行（git 的助手协议要求写出密码），其他输出不带令牌
        assert result.stdout.count(MINTED_TOKEN) == 1
        assert MINTED_TOKEN not in result.stderr
        # 缓存文件只写令牌与过期时刻，不写私钥与其他内容
        cache = json.loads(_cache_file(env["LOCALAPPDATA"]).read_text(encoding="utf-8"))
        assert set(cache) == {"token", "expires_at_epoch"}
        assert cache["token"] == MINTED_TOKEN


def test_gh_receives_the_token_in_place_of_the_login(key, tmp_path):
    # 验收 1 的 gh 侧：真二进制换成假 gh 记录环境，核对令牌经 GH_TOKEN 传入、
    # 登录态的 GITHUB_TOKEN 被盖掉、参数与退出码原样
    bin_dir = tmp_path / "bin"
    _write_fake_gh(bin_dir)
    with _FakeGitHub() as github:
        env = {**_configured_env(tmp_path, github.root),
               "PATH": _front_path(APP_DIR, bin_dir)}
        result = _run_shell("gh pr list --limit 5", env)
    assert result.returncode == 7
    record = _read_record(bin_dir)
    assert record["GH_TOKEN"] == MINTED_TOKEN
    assert record["GITHUB_TOKEN"] == ""
    assert record["ARGS"] == "pr list --limit 5"


def test_git_credential_helper_answers_for_github_over_https(key, tmp_path):
    # 验收 1 的 git 侧：真 git 走 credential 助手协议端到端拿到令牌。
    # 不需要网络推送：git 内部用 sh -c 调起我们的助手
    with _FakeGitHub() as github:
        env = {**_configured_env(tmp_path, github.root), "PATH": _front_path(APP_DIR)}
        result = _run_shell("git credential fill", env,
                            stdin="protocol=https\nhost=github.com\n\n")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "username=x-access-token" in result.stdout
    assert f"password={MINTED_TOKEN}" in result.stdout
    assert github.token_count == 1


def test_credential_helper_ignores_other_hosts(key, tmp_path):
    # 助手只对 https + github.com 应答，其他 host 退出非零让 git 走后面的助手。
    # 不端到端喂非 github host：git 会落到交互式助手上等待输入
    with _FakeGitHub() as github:
        env = {**_configured_env(tmp_path, github.root)}
        result = subprocess.run([str(_python()), str(MODULE_PATH), "credential"],
                                env=env, input="protocol=https\nhost=example.com\n\n",
                                capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=120)
    assert result.returncode == 1
    assert github.token_count == 0
    assert MINTED_TOKEN not in result.stdout + result.stderr


def _python() -> Path:
    # 项目环境中的 Python：与测试进程同一个解释器
    return Path(sys.executable)


def _cache_file(local_app_data: str) -> Path:
    return Path(local_app_data) / "yudao" / f"github-app-token-{APP_ID}.json"
