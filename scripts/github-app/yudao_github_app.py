# GitHub App 的安装令牌：给 gh 与 git 提供按 App 身份运行的凭据（工单 #513）。
#
# 角色进程启动前设置两个环境变量，并把本目录放在 PATH 最前面：
#   YUDAO_GH_APP_ID        App 编号
#   YUDAO_GH_APP_KEY_FILE  私钥文件（GitHub App 生成的 .private-key.pem）
# 两个变量都没有设置时，入口直接运行原来的 gh 与 git，行为不变。
#
# 令牌按需换取：安装令牌一小时过期，剩余不到 600 秒换新，否则复用缓存。
# 缓存放在仓库以外的用户目录（%LOCALAPPDATA%\yudao），只写令牌与过期时刻，不写私钥。
#
# 入口（gh.cmd/gh、git.cmd/git）都转到这里：先探测能 import cryptography 的解释器，
# 再按 argv[0] 的名字分发到 gh 包装或 git 包装。

from __future__ import annotations

import base64
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# 仓库写死：两个 App 只装在 bender2333/yudao 上（运行配置第 2 节）
API_ROOT = "https://api.github.com"
REPO_OWNER = "bender2333"
# 只给这个 host 的 https 请求提供凭据（工单：两个 App 只服务 bender2333/yudao）
GITHUB_HOST = "github.com"
# 安装令牌一小时过期，剩余不到这个秒数就换新
RENEW_MARGIN_SECONDS = 600
# App JWT 的最长有效期（GitHub 要求不超过 10 分钟）
JWT_LIFETIME_SECONDS = 540


def api_root() -> str:
    # 测试用模拟的 GitHub 接口时由环境变量覆盖；生产不设置，走真的 api.github.com
    return os.environ.get("YUDAO_GH_APP_API_ROOT", "").strip().rstrip("/") or API_ROOT


class TokenError(Exception):
    # 取令牌失败：信息里写明是哪个变量、哪个路径，不回退到其他身份
    pass


def _fail(message: str) -> None:
    sys.stderr.write("yudao github-app: " + message + "\n")
    raise SystemExit(1)


def app_id() -> str:
    value = os.environ.get("YUDAO_GH_APP_ID", "").strip()
    if not value:
        raise TokenError("环境变量 YUDAO_GH_APP_ID 没有设置")
    return value


def key_file() -> Path:
    raw = os.environ.get("YUDAO_GH_APP_KEY_FILE", "").strip()
    if not raw:
        raise TokenError("环境变量 YUDAO_GH_APP_KEY_FILE 没有设置")
    path = Path(raw)
    if not path.is_file():
        raise TokenError(f"环境变量 YUDAO_GH_APP_KEY_FILE 指向的私钥文件不存在：{path}")
    try:
        path.read_bytes()
    except OSError as exc:
        raise TokenError(
            f"环境变量 YUDAO_GH_APP_KEY_FILE 指向的私钥文件不可读：{path}（{exc}）") from exc
    return path


def configured() -> bool:
    # 两个变量都没有设置时按原来的 gh 与 git 运行
    return bool(os.environ.get("YUDAO_GH_APP_ID", "").strip()
                or os.environ.get("YUDAO_GH_APP_KEY_FILE", "").strip())


def _cache_path(identifier: str) -> Path:
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if not local:
        raise TokenError("环境变量 LOCALAPPDATA 没有设置，无法确定令牌缓存目录")
    return Path(local) / "yudao" / f"github-app-token-{identifier}.json"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _sign_jwt(identifier: str, key_path: Path) -> str:
    # GitHub App 的 JWT：RS256，header 固定 alg 与 typ，claims 只有 iat、exp、iss
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    try:
        private_key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    except Exception as exc:
        raise TokenError(
            f"无法解析私钥文件（YUDAO_GH_APP_KEY_FILE={key_path}）：{exc}") from exc
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"},
                                separators=(",", ":")).encode("utf-8"))
    now = int(time.time())
    claims = _b64url(json.dumps({"iat": now - 30, "exp": now + JWT_LIFETIME_SECONDS,
                                 "iss": identifier},
                                separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header}.{claims}".encode("ascii")
    try:
        signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    except Exception as exc:
        raise TokenError(f"私钥无法用于 RS256 签名（YUDAO_GH_APP_KEY_FILE={key_path}）：{exc}") from exc
    return f"{header}.{claims}.{_b64url(signature)}"


def _request(method: str, url: str, token: str, body: dict | None = None) -> dict:
    import urllib.error
    import urllib.request

    payload = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}",
               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "yudao-github-app"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        raise TokenError(f"GitHub 接口返回 {exc.code}：{method} {url} {detail}") from exc
    except urllib.error.URLError as exc:
        raise TokenError(f"无法连接 GitHub 接口：{method} {url}（{exc.reason}）") from exc
    return json.loads(raw) if raw else {}


def _parse_expiry(value: str) -> int:
    text = value.replace("Z", "+00:00")
    return int(datetime.fromisoformat(text).astimezone(timezone.utc).timestamp())


def _installation_id(identifier: str, jwt: str) -> int:
    page = _request("GET", f"{api_root()}/app/installations", jwt)
    for item in page if isinstance(page, list) else []:
        account = item.get("account") or {}
        if account.get("login") == REPO_OWNER:
            return int(item["id"])
    raise TokenError(f"App {identifier} 在 {REPO_OWNER} 名下没有安装记录")


def _mint(identifier: str, jwt: str) -> tuple[str, int]:
    installation = _installation_id(identifier, jwt)
    result = _request("POST", f"{api_root()}/app/installations/{installation}/access_tokens",
                      jwt, body={})
    token = result.get("token")
    expires_at = result.get("expires_at")
    if not token or not expires_at:
        raise TokenError("GitHub 接口没有返回安装令牌或过期时刻")
    return token, _parse_expiry(expires_at)


def _read_cache(path: Path) -> tuple[str, int] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return str(data["token"]), int(data["expires_at_epoch"])
    except (OSError, KeyError, TypeError, ValueError):
        return None


def _write_cache(path: Path, token: str, expires_at: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"token": token, "expires_at_epoch": expires_at}),
                    encoding="utf-8")


def installation_token() -> str:
    # 缓存的令牌剩余不足 RENEW_MARGIN_SECONDS 时换新，否则复用
    identifier = app_id()
    key_path = key_file()
    cache = _cache_path(identifier)
    cached = _read_cache(cache)
    if cached is not None:
        token, expires_at = cached
        if expires_at - time.time() >= RENEW_MARGIN_SECONDS:
            return token
    jwt = _sign_jwt(identifier, key_path)
    token, expires_at = _mint(identifier, jwt)
    _write_cache(cache, token, expires_at)
    return token

# 入口调用本模块的参数布局：
#   python yudao_github_app.py gh  <真 gh 绝对路径> [gh 参数...]
#   python yudao_github_app.py git <真 git 绝对路径> [git 参数...]
#   python yudao_github_app.py credential            （git 的凭证助手协议，读 stdin）
# 入口可能由任意 Python 启动（系统 Python 往往没有 cryptography）。
# 探测一个能 import cryptography 的解释器；探测过就打标记，避免重复 exec 自己。
PROBE_MARK = "YUDAO_GH_APP_PROBED"


def _has_cryptography(interpreter: str) -> bool:
    import subprocess
    result = subprocess.run([interpreter, "-c", "import cryptography"],
                            capture_output=True, check=False)
    return result.returncode == 0


def _candidate_interpreters() -> list[str]:
    # 当前解释器优先；其次仓库内的 .venv（相对本文件两级就是仓库根）；
    # 最后 PATH 上的 python 与 python3
    repo_root = Path(__file__).resolve().parents[2]
    candidates = [sys.executable,
                  str(repo_root / ".venv" / "Scripts" / "python.exe"),
                  str(repo_root / ".venv" / "bin" / "python")]
    import shutil
    for name in ("python", "python3"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    ordered: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in ordered:
            ordered.append(candidate)
    return ordered


def ensure_interpreter() -> None:
    # 当前解释器缺 cryptography 时 exec 到第一个可用的解释器，并带上探测标记；
    # 都不可用说明依赖没装，报错而不是退回其他身份
    if os.environ.get(PROBE_MARK) == "1":
        return
    if _has_cryptography(sys.executable):
        return
    for candidate in _candidate_interpreters():
        if candidate != sys.executable and _has_cryptography(candidate):
            os.environ[PROBE_MARK] = "1"
            os.execv(candidate, [candidate, str(Path(__file__).resolve()), *sys.argv[1:]])
    _fail("找不到带 cryptography 的 Python 解释器；在项目环境里装好依赖（uv sync）再运行")


def _run_gh(real: str, arguments: list[str]) -> None:
    # 透传参数与退出码：stdin/stdout/stderr 直接继承，令牌只经环境变量传给子进程。
    # 盖掉登录态可能带来的 GITHUB_TOKEN，确保用的是 App 身份
    environment = dict(os.environ)
    environment["GH_TOKEN"] = installation_token()
    environment.pop("GITHUB_TOKEN", None)
    import subprocess
    result = subprocess.run([real, *arguments], env=environment, check=False)
    raise SystemExit(result.returncode)


def _helper_command() -> str:
    # git 用 sh -c 执行这个字符串：路径必须正斜杠（实测反斜杠会被 sh 吞掉转义），
    # 含空格用双引号包住
    interpreter = Path(sys.executable).as_posix()
    module = Path(__file__).resolve().as_posix()
    return f'"{interpreter}" -u "{module}" credential'


def _run_git(real: str, arguments: list[str]) -> None:
    # 令牌不在这里取：git status 之类不该访问网络，凭据只在 helper 被调用时按需取。
    # helper 列表按配置出现顺序收集，命令行配置永远排在用户全局与系统配置之后，
    # 系统里的 Git Credential Manager 与全局的 gh 助手都会先应答，抢走 github.com 的凭据。
    # GIT_CONFIG_PARAMETERS 支持空值重置（GIT_CONFIG_COUNT 在 Windows 上传不了空值），
    # 先放空值把 github.com 上的助手清空，再放我们的助手。空值只影响这个精确 host，
    # gist.github.com 与其他 host 的行为不变。
    parameters = os.environ.get("GIT_CONFIG_PARAMETERS", "")
    parameters = (parameters + " " if parameters.strip() else "")
    parameters += "'credential.https://github.com.helper'='' "
    parameters += f"'credential.https://github.com.helper'='!{_helper_command()}'"
    os.environ["GIT_CONFIG_PARAMETERS"] = parameters
    import subprocess
    result = subprocess.run([real, *arguments], check=False)
    raise SystemExit(result.returncode)


def _run_credential() -> None:
    # git 的凭证助手协议：读 stdin 的键值对，只对 https + github.com 应答，
    # 其他情况退出非零，让 git 继续用后面的助手
    fields: dict[str, str] = {}
    for line in sys.stdin.read().splitlines():
        key, separator, value = line.partition("=")
        if separator:
            fields[key.strip()] = value.strip()
    if fields.get("protocol") != "https" or fields.get("host") != "github.com":
        raise SystemExit(1)
    sys.stdout.write("username=x-access-token\n")
    sys.stdout.write("password=" + installation_token() + "\n")


def main() -> None:
    ensure_interpreter()
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    arguments = sys.argv[3:]
    try:
        if command == "gh":
            _run_gh(sys.argv[2], arguments)
        elif command == "git":
            _run_git(sys.argv[2], arguments)
        elif command == "credential":
            _run_credential()
        else:
            _fail(f"未知的入口：{command}")
    except TokenError as exc:
        _fail(str(exc))


if __name__ == "__main__":
    main()
