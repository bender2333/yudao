import difflib
import json
from pathlib import Path

from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.runtime import LoopSystem
from harness.tests.api_helpers import running_api

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
