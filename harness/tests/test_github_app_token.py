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
import json
import os
import subprocess
import threading
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


def _front_path(*directories: Path) -> str:
    # 入口目录放在 PATH 最前面，假二进制紧跟其后；两者都要排在真 gh、真 git 之前，
    # where gh 的返回顺序按 PATH 顺序，靠后就抢不过 GitHub CLI 自带的 gh.exe
    front = os.pathsep.join(str(directory) for directory in directories)
    return front + os.pathsep + os.environ["PATH"]


@pytest.fixture
def key(tmp_path: Path) -> Path:
    return _write_key(tmp_path / "key.pem")


def _run_shell(command: str, environment: dict, stdin: str = "",
               cwd: Path | None = None) -> subprocess.CompletedProcess:
    # Windows 上经 cmd /c 运行命令：shell 的 PATH 查找带 PATHEXT，命中放在最前面的
    # .cmd 入口；Linux 与 macOS 上用 sh -c，命中同目录下无扩展名的入口。
    # stdin 直接传给子进程：cmd 的重定向不支持带引号的路径，凭据助手协议的输入
    # 由父进程写进去
    if os.name == "nt":
        return subprocess.run(["cmd", "/c", command], env=environment, input=stdin,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=120, cwd=cwd)
    return subprocess.run(["sh", "-c", command], env=environment, input=stdin,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=120, cwd=cwd)


def test_missing_key_file_names_the_variable_and_the_path(key, tmp_path):
    # 验收 4：私钥文件不存在时报错写明是哪个变量、哪个路径，不回退到其他身份
    bin_dir = tmp_path / "bin"
    _write_fake_gh(bin_dir)
    missing = tmp_path / "not-here" / "key.pem"
    # git push 在一个临时仓库里运行，远端是本项目所有者名下一个不存在的仓库：GitHub 对它同样
    # 要求凭据，凭据助手因此被调用；万一取得了凭据，推送也只会得到「仓库不存在」。不依赖运行它的
    # 机器的状态。GitHub 运行机上 actions/checkout 把 github-actions[bot] 的凭据写在
    # 检出仓库的 http.extraheader 里，git 带着它请求，不会再向凭据助手要凭据，
    # 测试就走不到「缺私钥文件」的报错，还会真的向仓库推送（403）。
    workdir = tmp_path / "push-repo"
    workdir.mkdir()
    for git_args in (["init", "-q"], ["remote", "add", "origin", "https://github.com/bender2333/yudao-push-target-does-not-exist.git"],
                     ["-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q",
                      "--allow-empty", "-m", "init"]):
        subprocess.run(["git", *git_args], cwd=workdir, check=True, env=_env(), capture_output=True)
    env = {**_configured_env(tmp_path, "http://127.0.0.1:1"),
           "YUDAO_GH_APP_KEY_FILE": str(missing),
           # 再把全局与系统配置里可能带的 github.com 授权头清空（空值覆盖更低层级的配置）
           "GIT_CONFIG_COUNT": "1",
           "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
           "GIT_CONFIG_VALUE_0": ""}
    env.pop("GIT_CONFIG_PARAMETERS", None)
    for command in ("gh --version", "git push origin HEAD"):
        result = _run_shell(command, {**env, "PATH": _front_path(APP_DIR, bin_dir)}, cwd=workdir)
        assert result.returncode != 0, result.stdout + result.stderr
        assert "YUDAO_GH_APP_KEY_FILE" in result.stderr
        assert str(missing) in result.stderr
        # 不回退：假 gh 没有被调用
        assert not (bin_dir / "record.txt").exists(), "私钥缺失时回退到了原来的 gh"


