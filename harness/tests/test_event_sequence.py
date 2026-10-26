# 事件序列基准（docs/design/test-pyramid.md，ADR-0019）：每个场景跑完以后，把规整后的事件序列与
# harness/tests/event_sequences/<场景名>.json 比较；规整规则与基准文件的结构见 event_sequence.py。
# 基准与当前运行不一致说明行为改变：修正代码，不更新基准。只有架构师确认的有意改变才用
# python -m pytest harness/tests/test_event_sequence.py --write-event-baselines 重写基准，并在提交说明中写明原因；
# 这个开关只重写比对不过的文件，比对通过的不动（工单 #1019），第二次运行不改任何文件。
# 场景本身（脚本、驱动与替换规则）在 event_scenarios.py，其他测试也按名字取一个场景跑完整序列。

import difflib
import json
from pathlib import Path

import pytest

from harness.tests.contract_checks import assert_payloads_follow_contract
from harness.tests.event_scenarios import SCENARIOS
from harness.tests.event_sequence import compare_with_baseline, normalized_run, prompt_entries
from harness.streams import RUN_EVENT_VERSION

# 投影里的事件版本号不进每个场景的比对（工单 #1019）：升版不让全部基准一起重写，由下面这一条
# 单独核对当前值。升版时把这里的数字一起改，改动本身就是要评审的那一处。
# 基准的投影里没有它（生成规则）、只差这一项时比对通过，各自在 test_event_sequence_compare.py。
EXPECTED_RUN_EVENT_VERSION = 11


def test_the_current_run_event_version_is_the_expected_one():
    assert RUN_EVENT_VERSION == EXPECTED_RUN_EVENT_VERSION, (
        f"当前 run 事件版本是 {RUN_EVENT_VERSION}，基准与这条测试记的是 {EXPECTED_RUN_EVENT_VERSION}；"
        "有意升版时改这里，事件序列基准不再随版本号重写")


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_event_sequence_matches_its_baseline(name, data_dir, request):
    scenario = SCENARIOS[name]
    system, run_id, replacements = scenario.run(data_dir)
    assert system.project(run_id).canonical_state() == system.replay(run_id).canonical_state()
    # 每条事件的载荷都符合应用层合同中的载荷类型
    assert_payloads_follow_contract(system.store.list_events(run_id))
    compare_with_baseline(name, scenario.covers, normalized_run(system, run_id, replacements),
                          write=request.config.getoption("--write-event-baselines"))


# 部门提示与工具说明快照（#532 步骤 3）：这四个场景各自跑一遍，合并 prompt_entries 的结果与
# harness/tests/prompt_snapshot.json 比较。快照集中记录发出去的部门材料与工具说明，
# 事件序列基准里不再出现它们的全文。故意改变时用 --write-event-baselines 重写。
# 只回应指导的那种轮次随工单 #560 删除，tool_denied_guidance_only 场景随之删除。
SNAPSHOT_SCENARIOS = ("handoff_release", "compaction_success",
                      "guidance_answered",
                      "ask_answer_with_spec_revision")


def _snapshot_entries(request) -> dict[str, dict]:
    entries: dict[str, dict] = {}
    origins: dict[str, str] = {}
    for name in SNAPSHOT_SCENARIOS:
        scenario = SCENARIOS[name]
        data_dir = request.getfixturevalue("tmp_path") / name
        data_dir.mkdir()
        system, run_id, _ = scenario.run(data_dir)
        for key, entry in prompt_entries(system, run_id).items():
            if key in entries and entries[key] != entry:
                raise AssertionError(f"prompt snapshot key {key} differs between {origins[key]} and {name}")
            entries[key] = entry
            origins.setdefault(key, name)
    return entries


def test_prompt_snapshot_matches(request):
    actual = _snapshot_entries(request)
    path = Path(__file__).resolve().parent / "prompt_snapshot.json"
    if request.config.getoption("--write-event-baselines"):
        path.write_text(json.dumps(actual, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8", newline="\n")
        return
    expected = json.loads(path.read_text(encoding="utf-8"))
    if expected != actual:
        raise AssertionError("prompt snapshot differs from harness/tests/prompt_snapshot.json:\n"
                             + "\n".join(difflib.unified_diff(
                                 json.dumps(expected, ensure_ascii=False, indent=1, sort_keys=True).splitlines(),
                                 json.dumps(actual, ensure_ascii=False, indent=1, sort_keys=True).splitlines(),
                                 "snapshot", "actual", lineterm="", n=2)))
