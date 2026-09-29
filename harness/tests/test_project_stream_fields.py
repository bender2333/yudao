# 项目流字段清单（ADR-0019，工单 #126）：项目流事件种类与字段的登记由清单与合同类型共同核对。
# 删除事件种类、删除字段或改变字段类型时测试失败；增加种类或字段时通过，但必须写明旧事件中的缺省含义。

import pytest

from harness.tests.project_stream_fields import live_fields, load_manifest, write_manifest

def _manifest_documents():
    document = load_manifest()
    return document["fields"], document["baseline"], document["added_defaults"]

def test_the_manifest_lists_every_project_stream_kind():
    fields, _, _ = _manifest_documents()
    assert set(fields) == set(live_fields())

def test_every_field_of_a_listed_kind_keeps_its_declared_type():
    # 清单中登记的字段在合同类型中以同样的类型存在：删除字段或改变类型时失败
    fields, _, _ = _manifest_documents()
    live = live_fields()
    removed, retyped = {}, {}
    for kind, manifest_fields in fields.items():
        live_kind = live[kind]
        for name, declared in manifest_fields.items():
            if name not in live_kind:
                removed.setdefault(kind, []).append(name)
            elif live_kind[name] != declared:
                retyped.setdefault(kind, []).append(f"{name}: {declared} -> {live_kind[name]}")
    assert not removed, f"项目流字段清单中的字段已从合同类型中删除：{removed}"
    assert not retyped, f"项目流字段的类型已改变：{retyped}"

def test_the_manifest_is_up_to_date_with_the_contract():
    # 清单与合同类型一致：增加字段时把字段写入清单以后通过
    fields, _, _ = _manifest_documents()
    live = live_fields()
    additions = {}
    for kind, live_kind in live.items():
        for name, declared in live_kind.items():
            if name not in fields.get(kind, {}):
                additions.setdefault(kind, {})[name] = declared
    assert not additions, (
        "合同类型中出现了清单没有登记的字段，用 "
        "python -m pytest harness/tests/test_project_stream_fields.py --write-project-stream-fields 重写清单，"
        f"并在 added_defaults 中写明缺省含义：{additions}"
    )

def test_a_field_added_after_the_baseline_states_its_meaning_in_older_events():
    # baseline 之后新增的字段必须写明它在旧事件中的缺省含义（ADR-0019）
    fields, baseline, defaults = _manifest_documents()
    missing = {}
    for kind, manifest_fields in fields.items():
        for name in manifest_fields:
            if name in baseline.get(kind, {}):
                continue
            if name not in defaults.get(kind, {}):
                missing.setdefault(kind, []).append(name)
    assert not missing, f"新增的字段没有写明它在旧事件中的缺省含义：{missing}"

def test_writing_the_manifest_refreshes_fields_and_freezes_the_baseline(request):
    # 重写选项：只在清单有意改变时使用。fields 随合同类型刷新；baseline 在第一次写入时确定，以后保持不动，
    # 这样之后新增的字段都要在 added_defaults 中写明缺省含义
    if not request.config.getoption("--write-project-stream-fields"):
        pytest.skip("pass --write-project-stream-fields to rewrite the manifest")
    document = load_manifest()
    document["fields"] = live_fields()
    document.setdefault("baseline", live_fields())
    write_manifest(document)
    assert live_fields() == load_manifest()["fields"]
