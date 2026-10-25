# 项目流字段清单（ADR-0019、#241，工单 #126）：项目流事件种类与字段的登记由清单与合同类型共同核对。
# 删除事件种类、删除字段、改变字段类型或删除取值固定字段（const/enum）的已登记取值时测试失败；
# 增加种类、字段或扩大取值集合时通过，新种类或新字段必须写明旧事件中的缺省含义（取值扩大不需要）。
# 写入路径（--write-project-stream-fields）只允许添加新的种类、字段或扩大取值集合，删除与改类型
# 一律拒绝（删除取值时写明被删除的取值），清单缺失时提示从 git 恢复。

import pytest

from harness.tests import project_stream_fields
from harness.tests.project_stream_fields import (
    MANIFEST, ManifestWriteRejected, apply_rewrite, live_fields, load_manifest, same_type)

def _manifest_documents():
    document = load_manifest()
    return document["fields"], document["baseline"], document["added_defaults"]

def test_the_manifest_lists_every_project_stream_kind():
    fields, _, _ = _manifest_documents()
    assert set(fields) == set(live_fields())

def test_every_field_of_a_listed_kind_keeps_its_declared_type():
    # 清单中登记的字段在合同类型中以同样的类型存在：删除字段、改变类型或删除已登记取值时失败；
    # 取值固定的字段取值集合扩大时仍算同一类型（#241）
    fields, _, _ = _manifest_documents()
    live = live_fields()
    removed, retyped = {}, {}
    for kind, manifest_fields in fields.items():
        live_kind = live[kind]
        for name, declared in manifest_fields.items():
            if name not in live_kind:
                removed.setdefault(kind, []).append(name)
            elif not same_type(declared, live_kind[name]):
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
        "合同类型中出现了清单没有登记的新种类或新字段，用 "
        "python -m pytest harness/tests/test_project_stream_fields.py --write-project-stream-fields 写入清单，"
        f"并在 added_defaults 中写明新字段在旧事件中的缺省含义：{additions}"
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

def _doctored_live(registered: dict, drop_kinds=(), drop_fields=(), retypes=(), additions=()):
    # 以已登记的字段为基础造出合同类型：删掉种类、删掉字段、改掉类型或增加种类与字段，
    # 用来核对写入路径只接受添加
    live = {kind: dict(fields) for kind, fields in registered.items()}
    for kind in drop_kinds:
        live.pop(kind)
    for kind, name in drop_fields:
        live[kind].pop(name)
    for kind, name, declared in retypes:
        live[kind][name] = declared
    for kind, name, declared in additions:
        live.setdefault(kind, {})[name] = declared
    return live

@pytest.fixture
def scratch_manifest(tmp_path, monkeypatch):
    # 写入类的测试都在临时目录的清单副本上进行，仓库里提交的那一份不会被改动。
    # 默认内容是当前提交的清单，因此写入路径面对的是与合同类型一致的清单
    path = tmp_path / "project_stream_fields.json"
    path.write_text(MANIFEST.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(project_stream_fields, "MANIFEST", path)
    return path

def test_writing_rejects_a_removed_event_kind(scratch_manifest, monkeypatch):
    # 合同类型里删掉一个项目流事件种类：写入被拒绝，写明是哪个种类，清单不变
    registered = load_manifest()["fields"]
    before = scratch_manifest.read_text(encoding="utf-8")
    removed = "material_recorded"
    monkeypatch.setattr(project_stream_fields, "live_fields",
                        lambda: _doctored_live(registered, drop_kinds=(removed,)))
    with pytest.raises(ManifestWriteRejected) as caught:
        apply_rewrite()
    assert "删除事件种类" in str(caught.value)
    assert removed in str(caught.value)
    assert scratch_manifest.read_text(encoding="utf-8") == before

def test_writing_rejects_a_removed_field(scratch_manifest, monkeypatch):
    # 合同类型里删掉一个已登记的字段：写入被拒绝，写明种类与字段名，清单不变
    registered = load_manifest()["fields"]
    before = scratch_manifest.read_text(encoding="utf-8")
    monkeypatch.setattr(project_stream_fields, "live_fields",
                        lambda: _doctored_live(registered, drop_fields=(("project_renamed", "name"),)))
    with pytest.raises(ManifestWriteRejected) as caught:
        apply_rewrite()
    assert "删除字段" in str(caught.value)
    assert "project_renamed.name" in str(caught.value)
    assert scratch_manifest.read_text(encoding="utf-8") == before

def test_writing_rejects_a_changed_field_type(scratch_manifest, monkeypatch):
    # 合同类型里改掉一个已登记字段的类型：写入被拒绝，写明原来的类型与新的类型
    registered = load_manifest()["fields"]
    before = scratch_manifest.read_text(encoding="utf-8")
    monkeypatch.setattr(project_stream_fields, "live_fields",
                        lambda: _doctored_live(registered,
                                               retypes=(("project_pinned", "pinned", "string"),)))
    with pytest.raises(ManifestWriteRejected) as caught:
        apply_rewrite()
    assert "改变字段类型" in str(caught.value)
    assert "project_pinned.pinned: boolean -> string" in str(caught.value)
    assert scratch_manifest.read_text(encoding="utf-8") == before

def test_writing_adds_a_new_kind_and_a_new_field_and_keeps_the_baseline(scratch_manifest, monkeypatch):
    # 写入路径接受添加：新的种类与新的字段进入 fields；baseline 与 added_defaults 原样不动，
    # 新字段在旧事件中的缺省含义由改动者另行写明，写入路径不代填
    document = load_manifest()
    added_kind, added_field = "fault_recorded", "fault_id"
    live = _doctored_live(document["fields"], additions=(
        (added_kind, added_field, "string"), (added_kind, "severity", "enum string"),
        ("project_renamed", "renamed_at", "string")))
    monkeypatch.setattr(project_stream_fields, "live_fields", lambda: live)
    apply_rewrite()
    written = load_manifest()
    assert written["fields"] == live
    assert written["fields"][added_kind] == {added_field: "string", "severity": "enum string"}
    assert written["baseline"] == document["baseline"]
    assert written["added_defaults"] == document["added_defaults"]
    assert written["note"] == document["note"]

def test_writing_a_missing_manifest_reports_recovery_from_git(tmp_path, monkeypatch):
    # 清单文件缺失：写入路径报错并说明从 git 历史恢复，不新建清单
    missing = tmp_path / "project_stream_fields.json"
    monkeypatch.setattr(project_stream_fields, "MANIFEST", missing)
    with pytest.raises(FileNotFoundError) as caught:
        apply_rewrite()
    assert "从 git 历史恢复" in str(caught.value)
    assert not missing.exists()


def test_writing_accepts_an_expanded_value_set_and_records_it(scratch_manifest, monkeypatch):
    # #241：取值固定字段（enum）的取值集合扩大时写入成功，清单记录扩大后的取值集合
    registered = load_manifest()["fields"]
    live = _doctored_live(registered, retypes=(
        ("department_prompt_configured", "department",
         "enum string[engineering, product, quality, research]"),))
    monkeypatch.setattr(project_stream_fields, "live_fields", lambda: live)
    apply_rewrite()
    written = load_manifest()
    assert written["fields"]["department_prompt_configured"]["department"] == (
        "enum string[engineering, product, quality, research]")

def test_writing_rejects_a_removed_value_and_names_it(scratch_manifest, monkeypatch):
    # #241：取值固定字段删除一个已登记的取值时写入被拒绝，拒绝原因写明被删除的取值；改变字段类型仍被拒绝
    registered = load_manifest()["fields"]
    before = scratch_manifest.read_text(encoding="utf-8")
    live = _doctored_live(registered, retypes=(
        ("department_prompt_configured", "department", "enum string[engineering, product]"),))
    monkeypatch.setattr(project_stream_fields, "live_fields", lambda: live)
    with pytest.raises(ManifestWriteRejected) as caught:
        apply_rewrite()
    assert "改变字段类型" in str(caught.value)
    assert "删除取值 quality" in str(caught.value)
    assert scratch_manifest.read_text(encoding="utf-8") == before

