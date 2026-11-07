# 故障矩阵第 11 行：用量/费用缺失、评价分母为空（恢复契约与故障矩阵 docs/design/recovery-contract-and-fault-matrix.md「故障矩阵」）。
# 一整轮三部门循环里每一次模型请求都没有上报用量：用量汇总的每一项是未知（空），不是零；
# 费用同样未知；用书本地的用时照常累加。离开期间的报告没有来源事件的项不显示，不写成一个零。
# 评价分母为空的那一半在评测工具里（evals/），本工单与 harness/tests 不覆盖它；这一条不把它写成通过。
#
# 层：集成层（完整的三部门循环、真实事件库与读模型）。
# 守 R2（用量查询的交换字段：未上报的项为空）与 R3（用量缺失显示未知、不记零费用）。

from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.app.home import AwayReportRequest
from harness.app.project_queries import ProjectAttempts, ProjectUsage
from harness.proposals import delivery_turn, product_spec_turn
from harness.runtime import LoopSystem
from harness.tests.helpers import quality_turns

USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
                "total_tokens", "cost")


def test_missing_usage_is_unknown_and_never_recorded_as_zero(tmp_path):
    # 故障矩阵第 11 行：每一次模型请求都没有上报用量：汇总里每一项用量是空（未知），不是零；上报次数是零
    system = LoopSystem.for_testing(tmp_path / "data", FakeAdapter({
        "product": [product_spec_turn()],
        "engineering": [delivery_turn()],
        "quality": quality_turns("release", "checks passed on the current snapshot"),
    }))
    try:
        project_id = system.projects.register("用量未知", "核对缺失的用量不记成零")
        work_item_id, run_id = system.projects.start_work_item(project_id, "没有上报用量的一轮")
        result = system.run_until_stop(run_id)
        assert result.status == "done", (result.status, result.stop_reason, result.error)

        application = Application(system)
        usage = application.query("project.usage", ProjectUsage(
            project_id=project_id, work_item=work_item_id)).data
        assert usage.totals.attempts >= 3
        assert usage.totals.reported == 0
        for field in USAGE_FIELDS:
            assert getattr(usage.totals, field) is None, field
        for group in (*usage.departments, *usage.models):
            assert group.reported == 0
            for field in USAGE_FIELDS:
                assert getattr(group, field) is None, (group.key, field)

        # 每次尝试的用量都是未知（没有上报），没有一次写成上报的零
        rows = application.query("project.attempts", ProjectAttempts(
            project_id=project_id, work_item=work_item_id)).data.attempts
        assert rows
        assert all(row.usage.get("source") in {"unknown", "missing"} for row in rows)
        assert not any(row.usage.get("reported") is True for row in rows)
        assert all(row.usage.get("total_tokens") is None for row in rows)

        # 离开期间的报告不显示用量一项：没有来源事件的项不返回，不写成一个零
        report = application.query("home.away_report", AwayReportRequest(range="7d")).data
        assert "usage" not in {item.id for item in report.summary}
    finally:
        system.close()
