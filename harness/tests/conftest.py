from pathlib import Path

import pytest

from harness.adapters.fake import clear_shared_list_scripts, shared_list_scripts


def pytest_addoption(parser):
    # 只在第一次建立事件序列基准、或行为有意改变并经架构师确认时使用；同时重写 event_sequences/*.json
    # 与 prompt_snapshot.json。只重写比对不过的基准文件，比对通过的不动（工单 #1019）
    parser.addoption("--write-event-baselines", action="store_true", default=False,
                     help="write the event sequence baselines under harness/tests/event_sequences/ and "
                          "prompt_snapshot.json that differ from the current run; baselines that still compare "
                          "equal are left untouched")
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


@pytest.fixture(autouse=True)
def _list_script_is_not_shared_by_engineering_and_quality():
    # 工单 #879：一条按先后排队的列表脚本被工程与质检同时取用时，用例失败。
    # 失败落在用例上：适配器只记下这件事（harness/adapters/fake.py），这里在用例结束时核对。
    # 在适配器里抛错会被当成模型服务的错误，事项停在 provider_error，用例报的是别处的错
    clear_shared_list_scripts()
    yield


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    # 工单 #879：记下的违反让这一项用例失败（失败落在用例上，收尾阶段不报错）
    report = yield
    if report.when != "call" or report.outcome != "passed":
        return report
    shared = shared_list_scripts()
    if not shared:
        return report
    report.outcome = "failed"
    report.longrepr = "\n".join(shared)
    return report
