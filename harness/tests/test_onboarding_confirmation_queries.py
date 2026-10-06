# 建档确认往返的四个查询（工单 #136，docs/design/existing-project-onboarding.md 第 3.4、4.7、5 节）：
# projects.list 的「等待确认初始 PRD」标记、project.overview 的建档基线成果、project.loop 的事项状态、
# work_item.materials 按轮列出的建档材料。系统整体运行：真实启动 FastAPI 应用（uvicorn），经 HTTP 读取查询与
# 提交 decision.answer；控制核心在服务生命周期中建立，事件日志是真实的 SQLite 文件，模型回答由 FakeAdapter 给出。

import time
import uuid
from pathlib import Path

from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.app.application import Application
from harness.app.project_queries import ProjectOverview, WorkItemMaterials
from harness.proposals import baseline_review_turn, product_spec, structure_turn
from harness.runtime import LoopSystem
from harness.tests.api_helpers import running_api
from harness.tests.helpers import happy_script
from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC

GOAL = "把已有项目接入 Yudao，写出初始 PRD 并核验现有行为"
REQUIREMENT = "print the given argument to stdout"

# 等待一次建档 run 结束的墙钟界限只用来防止测试一直等待（#107）；run 是否按预期结束由等待之后的断言核对
_WAIT_LIMIT = WAIT_FOR_HOST_WORK_SEC


def _source(root: Path) -> Path:
    # 一份最小的已有项目：一个脚本、一个说明文件、一个通过的测试与一个失败的测试
    (root / "src").mkdir(parents=True)
    (root / "src" / "echo.py").write_text("import sys\nprint(sys.argv[1])\n", encoding="utf-8")
    (root / "README.md").write_text("# Echo\n\nPrint the given argument.\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_echo.py").write_text("def test_placeholder():\n    assert True\n", encoding="utf-8")
    (root / "tests" / "test_broken.py").write_text("def test_broken():\n    assert False\n", encoding="utf-8")
    return root


def _script():
    # 建档的三个部门各一轮。核验把失败的检查记为现有缺陷：确认以后采纳成果的已知风险与现有缺陷数才有内容
    return [
        FakeTurn(proposal=product_spec(requirements=[REQUIREMENT], acceptance=["run the CLI with a word"])),
        structure_turn(checks={"smoke": 0, "broken": 1},
                       requirement_locations=[{"requirement": REQUIREMENT, "locations": ["src/echo.py"]}]),
        baseline_review_turn(conclusions=[{"requirement": REQUIREMENT, "status": "existing_defect",
                                           "evidence": "broken"}],
                             checks={"smoke": 0, "broken": 1}),
    ]


class _Opened:
    def __init__(self, data_dir, turns=None) -> None:
        self.data_dir = data_dir
        self.adapter = FakeAdapter(_script() if turns is None else turns)
        self.applications: list[Application] = []

    def __call__(self) -> Application:
        application = Application(LoopSystem.for_testing(self.data_dir, self.adapter))
        self.applications.append(application)
        return application

    @property
    def system(self) -> LoopSystem:
        return self.applications[-1].system


def _post(client, command, **body):
    return client.post(f"/api/commands/{command}", json={"command_id": str(uuid.uuid4()), **body})


def _wait_for(predicate, timeout=_WAIT_LIMIT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _open_initial_prd(client, project_id) -> dict | None:
    decisions = client.get(f"/api/queries/decisions.list?project_id={project_id}").json()["data"]["decisions"]
    return next((item for item in decisions if item["kind"] == "initial_prd" and item["status"] == "open"), None)


def _onboard(client, opened, tmp_path):
    # 经接口层接入已有项目并建档，等 run 结束、结算出候选与确认请求
    source = _source(tmp_path / "source")
    accepted = _post(client, "project.onboard", name="已有项目", goal=GOAL,
                     source_name="src", source_path=str(source))
    assert accepted.status_code == 200, accepted.text
    refs = accepted.json()["refs"]
    assert _wait_for(lambda: opened.system.project(refs["run_id"]).phase == "DONE"), \
        "the onboarding run did not stop"
    assert _wait_for(lambda: _open_initial_prd(client, refs["project_id"]) is not None), \
        "the initial PRD decision was not requested"
    return source, refs


def _row(client, project_id):
    return next(entry for entry in client.get("/api/queries/projects.list").json()["data"]["projects"]
                if entry["project_id"] == project_id)


def test_projects_list_marks_the_item_awaiting_initial_prd_confirmation(data_dir, tmp_path):
    # 验收（3.4 节）：建档 run 结束并发出确认请求以后，projects.list 的建档状态标记为 awaiting_initial_prd；
    # project.loop 里建档事项的种类为 onboarding、状态为 awaiting_initial_prd
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        _source_dir, refs = _onboard(client, opened, tmp_path)
        assert _row(client, refs["project_id"])["onboarding_status"] == "awaiting_initial_prd"
        loop = client.get(f"/api/queries/project.loop?project_id={refs['project_id']}").json()["data"]
        assert [item["kind"] for item in loop["work_items"]] == ["onboarding"]
        assert loop["work_items"][0]["status"] == "awaiting_initial_prd"


def test_materials_list_the_onboarding_round_by_round(data_dir, tmp_path):
    # 验收（3.4 节）：work_item.materials 按轮列出初始 PRD 原文、现有结构说明原文、基线核验结论与基线检查、
    # 仓库概况原文；还没有回答时这一轮没有确认记录
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        _source_dir, refs = _onboard(client, opened, tmp_path)
        materials = client.get(f"/api/queries/work_item.materials?project_id={refs['project_id']}"
                               f"&work_item={refs['work_item_id']}").json()["data"]
        rounds = materials["onboarding_rounds"]
        assert [entry["round"] for entry in rounds] == [1]
        first = rounds[0]
        assert first["run_id"] == refs["run_id"]
        assert REQUIREMENT in first["prd"]
        assert "src/echo.py" in first["structure"]
        # 仓库概况由快照的公开树生成：列出识别出的说明文件与测试目录
        assert "README.md" in first["overview"]
        assert first["revision_note"] is None
        assert first["decisions"] == []
        review = first["baseline_review"]
        assert review["conclusions"] == [
            {"requirement": REQUIREMENT, "status": "existing_defect", "evidence": "broken"}]
        assert review["omissions"] == []
        assert review["other_failures"] == []
        assert {check["name"]: check["exit_code"] for check in review["checks"]} == {"smoke": 0, "broken": 1}
        assert all(check["snapshot_hash"] for check in review["checks"])


def test_confirming_the_initial_prd_adopts_the_baseline_and_clears_the_marks(data_dir, tmp_path):
    # 验收（3.4、5 节）：回答「确认」以后 project.overview 的当前成果是建档基线，带快照来源与现有缺陷数；
    # projects.list 不再带建档状态标记，project.loop 里事项状态为 adopted，该轮的确认记录列出这次回答
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        source, refs = _onboard(client, opened, tmp_path)
        project_id, work_item_id = refs["project_id"], refs["work_item_id"]
        decision = _open_initial_prd(client, project_id)
        answered = client.post("/api/commands/decision.answer",
                               json={"command_id": str(uuid.uuid4()), "decision_id": decision["decision_id"],
                                     "option": "confirm", "base_version": decision["version"]})
        assert answered.status_code == 200, answered.text

        adoption = client.get(f"/api/queries/project.overview?project_id={project_id}").json()["data"]["current_adoption"]
        assert adoption is not None
        assert adoption["onboarding_baseline"] is True
        assert adoption["snapshot_source"] == str(source)
        # 源目录不是 git 仓库：没有提交信息，来源只有采集到的源目录
        assert adoption["snapshot_provenance"] in (None, {})
        assert adoption["existing_defect_count"] == 1
        assert adoption["known_risks"] == [f"现有缺陷：{REQUIREMENT}（broken）"]
        assert adoption["previous_adoption_id"] is None
        assert adoption["code_tree_digest"]
        # 确认以后项目有了基线，不再有建档状态标记
        assert _row(client, project_id)["onboarding_status"] is None
        loop = client.get(f"/api/queries/project.loop?project_id={project_id}").json()["data"]
        assert loop["work_items"][0]["status"] == "adopted"
        assert [entry["adoption_id"] for entry in loop["adoptions"]] == [adoption["adoption_id"]]
        materials = client.get(f"/api/queries/work_item.materials?project_id={project_id}"
                               f"&work_item={work_item_id}").json()["data"]
        records = materials["onboarding_rounds"][0]["decisions"]
        assert [(item["outcome"], item["option"]) for item in records] == [("answered", "confirm")]


def test_ordinary_adoption_has_no_baseline_fields(data_dir):
    # 对照：普通事项的交付采纳不是建档基线，基线标记为假、快照来源为空、现有缺陷数为 0；
    # 普通事项也没有建档各轮
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    project_id = system.projects.register("普通项目", "做一件事")
    work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    system.run_until_stop(run_id)
    system.projects.settle(run_id)
    application = Application(system)
    overview = application.query("project.overview", ProjectOverview(project_id=project_id)).data
    adoption = overview.current_adoption
    assert adoption is not None and adoption.onboarding_baseline is False
    assert adoption.snapshot_source is None and adoption.snapshot_provenance is None
    assert adoption.existing_defect_count == 0
    materials = application.query("work_item.materials",
                                  WorkItemMaterials(project_id=project_id, work_item=work_item_id)).data
    assert materials.onboarding_rounds == []
    assert materials.deliveries