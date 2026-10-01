import difflib
import json
from pathlib import Path

import pytest

from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.runtime import LoopSystem
from harness.tests.api_helpers import running_api
from harness.tests.client_types_check import check_client_types

# OpenAPI 快照：运行中的服务在 /openapi.json 返回的文档与 harness/tests/openapi/openapi.json 相同。
# 合同（应用层的 pydantic 类型、注册表）改变时这个测试失败；有意的改变用
# python -m pytest harness/tests/test_openapi_snapshot.py --write-openapi-snapshot 重写快照，
# 再在 harness/tests/openapi 中运行 npm run check，由快照生成 TypeScript 类型并编译。

SNAPSHOT = Path(__file__).parent / "openapi" / "openapi.json"


def _text(document) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def test_the_served_openapi_document_matches_its_snapshot(data_dir, request):
    with running_api(lambda: Application(LoopSystem.for_testing(data_dir, FakeAdapter([])))) as client:
        response = client.get("/openapi.json")
    assert response.status_code == 200
    document = response.json()
    if request.config.getoption("--write-openapi-snapshot"):
        SNAPSHOT.write_text(_text(document), encoding="utf-8")
    expected = SNAPSHOT.read_text(encoding="utf-8")
    difference = list(difflib.unified_diff(expected.splitlines(), _text(document).splitlines(), "snapshot",
                                           "served", lineterm="", n=2))
    assert not difference, "OpenAPI document differs from its snapshot:\n" + "\n".join(difference[:120])

def test_the_committed_client_types_match_the_snapshot(request):
    # 重写快照时这项检查没有意义：先在 harness/tests/openapi 中运行 npm run check 编译，
    # 再在 client 中运行 npm run generate:api 重新生成客户端类型并提交
    if request.config.getoption("--write-openapi-snapshot"):
        pytest.skip("重写快照时不检查客户端类型")
    differences = check_client_types()
    assert not differences, "提交的客户端类型与 OpenAPI 快照不一致：\n" + "\n".join(differences)
