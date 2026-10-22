# 页面文件对应的接口版本（工单 #704）：发布脚本写下的那个文件，服务读出来写进日志。
# 页面与服务不匹配时，运维与日志能说清是哪一边落后了。

import json

from harness.api import pages as pages_module


def test_the_pages_api_version_is_read_from_the_release_assets(tmp_path, monkeypatch):
    assets = tmp_path / "release_assets"
    assets.mkdir()
    (assets / pages_module.PAGES_API_VERSION_FILE).write_text(
        json.dumps({"api_version": 7}), encoding="utf-8")
    monkeypatch.setattr(pages_module, "RELEASE_ASSETS", assets)
    assert pages_module.pages_api_version() == 7


def test_without_pages_or_without_a_version_it_says_nothing(tmp_path, monkeypatch):
    assets = tmp_path / "release_assets"
    assets.mkdir()
    monkeypatch.setattr(pages_module, "RELEASE_ASSETS", assets)
    assert pages_module.pages_api_version() is None
    (assets / pages_module.PAGES_API_VERSION_FILE).write_text("不是 JSON", encoding="utf-8")
    assert pages_module.pages_api_version() is None
