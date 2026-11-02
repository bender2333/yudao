import pytest

from harness.watched_outputs import has_new_work
from harness.adapters.fake import FakeTurn
from harness.proposals import answer_turn, ask_turn, delivery_turn, judgement_turn, product_spec, review_turn
from harness.smoke import isolation_fields, summarize_run
from harness.tests.helpers import (
    compacted_runner,
    explore_turn,
    recorded_context,
    run_scripted,
    system_on_copy,
)

# 需要一份真实运行记录的文件：module 作用域的夹具各跑一次完整循环并保存数据目录，
# 每项测试复制一份数据目录，在自己的副本上改写与检查。数据来自真实运行，这些文件登记为集成层。


@pytest.fixture(scope="module")
def saved_native(tmp_path_factory):
    # 一次本机流程走完的运行：产品给要求、工程写入、检查、交付、再检查、质检放行
    # 提交依据的版本由工厂从请求里的当前版本取（工单 #471）：脚本项是工厂而不是裸提交
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）：
    # 质检在 PRD 被接纳以后还有一轮预测性探索，这一轮没有交付可以核验，提交的结论被拒绝
    # 提交依据的版本由工厂从请求里的当前版本取（工单 #471）：脚本项是工厂而不是裸提交。
    # 按部门给出（工单 #557：同时运行的会话各自取用自己的脚本），质检先起草测试材料
    script = {
        "product": [product_spec()],
        "engineering": [
            FakeTurn(writes={"src/echo.py": "import sys\nprint(sys.argv[1])\n"}),
            FakeTurn(checks={"smoke": 0}),
            delivery_turn(),
        ],
        "quality": [
            explore_turn(),
            FakeTurn(checks={"smoke": 0}),
            review_turn("release", "host checks passed"),
        ],
    }
    system, projection = run_scripted(tmp_path_factory.mktemp("native"), script)
    assert projection.status == "done"
    system.close()
    return system.data_dir, projection.run_id

@pytest.fixture
def native_run(saved_native, tmp_path):
    saved, run_id = saved_native
    return system_on_copy(saved, tmp_path / "native"), run_id


@pytest.fixture(scope="module")
def saved_ask(tmp_path_factory):
    from harness.demo import run_demo

    system, run_id = run_demo(tmp_path_factory.mktemp("ask"))
    # 记录装配上下文的检查要按 run 读回每一次请求：请求本身在调用清单里，清单随数据目录保存
    invocations = list(system.test_adapter.invocations)
    system.close()
    return system.data_dir, run_id, invocations

@pytest.fixture
def ask_run(saved_ask, tmp_path):
    saved, run_id, _invocations = saved_ask
    return system_on_copy(saved, tmp_path / "ask"), run_id

@pytest.fixture
def ask_invocations(saved_ask):
    # 保存的运行里每一次模型请求：检查装配上下文时按请求读回同一份清单
    _saved, _run_id, invocations = saved_ask
    return invocations


def test_model_input_audit_tracks_new_input_and_prompt_versions(ask_run, ask_invocations):
    system, run_id = ask_run
    summary = summarize_run(system, run_id, scenario="ask")
    assert summary["model_input_audit"]["status"] == "verified", summary["model_input_audit"]
    assert summary["check_receipts_verified"] is True
    assert summary["delivery_archive"]["status"] == "verified"
    manifests = [(request.department, recorded_context(system, request).manifest)
                 for request in ask_invocations]
    assert {manifest.input_version for _department, manifest in manifests} == {1, 2}
    # demo 在事项进行中修改产品部门的部门 Prompt：修改前的请求用内置默认（版本 0），之后用项目设置（版本 1）
    assert {manifest.prompt_version for department, manifest in manifests if department == "product"} == {0, 1}


# 工程询问产品、产品在询问分支里回答的一份运行记录；用到它的用例已随测试减法删除（#1024），脚本与夹具暂留
# 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本）
_PRODUCT_RETURN_SCRIPT = {
    "product": [product_spec()],
    "engineering": [ask_turn(recipient="product", question="Clarify flags?"), delivery_turn()],
    "product:ask": [answer_turn("The existing requirements do not distinguish flags.")],
    "quality": [explore_turn(), judgement_turn(), review_turn("release", "host checks passed")],
}

@pytest.fixture(scope="module")
def saved_product_return(tmp_path_factory):
    system, projection = run_scripted(tmp_path_factory.mktemp("product-return"), _PRODUCT_RETURN_SCRIPT)
    assert projection.status == "done"
    system.close()
    return system.data_dir, projection.run_id

@pytest.fixture
def product_return_run(saved_product_return, tmp_path):
    saved, run_id = saved_product_return
    return system_on_copy(saved, tmp_path / "product-return"), run_id


@pytest.fixture(scope="module")
def saved_compacted(tmp_path_factory):
    # 上下文窗口只有 6000 的运行：压缩以后继续工程工作，保存到第一次压缩之后
    system, adapter, run_id, _original = compacted_runner(tmp_path_factory.mktemp("compacted"))
    # 脚本按部门给出（工单 #888）：compacted_runner 直接给每个部门各一份剧本
    result = system.activate_once(run_id)
    assert has_new_work(result, "engineering")
    assert len(result.compactions) > 1
    system.close()
    return system.data_dir, run_id

@pytest.fixture
def compacted_run(saved_compacted, tmp_path):
    saved, run_id = saved_compacted
    return system_on_copy(saved, tmp_path / "compacted"), run_id

def test_compaction_audit_checks_partial_sources_and_resumed_input(compacted_run):
    system, run_id = compacted_run
    fields = isolation_fields(system.store, system.artifacts, run_id)
    assert fields["context_isolated"] is True, fields["model_input_audit"]["notes"]
    assert fields["model_input_audit"]["compaction_count"] > 1


