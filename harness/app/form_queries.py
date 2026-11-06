# 项目设置里「形态」的查询（工单 #1402，项目的组织设计说明「采用与历史」「模板一键选用」；
# 形态与核验角色设计说明「形态随事项冻结」；总图第四节「接口」缝与「定义」缝）：
# project.organization 回答一个项目现在的组织，这一版只有形态这一节——现在用哪一份、它的组织版本、
# 发布带的每一份形态（名字、一句说明、有没有核验角色），以及改动的历史（原值、新值、理由、时间、谁改的，
# 按事件顺序，早的在前）。只读事实，不写入。
#
# organization.draft 是校验草稿（工单 #1515，项目的组织设计说明「草稿与校验」）：输入项目、形态与本项目的改动，
# 输出合成结果、拒绝项、提醒与「这样改以后事项怎么结束」。它不写入任何事件：合成在应用一侧
# （harness/organization_compose.py），结构校验是内核加载定义时的同一套（harness/definitions）。

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Literal

from pydantic import AwareDatetime

from ..definitions import (
    ITEM_SOURCES, DefinitionError, Definitions, organization_change_issues, parse_organization_changes,
    submitted_outcomes,
)
from ..models import ProjectEventType
from ..organization_compose import compose, finish_statement, reminders, write_scopes
from ..projects import ProjectNotFoundError, project_projection
from ..runtime import FORM_REGISTRY
from .contracts import Contract, Snapshot
from .project_queries import NotFound, QueryInputInvalid
from .registry import QueryDefinition

if TYPE_CHECKING:
    from .application import Application


class ProjectOrganization(Contract):
    # 一个项目的组织：这一版只问形态这一节（docs/design/project-organization.md「接口」「接口：查询」的组织那一行，
    # 合成结果、每项来源、观察者开关与和上一个事项用的组织的不同由别的工单加进来）
    project_id: str


class FormChoice(Contract):
    # 发布带的一份形态：名字（发布带里的标识）、一句说明、这份定义的版本（它就是没有改动时的组织版本）、
    # 核验角色的编号（空表示没有核验角色）与开环与否（没有核验角色核验最后采纳的成果）
    form: str
    description: str
    version: str
    verifier_roles: list[str]
    open_loop: bool


class OrganizationDepartment(Contract):
    # 项目现在用的形态里的一个部门（工单 #1457）：标识、显示名，以及它是不是核验角色。
    # 页面的部门页签、看板列与默认部门按这一项排；显示名也取这里，不另写一份部门清单
    id: str
    label: str
    verifier: bool = False


class FormChange(Contract):
    # 一次形态改动（项目流上的一条 project_form_set）：原值、新值、理由（没写时为空）、时间与谁改的
    event_id: str
    previous_form: str
    form: str
    reason: str
    at: AwareDatetime
    actor: str


class ProjectOrganizationResult(Contract):
    # 项目现在的组织（这一版只有形态这一节）：现在用哪一份、它的组织版本（那份形态的定义版本；
    # 现在这一份已经不在发布里时为空，form_in_release 为假，页面写明原因）、
    # 发布带的每一份形态与改动历史（按事件顺序，早的在前）
    project_id: str
    form: str
    version: str | None
    form_in_release: bool
    # 现在这一份形态里的部门（按定义里的顺序）：页面的部门页签、看板列、部门页的默认部门与
    # 部门显示名都取这里（工单 #1457）。这一份不在发布里时为空，不拿别的形态顶替
    departments: list[OrganizationDepartment]
    forms: list[FormChoice]
    history: list[FormChange]


def _release_forms(system: Any) -> dict[str, Definitions]:
    # 发布带的形态：实例加载的那几份（测试与演示可以把别的几份交给组装处）。
    # 只读打开没有组装处，按发布带的登记处读出名字与定义：这条查询只要这两样，不接路由
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


def _choice(name: str, definitions: Definitions) -> FormChoice:
    verifiers = list(definitions.verifier_roles())
    return FormChoice(form=name, description=_describe(definitions), version=definitions.version,
                      verifier_roles=verifiers, open_loop=not verifiers)


def _project_organization(application: Application,
                          request: ProjectOrganization) -> Snapshot[ProjectOrganizationResult]:
    store = application.system.store
    try:
        state = project_projection(store, application.system.artifacts, request.project_id,
                                   include_history=False)
    except ProjectNotFoundError:
        raise NotFound(f"project not found: {request.project_id}") from None
    forms = _release_forms(application.system)
    current = state.form_name
    current_definitions = forms.get(current)
    changes = [event for event in store.list_project_events(request.project_id)
               if event.type == ProjectEventType.PROJECT_FORM_SET]
    return Snapshot[ProjectOrganizationResult](
        position=store.end_position(),
        data=ProjectOrganizationResult(
            project_id=state.project_id, form=current,
            version=None if current_definitions is None else current_definitions.version,
            form_in_release=current_definitions is not None,
            departments=[] if current_definitions is None else [
                OrganizationDepartment(
                    id=department,
                    label=current_definitions.department_labels.get(department, department),
                    verifier=current_definitions.is_verifier(department))
                for department in current_definitions.departments],
            forms=[_choice(name, definitions) for name, definitions in forms.items()],
            history=[FormChange(
                event_id=event.event_id, previous_form=event.payload["previous_form"],
                form=event.payload["form"], reason=event.payload.get("reason", ""),
                at=event.created_at, actor=event.actor) for event in changes],
        ))


PROJECT_ORGANIZATION = QueryDefinition(
    name="project.organization", request=ProjectOrganization, result=ProjectOrganizationResult,
    handle=_project_organization,
    # 项目现在用哪一份只由形态改动改变；发布带的清单来自这个实例加载的形态，不来自事件
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


class DraftIssue(Contract):
    # 一条拒绝项：哪一项、为什么。项写文件与字段路径，例如「organization.json departments[1].watched[2]」
    item: str
    message: str


class DraftReminder(Contract):
    # 一条提醒：可以采用，页面显示它。kind 说明是哪一条提醒，页面按它排
    kind: Literal["open_loop", "midway_verifier", "no_outcomes"]
    message: str


class DraftDepartment(Contract):
    # 合成结果里的一个部门：身份、显示名、三样说明、关注的成果、交出的成果、是不是核验角色、写入范围
    id: str
    label: str
    target: str
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


class OrganizationDraftResult(Contract):
    # 校验草稿的结果：合成结果、拒绝项、提醒与「这样改以后事项怎么结束」。
    # 有拒绝项时没有合成结果（改动还合不到一起），finishes 与 open_loop 也为空
    project_id: str
    organization: DraftOrganization | None
    rejections: list[DraftIssue]
    reminders: list[DraftReminder]
    finishes: str | None
    open_loop: bool | None


def _item(file: str, field: str) -> str:
    return f"{file} {field}"


def _refused(project_id: str, issues: list[tuple[str, str, str]]) -> OrganizationDraftResult:
    # 改动还合不到一起：只回答拒绝项
    return OrganizationDraftResult(
        project_id=project_id, organization=None,
        rejections=[DraftIssue(item=_item(file, field), message=message) for file, field, message in issues],
        reminders=[], finishes=None, open_loop=None)


def _draft_organization(form_name: str, definitions: Definitions) -> DraftOrganization:
    scopes = write_scopes(definitions)
    sources = definitions.organization.sources
    return DraftOrganization(
        version=definitions.version, form=form_name, routing=definitions.routing,
        routing_label=definitions.routing_definition().label,
        departments=[DraftDepartment(
            id=department.id, label=department.label, target=department.target,
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


def _organization_draft(application: Application,
                        request: OrganizationDraft) -> Snapshot[OrganizationDraftResult]:
    store = application.system.store
    try:
        project_projection(store, application.system.artifacts, request.project_id, include_history=False)
    except ProjectNotFoundError:
        raise NotFound(f"project not found: {request.project_id}") from None
    forms = _release_forms(application.system)
    form = forms.get(request.form)
    if form is None:
        raise QueryInputInvalid(f"发布带里没有形态 {request.form}；可以选的形态是：{'、'.join(forms)}")
    try:
        payload = json.loads(request.changes or "{}")
    except json.JSONDecodeError as exc:
        raise QueryInputInvalid(f"改动不是合法的 JSON：第 {exc.lineno} 行第 {exc.colno} 列 {exc.msg}") from exc
    changes, issues = parse_organization_changes(payload)
    if changes is None:
        return Snapshot[OrganizationDraftResult](position=store.end_position(), data=_refused(request.project_id, issues))
    issues = organization_change_issues(form, changes)
    if issues:
        return Snapshot[OrganizationDraftResult](position=store.end_position(), data=_refused(request.project_id, issues))
    try:
        definitions = compose(form, changes)
    except DefinitionError as exc:
        return Snapshot[OrganizationDraftResult](position=store.end_position(),
                                                 data=_refused(request.project_id, list(exc.issues)))
    finishes, open_loop = finish_statement(definitions)
    return Snapshot[OrganizationDraftResult](
        position=store.end_position(),
        data=OrganizationDraftResult(
            project_id=request.project_id, organization=_draft_organization(request.form, definitions),
            rejections=[],
            reminders=[DraftReminder(kind=item.kind, message=item.message)
                       for item in reminders(definitions)],
            finishes=finishes, open_loop=open_loop))


ORGANIZATION_DRAFT = QueryDefinition(
    name="organization.draft", request=OrganizationDraft, result=OrganizationDraftResult,
    handle=_organization_draft,
    # 结果只由请求（项目、形态、改动）与这个实例加载的发布带决定，不由任何事件改变
    changed_by=(),
)

