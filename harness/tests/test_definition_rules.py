# 定义、限额与视图计算的纯规则：定义只加载一次并带内容摘要、限额规则的现值与 bounds、
# 建档工作说明写明的材料种类、压缩覆盖范围的序列区间。这些结论只读取仓库内的定义与纯函数，登记为单元层。

from harness.definitions import DEFINITIONS, load_definitions
from harness.parameters import NOT_WIRED_REASONS, not_wired_reason, wired


def test_shipped_definitions_are_loaded_once_at_import():
    loaded = load_definitions()
    assert loaded == DEFINITIONS
    assert DEFINITIONS.version.startswith("sha256:") and len(DEFINITIONS.version) == len("sha256:") + 64


def test_every_registered_rule_has_a_wiring_conclusion():
    # 守 R2（对外合同：规则登记的 wired 与 not_wired_reason 两个字段）与 R3 的阶段二要求：
    # 登记如实说明哪些条目已经接入行为。已接入的是这一组，接入一项要同时有消费者、改这份清单与用例
    assert set(NOT_WIRED_REASONS) == set(DEFINITIONS.rules)
    assert all(reason == reason.strip() for reason in NOT_WIRED_REASONS.values())
    assert {name for name in DEFINITIONS.rules if wired(name)} == {
        "max_cycles", "run_time_limit_sec", "check_timeout_sec", "onboarding.round_time_limit_sec",
        "organization.ask_chain_max_depth",
        # 工单 #1189：建 run 时冻结的 10 个参数与 3 条可见范围
        "tool_call_required_limit", "max_model_steps", "max_provider_attempts",
        "retry_initial_delay_sec", "retry_max_delay_sec", "tool_output_limit",
        "bash_timeout_default_sec", "bash_timeout_max_sec", "check_timeout_max_sec",
        "compaction.stalled_limit",
        "roles.product.visibility", "roles.engineering.visibility", "roles.quality.visibility",
    }
    assert all(NOT_WIRED_REASONS[name] for name in DEFINITIONS.rules if not wired(name))


def test_the_evaluation_run_limit_starts_at_120_minutes_and_has_no_consumer():
    # 守 R3（评测场景设计说明第 3 节的每次运行 120 分钟）：初值是 120 分钟；
    # 两个独立运行器读自己的默认值，不读运行时规则，所以这条登记保持未接入（#324）
    assert DEFINITIONS.rule_value("evaluation.run_minutes") == 120
    assert wired("evaluation.run_minutes") is False
    assert not_wired_reason("evaluation.run_minutes")


def test_model_test_request_timeout_matches_the_design():
    # R2：模型测试的等待上限属于规则登记合同；参数事件尚未接入，接入说明如实声明初值消费者。
    rule = DEFINITIONS.rule("provider.model_test_timeout_sec")
    assert rule.value == 60 and list(rule.bounds) == [10, 300]
    assert "模型测试" in rule.origin and "model-management.md" in rule.origin
    assert not_wired_reason("provider.model_test_timeout_sec")


def test_model_test_concurrency_matches_the_selection_contract():
    # R2：选用并发登记的初值、上下界、来源和现值消费者属于公开规则合同。
    rule = DEFINITIONS.rule("provider.model_test_max_concurrent")
    assert rule.value == 3 and list(rule.bounds) == [1, 8]
    assert "model-management.md" in rule.origin and "选用" in rule.origin
    assert wired("provider.model_test_max_concurrent") is True


