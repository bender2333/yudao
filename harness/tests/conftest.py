from pathlib import Path

import pytest


def pytest_addoption(parser):
    # 只在第一次建立事件序列基准、或行为有意改变并经架构师确认时使用
    parser.addoption("--write-event-baselines", action="store_true", default=False,
                     help="write harness/tests/event_sequences/*.json from the current run instead of comparing")


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "loop"
