# 刷新清单的重放核对（设计说明第 4.2 节，工单 #891）。
#
# 每个查询登记两份清单：会改变结果的事件种类（刷新清单，QueryDefinition.changed_by）与已核对过不改变结果的
# 事件种类（不刷新清单，QueryDefinition.unchanged_by）。这里用假模型跑出带项目的场景，把事件按位置逐条写进
# 一个新的事件存储，每写一条调用一次全部已登记的查询；某条事件改变了一个查询的结果，而它的种类既不在刷新
# 清单里也不在不刷新清单里，用例失败。失败信息写明查询、事件种类、事件位置与变化的字段。
#
# 场景分两部分：一个项目里完整的三部门循环（询问、缺陷返工、指导、决定请求与回答、采纳），
# 以及一段项目命令（改名、置顶、保存部门设置、登记源目录）。假模型脚本按部门给出（工单 #877）。

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from harness.adapters.fake import FakeAdapter
from harness.app.application import DEFAULT_REGISTRY, Application
from harness.app.catalog_queries import ChangeImpactRequest
from harness.app.decision_queries import DecisionsList
from harness.app.home import AwayReportRequest
from harness.app.project_queries import (
    DepartmentWorkspace, DeliveryFile, EventDetail, NotFound, ProjectAttempts, ProjectFlow, ProjectLoop,
    ProjectOverview, ProjectsList, ProjectSettings, ProjectUsage, ProjectWriteback, ReplayCheck, RunActions,
    RunAsks, RunAttempt, RunExport, RunRecovery, WorkItemInputs, WorkItemMaterials,
)
from harness.app.registry import QueryDefinition, Registry, UnchangedEvent
from harness.app.rules_queries import RulesRegistryRequest
from harness.app.system_queries import LiveAttemptRequest, SystemStatusRequest
from harness.event_store import Command, EventStore, catalog_stream, run_stream
from harness.models import EventType, json_dumps
from harness.projection import dump_decision, replay_decisions, saved_decisions
from harness.project_projection import catalog_handler, handler_for
from harness.projects import project_projection
from harness.proposals import answer_turn, ask_turn, delivery_turn, product_spec
from harness.providers.selection import ModelSelection
from harness.runtime import LoopSystem
from harness.tests.helpers import guidance_reply, quality_turns
from harness.write_path import NewEvent

CHECKS = {"smoke": {"command": "python -c \"print('smoke ok')\""}}
ECHO = "import sys\nprint(sys.argv[1])\n"
GOAL = "核对查询的刷新清单"


# ---------------------------------------------------------------------------
# 场景


def _script() -> dict[str, list[Any]]:
    # 脚本按部门给出（工单 #877：PRD 被接纳以后工程与质检同时工作，一条按先后排队的列表脚本被两个部门
    # 取用时谁拿到哪一项随调度变化）。工程先回应指导，再询问产品，然后交付；被质检退回以后再交付一次。
    return {
        "product": [product_spec()],
        "engineering": [
            guidance_reply(),
            ask_turn("product", "输出要保留换行吗？", background="交付的输出格式需要澄清", expected="规格更新"),
            delivery_turn(files={"src/echo.py": ECHO}, checks=CHECKS),
            delivery_turn(summary="处理了带空格的参数",
                          files={"src/echo.py": "import sys\nprint(' '.join(sys.argv[1:]))\n"}, checks=CHECKS),
        ],
        "product:ask": [answer_turn("保留换行。", requirements=["print the given argument to stdout"],
                                    change_record={"changed": [], "retained": ["print the given argument to stdout"]})],
        "quality": quality_turns("rework_engineering", "没有检查覆盖带空格的参数",
                                  defects=[{"severity": "major", "summary": "缺少带空格参数的检查"}], checks=CHECKS),
    }


def _request_decision(system: LoopSystem, run_id: str) -> None:
    # 运行中提出一个等待回答的决定（阻塞整个 run）：经写入口写入，与流程编排自己提出的决定同一条路径
    system.writes.transact(run_stream(run_id), lambda transaction: transaction.append(NewEvent(
        EventType.DECISION_REQUESTED, actor="system", department="product",
        state_before=transaction.projection.status, state_after=transaction.projection.status,
        payload={"kind": "model_unavailable", "blocks": "run",
                 "options": [{"id": "continue", "label": "继续执行"}, {"id": "stop", "label": "停止事项"}],
                 "description": "产品部门的模型无法使用", "facts": [], "department": "product",
                 "target": None, "reason": "provider_unavailable",
                 "message": "Missing configuration: provider credential"})))


def _answer_decision(system: LoopSystem, run_id: str) -> None:
    # 回答那个决定（继续执行），回答以后事项从这次请求接着进行
    [decision] = [item for item in saved_decisions(system.store)[1]
                  if item.status == "open" and item.run_id == run_id]
    command = Command(str(uuid.uuid4()), "decision.answer", "sha256:continue", "user:local")
    resumed = system.orchestrator.answer_decision(decision.decision_id, "continue", None,
                                                  base_version=decision.version, command=command)
    assert resumed == run_id


def _scenario(data_dir: Path) -> tuple[LoopSystem, str, str, str]:
    # 跑出场景：一个项目里完整的三部门循环与一段项目命令。返回系统与项目、事项、run 的身份
    system = LoopSystem.for_testing(data_dir, FakeAdapter(_script()))
    project_id = system.projects.register("重放核对项目", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "完成一个事项")
    system.activate_once(run_id)                       # 产品提出 PRD
    system.add_guidance(run_id, "engineering", "交付前说明输出的边界。")   # 指导
    _request_decision(system, run_id)                  # 决定请求
    system.run_until_stop(run_id)                      # 运行到等待回答
    _answer_decision(system, run_id)                  # 决定回答
    system.run_until_stop(run_id)                      # 跑到结束（放行）
    system.projects.settle(run_id)                     # 采纳
    # 第二部分：项目命令（改名、置顶、保存部门设置、登记源目录）
    system.projects.rename(project_id, "重放核对项目（改名）")
    system.projects.pin(project_id, True)
    system.projects.configure_department_settings(
        project_id, "engineering", ModelSelection(department_prompt="交付前先说明输出边界。"), 0)
    system.projects.configure_source_directory(project_id, "主仓库", str(data_dir / "source"), base_version=0)
    return system, project_id, work_item_id, run_id


# ---------------------------------------------------------------------------
# 重放核对


@dataclass
class _Scope:
    # 查询参数：项目、事项、run、部门、调用尝试与事件编号，逐条事件从事件里取（工单 #891 的要求）
    project_id: str = ""
    work_item_id: str = ""
    run_id: str = ""
    department: str = "engineering"
    attempt_id: str = ""
    first_event_id: str = ""
    delivery_event_id: str = ""
    delivery_path: str = ""

    def observe(self, event: Any) -> None:
        # 参数取场景里第一次出现的那个对象：请求在整个重放中保持不变，结果的变化只来自事件本身
        if not self.project_id and event.project_id:
            self.project_id = event.project_id
        if not self.work_item_id and event.work_item_id:
            self.work_item_id = event.work_item_id
        if not self.run_id and event.run_id:
            self.run_id = event.run_id
        if self.department == "engineering" and event.department:
            self.department = event.department
        attempt_id = (event.payload or {}).get("attempt_id")
        if not self.attempt_id and isinstance(attempt_id, str) and attempt_id:
            self.attempt_id = attempt_id
        if not self.first_event_id:
            self.first_event_id = event.event_id
        if not self.delivery_event_id and event.type == EventType.DELIVERY_ACCEPTED:
            files = list((event.payload or {}).get("files") or [])
            if files:
                self.delivery_event_id = event.event_id
                self.delivery_path = str(files[0])


class _ReplayProjects:
    # 重放核对期间的项目读取：只从新的事件存储读（源系统的项目服务读的是源事件存储）
    def __init__(self, store: EventStore, artifacts: Any) -> None:
        self.store = store
        self.artifacts = artifacts

    def list_projects(self, *, include_archived: bool = False) -> list[Any]:
        return [project_projection(self.store, self.artifacts, project_id, include_history=False)
                for project_id in self.store.list_project_ids()]


class _ReplayCore:
    # 重放核对用的控制核心：事件日志是新写的那一份，工件、Provider 与排空状态沿用源系统，
    # 数据目录是重放用的那一份（读取模型写在它里面，不动源数据目录）
    read_only = False

    def __init__(self, source: LoopSystem, store: EventStore, data_dir: Path) -> None:
        self._source = source
        self.store = store
        self.data_dir = data_dir

    @property
    def artifacts(self) -> Any:
        return self._source.artifacts

    @property
    def facade(self) -> Any:
        return self._source.facade

    @property
    def drain(self) -> Any:
        return self._source.drain

    @property
    def running_runs(self) -> int:
        return self._source.running_runs

    @property
    def deltas(self) -> Any:
        return self._source.deltas

    @property
    def projects(self) -> _ReplayProjects:
        return _ReplayProjects(self.store, self.artifacts)

    def provider_status(self) -> dict[str, Any]:
        return self._source.provider_status()

    @property
    def home_seen(self) -> tuple[int, str] | None:
        saved = self.store.projection(catalog_stream())
        if saved is None:
            return None
        state = catalog_handler().load(saved)
        if state.last_seen_position is None:
            return None
        return state.last_seen_position, state.last_seen_at

    def close(self) -> None:
        self.store.close()


def _requests(scope: _Scope) -> dict[str, Any]:
    # 全部已登记查询的请求：参数从事件里取，没有对象时给空值（查询这时返回「找不到」，不算变化）
    project_id = scope.project_id
    work_item_id = scope.work_item_id
    run_id = scope.run_id
    # 还没有对应对象时给一个不存在的标识：查询这时返回「找不到」，不算变化
    return {
        "system.status": SystemStatusRequest(),
        "attempt.live": LiveAttemptRequest(attempt_id=scope.attempt_id or "none"),
        "decisions.list": DecisionsList(),
        "projects.list": ProjectsList(),
        "project.overview": ProjectOverview(project_id=project_id),
        "project.loop": ProjectLoop(project_id=project_id),
        "project.flow": ProjectFlow(project_id=project_id),
        "work_item.inputs": WorkItemInputs(project_id=project_id, work_item=work_item_id),
        "event.detail": EventDetail(event_id=scope.first_event_id or "none"),
        "department.workspace": DepartmentWorkspace(project_id=project_id, department=scope.department),
        "run.actions": RunActions(run_id=run_id),
        "run.asks": RunAsks(run_id=run_id),
        "work_item.materials": WorkItemMaterials(project_id=project_id, work_item=work_item_id),
        "delivery.file": DeliveryFile(event_id=scope.delivery_event_id or "none",
                                      path=scope.delivery_path or "none"),
        "project.attempts": ProjectAttempts(project_id=project_id),
        "project.usage": ProjectUsage(project_id=project_id),
        "run.attempt": RunAttempt(run_id=run_id, attempt_id=scope.attempt_id or "none"),
        "project.settings": ProjectSettings(project_id=project_id),
        "project.writeback": ProjectWriteback(project_id=project_id),
        "run.export": RunExport(run_id=run_id),
        "replay.check": ReplayCheck(project_id=project_id),
        "run.recovery": RunRecovery(run_id=run_id),
        "catalog": None,
        "catalog.document": None,
        "catalog.change_impact": ChangeImpactRequest(
            kind="document", document=json.dumps({"providers": [], "models": []})),
        "home.away_report": AwayReportRequest(),
        "rules.registry": RulesRegistryRequest(),
    }


# 不参与比较的读数（设计说明第 4.2 节列出的几类，逐个写明字段与理由）
EXCLUDED_READINGS = (
    # 最近活动时间：每条事件到达都更新它，变化本身没有意义
    ("projects.list", "projects.*.last_activity_at"),
    # 已用秒数：随墙钟增长，与事件无关
    ("project.loop", "work_items.*.elapsed_sec"),
    # 恢复页最后确认的位置与事件：每条事件到达都推进它
    ("run.recovery", "last_confirmed_position"),
    ("run.recovery", "last_confirmed_event_id"),
    # 离开期间报告的截止位置、截止时间与起始时间：随日志末尾与上次查看的位置变化
    ("home.away_report", "range.from_at"),
    ("home.away_report", "range.to_position"),
    ("home.away_report", "range.to_at"),
    # 磁盘剩余空间：本机的实时值，与事件无关
    ("system.status", "home.disk_free_bytes"),
)


def _excluded(query: str, path: str) -> bool:
    return any(name == query and (path == item or path.startswith(item + "."))
               for name, item in EXCLUDED_READINGS)


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    # 把结果拍平成「路径 → 值」：列表元素的路径用 *，便于写明变化的字段
    flat: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            flat.update(_flatten(item, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(value, list):
        for item in value:
            flat.update(_flatten(item, f"{prefix}.*"))
    else:
        flat[prefix] = value
    return flat


@dataclass(frozen=True)
class Missing:
    # 一条漏登记：某条事件改变了某个查询的结果，而它的种类不在那个查询的两份清单里
    query: str
    event_type: str
    position: int
    fields: tuple[str, ...]


def _summarize(missing: list[Missing]) -> list[str]:
    # 失败信息按「查询 + 事件种类」归并：写明查询、事件种类、事件位置与变化的字段
    grouped: dict[tuple[str, str], list[Missing]] = {}
    for item in missing:
        grouped.setdefault((item.query, item.event_type), []).append(item)
    lines = []
    for (query, kind), items in sorted(grouped.items()):
        fields = sorted({field for item in items for field in item.fields})
        shown = ", ".join(fields[:6]) + ("…" if len(fields) > 6 else "")
        lines.append(f"查询 {query} 的两份清单里没有 {kind}（位置 {items[0].position}），"
                     f"它改变了这些字段：{shown}")
    return lines


def _all_events(store: EventStore) -> list[Any]:
    events: list[Any] = []
    cursor = 0
    while True:
        batch = store.read(after=cursor, limit=1000)
        if not batch:
            break
        events.extend(batch)
        cursor = batch[-1].position
    return events


def _write(store: EventStore, event: Any, prefix: list[Any], version: int) -> int:
    # 把一条事件写进新的事件存储：同一时刻保存这个流的投影与它的决定请求（与写入口做的事相同）
    handler = handler_for(event.stream)
    state = handler.dump(handler.replay(event.stream, prefix))
    decisions = [dump_decision(item) for item in replay_decisions(prefix).values()]
    store.commit(event.stream, version, [event], state, epoch=event.epoch, decisions=decisions)
    store.notify([event])
    return version + 1


def _replay_check(source: LoopSystem, target_dir: Path) -> list[Missing]:
    # 重放核对：把源事件存储的事件按位置逐条写进新的事件存储，每写一条调用一次全部已登记的查询。
    # 返回漏登记的清单（空表示两份清单覆盖了全部已改变结果的事件种类）
    events = _all_events(source.store)
    by_stream: dict[str, list[Any]] = {}
    for event in events:
        by_stream.setdefault(event.stream, []).append(event)
    target_dir.mkdir(parents=True, exist_ok=True)
    store = EventStore(target_dir / "events.sqlite")
    application = Application(_ReplayCore(source, store, target_dir))
    scope = _Scope()
    for event in events:
        scope.observe(event)          # 先把参数定下来：请求在整个重放中保持不变
    versions: dict[str, int] = {}
    seen: dict[str, int] = {}
    previous: dict[str, dict[str, Any]] = {}
    missing: list[Missing] = []
    try:
        for event in events:
            stream = event.stream
            index = seen.get(stream, 0)
            seen[stream] = index + 1
            versions[stream] = _write(store, event, by_stream[stream][:index + 1], versions.get(stream, 0))
            scope.observe(event)
            for name, request in _requests(scope).items():
                definition = DEFAULT_REGISTRY.queries[name]
                try:
                    snapshot = application.query(name, request)
                except NotFound:
                    # 事件到达之前返回「找不到」的，不算变化
                    continue
                flat = _flatten(snapshot.data.model_dump(mode="json"))
                before = previous.get(name)
                previous[name] = flat
                if before is None:
                    continue
                changed = tuple(sorted(path for path, value in flat.items()
                                      if before.get(path) != value and not _excluded(name, path)))
                if not changed:
                    continue
                kind = event.type
                if kind in definition.changed_by:
                    continue
                if any(item.kind == kind for item in definition.unchanged_by):
                    continue
                missing.append(Missing(query=name, event_type=kind, position=event.position, fields=changed))
    finally:
        application.close()
    return missing


# ---------------------------------------------------------------------------
# 用例


def test_every_event_that_changes_a_query_is_listed_in_one_of_its_two_lists(data_dir, tmp_path):
    # 场景与重放核对：漏登记时失败，失败信息写明查询、事件种类、位置与变化的字段
    system, project_id, work_item_id, run_id = _scenario(data_dir)
    try:
        missing = _replay_check(system, tmp_path / "replay")
    finally:
        system.close()
    assert missing == [], "\n".join(_summarize(missing))


def test_the_scenario_covers_the_asked_for_behaviours(data_dir):
    # 场景确实覆盖了工单要求的那些行为：询问、缺陷返工、指导、决定请求与回答、采纳，
    # 以及改名、置顶、部门设置与源目录登记
    system, project_id, work_item_id, run_id = _scenario(data_dir)
    try:
        types = {event.type for event in _all_events(system.store)}
        project_types = {event.type for event in system.store.list_project_events(project_id)}
    finally:
        system.close()
    assert {EventType.ASK_STARTED, EventType.ASK_ANSWERED, EventType.QA_SUBMITTED,
            EventType.DECISION_REQUESTED, EventType.DECISION_ANSWERED,
            EventType.DEPARTMENT_GUIDANCE_RECEIVED, EventType.DEPARTMENT_GUIDANCE_RESPONDED} <= types
    assert {"project_renamed", "project_pinned", "department_prompt_configured",
            "source_directory_configured", "deliverable_adopted"} <= project_types


def test_the_registry_checks_the_unchanged_list():
    # 注册时的两项检查：种类都已登记；与刷新清单不重叠（设计说明第 4.2 节）
    def query(**kwargs) -> QueryDefinition:
        return QueryDefinition(name="q", request=None, result=dict, handle=lambda application, request: None,
                               **kwargs)

    with pytest.raises(ValueError, match="unknown unchanged event types"):
        Registry(commands=[], queries=[query(unchanged_by=(UnchangedEvent("no_such_kind", "理由"),))])
    with pytest.raises(ValueError, match="both lists"):
        Registry(commands=[], queries=[query(changed_by=(EventType.RUN_CREATED,),
                                             unchanged_by=(UnchangedEvent(EventType.RUN_CREATED, "理由"),))])


def test_the_unchanged_list_is_not_in_the_capabilities():
    # 「不刷新」清单不进入能力清单，接口合同不变
    capabilities = DEFAULT_REGISTRY.capabilities(
        __import__("harness.app.contracts", fromlist=["Deployment"]).Deployment(
            log_id="log", boot_id="boot", version="1", api_version="1", contract_digest="digest",
            access="local"))
    for capability in capabilities.queries:
        assert set(capability.model_dump()) == {"name", "changed_by", "replayable"}
