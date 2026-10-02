# Yudao 版本的发布脚本（桌面客户端的安装、更新与发布设计说明第 6 节，ADR-0023）。
# 架构师在里程碑交给用户之前运行：核对版本与工作区，构建客户端安装包，组装 Yudao 服务的 wheel，
# 输出 wheel 的路径与 SHA-256；带 --publish 时另外打标签、推送并把 wheel 上传到私有仓库的 Release。
#
# 步骤（设计说明第 6.3 节）：
#   1. 核对：工作区干净；当前提交在 main 上并已推送；版本号三处相同；Node 不低于 22.12，uv 可用。
#   2. 构建客户端：npm ci，electron-builder 生成安装程序、blockmap 与 latest.yml。
#   3. M3 起构建执行代理的 wheel（#144 加入），现在留出 release_assets/ 中的位置。
#   4. 复制进 harness/release_assets/，uv build --wheel 生成 Yudao 服务的 wheel；
#      核对 wheel 内含这些文件，latest.yml 中的 SHA-512 与安装程序一致。
#   5. 仅带 --publish 时：打标签 v<版本> 并推送，gh release create 把 wheel 上传到 Release。
#   6. 输出 wheel 的路径与 SHA-256。
#
# 脚本只构建与上传，不安装、不升级这台电脑上已经安装的 Yudao 服务与客户端。
#
# 用法：
#   uv run python scripts/release.py            # 构建并输出 wheel，不发布
#   uv run python scripts/release.py --publish  # 构建后打标签、推送并上传到 Release
#
# 测试与离线核对可以改写这些环境变量（默认值与设计说明一致）：
#   YUDAO_RELEASE_APP_ID          客户端 appId（默认 com.yudao.client）
#   YUDAO_RELEASE_PRODUCT_NAME    客户端产品名（默认 Yudao）
#   YUDAO_RELEASE_SETUP_BASENAME  安装包文件名前缀（默认 Yudao-Setup）
#   YUDAO_RELEASE_OUTPUT_DIR      wheel 的输出目录（默认仓库下的 dist/）
#   YUDAO_RELEASE_BRANCH          发布所在的分支（默认 main）
#   YUDAO_RELEASE_REMOTE          发布推送到的远端（默认 origin）

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
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

class ReleaseError(Exception):
    # 核对不通过或构建结果不符合预期：写明原因，脚本以非零状态退出
    pass

def _run(command: list[str], cwd: Path | None = None) -> None:
    # 运行外部命令，失败时就地抛出（fast-fail），不吞掉错误
    subprocess.run(command, cwd=cwd, check=True)

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
    # 从 pyproject.toml 读取 [project] 的 version。发布脚本只关心这一个字段，
    # 用标准库 tomllib 读取
    import tomllib

    document = tomllib.loads(path.read_text(encoding="utf-8"))
    version = document.get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        raise ReleaseError(f"{path} 的 [project] 缺少 version")
    return version

def _client_version(path: Path) -> str:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    version = parsed.get("version")
    if not isinstance(version, str) or not version:
        raise ReleaseError(f"{path} 缺少 version")
    return version

def _check_node_version() -> str:
    # Node 不低于 22.12（设计说明第 6.3 节）。取 node --version 的 vX.Y.Z
    raw = _capture([_tool("node"), "--version"]).lstrip("v")
    parts = raw.split(".")
    try:
        major, minor = int(parts[0]), int(parts[1])
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
    # 当前提交已经推送到远端：HEAD 的提交号与远端分支相同
    head = _capture(["git", "rev-parse", "HEAD"], cwd=repo_root)
    remote_ref = f"refs/remotes/{remote}/{branch}"
    try:
        pushed = _capture(["git", "rev-parse", remote_ref], cwd=repo_root)
    except subprocess.CalledProcessError:
        pushed = ""
    if pushed != head:
        raise ReleaseError(f"当前提交 {head[:12]} 还没有推送到 {remote}/{branch}")

def _check_versions(repo_root: Path) -> str:
    # 版本号三处相同：pyproject.toml 的 version、客户端 package.json 的 version 与标签 v<版本>。
    # 标签在发布时由脚本建立，核对时先要求前两处相同
    service = _pyproject_version(repo_root / "pyproject.toml")
    client = _client_version(repo_root / "client" / "package.json")
    if service != client:
        raise ReleaseError(
            f"版本号不一致：pyproject.toml 是 {service}，client/package.json 是 {client}")
    return service

def _check_environment() -> None:
    if not _tool_exists("uv"):
        raise ReleaseError("uv 不可用，请先安装 uv")
    _check_node_version()

def verify(repo_root: Path, *, branch: str, remote: str) -> str:
    # 第 1 步：核对。全部通过时返回发布版本号
    _check_clean_worktree(repo_root)
    _check_on_publish_branch(repo_root, branch)
    _check_pushed(repo_root, branch, remote)
    version = _check_versions(repo_root)
    _check_environment()
    return version

def sha512_base64(path: Path) -> str:
    # 文件 SHA-512 的 base64 值。electron-builder 的 latest.yml 用这个值作为 files[].sha512
    # （builder-util-runtime 的 UpdateFileInfo；调研第 3.2 节）
    digest = hashlib.sha512()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return base64.b64encode(digest.digest()).decode("ascii")

def sha256_hex(path: Path) -> str:
    # 文件 SHA-256 的十六进制值，作为 wheel 的核对值输出
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def build_client(repo_root: Path, *, app_id: str, product_name: str,
                 setup_basename: str) -> dict[str, Path]:
    # 第 2 步：构建客户端。npm ci 安装依赖，electron-builder 生成安装程序、blockmap 与 latest.yml。
    # build-installer.mjs（#208）已经封装了这一步，并输出一行 JSON 写明三个文件的位置
    client_root = repo_root / "client"
    environment = {**os.environ, "YUDAO_APP_ID": app_id, "YUDAO_PRODUCT_NAME": product_name,
                   "YUDAO_SETUP_BASENAME": setup_basename}
    subprocess.run([_tool("npm"), "ci"], cwd=client_root, check=True, env=environment)
    result = subprocess.run([_tool("node"), "scripts/build-installer.mjs"], cwd=client_root,
                            check=True, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", env=environment)
    # build-installer.mjs 最后一行是 JSON；取最后一个 JSON 对象
    parsed = json.loads(result.stdout.strip().splitlines()[-1])
    installer = Path(parsed["setup"])
    blockmap = Path(parsed["blockmap"])
    manifest = Path(parsed["manifest"])
    for path in (installer, blockmap, manifest):
        if not path.is_file():
            raise ReleaseError(f"客户端构建没有生成 {path}")
    return {"installer": installer, "blockmap": blockmap, "manifest": manifest}

def verify_manifest_matches_installer(manifest: Path, installer: Path) -> None:
    # 核对 latest.yml 中的 SHA-512 与安装程序一致（设计说明第 6.3 节第 4 步）。
    # latest.yml 是 YAML；读取 files 中 url 与安装程序同名的项，比较 sha512
    import yaml

    document = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    files = document.get("files")
    if not isinstance(files, list) or not files:
        raise ReleaseError(f"{manifest} 的 files 为空")
    expected = sha512_base64(installer)
    name = installer.name
    entry = next((item for item in files if isinstance(item, dict) and item.get("url") == name), None)
    if entry is None:
        raise ReleaseError(f"{manifest} 的 files 中没有 {name}")
    recorded = entry.get("sha512")
    if recorded != expected:
        raise ReleaseError(
            f"{manifest} 中 {name} 的 SHA-512 是 {recorded}，安装程序的实际值是 {expected}")

def assemble_assets(repo_root: Path, client: dict[str, Path]) -> dict[str, Path]:
    # 第 4 步前半：把客户端构建产物复制进发布资源目录（该目录被 git 忽略）。
    # 先清空目录，避免上一次发布留下的旧文件混进 wheel
    assets_dir = repo_root / "harness" / "release_assets"
    if assets_dir.exists():
        shutil.rmtree(assets_dir)
    assets_dir.mkdir(parents=True)
    copied: dict[str, Path] = {}
    for key in ("installer", "blockmap", "manifest"):
        target = assets_dir / client[key].name
        shutil.copy2(client[key], target)
        copied[key] = target
    return copied

def build_wheel(repo_root: Path, version: str, output_dir: Path) -> Path:
    # 第 4 步后半：uv build --wheel 生成 Yudao 服务的 wheel
    output_dir.mkdir(parents=True, exist_ok=True)
    _run(["uv", "build", "--wheel", "--out-dir", str(output_dir)], cwd=repo_root)
    expected = output_dir / f"yudao_harness-{version}-py3-none-any.whl"
    if not expected.is_file():
        raise ReleaseError(f"uv build 没有生成 {expected}")
    return expected

def verify_wheel_contents(wheel: Path, assets: dict[str, Path]) -> None:
    # 核对 wheel 内含客户端安装程序、blockmap 与 latest.yml（设计说明第 6.3 节第 4 步）。
    # wheel 是一个 ZIP 包，用标准库 zipfile 读取其中的文件名
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    for key, path in assets.items():
        member = f"harness/release_assets/{path.name}"
        if member not in names:
            raise ReleaseError(f"wheel {wheel.name} 中缺少 {member}（{key}）")

def publish(repo_root: Path, version: str, wheel: Path, *, remote: str) -> None:
    # 第 5 步：仅带 --publish 时。打标签 v<版本> 并推送，
    # gh release create 把 wheel 上传到私有仓库的 Release
    tag = f"{TAG_PREFIX}{version}"
    _run(["git", "tag", tag], cwd=repo_root)
    _run(["git", "push", remote, tag], cwd=repo_root)
    _run([_tool("gh"), "release", "create", tag, str(wheel), "--title", tag,
          "--notes", f"Yudao {version}"], cwd=repo_root)

def release(repo_root: Path, *, publish_flag: bool, app_id: str, product_name: str,
            setup_basename: str, output_dir: Path, branch: str, remote: str) -> dict[str, object]:
    # 依设计说明第 6.3 节的顺序执行，返回 wheel 的路径与核对值
    version = verify(repo_root, branch=branch, remote=remote)
    client = build_client(repo_root, app_id=app_id, product_name=product_name,
                          setup_basename=setup_basename)
    verify_manifest_matches_installer(client["manifest"], client["installer"])
    assets = assemble_assets(repo_root, client)
    wheel = build_wheel(repo_root, version, output_dir)
    verify_wheel_contents(wheel, assets)
    if publish_flag:
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

    app_id = os.environ.get("YUDAO_RELEASE_APP_ID", "com.yudao.client")
    product_name = os.environ.get("YUDAO_RELEASE_PRODUCT_NAME", "Yudao")
    setup_basename = os.environ.get("YUDAO_RELEASE_SETUP_BASENAME", "Yudao-Setup")
    try:
        result = release(args.repo_root, publish_flag=args.publish, app_id=app_id,
                         product_name=product_name, setup_basename=setup_basename,
                         output_dir=args.output_dir, branch=args.branch, remote=args.remote)
    except ReleaseError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"wheel: {result['wheel']}")
    print(f"sha256: {result['sha256']}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
