# 项目设置里「形态」的命令（工单 #1402，项目的组织设计说明「采用与历史」「模板一键选用」；
# 形态与核验角色设计说明「形态随事项冻结」；总图第四节「接口」缝与「定义」缝）：
# organization.adopt 把项目现在用的形态换成发布带的某一份，写成项目流的一条 project_form_set 事件
# （原值、新值与理由，工单 #1392 定下的那条）；之后新建的事项按新的那一份冻结，正在跑的不变。
# 带用户看到的组织版本（没有改动时就是那份形态的定义版本），对不上时以 stale_base 拒绝并带当前版本；
# 名字不在发布带的清单里、或这一版还不接受的本项目改动，以 not_allowed 拒绝，说明里写明原因与可选的形态。
# 理由可以不写（换模板这条路，docs/design/project-organization.md「模板一键选用」）。改回就是把原值再采用一次。
# 同一命令身份重发不再写第二条事件：写入口登记命令身份，重复提交交回原来的接受结果。

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import Field

from ..event_store import Command, project_stream
from ..models import ProjectEventType
from ..projects import ProjectArchivedError, ProjectNotFoundError
from ..write_path import NewProjectEvent
from .commands import Rejection
from .contracts import CommandRequest, NoRefs
from .registry import CommandDefinition

if TYPE_CHECKING:
    from .application import Application


class OrganizationAdopt(CommandRequest):
    # 采用本项目的一份组织（设计说明「采用与历史」；换模板是形态名加空改动的一次采用）：
    # form 是发布带里那一份形态的名字；changes 是本项目的改动，这一版只接受空（字段以后只增）；
    # reason 可以不写，写了就进历史；base_version 是用户看到的组织版本——项目现在的形态的那份定义版本
    # （现在这一份不在发布里时为空），对不上时拒绝，页面按新的版本重新读取
    project_id: str = Field(min_length=1)
    form: str = Field(min_length=1)
    changes: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    base_version: str | None


class _StaleOrganization(Exception):
    # 用户看到的组织版本与项目现在的不同：带上现在的版本（可能是空，现在这一份不在发布里）
    def __init__(self, current: str | None) -> None:
        super().__init__(current)
        self.current = current


async def _adopt(application: "Application", command: Command, request: OrganizationAdopt) -> None:
    # 采用的判断在一个写事务里：读项目现在用的那一份与它的版本，核对用户看到的版本，再追加那条项目事件
    system = application.system
    forms = system.forms
    if request.form not in forms:
        raise Rejection("not_allowed",
                        f"发布带里没有形态 {request.form}；可以选的形态是：{'、'.join(forms)}")
    if request.changes:
        # 本项目的改动这一版只接受空：合成与结构校验还没接（docs/design/forms-and-verifier-role.md「形态随事项冻结」），先不接受改动
        raise Rejection("not_allowed", "这一版还不能改本项目的改动：只能选发布带里的一份形态，改动留空")

    def adopt(transaction: Any) -> None:
        project = transaction.projection
        if transaction.version == 0:
            raise ProjectNotFoundError(request.project_id)
        if project.archived:
            raise ProjectArchivedError(request.project_id)
        current = project.form_name
        current_version = None if current not in forms else forms[current].definitions.version
        if request.base_version != current_version:
            raise _StaleOrganization(current_version)
        transaction.append(NewProjectEvent(ProjectEventType.PROJECT_FORM_SET, {
            "previous_form": current, "form": request.form, "reason": request.reason}, actor="user:local"))

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
    # 采用的接受结果不带新建对象的标识：新的组织版本由查询按项目现在的形态得出，
    # 页面收到 project_form_set 事件以后重新查询（刷新清单里有这一种）
    return NoRefs()


ORGANIZATION_ADOPT = CommandDefinition(
    name="organization.adopt", request=OrganizationAdopt, refs=NoRefs, handle=_adopt,
    derive_refs=_no_refs,
    reasons=("not_found", "stale_base", "project_archived", "not_allowed"),
)
