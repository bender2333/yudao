# Yudao 版本的发布脚本（网页界面的提供与发布设计说明第 6 节，ADR-0032）。
# 架构师在里程碑交给用户之前运行：核对版本与工作区，构建页面文件，组装 Yudao 服务的 wheel，
# 输出 wheel 的路径与 SHA-256；带 --publish 时另外打标签、推送并把 wheel 上传到私有仓库的 Release。
#
# 步骤（设计说明第 6.3 节）：
#   1. 核对：工作区干净；当前提交在 main 上并已推送；pyproject.toml 的版本号；Node 不低于 22.12，uv 可用。
#   2. 构建页面：npm ci，Vite 把页面文件构建到 client/out/renderer。
#   3. M3 起构建执行代理的 wheel（#144 加入）。
#   4. 清空 harness/release_assets/，把页面文件复制进去，删除仓库根下的 build/ 与 *.egg-info，
#      uv build --wheel 生成 wheel；核对 wheel 内的页面文件与页面构建输出逐个一致。
#   5. 仅带 --publish 时：打标签 v<版本> 并推送，gh release create 把 wheel 上传到 Release。
#   6. 输出 wheel 的路径与 SHA-256。
#
# 脚本只构建与上传，不安装、不升级这台电脑上已经安装的 Yudao 服务。
#
# 用法：
#   uv run python scripts/release.py            # 构建并输出 wheel，不发布
#   uv run python scripts/release.py --publish  # 构建后打标签、推送并上传到 Release
#
# 测试与离线核对可以改写这些环境变量（默认值与设计说明一致）：
#   YUDAO_RELEASE_OUTPUT_DIR  wheel 的输出目录（默认仓库下的 dist/）
#   YUDAO_RELEASE_BRANCH      发布所在的分支（默认 main）
#   YUDAO_RELEASE_REMOTE      发布推送到的远端（默认 origin）

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
# 默认的 wheel 输出目录，被 git 忽略
DEFAULT_OUTPUT_DIR = REPO_ROOT / "dist"
# Node 的最低版本（设计说明第 6.3 节）
MIN_NODE = (22, 12)
# 私有仓库的 Release 名称前缀
TAG_PREFIX = "v"
# 页面构建输出目录（vite.pages.config.ts 的 build.outDir）
PAGES_OUTPUT = Path("out") / "renderer"
# 页面文件对应的接口版本写在发布资源目录的这个文件里（工单 #704）
PAGES_API_VERSION_FILE = "api-version.json"
# 发布资源目录：页面文件与执行代理的 wheel 随 wheel 一起发布（设计说明第 5.1、6.1 节）
RELEASE_ASSETS = Path("harness") / "release_assets"

class ReleaseError(Exception):
    # 核对不通过或构建结果不符合预期：写明原因，脚本以非零状态退出
    pass

def _run(command: list[str], cwd: Path | None = None,
         environment: dict[str, str] | None = None) -> None:
    # 运行外部命令，失败时就地抛出（fast-fail），不吞掉错误
    subprocess.run(command, cwd=cwd, check=True, env=environment)

def _capture(command: list[str], cwd: Path | None = None) -> str:
    # 运行外部命令并取回标准输出的文本，失败时就地抛出。按 UTF-8 解码，非法字节替换，
    # 避免 Windows 上 npm 等工具的设备编码导致解码失败
    result = subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    return result.stdout.strip()

def _tool(name: str) -> str:
    # 解析外部工具的路径。Windows 上 npm 是 npm.cmd 的包装，直接写 "npm" 时 subprocess 找不到它。
    # 测试把假的 gh 放在 PATH 最前面时也经这里取到
    path = shutil.which(name)
    if path is None:
        raise ReleaseError(f"找不到 {name}，请先安装并放进 PATH")
    return path

def _tool_exists(name: str) -> bool:
    return shutil.which(name) is not None

def _pyproject_version(path: Path) -> str:
    # 从 pyproject.toml 读取 [project] 的 version。发布版本号只以这里为准（设计说明第 6.2 节），
    # 用标准库 tomllib 读取
    import tomllib

    document = tomllib.loads(path.read_text(encoding="utf-8"))
    version = document.get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        raise ReleaseError(f"{path} 的 [project] 缺少 version")
    return version

def _check_node_version() -> str:
    # Node 不低于 22.12（设计说明第 6.3 节）。取 node --version 的 vX.Y.Z
    raw = _capture([_tool("node"), "--version"]).lstrip("v")
    try:
        major, minor = (int(part) for part in raw.split(".")[:2])
    except (IndexError, ValueError) as exc:
        raise ReleaseError(f"无法解析 Node 版本：{raw}") from exc
    if (major, minor) < MIN_NODE:
        raise ReleaseError(f"Node 版本 {raw} 低于要求的 {MIN_NODE[0]}.{MIN_NODE[1]}")
    return raw

def _check_clean_worktree(repo_root: Path) -> None:
    # 工作区干净：git status --porcelain 为空。构建产物与发布资源都在 .gitignore 中，不影响
    dirty = _capture(["git", "status", "--porcelain"], cwd=repo_root)
    if dirty:
        raise ReleaseError("工作区不干净，请先提交或清理：\n" + dirty)

def _check_on_publish_branch(repo_root: Path, branch: str) -> None:
    # 当前提交在发布分支上
    current = _capture(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root)
    if current != branch:
        raise ReleaseError(f"当前分支是 {current}，发布要求当前提交在 {branch} 上")

def _check_pushed(repo_root: Path, branch: str, remote: str) -> None:
    # 当前提交已经推送到远端：用 git ls-remote 向真实远端查询分支的提交号，与 HEAD 比较。
    # 只读本地跟踪引用时，远端被另一处推进或强制更新以后会得到过期的结论
    head = _capture(["git", "rev-parse", "HEAD"], cwd=repo_root)
    reference = f"refs/heads/{branch}"
    output = _capture(["git", "ls-remote", remote, reference], cwd=repo_root)
    pushed = output.split()[0] if output else ""
    if pushed != head:
        raise ReleaseError(f"当前提交 {head[:12]} 还没有推送到 {remote}/{branch}")

def _check_tag_matches_version(repo_root: Path, version: str) -> None:
    # 版本号核对 pyproject.toml 与标签（设计说明第 6.2 节）：标签 v<版本> 由发布步骤建立，
    # 这个版本已经有标签时说明发布过，重复发布会覆盖上一次的记录
    tag = f"{TAG_PREFIX}{version}"
    existing = _capture(["git", "tag", "--list", tag], cwd=repo_root)
    if existing:
        raise ReleaseError(f"标签 {tag} 已经存在，这个版本发布过了")

def _check_environment() -> None:
    if not _tool_exists("uv"):
        raise ReleaseError("uv 不可用，请先安装 uv")
    _check_node_version()

def verify(repo_root: Path, *, branch: str, remote: str) -> str:
    # 第 1 步：核对。全部通过时返回发布版本号
    _check_clean_worktree(repo_root)
    _check_on_publish_branch(repo_root, branch)
    _check_pushed(repo_root, branch, remote)
    version = _pyproject_version(repo_root / "pyproject.toml")
    _check_tag_matches_version(repo_root, version)
    _check_environment()
    return version

def sha256_hex(path: Path) -> str:
    # 文件 SHA-256 的十六进制值，作为 wheel 的核对值输出
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def page_files(directory: Path) -> dict[str, Path]:
    # 目录下的全部文件（含 assets/ 等子目录），键是相对目录的路径，用 / 分隔
    return {path.relative_to(directory).as_posix(): path
            for path in sorted(directory.rglob("*")) if path.is_file()}

def build_pages(repo_root: Path, *, version: str) -> Path:
    # 第 2 步：构建页面。npm ci 安装依赖，Vite 按 vite.pages.config.ts 把页面文件构建到
    # client/out/renderer。页面记录的版本写成已核对的发布版本，与服务同版本（设计说明第 5.1 节），
    # package.json 的版本不同时页面会在每次连接时重新加载
    client_root = repo_root / "client"
    environment = {**os.environ, "YUDAO_RELEASE_VERSION": version}
    npm = _tool("npm")
    _run([npm, "ci"], cwd=client_root, environment=environment)
    _run([npm, "run", "build:pages"], cwd=client_root, environment=environment)
    output = client_root / PAGES_OUTPUT
    if not (output / "index.html").is_file():
        raise ReleaseError(f"页面构建没有生成 {output / 'index.html'}")
    return output

def _pages_api_version(repo_root: Path) -> int | None:
    # 这一份页面文件对应哪个接口版本（工单 #704）：从客户端生成的版本常量读出；
    # 读不到就写不了，服务那时的日志只说「不知道」
    source = repo_root / "client" / "src" / "renderer" / "src" / "api" / "interface-version.ts"
    try:
        text = source.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"CLIENT_API_VERSION\s*=\s*(\d+)", text)
    return int(match.group(1)) if match else None


def assemble_assets(repo_root: Path, pages: Path) -> Path:
    # 第 4 步前半：清空发布资源目录（该目录被 git 忽略），把页面文件整个复制进去。
    # 先清空，避免上一次发布留下的文件混进 wheel；执行代理的 wheel 在 M3 由 #144 复制进来
    assets_dir = repo_root / RELEASE_ASSETS
    if assets_dir.exists():
        shutil.rmtree(assets_dir)
    shutil.copytree(pages, assets_dir)
    # 这份页面文件对应哪个接口版本（工单 #704）：服务启动时读出来写进日志，
    # 页面与服务不匹配时能说清是哪一边落后了
    version = _pages_api_version(repo_root)
    if version is not None:
        (assets_dir / PAGES_API_VERSION_FILE).write_text(
            json.dumps({"api_version": version}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
    return assets_dir

def clean_build_artifacts(repo_root: Path) -> None:
    # 第 4 步：删除仓库根下的 build/ 与 *.egg-info 以后再构建。
    # setuptools 把 harness/release_assets/ 复制进 build/lib/harness/release_assets/ 以后不会清理它，
    # 上一次构建留下的文件会跟着这次构建一起进 wheel（工单 #313）
    build_dir = repo_root / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir)
    for egg_info in repo_root.glob("*.egg-info"):
        if egg_info.is_dir():
            shutil.rmtree(egg_info)

def build_wheel(repo_root: Path, version: str, output_dir: Path) -> Path:
    # 第 4 步后半：uv build --wheel 生成 Yudao 服务的 wheel。每次构建都先清空构建产物，
    # 从当前工作区重新产生全部文件
    clean_build_artifacts(repo_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    _run(["uv", "build", "--wheel", "--out-dir", str(output_dir)], cwd=repo_root)
    expected = output_dir / f"yudao_harness-{version}-py3-none-any.whl"
    if not expected.is_file():
        raise ReleaseError(f"uv build 没有生成 {expected}")
    return expected

def verify_wheel_contents(wheel: Path, built: Path) -> None:
    # 核对 wheel 内的页面文件与页面构建输出逐个一致（设计说明第 6.3 节第 4 步）：缺少、多出
    # 与内容不同都写明文件名退出。M3 起执行代理的 wheel 也放在发布资源目录里（#144 加入）
    prefix = RELEASE_ASSETS.as_posix() + "/"
    expected = page_files(built)
    with zipfile.ZipFile(wheel) as archive:
        packaged = sorted(name[len(prefix):] for name in archive.namelist()
                          if name.startswith(prefix) and not name.endswith("/"))
        contents = {name: archive.read(prefix + name) for name in packaged}
    missing = sorted(set(expected) - set(packaged))
    if missing:
        raise ReleaseError(f"wheel {wheel.name} 中缺少页面文件：" + "、".join(missing))
    foreign = sorted(set(packaged) - set(expected))
    if foreign:
        raise ReleaseError(f"wheel {wheel.name} 的 {prefix} 中有页面构建输出以外的文件："
                           + "、".join(foreign))
    changed = [name for name, path in expected.items() if contents[name] != path.read_bytes()]
    if changed:
        raise ReleaseError(f"wheel {wheel.name} 中的页面文件与页面构建输出不同：" + "、".join(changed))

def publish(repo_root: Path, version: str, wheel: Path, *, remote: str) -> None:
    # 第 5 步：仅带 --publish 时。打标签 v<版本> 并推送，
    # gh release create 把 wheel 上传到私有仓库的 Release
    tag = f"{TAG_PREFIX}{version}"
    _run(["git", "tag", tag], cwd=repo_root)
    _run(["git", "push", remote, tag], cwd=repo_root)
    _run([_tool("gh"), "release", "create", tag, str(wheel), "--title", tag,
          "--notes", f"Yudao {version}"], cwd=repo_root)

def _check_release(repo_root: Path) -> None:
    # 发布检查（网页界面的提供与发布设计说明第 6.3、6.4 节）：由已安装的实例提供，
    # 用当前运行版本里的清单与检查检查待发布的提交；脚本不运行也不修改这些检查。
    # 命令不存在或检查不通过时拒绝上传；检查通过以后才打标签与上传
    yudao = _tool("yudao")
    result = subprocess.run([yudao, "release-check", str(repo_root)], cwd=repo_root, check=False,
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise ReleaseError("发布检查不通过，先让用户经决定请求「实例升级」批准，再发布：\n"
                           + (result.stdout or "").strip())

def release(repo_root: Path, *, publish_flag: bool, output_dir: Path, branch: str,
            remote: str) -> dict[str, object]:
    # 依设计说明第 6.3 节的顺序执行，返回 wheel 的路径与核对值
    version = verify(repo_root, branch=branch, remote=remote)
    pages = build_pages(repo_root, version=version)
    assets = assemble_assets(repo_root, pages)
    wheel = build_wheel(repo_root, version, output_dir)
    verify_wheel_contents(wheel, pages)
    if publish_flag:
        _check_release(repo_root)
        publish(repo_root, version, wheel, remote=remote)
    return {"version": version, "wheel": wheel, "sha256": sha256_hex(wheel)}

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="构建并发布一个 Yudao 版本")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT,
                        help="仓库的根目录，默认脚本所在的上级目录")
    parser.add_argument("--publish", action="store_true",
                        help="打标签、推送并把 wheel 上传到私有仓库的 Release")
    parser.add_argument("--branch", default=os.environ.get("YUDAO_RELEASE_BRANCH", "main"),
                        help="发布所在的分支，默认 main")
    parser.add_argument("--remote", default=os.environ.get("YUDAO_RELEASE_REMOTE", "origin"),
                        help="推送与上传的远端，默认 origin")
    parser.add_argument("--output-dir", type=Path,
                        default=Path(os.environ.get("YUDAO_RELEASE_OUTPUT_DIR", DEFAULT_OUTPUT_DIR)),
                        help="wheel 的输出目录，默认仓库下的 dist/")
    args = parser.parse_args(argv)

    try:
        result = release(args.repo_root, publish_flag=args.publish, output_dir=args.output_dir,
                         branch=args.branch, remote=args.remote)
    except ReleaseError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"wheel: {result['wheel']}")
    print(f"sha256: {result['sha256']}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())