# 产品部门的 Prompt 是定义数据，会话里看到两段：部门自己的默认 Prompt（roles.json 的 product）与事项种类的
# 说明（work_items.json 的 change）。工单 #736 要求两段都写明：验收标准要能直接写成一条断言，条件式的一般规则
# 不算；要求与验收标准各有各的读者（要求给实现读，验收标准给检验用）。普通事项的说明里另给一对例子说明差别。
# 读静态定义、不跑会话、不使用临时目录，属于单元层（测试分层设计说明第 2 节）。

from harness.definitions import DEFINITIONS


def _product_prompts() -> dict[str, str]:
    # 产品在普通事项里看到的两段说明
    return {
        "roles.json 的 product": DEFINITIONS.role("product").prompt,
        "work_items.json 的普通事项说明": DEFINITIONS.work_item("change").departments["product"].prompt,
    }


def test_acceptance_criteria_must_become_one_assertion():
    # 每条验收标准都要能直接写成一条断言，写死输入与期望结果；条件式的一般规则不算（工单 #736 验收第 1 条）。
    # 守 R3（独立核验设计说明第 7 节：验收条件要能检验），也是防回退护栏：这两处内容被删掉时失败
    for source, prompt in _product_prompts().items():
        assert "能直接写成一条断言" in prompt, source
        assert "条件式的一般规则不算" in prompt, source
        assert any(word in prompt for word in ("期望的输出", "退出码", "文件内容")), source


def test_requirements_and_acceptance_criteria_have_different_readers():
    # 要求是给实现读的，验收标准是给检验用的（验收第 2 条）
    for source, prompt in _product_prompts().items():
        assert "要求是给实现读的" in prompt, source
        assert "验收标准是给检验用的" in prompt, source


def test_the_prompt_shows_a_conditional_rule_and_a_check_that_pins_its_inputs():
    # 一对例子：条件式的一般规则（反例）与写死输入与期望结果的检查（正例）
    prompt = DEFINITIONS.work_item("change").departments["product"].prompt
    counterexample, separator, example = prompt.partition("正例（可复现的检查）")
    assert separator, "普通事项的产品说明里没有可复现检查的例子"
    assert "反例（条件式的一般规则）" in counterexample
    # 反例是「若……则……」的条件式规则
    assert "若" in counterexample and "则" in counterexample
    # 正例写死了输入、期望的标准输出与退出码
    assert "echo hello" in example, example
    assert "HELLO" in example, example
    assert "退出码 0" in example, example
