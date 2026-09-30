from pathlib import Path

import pytest


def pytest_addoption(parser):
    # 只在第一次建立事件序列基准、或行为有意改变并经架构师确认时使用
    parser.addoption("--write-event-baselines", action="store_true", default=False,
                     help="write harness/tests/event_sequences/*.json from the current run instead of comparing")
    # 只在合同有意改变时使用：重写 OpenAPI 快照，提交前用 git diff 核对变化
    parser.addoption("--write-openapi-snapshot", action="store_true", default=False,
                     help="write harness/tests/openapi/openapi.json from the running service instead of comparing")
    # 只在项目流新增事件种类或新增字段时使用：把新的种类与字段写入清单并在 added_defaults 写明缺省含义；
    # 删除种类、删除字段或改变字段类型时拒绝写入；清单文件缺失时不重建，从 git 历史恢复
    parser.addoption("--write-project-stream-fields", action="store_true", default=False,
                     help="add newly declared project-stream kinds and fields to harness/tests/project_stream_fields.json")


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "loop"
