"""B1 项目与事项内核：§11 API 与 §13 反例（HTTP 部分）。"""

import json
import threading
import time
from http.client import HTTPConnection

import pytest

from harness.adapters.fake import FakeAdapter
from harness.definitions import DEFINITIONS
from harness.models import EventType, ProjectEventType
from harness.proposals import delivery_turn, plan_turn, product_spec, review_turn
from harness.runtime import LoopSystem
from harness.tests.helpers import happy_script
from harness.tests.test_web import get_json, request, running_server, wait_until

GOAL = "做一个可以长期演进的逐行文本处理工具。"


def _release_script(summary="v1", files=None):
    return [product_spec(), plan_turn(), delivery_turn(summary=summary, files=files), review_turn("release", f"ok {summary}")]


def _v2_files():
    return {"src/echo.py": "import sys\nprint(sys.argv[1].upper())\n", "src/extra.py": "EXTRA = True\n"}


def _post(host, port, path, body=None, expected=200):
    status, raw, _ = request(host, port, "POST", path, body if body is not None else {})
    assert status == expected, raw
    return json.loads(raw) if raw else {}


def _put(host, port, path, body):
    status, raw, _ = request(host, port, "PUT", path, body)
    return status, json.loads(raw)


def _register(host, port, name="Echo", goal=GOAL):
    return _post(host, port, "/api/projects", {"name": name, "goal": goal}, 201)["project_id"]


def _wait_work_item(host, port, project_id, work_item_id, statuses=("adopted", "held", "stopped"), timeout=60.0):
    """等到事项进入终态且工作线程已退出（GET 项目会补跑结算，可能先于工作线程结束）。"""

    def check():
        project = get_json(host, port, f"/api/projects/{project_id}")
        item = next(entry for entry in project["work_items"] if entry["work_item_id"] == work_item_id)
        if item["status"] not in statuses or get_json(host, port, "/api/health")["busy"]:
            return False
        return project

    return wait_until(check, timeout=timeout)


def _gated_turn():
    entered, release = threading.Event(), threading.Event()

    def turn(_request):
        entered.set()
        assert release.wait(timeout=20)
        return product_spec()

    return turn, entered, release


def _read_sse_blocks(host, port, path, count, headers=None, timeout=10):
    conn = HTTPConnection(host, port, timeout=timeout)
    blocks = []
    try:
        conn.request("GET", path, headers=headers or {})
        response = conn.getresponse()
        assert response.status == 200, response.read().decode("utf-8", errors="ignore")
        assert "text/event-stream" in response.headers.get("Content-Type", "")
        buffer = ""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and len(blocks) < count:
            chunk = response.read(64)
            if not chunk:
                break
            buffer += chunk.decode("utf-8", errors="ignore")
            while "\n\n" in buffer:
                block, buffer = buffer.split("\n\n", 1)
                if block.startswith(":"):
                    continue
                blocks.append(_parse_sse(block))
                if len(blocks) >= count:
                    break
    finally:
        conn.close()
    assert len(blocks) >= count, blocks
    return blocks


def _parse_sse(block):
    fields = {}
    for line in block.splitlines():
        key, _, value = line.partition(":")
        fields[key] = value.strip()
    fields["data"] = json.loads(fields["data"])
    return fields


# ---------------------------------------------------------------------------
# 项目登记、列表、状态命令


def test_project_registration_listing_and_state_commands(data_dir):
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    with running_server(system) as (_server, host, port):
        status, raw, _ = request(host, port, "POST", "/api/projects", {"name": "只有名字"})
        assert status == 400, raw
        status, raw, _ = request(host, port, "POST", "/api/projects", {"name": "  ", "goal": GOAL})
        assert status == 400, raw
        first = _register(host, port, "第一个")
        second = _register(host, port, "第二个")
        assert first.startswith("proj_") and second.startswith("proj_") and first != second
        listed = get_json(host, port, "/api/projects")["projects"]
        assert [row["name"] for row in listed] == ["第二个", "第一个"]
        assert set(listed[0]) == {"project_id", "name", "pinned", "archived", "created_at", "updated_at",
                                  "work_item_count", "active_work_item_id", "current_adoption"}
        assert listed[0]["work_item_count"] == 0 and listed[0]["current_adoption"] is None
        _post(host, port, f"/api/projects/{first}/pin", {"pinned": True})
        assert [row["name"] for row in get_json(host, port, "/api/projects")["projects"]] == ["第一个", "第二个"]
        _post(host, port, f"/api/projects/{first}/rename", {"name": "改名后"})
        status, raw, _ = request(host, port, "POST", f"/api/projects/{first}/rename", {"name": ""})
        assert status == 400, raw
        detail = get_json(host, port, f"/api/projects/{first}")
        assert detail["name"] == "改名后" and detail["pinned"] is True and detail["archived"] is False
        assert detail["goal"] == GOAL and detail["work_items"] == [] and detail["current_adoption"] is None
        assert set(detail["overview"]) == {"goal", "current_adoption", "pending", "recent"}
        assert detail["overview"]["recent"][0]["type"] == ProjectEventType.PROJECT_RENAMED
        assert {config["version"] for config in detail["prompt_configs"].values()} == {0}
        _post(host, port, f"/api/projects/{second}/archive")
        assert [row["name"] for row in get_json(host, port, "/api/projects")["projects"]] == ["改名后"]
        archived_rows = get_json(host, port, "/api/projects?archived=1")["projects"]
        assert {row["name"]: row["archived"] for row in archived_rows} == {"改名后": False, "第二个": True}
        _post(host, port, f"/api/projects/{second}/restore")
        assert len(get_json(host, port, "/api/projects")["projects"]) == 2
        status, raw, _ = request(host, port, "GET", "/api/projects/proj_missing")
        assert status == 404 and "project not found" in raw
        status, raw, _ = request(host, port, "POST", "/api/projects/proj_missing/rename", {"name": "x"})
        assert status == 404, raw
        status, raw, _ = request(host, port, "GET", f"/api/projects/{first}/unknown")
        assert status == 404, raw


# ---------------------------------------------------------------------------
# 事项：创建、运行、结算、读模型；GET /api/runs 仍列出项目 run 与 bare run


def test_work_item_runs_settles_and_exposes_read_models(data_dir):
    held, entered, release = _gated_turn()
    system = LoopSystem.for_testing(data_dir, FakeAdapter([held, plan_turn(), delivery_turn(), review_turn("release", "ok"),
                                                          *happy_script()]))
    with running_server(system) as (server, host, port):
        project_id = _register(host, port)
        status, raw, _ = request(host, port, "POST", f"/api/projects/{project_id}/work-items", {"text": "  "})
        assert status == 400, raw
        status, raw, _ = request(host, port, "POST", f"/api/projects/{project_id}/work-items", {"text": "x", "extra": 1})
        assert status == 400, raw
        created = _post(host, port, f"/api/projects/{project_id}/work-items",
                        {"text": "第一步：逐行文本处理工具", "max_cycles": 6}, 201)
        work_item_id, run_id = created["work_item_id"], created["run_id"]
        assert created["phase"] == "PRODUCT_SPEC" and work_item_id.startswith("wi_") and run_id.startswith("run_")
        try:
            assert entered.wait(10)
            health = get_json(host, port, "/api/health")
            assert health["busy"] is True and health["active_run_id"] == run_id
            assert health["active_project_id"] == project_id and health["active_work_item_id"] == work_item_id
            live = get_json(host, port, f"/api/projects/{project_id}")
            assert live["active_work_item_id"] == work_item_id
            assert live["work_items"][0]["status"] == "in_progress" and live["work_items"][0]["department"] == "product"
            assert live["work_items"][0]["max_cycles"] == 6
            listed = get_json(host, port, "/api/projects")["projects"][0]
            assert listed["work_item_count"] == 1 and listed["active_work_item_id"] == work_item_id
            assert server.busy()
        finally:
            release.set()
        project = _wait_work_item(host, port, project_id, work_item_id)
        item = project["work_items"][0]
        assert item["status"] == "adopted" and item["phase"] == "DONE" and item["department"] is None
        assert item["adoption_id"] == project["current_adoption"]["adoption_id"]
        assert project["current_adoption"]["run_id"] == run_id and project["current_adoption"]["work_item_id"] == work_item_id
        assert project["overview"]["current_adoption"]["adoption_id"] == item["adoption_id"]
        assert project["active_work_item_id"] is None and project["overview"]["pending"] == []
        assert project["overview"]["recent"][0]["type"] == ProjectEventType.DELIVERABLE_ADOPTED
        health = get_json(host, port, "/api/health")
        assert health["busy"] is False and health["active_project_id"] is None and health["active_work_item_id"] is None
        assert health["worker_error"] is None

        board = get_json(host, port, f"/api/projects/{project_id}/board")
        assert [entry["work_item_id"] for entry in board["work_items"]] == [work_item_id]
        assert board["work_items"][0]["status"] == "adopted"

        detail = get_json(host, port, f"/api/projects/{project_id}/work-items/{work_item_id}")
        assert detail["run"] == {"run_id": run_id, "phase": "DONE", "outcome": "done", "stop_reason": "released"}
        assert (detail["handoffs"][0]["from"], detail["handoffs"][0]["to"]) == ("CREATED", "PRODUCT_SPEC")
        assert detail["handoffs"][-1]["to"] == "DONE" and detail["rework"] == []
        assert detail["adoption"]["adoption_id"] == item["adoption_id"] and detail["held"] is None
        status, raw, _ = request(host, port, "GET", f"/api/projects/{project_id}/work-items/wi_missing")
        assert status == 404, raw

        department = get_json(host, port, f"/api/projects/{project_id}/departments/engineering")
        assert department["department"] == "engineering" and department["project_id"] == project_id
        assert department["prompt_config"] == {"version": 0, "source": "default"}
        assert [entry["work_item_id"] for entry in department["items"]] == [work_item_id]
        assert department["items"][0]["view"]["run_id"] == run_id and department["items"][0]["view"]["department"] == "engineering"
        focused = get_json(host, port, f"/api/projects/{project_id}/departments/engineering?work_item={work_item_id}")
        assert len(focused["items"]) == 1 and focused["items"][0]["title"] == item["title"]
        status, raw, _ = request(host, port, "GET", f"/api/projects/{project_id}/departments/engineering?work_item=wi_missing")
        assert status == 404, raw
        status, raw, _ = request(host, port, "GET", f"/api/projects/{project_id}/departments/finance")
        assert status == 400, raw

        prompt = get_json(host, port, f"/api/projects/{project_id}/prompts/quality")
        quality_prompt = DEFINITIONS.role("quality").prompt
        assert prompt == {"department": "quality", "text": quality_prompt, "default_text": quality_prompt,
                          "version": 0, "updated_at": None, "source": "default"}

        # GET /api/runs 仍列出项目 run 与 bare run；POST /api/runs 已删除。
        status, raw, _ = request(host, port, "POST", "/api/runs", {"task": "bare run"})
        assert status == 404 and json.loads(raw)["error"] == "not found", raw
        bare_id = system.create_run("bare run")
        runs = {row["run_id"]: row for row in get_json(host, port, "/api/runs")["runs"]}
        assert runs[run_id]["project_id"] == project_id and runs[run_id]["work_item_id"] == work_item_id
        assert runs[bare_id]["project_id"] is None and runs[bare_id]["work_item_id"] is None
        board = get_json(host, port, f"/api/runs/{run_id}/board")
        assert board["project_id"] == project_id and board["work_item_id"] == work_item_id
        assert system.project(run_id).canonical_state() == system.replay(run_id).canonical_state()


def test_second_work_item_returns_409_while_worker_is_busy(data_dir):
    held, entered, release = _gated_turn()
    system = LoopSystem.for_testing(data_dir, FakeAdapter([held, *happy_script()[1:], *happy_script()]))
    with running_server(system) as (server, host, port):
        project_id = _register(host, port)
        first = _post(host, port, f"/api/projects/{project_id}/work-items", {"text": "第一个"}, 201)
        try:
            assert entered.wait(10)
            status, raw, _ = request(host, port, "POST", f"/api/projects/{project_id}/work-items", {"text": "第二个"})
            assert status == 409 and json.loads(raw)["reason"] == "busy", raw
            status, raw, _ = request(host, port, "POST", "/api/runs", {"task": "bare"})
            assert status == 404 and json.loads(raw)["error"] == "not found", raw
            assert len(get_json(host, port, f"/api/projects/{project_id}")["work_items"]) == 1
        finally:
            release.set()
        wait_until(lambda: not server.busy())
        second = _post(host, port, f"/api/projects/{project_id}/work-items", {"text": "第二个"}, 201)
        assert second["work_item_id"] != first["work_item_id"]
        _wait_work_item(host, port, project_id, second["work_item_id"])


# ---------------------------------------------------------------------------
# §13.4 两个项目各一事项：查询互不串数据；model-attempts 按项目过滤


def test_two_projects_are_isolated_over_http(data_dir):
    system = LoopSystem.for_testing(data_dir, FakeAdapter([*_release_script("A"), *_release_script("B")]))
    with running_server(system) as (_server, host, port):
        project_a = _register(host, port, "A", "目标 A")
        project_b = _register(host, port, "B", "目标 B")
        created_a = _post(host, port, f"/api/projects/{project_a}/work-items", {"text": "A 的事项"}, 201)
        _wait_work_item(host, port, project_a, created_a["work_item_id"])
        created_b = _post(host, port, f"/api/projects/{project_b}/work-items", {"text": "B 的事项"}, 201)
        _wait_work_item(host, port, project_b, created_b["work_item_id"])
        _put(host, port, f"/api/projects/{project_b}/prompts/quality", {"text": "只属于 B 的质检 Prompt", "base_version": 0})
        _post(host, port, f"/api/projects/{project_b}/materials", {"text": "只属于 B 的材料"}, 201)

        status, raw_a, _ = request(host, port, "GET", f"/api/projects/{project_a}")
        assert status == 200
        for foreign in (project_b, created_b["work_item_id"], created_b["run_id"], "只属于 B"):
            assert foreign not in raw_a
        view_a = json.loads(raw_a)
        assert view_a["work_items"][0]["status"] == "adopted" and view_a["materials"] == []
        assert view_a["prompt_configs"]["quality"]["source"] == "default"
        view_b = get_json(host, port, f"/api/projects/{project_b}")
        assert view_b["prompt_configs"]["quality"]["version"] == 1 and len(view_b["materials"]) == 1
        for foreign in (project_a, created_a["work_item_id"], created_a["run_id"]):
            assert foreign not in json.dumps(view_b)

        attempts_a = get_json(host, port, f"/api/projects/{project_a}/model-attempts")
        assert attempts_a["items"] and attempts_a["next_cursor"] is None
        assert {item["run_id"] for item in attempts_a["items"]} == {created_a["run_id"]}
        assert {item["work_item_id"] for item in attempts_a["items"]} == {created_a["work_item_id"]}
        assert all(item["title"] == "A 的事项" for item in attempts_a["items"])
        stamps = [item["created_at"] for item in attempts_a["items"]]
        assert stamps == sorted(stamps, reverse=True)
        assert attempts_a["total"] == len(attempts_a["items"])
        run_attempts = get_json(host, port, f"/api/runs/{created_a['run_id']}/model-attempts?limit=200")
        assert {item["id"] for item in attempts_a["items"]} == {item["id"] for item in run_attempts["items"]}

        # 不透明游标分页：逐页取完后 next_cursor 为 null。
        seen, cursor, pages = [], None, 0
        while True:
            suffix = "" if cursor is None else f"&cursor={cursor}"
            page = get_json(host, port, f"/api/projects/{project_a}/model-attempts?limit=2{suffix}")
            seen.extend(item["id"] for item in page["items"])
            pages += 1
            cursor = page["next_cursor"]
            if cursor is None:
                break
        assert seen == [item["id"] for item in attempts_a["items"]] and pages >= 2
        status, raw, _ = request(host, port, "GET", f"/api/projects/{project_a}/model-attempts?cursor=not-a-cursor")
        assert status == 400, raw
        filtered = get_json(host, port, f"/api/projects/{project_a}/model-attempts?department=quality")
        assert filtered["items"] and all(item["department"] == "quality" for item in filtered["items"])
        by_item = get_json(host, port, f"/api/projects/{project_a}/model-attempts?work_item={created_a['work_item_id']}")
        assert len(by_item["items"]) == attempts_a["total"]
        status, raw, _ = request(host, port, "GET", f"/api/projects/{project_a}/model-attempts?work_item={created_b['work_item_id']}")
        assert status == 404, raw

        usage_a = get_json(host, port, f"/api/projects/{project_a}/model-usage")
        assert usage_a["project_id"] == project_a and usage_a["total_attempts"] == attempts_a["total"]
        assert [entry["run_id"] for entry in usage_a["by_work_item"]] == [created_a["run_id"]]
        assert usage_a["by_work_item"][0]["total_attempts"] == attempts_a["total"]
        run_usage = get_json(host, port, f"/api/runs/{created_a['run_id']}/model-usage")
        assert usage_a["totals"] == run_usage["totals"] and usage_a["coverage"] == run_usage["coverage"]
        assert usage_a["groups"] == run_usage["groups"]
        assert created_b["run_id"] not in json.dumps(usage_a)


# ---------------------------------------------------------------------------
# §13.8 Prompt 配置接口


def test_prompt_config_endpoints(data_dir):
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    with running_server(system) as (_server, host, port):
        project_id = _register(host, port)
        path = f"/api/projects/{project_id}/prompts/engineering"
        assert get_json(host, port, path)["version"] == 0
        status, body = _put(host, port, path, {"text": "工程 v1", "base_version": 0})
        assert status == 200 and body["version"] == 1 and body["source"] == "configured" and body["unchanged"] is False
        assert body["text"] == "工程 v1" and body["default_text"] == DEFINITIONS.role("engineering").prompt
        status, body = _put(host, port, path, {"text": "工程 v1", "base_version": 1})
        assert status == 200 and body["version"] == 1 and body["unchanged"] is True
        status, body = _put(host, port, path, {"text": "   ", "base_version": 1})
        assert status == 400, body
        status, body = _put(host, port, path, {"text": "过期编辑", "base_version": 0})
        assert status == 409 and body["reason"] == "prompt_config_conflict", body
        assert body["current"]["version"] == 1 and body["current"]["text"] == "工程 v1"
        status, body = _put(host, port, path, {"text": "工程 v2"})
        assert status == 400, body
        status, body = _put(host, port, path, {"text": "工程 v2", "base_version": "1"})
        assert status == 400, body
        status, body = _put(host, port, f"/api/projects/{project_id}/prompts/finance", {"text": "x", "base_version": 0})
        assert status == 400, body
        status, body = _put(host, port, "/api/projects/proj_missing/prompts/engineering", {"text": "x", "base_version": 0})
        assert status == 404, body
        status, body = _put(host, port, path, {"text": "工程 v2", "base_version": 1})
        assert status == 200 and body["version"] == 2
        read = get_json(host, port, path)
        assert read["version"] == 2 and read["text"] == "工程 v2" and read["source"] == "configured"
        assert get_json(host, port, f"/api/projects/{project_id}/prompts/product")["version"] == 0
        department = get_json(host, port, f"/api/projects/{project_id}/departments/engineering")
        assert department["prompt_config"] == {"version": 2, "source": "configured"} and department["items"] == []
        detail = get_json(host, port, f"/api/projects/{project_id}")
        assert [entry["version"] for entry in detail["prompt_config_history"]] == [1, 2]
        # 新事项固化 v2。
        created = _post(host, port, f"/api/projects/{project_id}/work-items", {"text": "v2 期间的事项"}, 201)
        run = system.project(created["run_id"])
        assert run.department_prompts["engineering"].text == "工程 v2" and run.prompt_config_versions["engineering"] == 2
        _wait_work_item(host, port, project_id, created["work_item_id"])


# ---------------------------------------------------------------------------
# §13.9 归档项目：写命令 409，restore 后恢复


def test_archived_project_write_commands_return_409(data_dir):
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    with running_server(system) as (_server, host, port):
        project_id = _register(host, port)
        _post(host, port, f"/api/projects/{project_id}/archive")
        for method, path, body in (
            ("POST", f"/api/projects/{project_id}/work-items", {"text": "归档后的事项"}),
            ("PUT", f"/api/projects/{project_id}/prompts/product", {"text": "归档后的 Prompt", "base_version": 0}),
            ("POST", f"/api/projects/{project_id}/materials", {"text": "归档后的材料"}),
            ("POST", f"/api/projects/{project_id}/rename", {"name": "归档后改名"}),
            ("POST", f"/api/projects/{project_id}/pin", {"pinned": True}),
        ):
            status, raw, _ = request(host, port, method, path, body)
            assert status == 409 and json.loads(raw)["reason"] == "project_archived", (path, raw)
        assert get_json(host, port, "/api/runs")["runs"] == []
        detail = get_json(host, port, f"/api/projects/{project_id}")
        assert detail["archived"] is True and detail["work_items"] == [] and detail["materials"] == []
        _post(host, port, f"/api/projects/{project_id}/restore")
        assert get_json(host, port, f"/api/projects/{project_id}")["archived"] is False
        material = _post(host, port, f"/api/projects/{project_id}/materials", {"text": "恢复后的材料"}, 201)
        assert material["material_id"].startswith("material_")
        status, body = _put(host, port, f"/api/projects/{project_id}/prompts/product", {"text": "恢复后的 Prompt", "base_version": 0})
        assert status == 200 and body["version"] == 1
        created = _post(host, port, f"/api/projects/{project_id}/work-items", {"text": "恢复后的事项"}, 201)
        _wait_work_item(host, port, project_id, created["work_item_id"])


def test_in_progress_archive_and_materials_return_409(data_dir):
    held, entered, release = _gated_turn()
    system = LoopSystem.for_testing(data_dir, FakeAdapter([held, *happy_script()[1:]]))
    with running_server(system) as (_server, host, port):
        project_id = _register(host, port)
        created = _post(host, port, f"/api/projects/{project_id}/work-items", {"text": "进行中"}, 201)
        try:
            assert entered.wait(10)
            before = [event.event_id for event in system.store.list_project_events(project_id)]
            for path, body in (
                (f"/api/projects/{project_id}/archive", {}),
                (f"/api/projects/{project_id}/materials", {"text": "不该写入"}),
            ):
                status, raw, _ = request(host, port, "POST", path, body)
                assert status == 409 and json.loads(raw)["reason"] == "work_item_in_progress", raw
            after = system.store.list_project_events(project_id)
            assert [event.event_id for event in after] == before
        finally:
            release.set()
        _wait_work_item(host, port, project_id, created["work_item_id"])


def test_get_archived_project_settles_released_unsettled(data_dir):
    system = LoopSystem.for_testing(data_dir, FakeAdapter(_release_script("v1")))
    project_id = system.projects.register("Echo", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "第一步")
    system.run_until_stop(run_id)
    system.projects.archive(project_id)
    assert system.projects.projection(project_id).work_items[0].status == "released_unsettled"
    with running_server(system) as (_server, host, port):
        detail = get_json(host, port, f"/api/projects/{project_id}")
        assert detail["archived"] is True
        assert detail["current_adoption"]["run_id"] == run_id
        assert detail["work_items"][0]["status"] == "adopted"
        status, raw, _ = request(host, port, "POST", f"/api/projects/{project_id}/work-items", {"text": "新事项"})
        assert status == 409 and json.loads(raw)["reason"] == "project_archived", raw
        assert [item["work_item_id"] for item in get_json(host, port, f"/api/projects/{project_id}")["work_items"]] == [work_item_id]


# ---------------------------------------------------------------------------
# §13.10 D-H：无活跃事项时记录原文，不产生 run 事件


def test_materials_are_recorded_without_run_events(data_dir):
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    with running_server(system) as (_server, host, port):
        project_id = _register(host, port)
        status, raw, _ = request(host, port, "POST", f"/api/projects/{project_id}/materials", {"text": "  "})
        assert status == 400, raw
        status, raw, _ = request(host, port, "POST", f"/api/projects/{project_id}/materials", {"text": "x", "department": "finance"})
        assert status == 400, raw
        first = _post(host, port, f"/api/projects/{project_id}/materials", {"text": "产品输入框里的原文", "department": "product"}, 201)
        second = _post(host, port, f"/api/projects/{project_id}/materials", {"text": "不带部门的原文"}, 201)
        detail = get_json(host, port, f"/api/projects/{project_id}")
        assert [entry["material_id"] for entry in detail["materials"]] == [first["material_id"], second["material_id"]]
        assert [entry["department"] for entry in detail["materials"]] == ["product", None]
        assert detail["active_work_item_id"] is None and detail["work_items"] == []
        assert get_json(host, port, "/api/runs")["runs"] == []
        assert system.store.list_run_ids() == []
        types = [event.type for event in system.store.list_project_events(project_id)]
        assert types == [ProjectEventType.PROJECT_REGISTERED, ProjectEventType.MATERIAL_RECORDED, ProjectEventType.MATERIAL_RECORDED]
        assert get_json(host, port, "/api/health")["busy"] is False


# ---------------------------------------------------------------------------
# SSE：项目事件与所属 run 事件


def test_project_stream_emits_project_and_loop_events_by_global_position(data_dir):
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    with running_server(system) as (_server, host, port):
        project_id = _register(host, port)
        created = _post(host, port, f"/api/projects/{project_id}/work-items", {"text": "流式事项"}, 201)
        _wait_work_item(host, port, project_id, created["work_item_id"])
        logged = system.store.read(projects=[project_id], limit=10_000)
        blocks = _read_sse_blocks(host, port, f"/api/projects/{project_id}/stream", 6)
        # 按全局位置推送，SSE 的 id 就是位置
        assert [int(block["id"]) for block in blocks] == [event.position for event in logged[:6]]
        assert blocks[0]["event"] == "project" and blocks[0]["data"]["type"] == ProjectEventType.PROJECT_REGISTERED
        assert blocks[1]["event"] == "project" and blocks[1]["data"]["type"] == ProjectEventType.WORK_ITEM_CREATED
        assert blocks[1]["data"]["run_id"] == created["run_id"] and blocks[1]["data"]["work_item_id"] == created["work_item_id"]
        loops = [block for block in blocks if block["event"] == "loop"]
        assert loops and loops[0]["data"]["type"] == EventType.RUN_CREATED and loops[0]["data"]["seq"] == 1
        assert all(block["data"]["run_id"] == created["run_id"] and block["data"]["work_item_id"] == created["work_item_id"]
                   for block in loops)
        resumed = _read_sse_blocks(host, port, f"/api/projects/{project_id}/stream", 2, headers={"Last-Event-ID": blocks[3]["id"]})
        assert [block["data"]["event_id"] for block in resumed] == [event.event_id for event in logged[4:6]]
        status, raw, _ = request(host, port, "GET", f"/api/projects/{project_id}/stream", headers={"Last-Event-ID": "garbage"})
        assert status == 400, raw
        after = _read_sse_blocks(host, port, f"/api/projects/{project_id}/stream?after={blocks[2]['id']}", 1)
        assert after[0]["data"]["event_id"] == logged[3].event_id
        status, raw, _ = request(host, port, "GET", "/api/projects/proj_missing/stream")
        assert status == 404, raw


def test_project_stream_resumed_across_new_events_has_no_gap_or_duplicate(data_dir):
    # 第一次连接读到一半断开；之后项目写入新的事件；按最后收到的位置续传，两次收到的事件合起来正好是项目范围内的全部事件
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    with running_server(system) as (_server, host, port):
        project_id = _register(host, port)
        created = _post(host, port, f"/api/projects/{project_id}/work-items", {"text": "流式事项"}, 201)
        _wait_work_item(host, port, project_id, created["work_item_id"])
        written = system.store.read(projects=[project_id], limit=10_000)
        first = _read_sse_blocks(host, port, f"/api/projects/{project_id}/stream", len(written) // 2)
        system.projects.rename(project_id, "改名以后")
        system.projects.pin(project_id, True)
        everything = system.store.read(projects=[project_id], limit=10_000)
        rest = _read_sse_blocks(host, port, f"/api/projects/{project_id}/stream", len(everything) - len(first),
                                headers={"Last-Event-ID": first[-1]["id"]})
    received = first + rest
    assert [block["data"]["event_id"] for block in received] == [event.event_id for event in everything]
    assert [int(block["id"]) for block in received] == [event.position for event in everything]
    assert [block["data"]["type"] for block in rest[-2:]] == [ProjectEventType.PROJECT_RENAMED,
                                                              ProjectEventType.PROJECT_PINNED]
