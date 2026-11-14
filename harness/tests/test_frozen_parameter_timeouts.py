# 建 run 时冻结命令与检查的时间限额上限（规则登记与参数 docs/design/rules-and-parameters.md「参数怎样成为带版本的数据」）：
# bash_timeout_default_sec、bash_timeout_max_sec 与 check_timeout_max_sec 按 run 创建时冻结的取值生效。
# 两条用例启动真实子进程等待时间限额到期，按 docs/design/test-pyramid.md「测试往下层移」登记为集成层；
# 其余冻结参数的模块层用例见 test_frozen_parameters.py。守 R1（边界与冻结）。

from __future__ import annotations

import json
import sys

from harness.adapters.fake import FakeAdapter
from harness.models import EventType
from harness.proposals import product_spec
from harness.providers.call import ModelResponse
from harness.runtime import LoopSystem

GOAL = "print the argument in uppercase"


def _call(identity: str, tool: str, /, **arguments: object) -> dict[str, object]:
    return {"id": identity, "call_id": identity, "type": "function_call", "name": tool,
            "arguments": json.dumps(arguments)}


def _respond(*calls: dict[str, object]):
    # 这一次模型回答给出这些工具调用（每次请求取一条脚本项）
    def respond(request):
        return ModelResponse(output=list(calls))
    return respond


def _system(tmp_path, script=None) -> LoopSystem:
    # 不给 step_limits：上限按 run 创建时冻结的参数构造（给了就整份照用，绕开冻结）
    return LoopSystem.for_testing(tmp_path, FakeAdapter(script or {"product": [product_spec()]}))


def _python(command: str) -> str:
    # 命令串交给 bash 执行：解释器取当前进程的 sys.executable，路径写成正斜杠并加引号（helpers 的同一做法）
    return f'"{sys.executable.replace(chr(92), "/")}" {command}'


def _tool_called(system: LoopSystem, run_id: str, identity: str) -> dict:
    # tool_called 的载荷把结果存成 output_ref，结果本身按 input_item 里的三项 JSON 取回
    event = next(event for event in system.store.list_events(run_id)
                 if event.type == EventType.TOOL_CALLED and (event.payload or {}).get("id") == identity)
    return json.loads(event.payload["input_item"]["output"])


def _set(system: LoopSystem, name: str, value: object) -> None:
    system.set_parameter(name, value, reason="核对冻结", modified_by="user:test")


def test_bash_timeouts_come_from_the_frozen_values(tmp_path):
    slow = _python('-c "import time; time.sleep(30)"')
    script = {"product": [_respond(_call("slow-default", "bash", command=slow)),
                          _respond(_call("slow-max", "bash", command=slow, timeout_sec=100)), product_spec()]}
    system = _system(tmp_path, script)
    project_id = system.projects.register("命令时限", GOAL)
    _set(system, "bash_timeout_default_sec", 1)
    _set(system, "bash_timeout_max_sec", 10)
    _item, run_id = system.projects.start_work_item(project_id, GOAL)
    system.activate_once(run_id)

    assert _tool_called(system, run_id, "slow-default")["output"]["status"] == "timeout"
    # 请求里的 100 秒按冻结的上限压到 2 秒
    assert _tool_called(system, run_id, "slow-max")["output"]["status"] == "timeout"
    system.close()


def test_check_timeout_max_comes_from_the_frozen_value(tmp_path):
    script = {"product": [_respond(_call("slow-check", "run_check", name="slow", command=_python("sleep.py"),
                                         timeout_sec=100)),
                          product_spec()]}
    system = _system(tmp_path, script)
    project_id = system.projects.register("检查时限", GOAL)
    _set(system, "check_timeout_max_sec", 10)
    _item, run_id = system.projects.start_work_item(project_id, GOAL)
    system.workspace(run_id).write_file("sleep.py", "import time\ntime.sleep(30)\n")
    system.activate_once(run_id)

    assert "check timed out after 10s" in _tool_called(system, run_id, "slow-check")["output"]["summary"]
    system.close()
