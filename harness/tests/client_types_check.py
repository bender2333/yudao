# 客户端生成的接口类型与 OpenAPI 快照保持一致的检查。
# client/src/renderer/src/api/generated/ 由 client/scripts/generate-api.mjs 从
# harness/tests/openapi/openapi.json 生成并提交。这里按快照重新生成到临时目录，与提交的
# 客户端类型逐文件比较；改动接口合同的工单必须同时提交重新生成的客户端类型，
# 否则由 test_openapi_snapshot.py 内的检查失败。只用于测试，不进入运行时。

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

# 仓库根、快照、客户端生成目录与生成工具的位置
REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = REPO_ROOT / "harness" / "tests" / "openapi" / "openapi.json"
OPENAPI_DIR = REPO_ROOT / "harness" / "tests" / "openapi"
COMMITTED_TYPES = REPO_ROOT / "client" / "src" / "renderer" / "src" / "api" / "generated"
INTERFACE_VERSION = REPO_ROOT / "client" / "src" / "renderer" / "src" / "api" / "interface-version.ts"
# 生成临时目录的父目录：仓库内的中间结果目录（已在 .gitignore 中），每次调用在其中建独立子目录
WORK_DIR = REPO_ROOT / ".tmp" / "client-types-check"


def _openapi_ts_entry() -> Path:
    """openapi-ts 的入口脚本；生成工具安装在 openapi 检查目录的 node_modules 中。"""
    return OPENAPI_DIR / "node_modules" / "@hey-api" / "openapi-ts" / "bin" / "run.js"


def _generate(destination: Path) -> None:
    """按快照生成 TypeScript 类型到 destination。"""
    entry = _openapi_ts_entry()
    if not entry.exists():
        raise AssertionError(
            f"openapi-ts 未安装：{entry}\n"
            "在 harness/tests/openapi 下运行 npm install"
        )
    result = subprocess.run(
        ["node", str(entry), "-i", str(SNAPSHOT), "-o", str(destination)],
        cwd=OPENAPI_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            "按快照生成客户端类型失败：\n" + (result.stdout or "") + (result.stderr or "")
        )


def _relative_files(root: Path) -> set:
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}


def _normalized(path: Path) -> str:
    """统一换行以后的内容：Windows 上 core.autocrlf 会把提交的 LF 检出为 CRLF。"""
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _interface_version_matches(snapshot_api_version: int) -> bool:
    """提交的 interface-version.ts 是否记录快照的接口版本。"""
    if not INTERFACE_VERSION.exists():
        return False
    text = _normalized(INTERFACE_VERSION)
    return f"export const CLIENT_API_VERSION = {snapshot_api_version};" in text


def check_client_types() -> list:
    """按快照生成客户端类型并与提交的生成目录比较，返回不一致的文件路径清单。

    空清单表示提交的客户端类型与快照一致。清单中的每一项写明相对路径与不一致的原因，
    供调用方的断言直接引用。
    """
    document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    api_version = document["components"]["schemas"]["Deployment"]["properties"]["api_version"]["example"]

    if not COMMITTED_TYPES.is_dir():
        return [f"{COMMITTED_TYPES}: 目录不存在"]

    # 每次调用用独立的临时目录：多个进程同时运行这一检查时不会互相删除生成结果
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(dir=WORK_DIR))
    try:
        _generate(work_dir)
        generated = _relative_files(work_dir)
        committed = _relative_files(COMMITTED_TYPES)

        differences = []
        for relative in sorted(generated - committed):
            differences.append(f"缺少文件：{relative}")
        for relative in sorted(committed - generated):
            differences.append(f"多余文件：{relative}")
        for relative in sorted(generated & committed):
            if _normalized(work_dir / relative) != _normalized(COMMITTED_TYPES / relative):
                differences.append(f"内容不同：{relative}")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    if not _interface_version_matches(api_version):
        differences.append(
            f"接口版本不同：interface-version.ts 未记录 {api_version}"
        )

    return differences
