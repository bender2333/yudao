# 数据目录与日志的默认位置（桌面客户端的安装、更新与发布设计说明第 3.4、4.2 节）。
# 默认放在用户数据目录，不相对当前目录；开发、测试与评测用 --data-dir 指向其他目录。

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# 服务的发布版本号由 pyproject.toml 的 version 决定，从这里读取时用同一个分发名称
DISTRIBUTION = "yudao-harness"
LOG_DIR = "logs"
LOG_FILE = "yudao.log"
# 单个日志文件的上限与保留份数：按大小轮换（第 4.2 节）
LOG_MAX_BYTES = 1_000_000
LOG_BACKUP_COUNT = 5

def user_data_root() -> Path:
    # 用户数据目录的根：Windows 为 %LOCALAPPDATA%，Linux 为 $XDG_DATA_HOME 或 ~/.local/share。
    # 测试用环境变量改写根，不写用户的真实目录
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        return Path(base)
    base = os.environ.get("XDG_DATA_HOME")
    return Path(base) if base else Path.home() / ".local" / "share"

def default_data_dir() -> Path:
    # 默认数据目录：Windows 为 %LOCALAPPDATA%\Yudao，Linux 为 ~/.local/share/yudao
    name = "Yudao" if sys.platform == "win32" else "yudao"
    return user_data_root() / name

def default_provider_config(data_dir_path: str | Path) -> Path:
    # Provider 目录文件默认在数据目录内，不相对当前目录
    return Path(data_dir_path) / "providers.json"

def default_dotenv(data_dir_path: str | Path) -> Path:
    # 凭据文件默认在数据目录内
    return Path(data_dir_path) / ".env"

def configure_logging(data_dir_path: str | Path) -> Path:
    # 服务日志写在 <数据目录>/logs/，按大小轮换；返回日志文件路径
    log_dir = Path(data_dir_path) / LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / LOG_FILE
    handler = RotatingFileHandler(log_path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT,
                                  encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "harness"):
        logger = logging.getLogger(name)
        for existing in list(logger.handlers):
            logger.removeHandler(existing)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return log_path
