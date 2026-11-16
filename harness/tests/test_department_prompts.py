import json

import pytest

from harness.artifacts import ArtifactStore
from harness.definitions import DEFAULT_FORM, DEFINITIONS, DEFINITIONS_DIR, load_definitions
from harness.department_prompts import save_department_prompt
from harness.direct import SINGLE_ROLE_DIRECT
from harness.models import DEPARTMENTS, hash_bytes
from harness.runtime import SEVERAL_ROLES_DIRECT


@pytest.mark.parametrize("department", DEPARTMENTS)
def test_default_prompt_is_saved_verbatim_and_can_be_edited_without_changing_defaults(tmp_path, department):
    store = ArtifactStore(tmp_path / "artifacts")
    initial_text = DEFINITIONS.role(department).prompt
    initial = save_department_prompt(store, "run", department, initial_text)
    edited_text = "  updated\r\n\u4e2d\u6587 instructions\n\t"
    edited = save_department_prompt(store, "run", department, edited_text)
    assert store.get_for_run("run", initial) == initial_text.encode("utf-8")
    assert store.get_for_run("run", edited) == edited_text.encode("utf-8")
    assert initial.kind == edited.kind == "department_prompt"
    assert edited.content_hash == hash_bytes(edited_text.encode("utf-8"))
    assert initial.content_hash != edited.content_hash
    assert DEFINITIONS.role(department).prompt == initial_text


@pytest.mark.parametrize("department", [None, "", "other", "PRODUCT"])
def test_unknown_department_cannot_create_prompt_material(tmp_path, department):
    store = ArtifactStore(tmp_path / "artifacts")
    with pytest.raises(ValueError, match="unknown prompt department"):
        save_department_prompt(store, "run", department, "text")
    assert list(store.root.iterdir()) == []


def test_all_three_forms_grant_ask_user_and_remove_ask_suppression():
    # 守 R1（三份形态工具配备）与 R2（解除内部询问抑制）：三份形态全部自有角色（change 与 onboarding）均配备 ask_user，
    # 且角色、工作项、组织与提案合同定义均不再保留压制内部 ask 或阻断提问的字句。
    form_dirs = {
        DEFAULT_FORM: DEFINITIONS_DIR,
        SINGLE_ROLE_DIRECT: DEFINITIONS_DIR / "forms" / SINGLE_ROLE_DIRECT,
        SEVERAL_ROLES_DIRECT: DEFINITIONS_DIR / "forms" / SEVERAL_ROLES_DIRECT,
    }
    forbidden_suppression = ("少量提问", "尽量不问", "不要为了小问题停下来问")

    for form_name, form_dir in form_dirs.items():
        defs = load_definitions(form_dir)
        for role_id in defs.departments:
            assert "ask_user" in defs.roles[role_id].tools, f"{form_name}.{role_id} roles.json 缺少 ask_user"
            assert "ask_user" in defs.tools_for(role_id, "change"), f"{form_name}.{role_id} change 缺少 ask_user"
            assert "ask_user" in defs.tools_for(role_id, "onboarding"), f"{form_name}.{role_id} onboarding 缺少 ask_user"

        for filename in ("roles.json", "work_items.json", "organization.json", "proposal_contracts.json"):
            raw = (form_dir / filename).read_text(encoding="utf-8")
            for phrase in forbidden_suppression:
                assert phrase not in raw, f"{form_name}/{filename} 仍包含抑制字句 {phrase!r}"
            # 确认 JSON 结构仍合法可解
            json.loads(raw)


def test_three_forms_include_explore_before_asking_and_cross_perspective_audit_guidance():
    # 守 R1（探索后前沿提问与跨视角反向审视）：各形态接入口输入的起点角色先探索再发起 ask_user，
    # 默认形态三职能包含主动咨询与对照 [intend]、起始材料、[user_decisions] 反向审视合同的指引，
    # 几个角色直做形式由入口 engineering 发起前沿提问、product 保持不主动开工并在回答分支建议提问方案。
    default_defs = load_definitions(DEFINITIONS_DIR)
    single_defs = load_definitions(DEFINITIONS_DIR / "forms" / SINGLE_ROLE_DIRECT)
    several_defs = load_definitions(DEFINITIONS_DIR / "forms" / SEVERAL_ROLES_DIRECT)

    default_product = default_defs.roles["product"].prompt
    assert "先探索工作区" in default_product
    assert "事实能从代码或材料查清的不要问用户" in default_product
    assert "ask_user" in default_product and "互斥选项" in default_product and "推荐" in default_product
    assert "轮数上限内再追问" in default_product
    assert "ask 咨询 engineering" in default_product and "quality" in default_product and "独立执行观测" in default_product
    assert "[user_decisions]" in default_product

    default_eng = default_defs.roles["engineering"].prompt
    assert "[intend]" in default_eng and "[user_decisions]" in default_eng
    assert "通过 ask 向 product 指出并促请修订合同" in default_eng
    assert "优先通过内部 ask 向 product 核对" in default_eng and "ask_user" in default_eng

    default_qa = default_defs.roles["quality"].prompt
    assert "[intend]" in default_qa and "[user_decisions]" in default_qa
    assert "通过 ask 向 product 指出并促请修订合同" in default_qa
    assert "核验结论仍以有效合同为准" in default_qa
    assert "优先通过内部 ask 向 product 核对" in default_qa and "ask_user" in default_qa

    default_org = default_defs.organization.rules
    assert "不限制提问次数" in default_org.professional_completion
    assert "询问分支里禁止调用ask_user" in default_org.collaboration_rules

    single_eng = single_defs.roles["engineering"].prompt
    assert "先探索工作区" in single_eng and "事实能从代码或材料查清的不要问用户" in single_eng
    assert "ask_user" in single_eng and "互斥选项" in single_eng and "轮数上限内再追问" in single_eng
    assert "[user_decisions]" in single_eng

    several_eng = several_defs.roles["engineering"].prompt
    several_prod = several_defs.roles["product"].prompt
    assert "先探索工作区" in several_eng and "ask_user" in several_eng and "不限制提问次数" in several_eng
    assert "[intend]" in several_eng and "[user_decisions]" in several_eng
    assert "不主动开工" in several_prod and "不能在询问分支直接调用 ask_user" in several_prod
    assert "ask_user" in several_prod and "[user_decisions]" in several_prod



