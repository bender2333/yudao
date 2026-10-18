# 建档基线的基线检查在读侧的命令字段（工单 #504，docs/design/existing-project-onboarding.md 第 3.3、
# 4.4、4.6 节）：#480 起 run_check 的输入改为命令字符串，生产方 harness/projects.py 的 _baseline_checks
# 发 {"name","command","exit_code","summary","snapshot_hash"}，读侧 harness/app/payloads.py 的
# BaselineCheck 漏迁仍按 argv 解析，带检查回执的建档候选在 decisions.list 与 work_item.materials 上
# 返回 500。系统整体运行：真实启动 FastAPI 应用（uvicorn），经 HTTP 读取查询；事件日志是真实的
# SQLite 文件，模型回答由 FakeAdapter 给出，检查是 FakeAdapter 选择、主机真实执行的进程。

import sys

from harness.proposals import baseline_review_turn, product_spec, structure_turn
from harness.tests.api_helpers import running_api
from harness.tests.onboarding_project import (
    ONBOARDING_GOAL as GOAL,
    ONBOARDING_REQUIREMENT as REQUIREMENT,
    OpenedFake as _Opened,
    onboarding_source as _source,
    open_initial_prd,
    post_command as _post,
    wait_until as _wait_for,
)

# FakeAdapter 未给命令时的默认检查命令：质检这一轮的 run_check 由它发起，主机按检查名把它补进基线检查
DEFAULT_CHECK_COMMAND = f'"{sys.executable.replace(chr(92), "/")}" -c "raise SystemExit(0)"'


def _script():
    # 一轮建档的三个部门。质检核验的检查带一个由主机真实执行的命令（FakeAdapter 未给命令时的默认检查），
    # 主机结算候选时按检查名把它补进基线检查，读侧据此读出 command
    return [
        product_spec(requirements=[REQUIREMENT], acceptance=["run the CLI with a word"]),
        structure_turn(checks={"smoke": 0},
                       build_and_test=[{"name": "smoke", "command": DEFAULT_CHECK_COMMAND,
                                        "purpose": "run the CLI"}],
                       requirement_locations=[{"requirement": REQUIREMENT, "locations": ["src/echo.py"]}]),
        baseline_review_turn(conclusions=[{"requirement": REQUIREMENT, "status": "verified",
                                           "evidence": "smoke"}],
                             checks={"smoke": 0}),
    ]


def test_decisions_list_returns_the_baseline_checks_with_their_command(data_dir, tmp_path):
    # 验收（3.3、4.6 节）：建档候选的基线核验带检查回执时 decisions.list 返回 200，
    # 检查项带命令字符串、退出状态与快照摘要；request 的载荷按 BaselineCheck 解析成功
    opened = _Opened(data_dir, turns=_script())
    with running_api(opened) as client:
        source = _source(tmp_path / "src")
        accepted = _post(client, "project.onboard", name="已有项目", goal=GOAL,
                         source_name="src", source_path=str(source))
        assert accepted.status_code == 200, accepted.text
        refs = accepted.json()["refs"]
        assert _wait_for(lambda: opened.system.project(refs["run_id"]).phase == "DONE"), \
            "the onboarding run did not stop"
        # 运行到 DONE 与主机结算（写出建档候选和决定请求）是两步：结算在 DONE 之后才发生，
        # 读决定之前要等它出现，不能假定 DONE 时已经有
        assert _wait_for(lambda: open_initial_prd(client, refs["project_id"]) is not None), \
            "the initial PRD decision was not requested"
        listed = client.get(f"/api/queries/decisions.list?project_id={refs['project_id']}")
        assert listed.status_code == 200, listed.text
        decisions = listed.json()["data"]["decisions"]
        decision = next(item for item in decisions if item["kind"] == "initial_prd" and item["status"] == "open")
        checks = decision["request"]["baseline_review"]["checks"]
        assert [(item["name"], item["command"], item["exit_code"]) for item in checks] == \
            [("smoke", DEFAULT_CHECK_COMMAND, 0)]
        assert checks[0]["summary"] and checks[0]["snapshot_hash"].startswith("sha256:")
