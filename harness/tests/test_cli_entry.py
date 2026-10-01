# 命令行入口（工单 #206，设计说明第 4.1 节）：yudao --version 输出发布版本号；
# 从源码运行时 yudao client install 说明没有随包的安装程序并以非零状态退出。

import sys
from importlib.metadata import version

from harness import __main__ as cli
from harness.__main__ import build_parser, default_data_dir, main, release_version

def test_version_option_prints_the_release_version(capsys):
    assert release_version() == version("yudao-harness")
    try:
        build_parser().parse_args(["--version"])
    except SystemExit as exit_code:
        assert exit_code.code == 0
    assert capsys.readouterr().out.strip() == release_version()

def test_default_data_dir_follows_the_user_data_root(tmp_path, monkeypatch):
    # 测试用环境变量改写用户数据目录的根，不写用户的真实目录
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert default_data_dir() == tmp_path / "Yudao"

def test_client_install_without_a_bundled_installer_exits_nonzero(tmp_path, monkeypatch, capsys):
    # 从源码运行没有发布资源目录：说明原因并以非零状态退出。把发布资源指向一个不存在的目录，保证确定
    from harness.app.client_update import ReleaseAssets
    monkeypatch.setattr(cli, "ReleaseAssets", lambda: ReleaseAssets(tmp_path / "absent"))
    assert main(["client", "install"]) == 1
    error = capsys.readouterr().err
    assert "no client installer" in error and "没有客户端安装包" in error
