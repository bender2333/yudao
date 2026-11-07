# 项目设置里「形态」的命令（工单 #1402、#1516，项目的组织设计说明「采用与历史」「模板一键选用」；
# 形态与核验角色设计说明「形态随事项冻结」；总图第四节「接口」缝与「定义」缝）：
# organization.adopt 采用一份组织：形态名、本项目的改动、理由、用户看到的组织版本与命令身份，写成项目流
# 的一条 project_form_set 事件（原值、新值、理由，工单 #1516 只增改动与版本）；之后新建的事项按新的那一份
# 冻结，正在跑的不变。
#
# 采用时重新合成、过同一套结构校验（harness/organization_compose.py 的 compose_checked）：有拒绝项时拒绝，
# 说明里写明是哪一项；组织版本是合成结果的内容摘要，用户看到的版本对不上时以 stale_base 拒绝并带现在的版本；
# 名字不在发布带的清单里、或者改动文档不合法时以 not_allowed 拒绝。
#
# 三种路（命令用一个字段说明，默认换模板）：换模板是形态名加空改动的一次采用，理由可以不写；加或去掉核验角色
# 是设置页的一次点击，改动由查询给出（project.organization 的 add_verifier / remove_verifier），理由可以不写；
# 高级是改定义的采用，理由为空时拒绝。改回就是把那一条的形态与改动再采用一次。
# 同一命令身份重发不再写第二条事件：写入口登记命令身份，重复提交交回原来的接受结果。

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field

from ..definitions import parse_organization_changes
from ..event_store import Command, project_stream
from ..models import ProjectEventType
from ..organization_compose import compose_checked, current_organization
from ..projects import ProjectArchivedError, ProjectNotFoundError
from ..write_path import NewProjectEvent
from .commands import Rejection
from .contracts import CommandRequest, NoRefs
from .form_queries import release_forms
from .registry import CommandDefinition

if TYPE_CHECKING:
    from .application import Application


# 采用的三条路（项目的组织设计说明「采用与历史」「模板一键选用」）：换模板（默认）、加或去掉核验角色、
# 高级。差别只在理由：前两条的理由可以不写，高级的理由为空时拒绝
AdoptionMode = Literal["template", "verifier", "advanced"]


class OrganizationAdopt(CommandRequest):
    # 采用本项目的一份组织：form 是发布带里那一份形态的名字；changes 是本项目的改动（按身份只写不同的项，
    # 空表示与形态相同）；reason 可以不写，写了就进历史；base_version 是用户看到的组织版本（现在这份组织
    # 合成结果的内容摘要；现在这一份不在发布里或合不到一起时为空），对不上时拒绝，页面按新的版本重新读取；
    # mode 说明走的是哪一条路，默认换模板
    project_id: str = Field(min_length=1)
    form: str = Field(min_length=1)
    changes: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    base_version: str | None
    mode: AdoptionMode = "template"


class _StaleOrganization(Exception):
    # 用户看到的组织版本与项目现在的不同：带上现在的版本（可能是空，现在这一份不在发布里）
    def __init__(self, current: str | None) -> None:
        super().__init__(current)
        self.current = current


def _issues_text(issues: list[tuple[str, str, str]]) -> str:
    # 拒绝项写成人看的一句：文件与字段路径、说明；一条一项
    return "改动有拒绝项，不能采用：" + "；".join(f"{file} {field}：{message}" for file, field, message in issues)


async def _adopt(application: "Application", command: Command, request: OrganizationAdopt) -> None:
    # 采用的判断在一个写事务里：读项目现在用的那一份与它的改动、合成出现在的组织版本，核对用户看到的版本，
    # 再追加那条项目事件。新的组织的合成与校验在事务以前做：有拒绝项时不进入写入口
    system = application.system
    forms = release_forms(system)
    form = forms.get(request.form)
    if form is None:
        raise Rejection("not_allowed",
                        f"发布带里没有形态 {request.form}；可以选的形态是：{'、'.join(forms)}")
    if request.mode == "advanced" and not request.reason.strip():
        raise Rejection("not_allowed", "走高级的采用要写明理由：改了哪些项、为什么改")

    changes, issues = parse_organization_changes(request.changes)
    if changes is None:
        raise Rejection("not_allowed", _issues_text(issues))
    definitions, issues = compose_checked(form, changes, store=system.store)
    if definitions is None:
        raise Rejection("not_allowed", _issues_text(issues))
    version = definitions.version

    def adopt(transaction: Any) -> None:
        project = transaction.projection
        if transaction.version == 0:
            raise ProjectNotFoundError(request.project_id)
        if project.archived:
            raise ProjectArchivedError(request.project_id)
        current = project.form_name
        # 现在这份组织的版本：形态加它带的改动合成结果的摘要；形态不在发布里或合不到一起时没有版本
        current_definitions, _issues = current_organization(forms, current, project.organization_changes,
                                                           store=system.store)
        current_version = None if current_definitions is None else current_definitions.version
        if request.base_version != current_version:
            raise _StaleOrganization(current_version)
        transaction.append(NewProjectEvent(ProjectEventType.PROJECT_FORM_SET, {
            "previous_form": current, "form": request.form, "reason": request.reason,
            "changes": request.changes, "version": version}, actor="user:local"))

    try:
        system.writes.transact(project_stream(request.project_id), adopt, command=command)
    except ProjectNotFoundError as missing:
        raise Rejection("not_found", "没有这个项目，请重新读取以后提交") from missing
    except ProjectArchivedError as archived:
        raise Rejection("project_archived", "项目已归档，恢复以后才能修改") from archived
    except _StaleOrganization as stale:
        raise Rejection("stale_base", "项目的组织已经被改过，请重新读取以后再选一次",
                        current_version=stale.current) from stale


def _no_refs(_events: list[Any]) -> NoRefs:
    # 采用的接受结果不带新建对象的标识：新的组织版本由查询按项目现在的形态与改动合成得出，
    # 页面收到 project_form_set 事件以后重新查询（刷新清单里有这一种）
    return NoRefs()


ORGANIZATION_ADOPT = CommandDefinition(
    name="organization.adopt", request=OrganizationAdopt, refs=NoRefs, handle=_adopt,
    derive_refs=_no_refs,
    reasons=("not_found", "stale_base", "project_archived", "not_allowed"),
)
