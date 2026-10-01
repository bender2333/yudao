from harness.app.client_update import NO_INSTALLER, ReleaseAssetNotFound, ReleaseAssets

# 发布资源目录（设计说明第 5.1 节）：从源码运行没有这个目录时读取以「没有客户端安装包」结束；
# 只提供目录中的文件，不接受路径分隔符与上级引用。

def test_missing_release_assets_directory_reports_no_installer(tmp_path):
    assets = ReleaseAssets(tmp_path / "release_assets")
    assert assets.available() is False
    for call in (assets.latest_manifest, lambda: assets.installer("Yudao-Setup-0.1.0.exe")):
        try:
            call()
        except ReleaseAssetNotFound as exc:
            assert NO_INSTALLER in str(exc)
        else:
            raise AssertionError("expected ReleaseAssetNotFound")

def test_release_assets_serve_files_from_the_directory(tmp_path):
    directory = tmp_path / "release_assets"
    directory.mkdir()
    (directory / "latest.yml").write_text("version: 0.1.0\n", encoding="utf-8")
    installer = directory / "Yudao-Setup-0.1.0.exe"
    installer.write_bytes(b"installer-bytes")
    assets = ReleaseAssets(directory)
    assert assets.available() is True
    assert assets.latest_manifest() == directory / "latest.yml"
    assert assets.installer("Yudao-Setup-0.1.0.exe") == installer

def test_release_assets_refuse_names_outside_the_directory(tmp_path):
    directory = tmp_path / "release_assets"
    directory.mkdir()
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    assets = ReleaseAssets(directory)
    for name in ("../secret.txt", "sub/file.exe", "", ".", ".."):
        try:
            assets.installer(name)
        except ReleaseAssetNotFound:
            pass
        else:
            raise AssertionError(f"expected ReleaseAssetNotFound for {name!r}")
