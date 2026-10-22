# 发布脚本里 wheel 内容的核对（工单 #753）：发布资源目录里除页面文件以外还有接口版本这一个
# 元数据文件（工单 #704 写下），它不是页面文件，页面文件的核对不把它算成「页面构建输出以外的文件」；
# 除它以外的其它文件仍然要拒绝，元数据本身读不出版本也要拒绝。
#
# 这一层不跑真实构建：用一个假的 wheel（zip 文件）核对发布脚本的核对函数；
# 真实构建由 harness/tests/test_release_script.py（集成层）核对。

import importlib.util
import json
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_SCRIPT = REPO_ROOT / "scripts" / "release.py"
# 页面文件对应的接口版本写在发布资源目录的这个文件里（工单 #704）
PAGES_API_VERSION_FILE = "api-version.json"


def _release_module():
    # 直接加载 scripts/release.py：核对的是发布脚本自己的规则
    spec = importlib.util.spec_from_file_location("yudao_release_wheel_contents", RELEASE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _wheel(tmp_path: Path, files: dict[str, bytes]) -> Path:
    # 假的 wheel：一个 zip 文件，成员名与真实 wheel 里的相同
    path = tmp_path / "yudao_harness-0.1.1-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return path


def _pages(tmp_path: Path) -> Path:
    # 页面构建输出：入口页面与它引用的带内容摘要的文件
    built = tmp_path / "renderer"
    built.mkdir()
    (built / "index.html").write_bytes(b"<html></html>")
    (built / "assets").mkdir()
    (built / "assets" / "index-abc123.js").write_bytes(b"console.log(1)")
    return built


def test_the_api_version_file_is_not_a_foreign_page_file(tmp_path):
    # 页面文件与页面构建输出一致、发布资源目录里另有接口版本这一个元数据文件时，核对通过
    module = _release_module()
    built = _pages(tmp_path)
    wheel = _wheel(tmp_path, {
        "harness/release_assets/index.html": b"<html></html>",
        "harness/release_assets/assets/index-abc123.js": b"console.log(1)",
        f"harness/release_assets/{PAGES_API_VERSION_FILE}":
            json.dumps({"api_version": 7}).encode("utf-8"),
    })
    module.verify_wheel_contents(wheel, built)


def test_a_file_outside_the_page_output_is_still_refused(tmp_path):
    # 除接口版本以外的文件仍然要拒绝：上一次构建留下的文件不能跟着进 wheel
    module = _release_module()
    built = _pages(tmp_path)
    wheel = _wheel(tmp_path, {
        "harness/release_assets/index.html": b"<html></html>",
        "harness/release_assets/assets/index-abc123.js": b"console.log(1)",
        "harness/release_assets/stale-from-the-previous-build.html": b"stale-bytes",
    })
    try:
        module.verify_wheel_contents(wheel, built)
    except module.ReleaseError as error:
        assert "stale-from-the-previous-build.html" in str(error)
    else:
        raise AssertionError("verify_wheel_contents accepted a file outside the page output")


def test_an_unreadable_api_version_file_is_refused(tmp_path):
    # 接口版本那个文件读不出版本时也要拒绝：服务那时说不出这份页面文件对应哪个接口版本
    module = _release_module()
    built = _pages(tmp_path)
    wheel = _wheel(tmp_path, {
        "harness/release_assets/index.html": b"<html></html>",
        "harness/release_assets/assets/index-abc123.js": b"console.log(1)",
        f"harness/release_assets/{PAGES_API_VERSION_FILE}": b"not json",
    })
    try:
        module.verify_wheel_contents(wheel, built)
    except module.ReleaseError as error:
        assert PAGES_API_VERSION_FILE in str(error)
    else:
        raise AssertionError("verify_wheel_contents accepted an unreadable api version file")
