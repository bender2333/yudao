"""客户端的事件种类夹具与服务端的 EVENT_TYPES 相同（工单 #952 验收标准 5）。

客户端的翻译覆盖核对读不了 Python，用夹具 `client/tests/fixtures/event-types.json` 作为事件种类的来源；
这一个测试核对夹具与 `harness/app/contracts.py` 的 `EVENT_TYPES` 相同。服务端新增或删除事件种类时它先失败，
提示重新生成夹具；夹具更新以后客户端的覆盖核对（`client/src/renderer/src/translate/coverage.ts`）失败，
提示在那三个场景里补上归属。

EVENT_TYPES 以后换位置时（M0.5 的 S5a 把事件种类分成骨架事件与应用事件，工单 #828），这个测试跟着它取。

守第 13 节的 R2（两端共读的清单：事件种类）。
"""

import json
from pathlib import Path

from harness.app.contracts import EVENT_TYPES

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "client" / "tests" / "fixtures" / "event-types.json"
REGENERATE = (
    "服务端的事件种类变了：按 harness/app/contracts.py 的 EVENT_TYPES 重新生成 "
    "client/tests/fixtures/event-types.json，再在 client/src/renderer/src/translate/coverage.ts "
    "里给新增的事件补上三个场景的归属"
)


def _fixture() -> list[str]:
    assert FIXTURE.is_file(), f"缺少客户端的事件种类夹具：{FIXTURE}"
    types = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(types, list), f"夹具应当是一个事件种类的数组：{FIXTURE}"
    assert all(isinstance(value, str) and value for value in types), f"夹具里的每项都应当是一个事件种类：{FIXTURE}"
    assert len(types) == len(set(types)), f"夹具里有重复的事件种类：{sorted({value for value in types if types.count(value) > 1})}"
    return types


def test_the_client_fixture_matches_the_server_event_types():
    types = _fixture()
    missing = sorted(set(EVENT_TYPES) - set(types))
    extra = sorted(set(types) - set(EVENT_TYPES))
    assert not missing and not extra, (
        f"客户端的事件种类夹具与服务端的 EVENT_TYPES 不一致：缺 {missing}，多 {extra}。" + REGENERATE
    )
