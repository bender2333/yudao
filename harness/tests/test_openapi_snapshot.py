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

SNAPSHOT = Path(__file__).parent / "openapi" / "openapi.json"
# 包版本号不属于接口合同：比较与重写都把两边的 info.version 取成这个固定值，
# 因此发布只改版本号文件，不再需要重写快照与客户端类型
SNAPSHOT_VERSION = "0.0.0"


def _openapi_document():
    # 生成文档只需要路由与注册表：从不调用打开 Application 的回调
    return create_app(lambda: None).openapi()


def _text(document) -> str:
    document = json.loads(json.dumps(document))
    document["info"]["version"] = SNAPSHOT_VERSION
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def test_the_openapi_document_matches_its_snapshot(request):
    document = _openapi_document()
    if request.config.getoption("--write-openapi-snapshot"):
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

