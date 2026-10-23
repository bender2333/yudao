# 资料页的 PRD 一节显示各版真实状态（工单 #654、#683）：当前有效的一版标 active，
# 被取代的旧版标 superseded；同一页的交付一节用同一套词。
#
# 场景：产品提交第一版 PRD，工程发问，产品在回答里修订 PRD（第二版并重新接纳），
# 工程交付，质检放行。这样这个 run 里有两版 PRD 与两份有效合同。
# 另一种场景（工单 #683）：质检要求返工，产品用「产品决定」修订 PRD——新合同沿用同一条
# 产品需求，这时两版合同的状态要按「是不是当前有效的那一版」判定。

from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.app.project_queries import WorkItemMaterials
from harness.proposals import answer_turn, ask_turn, delivery_turn, product_decision, product_spec, review_turn
from harness.runtime import LoopSystem
from harness.tests.helpers import guidance_reply

GOAL = "把文本按行处理清楚"


def _scripts() -> dict[str, list]:
    return {
        "product": [product_spec()],
        "engineering": [
            ask_turn("product", "Should output be uppercase?",
                     background="Clarification needed", expected="Specification update"),
            delivery_turn(files={"src/echo.py": "import sys\nprint(sys.argv[1].upper())\n"}),
        ],
        "product:ask": [
            answer_turn("Yes, print in uppercase.",
                        requirements=["print the given argument in uppercase to stdout"],
                        change_record={"changed": ["print the given argument in uppercase to stdout"],
                                       "retained": ["single file implementation"],
                                       "retired": [],
                                       "rationale": "Clarification revision."}),
        ],
        "quality": [review_turn("release", "valid uppercase implementation")],
    }


def test_materials_prd_versions_carry_their_real_status(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter(_scripts()))
    project_id = system.projects.register("资料页的 PRD 状态", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    system.run_until_stop(run_id)

    # 投影里两版 PRD：旧的被取代，新的当前有效
    projection = system.project(run_id)
    assert [spec.status for spec in projection.product_specs] == ["superseded", "active"]

    application = Application(system)
    materials = application.query("work_item.materials", WorkItemMaterials(
        project_id=project_id, work_item=work_item_id))
    assert [entry.status for entry in materials.data.contracts] == ["superseded", "active"]
    # 交付一节用同一套词
    assert [entry.status for entry in materials.data.deliveries][-1] == "active"


def test_materials_prd_versions_follow_the_product_decision_path(tmp_path):
    # 工单 #683：产品用「产品决定」修订 PRD 时，新合同沿用同一条产品需求；
    # 两版合同的状态按「是不是当前有效的那一版」判定，第 1 版不再也是 active
    # 产品的工作由用户的指导触发（工单 #555）
    adapter = FakeAdapter({
        "product": [
            product_spec(),
            product_decision("Treat unknown flags as an error.", "Unknown flags must not silently change the command."),
            guidance_reply("已给出产品决定。"),
        ],
        "engineering": [delivery_turn(), delivery_turn()],
        "quality": [
            review_turn("rework_engineering", "the delivery misses an acceptance criterion",
                        defects=[{"severity": "major", "summary": "defect"}]),
            review_turn("release", "Verified the current requirements"),
        ],
    })
    system = LoopSystem.for_testing(tmp_path, adapter)
    project_id = system.projects.register("产品决定修订 PRD", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    system.activate_once(run_id)
    system.add_guidance(run_id, "product", "请补充产品决定。")
    projection = system.run_until_stop(run_id)
    assert projection.status == "done", projection.error
    # 一条产品需求、两版有效合同
    assert len(projection.product_specs) == 1
    assert len(projection.effective_contracts) == 2

    application = Application(system)
    materials = application.query("work_item.materials", WorkItemMaterials(
        project_id=project_id, work_item=work_item_id))
    assert [entry.status for entry in materials.data.contracts] == ["superseded", "active"]
