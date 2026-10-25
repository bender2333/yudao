# 命令行入口（工单 #206、#373，设计说明第 4.1 节）：yudao --version 输出发布版本号。
# 模型目录与凭据文件的默认位置（工单 #298，设计说明第 3.4 节）：按生效的 --data-dir 求出。
# --data-dir 与 --provider-config 写在子命令之前或之后都生效（工单 #315）：解析器自身不给默认值，
# 生效值由 _data_dir 按子命令求出。
#
# 工单 #373 以后 yudao client install 子命令不再提供，界面改为服务提供的网页。


from importlib.metadata import version

from harness.__main__ import _data_dir, build_parser, release_version, _provider_paths
from harness.data_directory import default_dotenv

def test_version_option_prints_the_release_version(capsys):
    assert release_version() == version("yudao-harness")
    try:
        build_parser().parse_args(["--version"])
    except SystemExit as exit_code:
        assert exit_code.code == 0
    assert capsys.readouterr().out.strip() == release_version()


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


def test_smoke_takes_the_provider_config_from_either_position(tmp_path):
    # 写在 smoke 之前与之后的 --provider-config 都生效；两处都没有给出时按生效的数据目录求出
    for argv in (["--provider-config", str(tmp_path / "before.json"), "smoke"],
                 ["smoke", "--provider-config", str(tmp_path / "after.json")]):
        parsed = build_parser().parse_args(argv)
        assert parsed.provider_config == argv[argv.index("--provider-config") + 1]
    parsed = build_parser().parse_args(["--data-dir", str(tmp_path / "data"), "smoke"])
    config, dotenv = _provider_paths(_data_dir(parsed, "smoke"), parsed.provider_config)
    assert config == (tmp_path / "data" / "providers.json").resolve()
    assert dotenv == default_dotenv(tmp_path / "data").resolve()


def test_release_check_takes_the_repository_and_the_data_directory_from_either_position(tmp_path):
    # 发布检查（工单 #355）：待发布仓库是位置参数，--data-dir 写在子命令之前或之后都生效
    before = build_parser().parse_args(["--data-dir", str(tmp_path), "release-check", "some-repo"])
    assert before.command == "release-check" and before.repository == "some-repo"
    assert _data_dir(before, "release-check") == str(tmp_path)
    after = build_parser().parse_args(["release-check", "some-repo", "--data-dir", str(tmp_path)])
    assert after.command == "release-check" and after.repository == "some-repo"
    assert _data_dir(after, "release-check") == str(tmp_path)
