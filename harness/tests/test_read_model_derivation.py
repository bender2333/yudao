# 读模型的推导版本（工单 #684）：改了推导方式以后旧行不会自己跟着变，
# 服务打开读取模型时按保存的版本决定要不要重建一次。
# 重建只从事件重放：不调用模型与工具，也不写事件日志。
#
# 只跑真实代码，不使用 mock。

import json
import sqlite3

from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.app.application import Application
from harness.app.project_queries import ProjectUsage
from harness.app.read_models import DERIVATION_KEY, DERIVATION_VERSION, ReadModels
from harness.models import Usage
from harness.proposals import delivery_turn, product_spec, review_turn
from harness.runtime import LoopSystem

GOAL = "把文本按行处理清楚"
# 模型报了用量：重建以后这一行应当能从工件里再算出分项
USAGE = Usage(input_tokens=100, output_tokens=20, cache_read_tokens=5, cache_write_tokens=1)


def _system(data_dir):
    return LoopSystem.for_testing(data_dir, FakeAdapter([
        FakeTurn(proposal=product_spec(), usage=USAGE),
    ]))


def _attempt_rows(data_dir):
    with sqlite3.connect(data_dir / "read-models.sqlite") as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(
            "SELECT attempt_id, record FROM app_attempts ORDER BY attempt_id")]


def _set_record(data_dir, attempt_id, record):
    with sqlite3.connect(data_dir / "read-models.sqlite") as connection:
        connection.execute("UPDATE app_attempts SET record = ? WHERE attempt_id = ?",
                           (json.dumps(record), attempt_id))


def _break_all_records(data_dir):
    # 把每一行的分项改成空：模拟修复以前写下来的旧行
    with sqlite3.connect(data_dir / "read-models.sqlite") as connection:
        connection.execute("UPDATE app_attempts SET record = ?", (json.dumps({
            "usage": {"input_tokens": None, "output_tokens": None,
                      "cache_read_tokens": None, "cache_write_tokens": None,
                      "total_tokens": None, "coverage": {"input_tokens": "missing"}},
        }),))


def _derivation_version(data_dir):
    with sqlite3.connect(data_dir / "read-models.sqlite") as connection:
        row = connection.execute("SELECT value FROM app_read_meta WHERE key = ?",
                                 (DERIVATION_KEY,)).fetchone()
    return None if row is None else row[0]


def _set_derivation_version(data_dir, value):
    with sqlite3.connect(data_dir / "read-models.sqlite") as connection:
        connection.execute("INSERT OR REPLACE INTO app_read_meta (key, value) VALUES (?, ?)",
                           (DERIVATION_KEY, value))


def _usage_of(record):
    return json.loads(record)["usage"]


def test_the_read_model_records_its_derivation_version_and_rebuilds_when_it_changed(data_dir):
    system = _system(data_dir)
    system.activate_once(system.create_run("echo"))
    end_position = system.store.end_position()
    calls = len(system.test_adapter.invocations)
    path = data_dir / "read-models.sqlite"

    # 第一次打开：没有版本记录（旧数据目录），重建一次并写下版本
    first = ReadModels(system.store, system.artifacts, path)
    rows = _attempt_rows(data_dir)
    assert rows, "没有调用尝试行"
    assert _derivation_version(data_dir) == str(DERIVATION_VERSION)
    usage = _usage_of(rows[0]["record"])
    # 重建以后这一行的用量分项按当前代码算出来了（输入含装配的上下文，比模型报的多几个 token）
    assert usage["input_tokens"] is not None and usage["output_tokens"] is not None
    assert usage["coverage"]["input_tokens"] == "reported"
    assert usage["coverage"]["output_tokens"] == "reported"
    # 重建不调用模型与工具，也不写事件日志
    assert len(system.test_adapter.invocations) == calls
    assert system.store.end_position() == end_position
    first.close()

    # 旧行不会因为算法改了而自己变好：把一行改坏
    _set_record(data_dir, rows[0]["attempt_id"], {"usage": {"input_tokens": None}})

    # 版本相同：重新打开时不重建，这一行仍然是坏的
    same = ReadModels(system.store, system.artifacts, path)
    assert _usage_of(_attempt_rows(data_dir)[0]["record"])["input_tokens"] is None
    same.close()

    # 版本不同（模拟改了推导方式）：重新打开时重建，行按当前代码重算
    _set_derivation_version(data_dir, "0")
    changed = ReadModels(system.store, system.artifacts, path)
    rebuilt = _usage_of(_attempt_rows(data_dir)[0]["record"])
    assert rebuilt["input_tokens"] is not None and rebuilt["output_tokens"] is not None
    assert rebuilt["coverage"]["input_tokens"] == "reported"
    assert _derivation_version(data_dir) == str(DERIVATION_VERSION)
    # 重建仍然不调用模型与工具，也不写事件日志
    assert len(system.test_adapter.invocations) == calls
    assert system.store.end_position() == end_position
    changed.close()


def test_the_usage_report_shows_the_breakdown_again_after_the_read_model_rebuilt(data_dir):
    # 观测页的用量统计读的是 project.usage：重建以后这一栏要重新有分项
    script = [
        FakeTurn(proposal=product_spec(), usage=USAGE),
        FakeTurn(proposal=delivery_turn(), usage=USAGE),
        FakeTurn(proposal=review_turn("release", "checks passed"), usage=USAGE),
    ]
    system = LoopSystem.for_testing(data_dir, FakeAdapter(script))
    project_id = system.projects.register("用量", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    system.run_until_stop(run_id)

    application = Application(system)
    totals = application.query("project.usage", ProjectUsage(project_id=project_id)).data.totals
    assert totals.attempts > 0
    assert totals.input_tokens is not None and totals.output_tokens is not None
    assert totals.cache_read_tokens is not None
    application.close()

    # 把所有行的分项改成空：模拟修复以前写下来的旧行
    _break_all_records(data_dir)

    # 版本相同：重新打开不重建，这一栏仍然是空的
    same = Application(LoopSystem(data_dir))
    totals = same.query("project.usage", ProjectUsage(project_id=project_id)).data.totals
    assert totals.reported == 0
    assert totals.input_tokens is None
    same.close()

    # 版本改成旧值：重新打开时重建，这一栏按当前代码算出来
    _set_derivation_version(data_dir, "0")
    changed = Application(LoopSystem(data_dir))
    totals = changed.query("project.usage", ProjectUsage(project_id=project_id)).data.totals
    assert totals.reported > 0
    assert totals.input_tokens is not None and totals.output_tokens is not None
    assert totals.cache_read_tokens is not None
    changed.close()
