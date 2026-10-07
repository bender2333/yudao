# 事件序列基准（docs/design/test-pyramid.md，ADR-0019）：每个场景跑完以后，把规整后的事件序列与
# harness/tests/event_sequences/<场景名>.json 比较；规整规则与基准文件的结构见 event_sequence.py。
# 基准与当前运行不一致说明行为改变：修正代码，不更新基准。只有架构师确认的有意改变才用
# python -m pytest harness/tests/test_event_sequence.py --write-event-baselines 重写基准，并在提交说明中写明原因。
# 场景本身（脚本、驱动与替换规则）在 event_scenarios.py，其他测试也按名字取一个场景跑完整序列。

import pytest

from harness.tests.contract_checks import assert_payloads_follow_contract
from harness.tests.event_scenarios import SCENARIOS
from harness.tests.event_sequence import compare_with_baseline, normalized_run


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_event_sequence_matches_its_baseline(name, data_dir, request):
    scenario = SCENARIOS[name]
    system, run_id, replacements = scenario.run(data_dir)
    assert system.project(run_id).canonical_state() == system.replay(run_id).canonical_state()
    # 每条事件的载荷都符合应用层合同中的载荷类型
    assert_payloads_follow_contract(system.store.list_events(run_id))
    compare_with_baseline(name, scenario.covers, normalized_run(system, run_id, replacements),
                          write=request.config.getoption("--write-event-baselines"))
