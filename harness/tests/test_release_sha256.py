# 发布脚本 sha256_hex 的单元层核对（工单 #1011）：集成层的 test_release_script.py 要构建一次
# wheel 才间接核到它，这里按同一个函数直接比对期望值，三层输入都用仓库内的静态文件：
# 空文件、内容为 abc 的夹具（harness/tests/data/sha256_abc.txt）、跨过 1 MiB 分块边界的大文件。

import hashlib
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_SCRIPT = REPO_ROOT / "scripts" / "release.py"
EMPTY_FILE = Path(__file__).resolve().parent / "__init__.py"
ABC_FILE = REPO_ROOT / "harness" / "tests" / "data" / "sha256_abc.txt"
LARGE_FILE = REPO_ROOT / "client" / "tests" / "fixtures" / "floor" / "recordings.json"

CHUNK = 1024 * 1024
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
ABC_SHA256 = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def _release():
    # 按文件路径加载发布脚本（scripts 目录不是安装包），只取 sha256_hex，不执行 main
    spec = importlib.util.spec_from_file_location("release", RELEASE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_sha256_hex_of_empty_file():
    assert EMPTY_FILE.stat().st_size == 0
    assert _release().sha256_hex(EMPTY_FILE) == EMPTY_SHA256


def test_sha256_hex_of_abc_file():
    assert ABC_FILE.read_bytes() == b"abc"
    assert _release().sha256_hex(ABC_FILE) == ABC_SHA256


def test_sha256_hex_of_file_larger_than_one_chunk():
    content = LARGE_FILE.read_bytes()
    assert len(content) > CHUNK
    assert _release().sha256_hex(LARGE_FILE) == hashlib.sha256(content).hexdigest()
