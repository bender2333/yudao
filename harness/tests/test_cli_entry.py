# 命令行入口（工单 #206，设计说明第 4.1 节）：yudao --version 输出发布版本号；
# 从源码运行时 yudao client install 说明没有随包的安装程序并以非零状态退出。
# 模型目录与凭据文件的默认位置（工单 #298，设计说明第 3.4 节）：按生效的 --data-dir 求出

import sys
from importlib.metadata import version
from pathlib import Path

from harness import __main__ as cli
from harness.__main__ import build_parser, default_data_dir, main, release_version, _provider_paths
from harness.data_directory import default_dotenv, default_provider_config

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

def test_the_catalog_and_credentials_default_to_the_data_directory(tmp_path):
    # 没有明确给 --provider-config 时目录文件在 --data-dir 内，admissions.json 由门面按同目录派生
    data_dir = tmp_path / "data"
    parsed = build_parser().parse_args(["--data-dir", str(data_dir), "api"])
    assert parsed.provider_config is None
    config, dotenv = _provider_paths(parsed.data_dir, parsed.provider_config)
    assert config == (data_dir / "providers.json").resolve()
    assert dotenv == default_dotenv(data_dir).resolve()

def test_an_explicit_provider_config_wins_over_the_data_directory(tmp_path):
    # 明确给了 --provider-config 时以它为准，凭据文件仍在数据目录内
    data_dir = tmp_path / "data"
    elsewhere = tmp_path / "elsewhere" / "catalog.json"
    parsed = build_parser().parse_args(["api", "--data-dir", str(data_dir),
                                       "--provider-config", str(elsewhere)])
    config, dotenv = _provider_paths(parsed.data_dir, parsed.provider_config)
    assert config == elsewhere.resolve()
    assert dotenv == default_dotenv(data_dir).resolve()

def test_an_empty_provider_config_reads_no_catalog(tmp_path):
    # 空字符串表示不读取目录文件（服务锁与发布验收的测试这样启动空态服务）
    config, dotenv = _provider_paths(tmp_path / "data", "")
    assert config is None
    assert dotenv == default_dotenv(tmp_path / "data").resolve()

def test_the_default_data_directory_keeps_the_previous_locations(tmp_path, monkeypatch):
    # 默认数据目录下的行为与改动前相同：两个默认值都来自用户数据目录内的默认数据目录
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    parsed = build_parser().parse_args([])
    assert parsed.data_dir == str(default_data_dir())
    assert parsed.provider_config is None
    config, dotenv = _provider_paths(Path(parsed.data_dir), parsed.provider_config)
    assert config == default_provider_config(tmp_path / "Yudao")
    assert dotenv == default_dotenv(tmp_path / "Yudao")
