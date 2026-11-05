import difflib
import json
from pathlib import Path

import pytest

from harness.api.app import create_app
from harness.tests.client_types_check import check_client_types

# OpenAPI 快照：harness.api.app.create_app 返回的应用的 openapi() 文档与 harness/tests/openapi/openapi.json 相同。
# 生成文档不经过生命周期，不打开 Application，也不启动服务。
# 合同（应用层的 pydantic 类型、注册表）改变时这个测试失败；有意的改变用
# python -m pytest harness/tests/test_openapi_snapshot.py --write-openapi-snapshot 重写快照，
# 再在 harness/tests/openapi 中运行 npm run check，由快照生成 TypeScript 类型并编译。
# 合同里删掉或改变已有的东西（路径、查询、命令、事件种类及其字段）时要同时提高 API_VERSION
# （应用层与接口层设计说明第 6.1 节、第 9 节第 1 条），重写快照也不例外。

SNAPSHOT = Path(__file__).parent / "openapi" / "openapi.json"
# 包版本号不属于接口合同：比较与重写都把两边的 info.version 取成这个固定值，
# 因此发布只改版本号文件，不再需要重写快照与客户端类型
SNAPSHOT_VERSION = "0.0.0"

# 接口版本记在 Deployment.api_version 的 example 里（contracts.py 用 Field 的 example 写出），
# 读快照的这一处就知道快照生成时的版本，不需要另外记。
_VERSION_SCHEMA = "Deployment"
_VERSION_FIELD = "api_version"
# 不属于合同：说明、标题、示例与调用编号只是措辞，改了不改变客户端能用的查询、命令与字段
_NOT_CONTRACT = frozenset({"description", "title", "summary", "example", "examples", "operationId", "tags",
                           "info", "servers"})
# 这三个键的值是类型声明：两边不同就是改变了类型
_TYPE_KEYS = ("type", "$ref", "format")


def _openapi_document():
    # 生成文档只需要路由与注册表：从不调用打开 Application 的回调
    return create_app(lambda: None).openapi()


def _read_snapshot():
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def _text(document) -> str:
    document = json.loads(json.dumps(document))
    document["info"]["version"] = SNAPSHOT_VERSION
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def _api_version(document):
    properties = document.get("components", {}).get("schemas", {}).get(_VERSION_SCHEMA, {}).get("properties", {})
    return properties.get(_VERSION_FIELD, {}).get("example")


def _element_name(item):
    """列表里的对象按名字认：参数按位置与名字、引用按引用名；标量按值认，没有名字。"""
    if isinstance(item, dict):
        if "name" in item:
            return f"{item.get('in', '')} {item['name']}"
        if "$ref" in item:
            return item["$ref"].rsplit("/", 1)[-1]
    return None


def _contract_changes(before, after, where="") -> list[str]:
    """列出 after 里不再有或改了类型的部分：只报失去的东西，不报措辞与顺序。"""
    changes: list[str] = []
    if isinstance(before, dict) and isinstance(after, dict):
        for key, old_value in before.items():
            if key in _NOT_CONTRACT:
                continue
            here = f"{where}.{key}" if where else key
            if key not in after:
                changes.append(f"删除 {here}")
            elif key in _TYPE_KEYS and not isinstance(old_value, (dict, list)):
                if after[key] != old_value:
                    changes.append(f"改变类型 {here}：{old_value} → {after[key]}")
            else:
                changes.extend(_contract_changes(old_value, after[key], here))
        return changes
    if isinstance(before, list) and isinstance(after, list):
        names = [_element_name(item) for item in before]
        if any(name is None for name in names):
            # 标量列表（enum、required）与其他没有名字的对象：按值比较，少了的就是删除
            for item in before:
                if item not in after:
                    changes.append(f"删除 {where}[{json.dumps(item, ensure_ascii=False)}]")
            return changes
        for name, item in zip(names, before):
            matched = next((other for other in after if _element_name(other) == name), None)
            if matched is None:
                changes.append(f"删除 {where}[{name}]")
            else:
                changes.extend(_contract_changes(item, matched, f"{where}[{name}]"))
    return changes


def _contract_regressions(snapshot, document) -> list[str]:
    """合同里删掉或改变了已有的东西而接口版本没有提高时，返回要说给人听的清单。"""
    changes = _contract_changes(snapshot, document)
    if not changes:
        return []
    recorded = _api_version(snapshot)
    current = _api_version(document)
    if current is not None and recorded is not None and current > recorded:
        return []
    return [
        f"快照记的接口版本是 {recorded}，现在生成的是 {current}，没有提高：",
        *(f"- {change}" for change in changes),
        "删除或改变已有的查询、命令、事件种类及其字段时提高 harness/app/contracts.py 的 API_VERSION，"
        "再重新生成快照与客户端类型。",
    ]


def test_the_openapi_document_matches_its_snapshot(request):
    document = _openapi_document()
    if request.config.getoption("--write-openapi-snapshot"):
        # 重写快照同样执行接口版本的检查：版本没有提高时拒绝写入，快照不会被悄悄改小
        regressions = _contract_regressions(_read_snapshot(), document)
        assert not regressions, "合同里少了或改了已有的东西而接口版本没有提高，拒绝重写快照：\n" + "\n".join(
            regressions)
        SNAPSHOT.write_text(_text(document), encoding="utf-8")
    expected = SNAPSHOT.read_text(encoding="utf-8")
    difference = list(difflib.unified_diff(expected.splitlines(), _text(document).splitlines(), "snapshot",
                                           "generated", lineterm="", n=2))
    assert not difference, "OpenAPI document differs from its snapshot:\n" + "\n".join(difference[:120])


def test_the_committed_client_types_match_the_snapshot(request):
    # 重写快照时这项检查没有意义：先在 harness/tests/openapi 中运行 npm run check 编译，
    # 再在 client 中运行 npm run generate:api 重新生成客户端类型并提交
    if request.config.getoption("--write-openapi-snapshot"):
        pytest.skip("重写快照时不检查客户端类型")
    differences = check_client_types()
    assert not differences, "提交的客户端类型与 OpenAPI 快照不一致：\n" + "\n".join(differences)


def test_the_interface_version_rises_when_an_existing_contract_disappears():
    # 守 R2（对外合同，测试分层设计说明第 13 节）：已有的查询、命令、事件种类及其字段被删除或改变类型时，
    # 接口版本必须提高；只增加时不要求提高。旧页面按自己记录的版本调用，版本没升就拿到它没有的类型。
    regressions = _contract_regressions(_read_snapshot(), _openapi_document())
    assert not regressions, "合同里少了或改了已有的东西而接口版本没有提高：\n" + "\n".join(regressions)
