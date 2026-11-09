# 项目设置里「形态」的查询（工单 #1402、#1516，项目的组织设计说明「采用与历史」「形态一键选用」「组织页」；
# 形态与核验角色设计说明「形态随事项冻结」；总图第四节「接口」缝与「定义」缝）：
# project.organization 回答一个项目现在的组织：形态加本项目的改动合成出的那份组织（与每项的来源）、
# 组织版本、发布带的每一份形态，以及改动的历史（原值、新值、原版本、新版本、理由、时间、谁改的与两次采用
# 之间的差异）。另外给出设置页一次点击要用的两个改动文档（加 / 去掉核验角色）。只读事实，不写入。
#
# organization.draft 是校验草稿（工单 #1515，项目的组织设计说明「草稿与校验」）：输入项目、形态与本项目的改动，
# 输出合成结果、拒绝项、提醒、「这样改以后事项怎么结束」，以及换一份时现有改动里会丢掉哪些（换模板时页面
# 据此确认一次）。它不写入任何事件：合成在应用一侧（harness/organization_compose.py），结构校验是内核加载
# 定义时的同一套（harness/definitions）与路由自己的校验。

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Literal

from pydantic import AwareDatetime, Field

from ..definitions import (
    DEFAULT_FORM, ITEM_SOURCES, Definitions, parse_organization_changes, submitted_outcomes,
)
from ..models import ProjectEventType
from ..organization_compose import (
    change_diff, compose_checked, current_organization, dropped_changes, finish_statement, reminders,
    verifier_changes, write_scopes,
)
from ..projects import ProjectNotFoundError, definitions_difference, definitions_from_ref, project_projection
from ..runtime import FORM_REGISTRY
from .contracts import Contract, Snapshot
from .project_queries import NotFound, QueryInputInvalid
from .registry import QueryDefinition

if TYPE_CHECKING:
    from .application import Application


# 还在跑的事项（工单 #1517，项目的组织设计说明「冻结与升级」补充条 7）：排队还没开始的、正在跑的、
# 等用户确认初始 PRD 的。它们各自的部门也算在项目的部门清单里，标出来源是还在跑的事项
RUNNING_ITEM_STATUSES = frozenset({"not_started", "running", "in_progress", "awaiting_initial_prd"})


# ---------------------------------------------------------------------------
# 合成结果与拒绝项（project.organization 与 organization.draft 共用同一组合同）


class DraftIssue(Contract):
    # 一条拒绝项：哪一项、为什么。项写文件与字段路径，例如「organization.json departments[1].watched[2]」
    item: str
    message: str


class DraftReminder(Contract):
    # 一条提醒：可以采用，页面显示它。kind 说明是哪一条提醒，页面按它排
    kind: Literal["open_loop", "midway_verifier", "no_outcomes"]
    message: str


class DraftDepartment(Contract):
    # 合成结果里的一个部门：身份、显示名、三样说明（它对什么负责、凭什么判断、怎么工作）、关注的成果、
    # 交出的成果、是不是核验角色、写入范围
    id: str
    label: str
    target: str
    evidence: str
    work: str
    watched: list[str]
    outcomes: list[str]
    verifier: bool
    write_scope: str


class DraftOutcomeKind(Contract):
    # 合成结果里的一种成果：身份与中文名
    id: str
    label: str


class DraftVerification(Contract):
    # 合成结果里的一条核验关系：核验角色、被核验的部门与成果种类
    verifier: str
    verified: str
    outcome: str


class DraftOrganization(Contract):
    # 合成结果：版本（内容的摘要）、形态名、轮转方式、部门、成果种类、核验关系与事项的来源
    version: str
    form: str
    routing: str
    routing_label: str
    departments: list[DraftDepartment]
    outcome_kinds: list[DraftOutcomeKind]
    verification: list[DraftVerification]
    sources: dict[str, str]


def _item(file: str, field: str) -> str:
    return f"{file} {field}"


def _organization_of(form_name: str, definitions: Definitions) -> DraftOrganization:
    scopes = write_scopes(definitions)
    sources = definitions.organization.sources
    return DraftOrganization(
        version=definitions.version, form=form_name, routing=definitions.routing,
        routing_label=definitions.routing_definition().label,
        departments=[DraftDepartment(
            id=department.id, label=department.label, target=department.target,
            evidence=department.evidence, work=department.work,
            watched=list(department.watched),
            outcomes=sorted(submitted_outcomes(definitions.roles, definitions.tools, definitions.work_items,
                                                department.id)),
            verifier=definitions.is_verifier(department.id),
            write_scope=scopes[department.id]) for department in definitions.organization.departments],
        outcome_kinds=[DraftOutcomeKind(id=kind.id, label=kind.label) for kind in definitions.outcome_kinds.kinds],
        verification=[DraftVerification(verifier=verifier, verified=verified, outcome=outcome)
                      for verifier, verified, outcome in definitions.rejection_edges()],
        sources=({source: sources[source] for source in ITEM_SOURCES}
                 if sources is not None else {source: definitions.source_department(source) for source in ITEM_SOURCES}),
    )


# ---------------------------------------------------------------------------
# 项目的组织（工单 #1402、#1516）


class ProjectOrganization(Contract):
    # 一个项目的组织：形态加本项目的改动之后的合成结果、每项来源、版本、历史与发布带的形态清单
    project_id: str


class FormChoice(Contract):
    # 发布带的一份形态：名字（发布带里的标识）、形态名（它有哪几个职能，从这份定义推出）、一句说明、
    # 这份定义的版本（改动为空时它就是组织版本）、核验角色的编号（空表示没有核验角色）与开环与否
    form: str
    label: str
    description: str
    version: str
    verifier_roles: list[str]
    open_loop: bool


class OrganizationDepartment(Contract):
    # 项目现在用的组织里的一个部门：标识、显示名、是不是核验角色，与它的来源（跟随发布、本项目改过、
    # 本项目加的；设计说明「组织页」部门表的来源一列）。页面的部门页签、看板列与默认部门按这一项排。
    # 工单 #1517 只增两项：running_items 是还在按这一份组织跑的事项个数（用它标出冻结着旧组织的事项）；
    # 只在还在跑的事项冻结的组织里有的部门也进这一列，来源写 running_item
    id: str
    label: str
    verifier: bool = False
    origin: Literal["release", "changed", "added", "running_item"] = "release"
    running_items: int = 0


class FormDifference(Contract):
    # 两条采用事件之间的一处差异：项（例如 form、departments.quality.label）、改动前与改动后
    item: str
    before: str
    after: str


class FormChange(Contract):
    # 一次形态改动（项目流上的一条 project_form_set）：原值、新值、理由（没写时为空）、时间与谁改的；
    # 工单 #1516 只增：原版本、新版本（合成结果的内容摘要，旧事件没有时为空）、这次带的本项目的改动，
    # 以及和上一次采用之间的差异（按两条事件的形态名与改动比较）
    event_id: str
    previous_form: str
    form: str
    reason: str
    at: AwareDatetime
    actor: str
    previous_version: str | None = None
    version: str | None = None
    changes: dict[str, Any] = Field(default_factory=dict)
    diff: list[FormDifference] = Field(default_factory=list)


class ItemOrganization(Contract):
    # 上一个事项用的组织（工单 #1517，项目的组织设计说明「冻结与升级」）：那个事项、它的形态名与组织版本，
    # 以及与项目现在这份组织之间的差异（比较两份合成结果，不另存状态）。
    # 「高级」里写明：发布升级以后，跟随发布的项下一个事项会自动用上新内容，这里看得到不同在哪
    work_item_id: str
    title: str
    form: str
    version: str
    differences: list[FormDifference] = Field(default_factory=list)


class ProjectOrganizationResult(Contract):
    # 项目现在的组织：现在用哪一份、它的形态名（它有哪几个职能，从这一份定义推出；这一份不在发布里时
    # 为空）、合成结果（现在这一份不在发布里、或改动合不到一起时为空，并给出拒绝项）、组织版本
    # （合成结果的内容摘要；取不到时为空）、发布带的每一份形态、改动历史，以及设置页一次点击的两个
    # 改动文档（加 / 去掉核验角色；不适用时为空）
    project_id: str
    form: str
    label: str | None
    version: str | None
    form_in_release: bool
    departments: list[OrganizationDepartment]
    forms: list[FormChoice]
    history: list[FormChange]
    changes: dict[str, Any] = Field(default_factory=dict)
    organization: DraftOrganization | None = None
    rejections: list[DraftIssue] = Field(default_factory=list)
    add_verifier: dict[str, Any] | None = None
    remove_verifier: dict[str, Any] | None = None
    # 和这个项目上一个事项用的组织相比有什么不同（工单 #1517）：下一个事项会自动用上现在这份，
    # 差异随这一项给出；没有事项、或者上一个事项是只记了形态名的旧事项时为空
    previous_item: ItemOrganization | None = None


def release_forms(system: Any) -> dict[str, Definitions]:
    # 发布带的形态：实例加载的那几份（测试与演示可以把别的几份交给组装处）。
    # 只读打开没有组装处，按发布带的登记处读出名字与定义：这两种读取只要这两样，不接路由
    forms = getattr(system, "forms", None)
    if forms is not None:
        return {name: item.definitions for name, item in forms.items()}
    return {name: definitions for name, (definitions, _tightening) in FORM_REGISTRY.items()}


def _describe(definitions: Definitions) -> str:
    # 一份形态的一句说明：由这份定义得出（部门的显示名与核验声明），不另写一份说明文字。
    # 有核验角色时写「谁核验谁」；没有时写清楚它以开环完成结束
    labels = definitions.department_labels
    names = "、".join(labels[department] for department in definitions.departments)
    pairs = list(dict.fromkeys((verifier, verified)
                               for verifier, verified, _outcome in definitions.rejection_edges()))
    if not pairs:
        return f"{names}；没有核验角色，事项以开环完成结束。"
    verifying = "，".join(f"{labels.get(verifier, verifier)}核验{labels.get(verified, verified)}"
                          for verifier, verified in pairs)
    return f"{names}；{verifying}。"


def _label(definitions: Definitions) -> str:
    # 形态名：列出这份形态有哪几个职能，从定义推出（术语表「形态」）。按定义里职能的显示名与定义的顺序，
    # 用「 · 」连起来，不另写一份名字
    labels = definitions.department_labels
    return " · ".join(labels[department] for department in definitions.departments)


def _choice(name: str, definitions: Definitions) -> FormChoice:
    verifiers = list(definitions.verifier_roles())
    return FormChoice(form=name, label=_label(definitions), description=_describe(definitions),
                      version=definitions.version, verifier_roles=verifiers, open_loop=not verifiers)


def _origin(department: str, changes: dict[str, Any]) -> str:
    # 一个部门的来源（设计说明「组织页」部门表）：本项目加进来的、本项目改过的，其余跟随发布
    added = {item.get("id") for item in changes.get("add_departments") or [] if isinstance(item, dict)}
    if department in added:
        return "added"
    edited = changes.get("departments")
    return "changed" if isinstance(edited, dict) and department in edited else "release"


def _history(events: list[Any], forms: dict[str, Definitions]) -> list[FormChange]:
    # 采用历史：每次采用的原值、新值、原版本、新版本、理由、时间、谁改的，以及和上一次采用之间的差异。
    # 第一次采用的原版本是没有改动时默认形态的版本；旧事件没有改动与版本时按空改动、没有版本读
    if not events:
        return []
    previous_form = str(events[0].payload["previous_form"])
    previous_changes: dict[str, Any] = {}
    previous_version = None if previous_form not in forms else forms[previous_form].version
    records: list[FormChange] = []
    for event in events:
        form = str(event.payload["form"])
        changes = dict(event.payload.get("changes") or {})
        version = event.payload.get("version")
        records.append(FormChange(
            event_id=event.event_id, previous_form=str(event.payload["previous_form"]), form=form,
            reason=str(event.payload.get("reason", "")), at=event.created_at, actor=event.actor,
            previous_version=previous_version, version=version, changes=changes,
            diff=[FormDifference(item=item, before=before, after=after)
                  for item, before, after in change_diff(previous_form, previous_changes, form, changes)]))
        previous_form, previous_changes, previous_version = form, changes, version
    return records


def _running_items(store: Any, artifacts: Any, project_id: str, work_items: list[Any],
                   forms: dict[str, Definitions]) -> list[tuple[str, Definitions]]:
    # 还在跑的事项与它冻结的组织（工单 #1517，设计说明「冻结与升级」）：同一个事项取最后一条创建事件里的
    # 那份合成结果；旧事项只记了形态名，按它在那一版发布里取（工单 #1392 的读法）。同一份组织只读一次
    creation = [event for event in store.list_project_events(project_id)
                if event.type == ProjectEventType.WORK_ITEM_CREATED]
    refs: dict[str, Any] = {}
    for event in creation:
        refs[str(event.payload.get("work_item_id", ""))] = event.payload.get("definitions_ref")
    loaded: dict[str, Definitions | None] = {}
    rows: list[tuple[str, Definitions]] = []
    for item in work_items:
        if item.status not in RUNNING_ITEM_STATUSES:
            continue
        ref = refs.get(item.work_item_id)
        key = (f"form:{item.form or DEFAULT_FORM}" if not isinstance(ref, dict)
               else str(ref.get("content_hash") or ""))
        if key not in loaded:
            loaded[key] = (definitions_from_ref(artifacts, ref)
                           or forms.get(item.form or DEFAULT_FORM))
        definitions = loaded[key]
        if definitions is not None:
            rows.append((item.work_item_id, definitions))
    return rows


def _departments_of_current(definitions: Definitions, changes: dict[str, Any],
                            running: dict[str, int]) -> list[OrganizationDepartment]:
    # 项目现在这份组织的部门，带上还在按它跑的事项个数（工单 #1517）
    return [OrganizationDepartment(
        id=department.id, label=department.label,
        verifier=definitions.is_verifier(department.id),
        origin=_origin(department.id, changes),
        running_items=running.get(department.id, 0))
        for department in definitions.organization.departments]


def _departments_of_running_items(definitions: Definitions | None,
                                  rows: list[tuple[str, Definitions]]) -> list[OrganizationDepartment]:
    # 只在还在跑的事项冻结的组织里有的部门（工单 #1517，设计说明「冻结与升级」与补充条 7）：项目现在这份
    # 组织里已经没有它（例如后来去掉了这个部门），名单仍然包含它并标出来源是还在跑的事项；
    # 个数是几个还在跑的事项在用它（不是几种组织在用它）
    current = set() if definitions is None else set(definitions.departments)
    counts: dict[str, int] = {}
    first: dict[str, Definitions] = {}
    for _work_item_id, frozen in rows:
        for department in frozen.organization.departments:
            if department.id in current:
                continue
            counts[department.id] = counts.get(department.id, 0) + 1
            first.setdefault(department.id, frozen)
    return [OrganizationDepartment(
        id=department_id,
        label=first[department_id].department_labels.get(department_id, department_id),
        verifier=first[department_id].is_verifier(department_id),
        origin="running_item", running_items=counts[department_id])
        for department_id in sorted(counts)]


def _previous_item(store: Any, artifacts: Any, project_id: str,
                   definitions: Definitions | None) -> ItemOrganization | None:
    # 这个项目上一个事项用的组织（工单 #1517，设计说明「冻结与升级」）：取项目流上最后一条事项创建事件，
    # 按它冻结的整份合成结果与现在的这一份比较。现在这份组织取不到、项目还没有事项、或者上一个事项是只记了
    # 形态名的旧事项（没有它当时那份合成结果）时为空
    if definitions is None:
        return None
    created = [event for event in store.list_project_events(project_id)
               if event.type == ProjectEventType.WORK_ITEM_CREATED]
    if not created:
        return None
    last = created[-1]
    frozen = definitions_from_ref(artifacts, last.payload.get("definitions_ref"))
    if frozen is None:
        return None
    return ItemOrganization(
        work_item_id=str(last.payload.get("work_item_id", "")), title=str(last.payload.get("title", "")),
        form=str(last.payload.get("form") or DEFAULT_FORM), version=frozen.version,
        differences=[FormDifference(item=item, before=before, after=after)
                     for item, before, after in definitions_difference(frozen, definitions)])


def _project_organization(application: Application,
                          request: ProjectOrganization) -> Snapshot[ProjectOrganizationResult]:
    store = application.system.store
    try:
        state = project_projection(store, application.system.artifacts, request.project_id,
                                   include_history=False)
    except ProjectNotFoundError:
        raise NotFound(f"project not found: {request.project_id}") from None
    forms = release_forms(application.system)
    current = state.form_name
    changes = dict(state.organization_changes)
    definitions, issues = current_organization(forms, current, changes, store=store)
    events = [event for event in store.list_project_events(request.project_id)
              if event.type == ProjectEventType.PROJECT_FORM_SET]
    added, removed = verifier_changes(forms, current, changes, definitions, store=store)
    # 还在跑的事项冻结着旧组织时（工单 #1517）：按它们各自的部门计数，并补上现在这份组织里已经没有了、
    # 但还在跑的事项仍在用的部门
    running = _running_items(store, application.system.artifacts, request.project_id, state.work_items, forms)
    counts: dict[str, int] = {}
    for _work_item_id, frozen in running:
        for department in frozen.organization.departments:
            counts[department.id] = counts.get(department.id, 0) + 1
    departments: list[OrganizationDepartment] = []
    if definitions is not None:
        departments = _departments_of_current(definitions, changes, counts)
    departments.extend(_departments_of_running_items(definitions, running))
    return Snapshot[ProjectOrganizationResult](
        position=store.end_position(),
        data=ProjectOrganizationResult(
            project_id=state.project_id, form=current,
            label=None if definitions is None else _label(definitions),
            version=None if definitions is None else definitions.version,
            form_in_release=current in forms,
            departments=departments,
            forms=[_choice(name, definitions) for name, definitions in forms.items()],
            history=_history(events, forms),
            changes=changes,
            organization=None if definitions is None else _organization_of(current, definitions),
            rejections=[DraftIssue(item=_item(file, field), message=message) for file, field, message in issues],
            add_verifier=added, remove_verifier=removed,
            previous_item=_previous_item(store, application.system.artifacts, request.project_id, definitions),
        ))


PROJECT_ORGANIZATION = QueryDefinition(
    name="project.organization", request=ProjectOrganization, result=ProjectOrganizationResult,
    handle=_project_organization,
    # 项目现在用哪一份、带哪些改动只由形态改动改变；发布带的清单与合成用的定义来自这个实例加载的形态，
    # 不来自事件
    changed_by=(ProjectEventType.PROJECT_FORM_SET,),
)


# ---------------------------------------------------------------------------
# 校验草稿（工单 #1515，项目的组织设计说明「草稿与校验」）


class OrganizationDraft(Contract):
    # 校验草稿的输入：项目、形态名与本项目的改动。改动是一份 JSON 文本（按身份只写不同的项，
    # 见 harness/definitions 的 OrganizationChanges）：GET 查询只有一个参数位，与目录文档的编辑同一做法。
    # 项目决定这份草稿是给哪个项目看的，草稿本身不存在事实里
    project_id: str
    form: str
    changes: str = "{}"


class OrganizationDraftResult(Contract):
    # 校验草稿的结果：合成结果、拒绝项、提醒与「这样改以后事项怎么结束」。
    # 有拒绝项时没有合成结果（改动还合不到一起），finishes 与 open_loop 也为空。
    # discarded 是换这一份时本项目现有改动里会丢掉的那些项（设计说明「形态一键选用」：页面确认一次，
    # 命令本身不拦）
    project_id: str
    organization: DraftOrganization | None
    rejections: list[DraftIssue]
    reminders: list[DraftReminder]
    finishes: str | None
    open_loop: bool | None
    discarded: list[str] = Field(default_factory=list)


def _refused(project_id: str, issues: list[tuple[str, str, str]], discarded: list[str]) -> OrganizationDraftResult:
    # 改动还合不到一起：只回答拒绝项（与换这一份会丢掉哪些）
    return OrganizationDraftResult(
        project_id=project_id, organization=None,
        rejections=[DraftIssue(item=_item(file, field), message=message) for file, field, message in issues],
        reminders=[], finishes=None, open_loop=None, discarded=discarded)


def _organization_draft(application: Application,
                        request: OrganizationDraft) -> Snapshot[OrganizationDraftResult]:
    store = application.system.store
    try:
        state = project_projection(store, application.system.artifacts, request.project_id, include_history=False)
    except ProjectNotFoundError:
        raise NotFound(f"project not found: {request.project_id}") from None
    forms = release_forms(application.system)
    form = forms.get(request.form)
    if form is None:
        raise QueryInputInvalid(f"发布带里没有形态 {request.form}；可以选的形态是：{'、'.join(forms)}")
    try:
        payload = json.loads(request.changes or "{}")
    except json.JSONDecodeError as exc:
        raise QueryInputInvalid(f"改动不是合法的 JSON：第 {exc.lineno} 行第 {exc.colno} 列 {exc.msg}") from exc
    discarded = dropped_changes(state.organization_changes, payload)
    changes, issues = parse_organization_changes(payload)
    if changes is None:
        return Snapshot[OrganizationDraftResult](position=store.end_position(),
                                                 data=_refused(request.project_id, issues, discarded))
    # 采用的三个时候跑的是同一套：改动能不能加到形态上、合成、路由自己的校验
    definitions, issues = compose_checked(form, changes, store=store)
    if definitions is None:
        return Snapshot[OrganizationDraftResult](position=store.end_position(),
                                                 data=_refused(request.project_id, issues, discarded))
    finishes, open_loop = finish_statement(definitions)
    return Snapshot[OrganizationDraftResult](
        position=store.end_position(),
        data=OrganizationDraftResult(
            project_id=request.project_id, organization=_organization_of(request.form, definitions),
            rejections=[],
            reminders=[DraftReminder(kind=item.kind, message=item.message)
                       for item in reminders(definitions)],
            finishes=finishes, open_loop=open_loop, discarded=discarded))


ORGANIZATION_DRAFT = QueryDefinition(
    name="organization.draft", request=OrganizationDraft, result=OrganizationDraftResult,
    handle=_organization_draft,
    # 结果只由请求（项目、形态、改动）与这个实例加载的发布带决定，不由任何事件改变
    changed_by=(),
)
