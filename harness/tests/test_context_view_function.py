import pytest

from harness.context import HISTORY, MATERIALS, ContextEntry, Rules, view
from harness.models import canonical_hash, json_dumps


def materials_item() -> dict:
    # 部门材料那一条：一步的固定部分按 [source] 分节拼成一条 developer 消息
    return {
        "role": "developer",
        "content": "[intend]\nbuild echo\n\n[current_work]\n{\"department\": \"engineering\"}\n\n[tool_schemas]\n[]",
    }


def history_items() -> list[dict]:
    # 部门历史的三条：工具调用、它的结果与模型的文字回答，与真实装配交给视图的条目同形
    return [
        {"type": "function_call", "id": "fc-1", "call_id": "call-1", "name": "read_file",
         "arguments": "{\"path\": \"README.md\"}"},
        {"type": "function_call_output", "call_id": "call-1", "output": "{\"ok\": true, \"text\": \"echo\"}"},
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "读完了"}]},
    ]


def entries(items: list[dict] | None = None) -> list[ContextEntry]:
    return [ContextEntry(MATERIALS, materials_item()),
            *[ContextEntry(HISTORY, item) for item in (history_items() if items is None else items)]]


def test_the_same_entries_and_rules_give_the_same_request():
    # 守 R3（同样的事件重放出同样的请求）：同一份条目与同一版规则装配两次，逐字节相同
    first = view(entries(), Rules(), tools=[{"type": "function", "name": "read_file"}])
    second = view(entries(), Rules(), tools=[{"type": "function", "name": "read_file"}])
    assert json_dumps(first.input_items) == json_dumps(second.input_items)
    assert first.tools == second.tools
    assert first == second


def test_no_rule_is_on_by_default_and_the_request_keeps_every_entry():
    # 守 R3（规则全关时与改动前逐字节相同）：请求就是部门材料在前、部门历史按条目顺序接在后面
    viewed = view(entries(), Rules(), tools=[])
    assert viewed.input_items == [materials_item(), *history_items()]
    # 一个减法规则都没有开：没有折叠任何一轮，规则版本是这一份取值的规范散列
    assert viewed.folded_rounds == ()
    assert viewed.rules_version == Rules().version()


def test_the_view_does_not_change_the_entries_it_was_given():
    # 守 R3（不修改输入）：视图交回的是拷贝，改返回值不影响交进去的条目
    given = entries()
    viewed = view(given, Rules(), tools=[])
    viewed.input_items[0]["content"] = "changed"
    assert given[0].item == materials_item()


def test_the_rule_version_is_the_canonical_hash_of_the_values():
    # 守 R2（合同：规则版本是取值的规范散列）：取值相同就是同一版，任何一个取值变了就是新的一版
    rules = Rules()
    assert rules.version() == canonical_hash(rules.to_dict())
    assert Rules().version() == rules.version()
    assert Rules(pinned_stub_chars=rules.pinned_stub_chars + 1).version() != rules.version()


def test_the_department_materials_must_come_first_and_only_once():
    # 守 R3（材料恒在首位，设计说明第 6.1 节）：条目排错时视图直接失败，不交出一份没有材料的请求
    with pytest.raises(ValueError):
        view(entries()[1:], Rules(), tools=[])
    with pytest.raises(ValueError):
        view([*entries(), ContextEntry(MATERIALS, materials_item())], Rules(), tools=[])
