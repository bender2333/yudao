# 装配的缝：同样的事件重放出同样的请求（工单 #1399；总图第四节「装配」缝的规矩「同样的事件重放出同样的请求」；
# 骨架与应用设计说明第 5.2 节「装配契约」；差异报告 docs/evaluation/seam-diff-2026-10-31-5f5ff252.md 的结论第 4 条）。
#
# 从一段真实运行的事件出发：一次部门激活写下的那一段事件与同一份定义交给装配两次，第二次在重新打开的事件库上
# （第一次装配跑完以后关掉事件库与工件库，再打开一次）。两次交出的请求字节与上下文清单必须完全相同。
# 真实装配（`assembly.py` 的 `ContextAssembly`）与第二种装配（`harness/tests/second_assembly.py`）各一条。
#
# 它拦什么：装配读了事件与定义以外的东西时这条失败——
# - 时钟：请求里带上「现在」，两次装配之间已经过去了一段时间，字节就不同；
# - 随机数：每次生成的编号、顺序或盐不同；
# - 进程里的缓存：第一次装配留下的状态改变第二次交出的材料，或者重新打开事件库以后读到的东西与第一次不同。
# 限度：两次装配在同一个进程里完成，只到秒或只到日期的粗粒度时间，以及取值只由事件内容决定的进程缓存，
# 它都分不出；这类取值要靠与记录下来的那一份请求比对（`test_assembly.py` 的用例）兜住。
#
# 层：模块层（一次部门激活、SQLite 事件库与工件库，不跑完整三部门循环）。缝的合同检查按测试分层设计说明
# 第 12 节登记在单元层或模块层，由 CI 的 module 作业在每次推送时运行。
# 守 R2（装配这只缝的两侧交换什么与它的规矩：同样的事件与定义，交出的请求字节与上下文清单相同）。

from __future__ import annotations

from dataclasses import asdict

import pytest

from harness.adapters.fake import FakeAdapter
from harness.artifacts import ArtifactStore
from harness.assembly import ContextAssembly, model_limits
from harness.assembly_contract import StepFrame
from harness.department_prompts import save_department_prompt
from harness.definitions import DEFINITIONS
from harness.event_store import EventStore
from harness.models import DepartmentPrompt, EventType, json_dumps
from harness.projection import project_run
from harness.proposals import product_spec
from harness.runtime import LoopSystem
from harness.tests import second_assembly
from harness.tightening import WATCHED_OUTPUTS

# 两种实现的名称：参数化的检查对它们各跑一遍（与 test_slot_contracts 同一组名字）
ASSEMBLIES = ["the real assembly", "the second assembly"]
DEPARTMENT = "product"
TASK = "print the argument in uppercase"


@pytest.fixture
def saved_run(tmp_path):
    # 一段真实运行：一次部门激活把事件写进 SQLite 事件库、把请求材料写进工件库；跑完关掉系统，
    # 下面每一次装配都从磁盘上重新读这两样，进程里不留这次运行的连接
    system = LoopSystem.for_testing(tmp_path, FakeAdapter({DEPARTMENT: [product_spec()]}))
    run_id = system.create_run(TASK)
    system.activate_once(run_id)
    system.close()
    return tmp_path, run_id


def _open_stores(data_dir):
    # 事件库与工件库各打开一次：调用方关掉以后再打开，就是「重新打开的事件库」
    return EventStore(data_dir / "events.sqlite"), ArtifactStore(data_dir / "artifacts")


def _recorded_input(data_dir, run_id):
    # 真实运行记下来的那一步装配的输入：部门、会话与激活的身份，这一轮采用的提示与版本，
    # 调用目标的窗口与输出上限，以及装配当时的工作区快照
    store, artifacts = _open_stores(data_dir)
    event = next(item for item in reversed(store.list_events(run_id))
                 if item.type == EventType.CONTEXT_ASSEMBLED)
    payload = event.payload
    # 这一段运行是 bare run（`create_run` 直接建的事项）：部门提示是内置默认的那一份，版本 0
    text = DEFINITIONS.role(event.department).prompt
    prompt = DepartmentPrompt(event.department, 0, text,
                              save_department_prompt(artifacts, run_id, event.department, text), "")
    # 重建的部门提示就是真实运行当时那一份：版本与摘要都与记录的对得上
    assert (prompt.version, prompt.prompt_ref.content_hash) == (payload["prompt_version"], payload["prompt_hash"])
    frame = StepFrame(department=event.department, session_id=event.session_id,
                      activation_id=payload["activation_id"], prompt=prompt,
                      effective_contract_hash=payload["effective_contract_hash"],
                      input_version=payload["input_version"], definitions=DEFINITIONS)
    limits = model_limits(payload["context_window"], payload["configured_max_output_tokens"])
    store.close()
    return frame, limits, payload["step_id"], payload["snapshot_hash"]


def _assemble(name, data_dir, run_id, frame, limits, step_id, snapshot_hash):
    # 一次装配：事件与保存的投影都从这一次打开的事件库读出来（是不是重新打开的那一个由调用次序决定），
    # 实现按名称接上，与组装处把实现交给薄驱动的接法相同
    store, artifacts = _open_stores(data_dir)
    events = store.list_events(run_id)
    implementation = (ContextAssembly(artifacts, store, tightening=WATCHED_OUTPUTS)
                      if name == ASSEMBLIES[0] else second_assembly.SecondAssembly())
    pinned = implementation.pin(project_run(store, run_id), frame, limits, step_id=step_id,
                                events=events, snapshot_hash=snapshot_hash)
    history = implementation.department_history(events, frame.department, session_id=frame.session_id)
    step = implementation.request(pinned, history)
    store.close()
    return events, step


def _mismatch(first, second):
    # 两次交出的请求不一样时指出第一个不同的位置与它前后的文字（整份请求太长，不打印）
    index = next((position for position, (left, right) in enumerate(zip(first, second)) if left != right),
                 min(len(first), len(second)))
    window = slice(max(0, index - 60), index + 120)
    return (f"\n第 {index} 个字节起不同（共 {len(first)} 与 {len(second)} 个字节）"
            f"\n第一次：{first[window]!r}\n第二次：{second[window]!r}")


@pytest.mark.parametrize("name", ASSEMBLIES)
def test_each_assembly_turns_the_same_events_into_the_same_request(name, saved_run):
    data_dir, run_id = saved_run
    frame, limits, step_id, snapshot_hash = _recorded_input(data_dir, run_id)

    first_events, first = _assemble(name, data_dir, run_id, frame, limits, step_id, snapshot_hash)
    # 第二次在重新打开的事件库上：上面那次装配已经跑完，事件库与工件库都关掉再打开一次
    second_events, second = _assemble(name, data_dir, run_id, frame, limits, step_id, snapshot_hash)

    # 比较的两边都不是空的：请求里有要发给模型的内容，上下文清单列出了材料
    assert first.payload["input"], "装配没有交出要发给模型的内容，这样的比较证明不了什么"
    assert first.context.manifest.injected and first.parts
    # 两次读到的确实是同一份事件
    assert second_events == first_events, "重新打开的事件库读到的不是同一份事件"
    # 交给模型的那份逐字节相同：与写进 model_request 工件的是同一份序列化
    first_bytes = json_dumps(first.payload).encode("utf-8")
    second_bytes = json_dumps(second.payload).encode("utf-8")
    assert second_bytes == first_bytes, "同一份事件与定义两次交出了不同的请求：" + _mismatch(first_bytes, second_bytes)
    # 上下文清单也相同：放进去的每一段、摘要、token 估算、预算与步骤
    assert asdict(second.context.manifest) == asdict(first.context.manifest)
    # 清单指着的那几段材料连同原文也相同
    assert second.parts == first.parts
