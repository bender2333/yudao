# 检验的有效性（验证的独立性设计说明「检验的有效性」，工单 #1181）：新功能的检验在基线快照上失败、
# 在交付快照上通过，两次都由主机执行。run_baseline_check 由主机在基线副本上运行同名交付检查：
# 基线副本 = 事项起点树 + 质检测试材料 + 声明涉及的交付文件（必须在起点到交付的改动清单里）；
# 命令取交付检查已经记录的那一条，质检不能改写；时限、输出截断、进程树清理与树变化核对与 run_check 相同。
# 基线回执先写进检查工作区（提交放行决定读取事实时它已经在了）；退出码非零且不是 124/130 时基线失败，
# 交付检查通过才计入检验覆盖；基线通过、缺少回执、超时或取消不计入，写进放行记录。
#
# 层：模块层。直接构造执行环境跑真实的基线检查进程（与 test_tools.py 的 run_check 用例同一层），
# 覆盖计数与放行记录的核对是纯函数与收紧检查的内存判断；不起完整三部门循环。
# 守 R2（基线回执是工作区事实，覆盖计数读它）与 R3（口径）。

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

from harness.actions import CheckReceipt, FactsQuery, TreeFacts
from harness.adapters.fake import FakeAdapter
from harness.coverage import (BASELINE_UNAVAILABLE, baseline_open_records, baseline_outcome,
                              baseline_records, coverage_report)
from harness.environment import LocalEnvironment
from harness.models import ArtifactRef, DeliverySpec, EffectiveContract, SessionRecord
from harness.public_tree import CapturedFile, CapturedTree
from harness.proposals import product_spec
from harness.runtime import LoopSystem
from harness.tests.helpers import perform
from harness.workspace import Workspace

START_FILE = "src/lib.py"
START_BODY = "VALUE = 1\n"
DELIVERY_BODY = "VALUE = 2\n"
QA_TEST = ".yudao-qa-tests/test_value.py"
QA_TEST_BODY = "import sys\nsys.exit(0)\n"
PYTHON = sys.executable.replace("\\", "/")


def _tree(*files: tuple[str, str]) -> CapturedTree:
    directories = tuple(sorted({path.rsplit("/", 1)[0] for path, _body in files if "/" in path}))
    return CapturedTree(directories=directories, files=tuple(
        CapturedFile(path, body.encode("utf-8")) for path, body in sorted(files)))


def _baseline_environment(tmp_path: Path, *, command: str = f'"{PYTHON}" -c "print(\'smoke\')"',
                          declared: list[str] | None = None,
                          exit_code: str = "0") -> LocalEnvironment:
    # 一台绑定好基线来源的执行环境：起点树一个文件、交付树改了它，交付记录同名检查的命令，
    # 质检的检查材料已在检查工作区。直接构造环境（与 test_qa_test_materials.py 的做法一致）
    start = _tree((START_FILE, START_BODY))
    sealed = _tree((START_FILE, DELIVERY_BODY))
    workspace = Workspace(tmp_path / "run")
    workspace.write_file(QA_TEST, QA_TEST_BODY)
    environment = LocalEnvironment(workspace, check_timeout_sec=60)
    environment.bind_baseline_source(start, (START_FILE,))
    environment.bind_delivery_checks(
        [{"name": "smoke", "exit_code": 0, "summary": "ran", "command": command}], sealed)
    return environment


def _baseline_call(name: str = "smoke", **files) -> dict[str, object]:
    args: dict[str, object] = {"name": name}
    if files:
        args.update(files)
    return args


def test_baseline_runs_the_recorded_command_on_start_plus_declared_files(tmp_path):
    # 验收第 1、4 条：基线副本是起点树加声明的交付文件，命令取交付检查记录的那一条；
    # 检查读到的是交付的新值（基线失败的前半段——起点只有旧值，声明的文件把它改成新值）
    command = f'"{PYTHON}" -c "from src.lib import VALUE; print(\'VALUE=\', VALUE)"'
    environment = _baseline_environment(tmp_path, command=command, declared=[START_FILE])
    result = perform(environment, "run_baseline_check",
                     _baseline_call("smoke", files=[START_FILE]), department="quality")
    assert result.ok, result.error
    assert result.output["baseline"] is True
    assert "VALUE= 2" in result.output["summary"], result.output["summary"]
    assert result.output["exit_code"] == 0


def test_baseline_copy_keeps_the_start_tree_for_undeclared_paths(tmp_path):
    # 验收第 1 条：起点树的文件都在，声明的文件只是叠加在它上面——没有声明的文件保持起点的旧值
    command = f'"{PYTHON}" -c "print(open(\'src/lib.py\').read().strip())"'
    environment = _baseline_environment(tmp_path, command=command)
    result = perform(environment, "run_baseline_check", _baseline_call("smoke", files=[]),
                     department="quality")
    assert result.ok, result.error
    assert "VALUE = 1" in result.output["summary"], result.output["summary"]


def test_baseline_carries_the_qa_test_materials(tmp_path):
    # 验收第 1 条：质检测试材料同时存在于基线与交付副本——材料在检查工作区里，基线副本带它
    command = f'"{PYTHON}" {QA_TEST}'
    environment = _baseline_environment(tmp_path, command=command)
    result = perform(environment, "run_baseline_check", _baseline_call("smoke", files=[]),
                     department="quality")
    assert result.ok, result.error
    assert result.output["exit_code"] == 0


def test_baseline_declared_file_must_be_in_the_change_list(tmp_path):
    # 验收第 2 条：声明的交付文件逐项核对属于起点到交付的改动清单——不在清单里的路径拒绝执行
    environment = _baseline_environment(tmp_path)
    result = perform(environment, "run_baseline_check",
                     _baseline_call("smoke", files=["src/other.py"]), department="quality")
    assert result.ok is False
    assert "changed between the start tree and the delivery" in (result.error or "")


def test_baseline_ignores_a_command_argument_and_rejects_an_unknown_check_name(tmp_path):
    # 验收第 4 条：命令取已记录的交付命令——模型给的 command 参数不改变主机运行的那一条；
    # 没有同名记录的检查名拒绝执行，写明要先跑交付检查
    environment = _baseline_environment(
        tmp_path, command=f'"{PYTHON}" -c "print(\'RECORDED_COMMAND_RAN\')"')
    result = perform(environment, "run_baseline_check",
                     {"name": "smoke", "command": f'"{PYTHON}" -c "print(\'NOT_USED\')"'},
                     department="quality")
    assert result.ok, result.error
    assert "RECORDED_COMMAND_RAN" in result.output["summary"]
    assert "NOT_USED" not in result.output["summary"]
    unknown = perform(environment, "run_baseline_check", _baseline_call("nope"), department="quality")
    assert unknown.ok is False
    assert "records no check named" in (unknown.error or "")


def test_baseline_receipt_is_recorded_as_a_baseline_fact(tmp_path):
    # 验收第 3 条：基线回执写入检查工作区的事实——工作区事实里的这条回执带 baseline 标记，
    # 提交放行决定读取事实时先读到的就是它
    environment = _baseline_environment(tmp_path)
    perform(environment, "run_baseline_check", _baseline_call("smoke", files=[]), department="quality")
    facts = environment.query(FactsQuery(tree=True)).tree
    baselines = [item for item in facts.checks if item.baseline]
    assert len(baselines) == 1 and baselines[0].name == "smoke"
    assert baselines[0].command is not None
    # 同名的交付检查回执还没有：基线回执不是交付检查的证据（latest_check 不取它）
    assert environment.query(FactsQuery(tree=True)).tree.latest_check("quality", "smoke") is None


def test_a_baseline_receipt_is_never_the_delivery_evidence_even_when_the_digests_match(tmp_path):
    # 审查观察事项 ①（PR #1526）：质检声明全部改动文件、且检查工作区就是交付内容时，
    # 基线副本的摘要可以等于工作区（交付）的摘要；latest_check 在这一角也不把基线回执当交付回执取——
    # 交付证据仍要一份真正的交付检查回执
    start = _tree((START_FILE, START_BODY))
    sealed = _tree((START_FILE, DELIVERY_BODY))
    workspace = Workspace(tmp_path / "run")
    workspace.write_file(START_FILE, DELIVERY_BODY)
    command = f'"{PYTHON}" -c "print(\'delivered check\')"'
    environment = LocalEnvironment(workspace, check_timeout_sec=60)
    environment.bind_baseline_source(start, (START_FILE,))
    environment.bind_delivery_checks(
        [{"name": "smoke", "exit_code": 0, "summary": "ran", "command": command}], sealed)
    # 先跑基线检查（树变化核对通过），再放一份同名交付回执：两者的摘要相同
    perform(environment, "run_baseline_check", _baseline_call("smoke", files=[START_FILE]),
            department="quality")
    facts = environment.query(FactsQuery(tree=True)).tree
    baselines = [item for item in facts.checks if item.baseline]
    assert baselines and baselines[0].snapshot_hash == facts.digest, \
        "前提：这个角上基线副本的摘要与工作区相同"
    workspace.bind_check(activation_id="act_q", product_spec_hash="sha256:" + "1" * 64,
                         delivery_spec_hash="sha256:" + "2" * 64,
                         effective_contract_hash="sha256:" + "3" * 64)
    workspace.record_check("quality", "smoke", 0, "delivered check", snapshot_hash=facts.digest)
    facts = environment.query(FactsQuery(tree=True)).tree
    receipt = facts.latest_check("quality", "smoke")
    assert receipt is not None and receipt.baseline is False
    assert "delivered check" in receipt.summary


def test_baseline_time_limit_truncation_and_cleanup_match_run_check(tmp_path):
    # 验收第 4 条：基线与交付使用相同的执行限制——超时按同一个退出码 124 记录，无法运行
    command = f'"{PYTHON}" -c "import time; time.sleep(30)"'
    environment = _baseline_environment(tmp_path, command=command)
    environment._check_timeout_sec = 2
    result = perform(environment, "run_baseline_check", _baseline_call("smoke", files=[]),
                     department="quality")
    assert result.status == "timeout"
    assert result.output["exit_code"] == 124
    receipt = next(item for item in environment.workspace.receipts() if item.baseline)
    assert receipt.exit_code == 124


def test_the_baseline_outcome_word_follows_the_exit_code():
    # 验收第 5 条：非零且不是 124、130 的结果可用于有效性判断；124 与 130 记为无法运行
    assert baseline_outcome(0) == "passed"
    assert baseline_outcome(1) == "failed" and baseline_outcome(7) == "failed"
    assert baseline_outcome(124) == BASELINE_UNAVAILABLE
    assert baseline_outcome(130) == BASELINE_UNAVAILABLE
    assert baseline_outcome(None) == BASELINE_UNAVAILABLE


def _receipt(name: str, exit_code: int, *, baseline: bool = True, tree_changed: bool = False,
             activation: str = "act_q") -> CheckReceipt:
    return CheckReceipt(name=name, department="quality", exit_code=exit_code, summary="ran",
                        snapshot_hash="sha256:" + "a" * 64, activation_id=activation,
                        baseline=baseline, tree_changed=tree_changed)


def _facts(*checks: CheckReceipt, digest: str = "sha256:" + "b" * 64) -> TreeFacts:
    return TreeFacts(digest=digest, files=("src/lib.py",), hashes=("h",), checks=checks)


def _ref(kind: str, content_hash: str) -> ArtifactRef:
    return ArtifactRef(kind=kind, content_hash=content_hash, path=f"{kind}/{content_hash[7:9]}/{content_hash[7:]}")


def _working(projection, department: str):
    # 这个部门正在工作：会话的记录是「工作中」（与 test_tightening.py 的同一做法）
    return replace(projection, sessions={**projection.sessions, department: SessionRecord(
        session_id=f"ses_{department}", department=department, status="active")})


def _structured(projection, department: str, proposal: dict, *, facts: TreeFacts | None = None,
                events: tuple = ()):
    # 收紧检查的请求：S2c 起格式检查与成果内容的组装也在这里，交最小投影与工作区事实
    from harness.tests.helpers import minimal_of
    from harness.validation import TightenRequest

    return TightenRequest(department=department, state=projection, proposal=proposal,
                          minimal=minimal_of(projection),
                          facts=_facts() if facts is None else facts, events=events)


def _criterion(method: str = "check", result: str = "passed", checks: tuple[str, ...] = ("smoke",)) -> dict:
    return {"criterion": "AC1", "method": method, "result": result,
            "checks": list(checks), "trial_cases": [], "note": ""}


def test_a_failing_baseline_with_a_passing_delivery_counts_as_covered():
    # 验收第 6 条：基线失败且交付通过 → 计入检验覆盖，baseline_valid 为真
    baseline = baseline_records([_receipt("smoke", 1)], ["smoke"])
    report = coverage_report([_criterion()], baseline=baseline)
    assert report["covered"] == 1 and report["coverage_ratio"] == 1.0
    assert report["baseline_valid"] is True
    assert baseline_open_records([_criterion()], baseline) == [
        {"criterion": "AC1", "checks": "smoke", "outcome": "failed"}]


def test_a_passing_baseline_does_not_count_and_is_recorded():
    # 验收第 6 条：基线通过 → 不计入覆盖并写进放行记录
    baseline = baseline_records([_receipt("smoke", 0)], ["smoke"])
    report = coverage_report([_criterion()], baseline=baseline)
    assert report["covered"] == 0 and report["baseline_valid"] is False
    assert baseline_open_records([_criterion()], baseline)[0]["outcome"] == "passed"


def test_a_missing_or_unable_baseline_does_not_count_and_is_recorded():
    # 验收第 6 条：缺少回执与超时（124）→ 不计入覆盖并写进放行记录
    missing = baseline_records([], ["smoke"])
    report = coverage_report([_criterion()], baseline=missing)
    assert report["covered"] == 0 and report["baseline_valid"] is False
    assert baseline_open_records([_criterion()], baseline=missing)[0]["outcome"] == "missing"

    unable = baseline_records([_receipt("smoke", 124)], ["smoke"])
    report = coverage_report([_criterion()], baseline=unable)
    assert report["covered"] == 0
    assert baseline_open_records([_criterion()], baseline=unable)[0]["outcome"] == BASELINE_UNAVAILABLE
    cancelled = baseline_records([_receipt("smoke", 130)], ["smoke"])
    assert coverage_report([_criterion()], baseline=cancelled)["covered"] == 0


def test_a_changed_tree_baseline_receipt_is_not_evidence():
    # 树变化核对与 run_check 相同：基线检查改了副本内容的回执不参与归并（不是可用的基线结果）
    baseline = baseline_records([_receipt("smoke", 1, tree_changed=True)], ["smoke"])
    assert coverage_report([_criterion()], baseline=baseline)["covered"] == 0
    assert baseline_open_records([_criterion()], baseline)[0]["outcome"] == "missing"


def test_non_check_methods_keep_their_own_evidence_path():
    # 试用用例与主机测量沿用各自的证据路径：检验有效性只适用于命令检查（docs/design/independent-verification.md「检验的有效性」最后一句）
    trial = [{"criterion": "AC1", "method": "trial", "result": "passed",
              "checks": [], "trial_cases": [], "note": ""}]
    baseline = baseline_records([], ["smoke"])
    assert coverage_report(trial, baseline=baseline)["covered"] == 1
    assert baseline_open_records(trial, baseline) == []


def test_baseline_valid_stays_true_when_no_criterion_is_a_check():
    # 没有命令检查的放行记录：没有要满足的基线条件，baseline_valid 保持真（不改变放行准入）
    trial = [{"criterion": "AC1", "method": "open", "result": "unverified",
              "checks": [], "trial_cases": [], "note": "开环"}]
    assert coverage_report(trial, baseline=None)["baseline_valid"] is True
    assert coverage_report(trial, baseline=baseline_records([], []))["baseline_valid"] is True


def _judgement_event(delivery_hash: str, spec_hash: str) -> object:
    # 一条独立判断事件的内存替身（工单 #358 的门核对它的存在与它写的交付摘要；与 test_tightening.py 同一做法）
    from harness.kernel_events import Event
    from harness.models import EventType

    return Event(event_id="evt_judgement", run_id="run_test", type=EventType.INDEPENDENT_JUDGEMENT_COMMITTED,
                 role=None, parent_event_id=None, state_before="running", state_after="running",
                 payload={"kind": "independent_judgement", "product_spec_hash": spec_hash,
                          "delivery_spec_hash": delivery_hash, "checks": ["smoke"],
                          "criteria_count": 1,
                          "criteria": [{"criterion": "AC1", "method": "check", "result": "passed",
                                        "checks": ["smoke"], "trial_cases": [], "note": ""}]},
                 artifact_hashes=[], session_id="ses_quality", provider=None, model=None,
                 context_digest=None, stop_reason=None, error=None, created_at="2026-11-05T00:00:00Z",
                 position=999, stream="run:run_test", stream_version=999, project_id=None,
                 work_item_id=None, department="quality")


def test_the_release_gate_is_unchanged_by_the_baseline(tmp_path):
    # 验收第 6 条：不改变放行准入与结果词——基线也通过时放行照样被接纳（结果词不变），
    # 基线明细随放行记录写出，QA_SUBMITTED 的门不因为基线变化。
    # 投影与回执按 test_tightening.py 的同一做法在内存里构造
    from harness.proposals import review
    from harness.tightening import WATCHED_OUTPUTS

    TREE = "sha256:" + "c" * 64
    DELIVERY = "sha256:" + "d" * 64
    CONTRACT = "sha256:" + "e" * 64
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([product_spec()]))
    run_id = system.create_run("echo")
    system.activate_once(run_id)   # 产品提交 PRD：投影里有一份当前的 PRD
    base = system.project(run_id)
    spec = base.product_spec
    contract = EffectiveContract(content_hash=CONTRACT, revision=1, product_spec_hash=spec.content_hash,
                                 input_version=spec.input_version, decision_hashes=[],
                                 created_event_id="evt_contract", prd_ref=_ref("prd", spec.content_hash))
    delivery = DeliverySpec(id="delivery_1", run_id=base.run_id, revision=1, parent_hash=None,
                            content_hash=DELIVERY, issuer="engineering", status="active",
                            created_event_id="evt_delivery", product_spec_hash=spec.content_hash,
                            effective_contract_hash=CONTRACT, summary="implemented", files=["src/echo.py"],
                            check_names=["smoke"], checks=[], known_risks=[], code_tree_digest=TREE,
                            tree_ref=_ref("tree", TREE))
    receipt = CheckReceipt(name="smoke", department="quality", exit_code=0, summary="ran",
                           snapshot_hash=TREE,
                           bindings={"product_spec": spec.content_hash, "contract": CONTRACT,
                                     "delivery_spec": DELIVERY},
                           product_spec_hash=spec.content_hash, delivery_spec_hash=DELIVERY,
                           activation_id="act_q", effective_contract_hash=CONTRACT)
    # 基线也通过的一份回执（异常情形）：放行记录里写明，不被拒绝
    baseline_receipt = CheckReceipt(name="smoke", department="quality", exit_code=0, summary="ran",
                                    snapshot_hash=TREE, activation_id="act_q", baseline=True)
    projection = replace(_working(base, "quality"), effective_contract=contract, delivery_spec=delivery,
                         last_activations={"quality": "act_q"})
    facts = _facts(receipt, baseline_receipt, digest=TREE)
    proposal = review("release", "the delivery passes", checks=["smoke"],
                      basis_delivery_spec_hash=DELIVERY, criteria=[_criterion()])
    tightened = WATCHED_OUTPUTS.submission(
        _structured(projection, "quality", proposal, facts=facts,
                    events=(_judgement_event(DELIVERY, spec.content_hash),)))
    assert not tightened.errors, [error.message for error in tightened.errors]
    content = tightened.content or {}
    # 三个数照旧算好；baseline_valid 为假、基线明细写明基线也通过——放行没有被拒绝
    assert content["coverage"]["covered"] == 0 and content["coverage"]["baseline_valid"] is False
    assert content["baseline_checks"] == [{"criterion": "AC1", "checks": "smoke", "outcome": "passed"}]
    assert content["verdict"] == "release"
