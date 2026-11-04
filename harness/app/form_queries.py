# 项目设置里「形态」的查询（工单 #1402，项目的组织设计说明「采用与历史」「模板一键选用」；
# 形态与核验角色设计说明「形态随事项冻结」；总图第四节「接口」缝与「定义」缝）：
# project.organization 回答一个项目现在的组织，这一版只有形态这一节——现在用哪一份、它的组织版本、
# 发布带的每一份形态（名字、一句说明、有没有核验角色），以及改动的历史（原值、新值、理由、时间、谁改的，
# 按事件顺序，早的在前）。只读事实，不写入。

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import AwareDatetime

from ..definitions import Definitions
from ..models import ProjectEventType
from ..projects import ProjectNotFoundError, project_projection
from ..runtime import FORM_REGISTRY
from .contracts import Contract, Snapshot
from .project_queries import NotFound
from .registry import QueryDefinition

if TYPE_CHECKING:
    from .application import Application


class ProjectOrganization(Contract):
    # 一个项目的组织：这一版只问形态这一节（设计说明第 3 节「接口：查询」的组织那一行，
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
