import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from harness.data_directory import (configure_logging, default_data_dir, default_dotenv,
                                    default_provider_config, user_data_root)

# 数据目录与日志的默认位置（设计说明第 3.4、4.2 节）：Windows 为 %LOCALAPPDATA%\Yudao，
# Linux 为 $XDG_DATA_HOME 或 ~/.local/share，遵守环境变量，不写用户的真实目录。

def test_windows_default_data_dir_is_local_app_data(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert user_data_root() == tmp_path / "Local"
    assert default_data_dir() == tmp_path / "Local" / "Yudao"

def test_windows_default_data_dir_falls_back_to_home(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert user_data_root() == Path.home() / "AppData" / "Local"

def test_linux_default_data_dir_follows_xdg_data_home(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    assert default_data_dir() == tmp_path / "share" / "yudao"

def test_linux_default_data_dir_falls_back_to_local_share(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert user_data_root() == Path.home() / ".local" / "share"

def test_provider_files_live_inside_the_data_dir(tmp_path):
    # Provider 目录文件与凭据文件默认在数据目录内，不相对当前目录
    assert default_provider_config(tmp_path) == tmp_path / "providers.json"
    assert default_dotenv(tmp_path) == tmp_path / ".env"

def test_logs_are_written_under_the_data_dir_and_rotate(tmp_path):
    # 日志写在 <数据目录>/logs/，处理器按大小轮换，记录能落到文件
    log_path = configure_logging(tmp_path)
    assert log_path == tmp_path / "logs" / "yudao.log"
    assert log_path.is_file()
    handler = next(item for item in logging.getLogger("uvicorn.error").handlers
                   if isinstance(item, RotatingFileHandler))
    assert handler.maxBytes > 0 and handler.backupCount >= 1
    logging.getLogger("harness").info("日志轮换的测试记录")
    handler.flush()
    assert "日志轮换的测试记录" in log_path.read_text(encoding="utf-8")
