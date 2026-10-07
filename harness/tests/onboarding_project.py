# 建档与排空测试共用的一份已有项目、轮询等待与重复打开的应用：多个测试文件共用，
# 原先分散在各自的测试文件中。真实数据目录、真实 SQLite 与真实的 FastAPI 服务在这些测试内部起，
# 这里只准备材料、等待条件与发命令的形状。

import time
import uuid

from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.runtime import LoopSystem
from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC

ONBOARDING_GOAL = "把已有项目接入 Yudao，写出初始 PRD 并核验现有行为"
ONBOARDING_REQUIREMENT = "print the given argument to stdout"

# 轮询等待的墙钟界限只用来防止测试一直等待（#107）；run 是否按预期结束由等待之后的断言核对
WAIT_LIMIT = WAIT_FOR_HOST_WORK_SEC


def onboarding_source(root, *, with_failing_test: bool = False):
    # 一份最小的已有项目：一个可运行的脚本、一个说明文件与一个通过的测试
    (root / "src").mkdir(parents=True)
    (root / "src" / "echo.py").write_text("import sys\nprint(sys.argv[1])\n", encoding="utf-8")
    (root / "README.md").write_text("# Echo\n\nPrint the given argument.\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_echo.py").write_text("def test_placeholder():\n    assert True\n", encoding="utf-8")
    if with_failing_test:
        (root / "tests" / "test_broken.py").write_text("def test_broken():\n    assert False\n", encoding="utf-8")
    return root


def wait_until(predicate) -> bool:
    deadline = time.monotonic() + WAIT_LIMIT
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def post_command(client, command, **body):
    return client.post(f"/api/commands/{command}", json={"command_id": str(uuid.uuid4()), **body})


def open_initial_prd(client, project_id) -> dict | None:
    decisions = client.get(f"/api/queries/decisions.list?project_id={project_id}").json()["data"]["decisions"]
    return next((item for item in decisions if item["kind"] == "initial_prd" and item["status"] == "open"), None)


class OpenedFake:
    # 一个可以反复打开的应用：每次打开都从头读取同一个数据目录，模型回答由同一个 FakeAdapter 给出。
    # turns 给出模型的一轮轮回答（FakeAdapter 的脚本），adapter 直接给出已构造好的适配器
    def __init__(self, data_dir, turns=None, adapter=None) -> None:
        self.data_dir = data_dir
        self.adapter = adapter if adapter is not None else FakeAdapter([] if turns is None else turns)
        self.applications: list[Application] = []

    def __call__(self) -> Application:
        application = Application(LoopSystem.for_testing(self.data_dir, self.adapter))
        self.applications.append(application)
        return application

    @property
    def store(self):
        return self.applications[-1].system.store

    @property
    def system(self) -> LoopSystem:
        return self.applications[-1].system
