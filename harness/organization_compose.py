# 合成：形态加本项目的改动（工单 #1515；项目的组织设计说明「组织是形态加本项目的改动」「合成规则」「草稿与校验」；
# 总图第四节「定义」缝；ADR-0045）。合并在应用一侧，内核只管结构校验：这里按身份把改动并进形态读到的那几份
# 定义文件的内容，再交给内核的同一套校验（definitions.definitions_from_contents），所以合成结果的版本与加载时
# 一样是这些内容的内容摘要；改动为空时合成结果与形态本身的内容相同，版本也相同。
#
# 合成规则（设计说明「合成规则」第 1 至 6 条）：
#   1. 单值的项整项替换：显示名、三样说明、事项的来源接哪个部门、核验声明、轮转方式。
#   2. 清单类的项记增加与去掉：工具许可、关注的成果；发布以后往清单里加的新项照样进来。
#   3. 事项的来源的种类由发布给出，本项目只改每一种接它的部门。
#   4. 可以新增部门、角色、成果种类，改动里写全部内容。
#   5. 可以去掉部门、角色、成果种类；要去掉的对象在形态里已经不存在时这条不起作用。去掉一个部门时，
#      它在角色、提案合同、事项种类、规则登记与核验声明里的登记一起去掉，路由自己那份定义里的部门清单
#      跟着组织走。别的部门对被去掉的部门所交成果的关注由改动写进去掉项（页面在编辑时写进改动），
#      漏掉的成果种类由结构校验「关注的成果没有部门交」拒绝。
#   6. 改名只改显示名，身份不变。
# 子组织（第 7 条）这个阶段不做。
#
# 提醒与「这样改以后事项怎么结束」也由合成结果得出（设计说明「草稿与校验」）：看轮转方式写明的最后采纳的
# 成果，再看它有没有核验角色核验。提醒不挡采用。

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal

from . import routing_contract
from .definitions import (
    Definitions, LEGACY_VERIFICATION, OrganizationChanges, WORKSPACE_WRITE_SCOPE, definitions_from_contents,
    submitted_outcomes,
)
from .routing_contract import InvalidRoutingDefinition

# 提醒的种类（设计说明「拒绝与提醒」的提醒一段）：这一版只算得出由合成结果得出的三条；
# 需要模型设置与项目事实的几条（建议能力、部门没有可用模型、还在按旧组织跑的事项）随各自的入口进来
ReminderKind = Literal["open_loop", "midway_verifier", "no_outcomes"]


@dataclass(frozen=True)
class Reminder:
    # 一条提醒：可以采用，页面显示它
    kind: ReminderKind
    message: str


def compose(form: Definitions, changes: OrganizationChanges) -> Definitions:
    """把本项目的改动并进形态，交回一份完整的定义；不合法时由内核的结构校验抛出 DefinitionError。"""
    # 从形态读到的那几份文件的内容出发（深拷贝：合成的中间结果不回到形态本身）
    contents: dict[str, Any] = deepcopy(dict(form.contents))
    organization = contents["organization.json"]
    roles = contents["roles.json"]
    tools = contents["tools.json"]
    contracts = contents["proposal_contracts.json"]
    work_items = contents["work_items.json"]
    routings = contents["routings.json"]
    outcome_kinds = contents.get("outcome_kinds.json")
    rules = contents.get("rules.json")

    # 第 1、2、6 条：改形态里的部门与它的角色
    for name, change in changes.departments.items():
        department = _find(organization["departments"], name)
        if department is None:
            continue
        if change.label is not None:
            department["label"] = change.label
        for field in ("target", "evidence", "work"):
            value = getattr(change, field)
            if value is not None:
                department[field] = value
        if change.watched.add or change.watched.remove:
            watched = [item for item in department.get("watched", []) if item not in change.watched.remove]
            watched.extend(item for item in change.watched.add if item not in watched)
            department["watched"] = watched
        if name not in roles:
            continue
        if change.tools.add or change.tools.remove:
            # 工具许可在两处都写：角色的清单与各事项种类里这个部门的工作说明（tools_for 先看种类的工作说明，
            # 两处都改，改动才在许可里看得到——与工单 #1098 的读法相同）
            names = [item for item in roles[name]["tools"] if item not in change.tools.remove]
            names.extend(item for item in change.tools.add if item not in names)
            roles[name]["tools"] = names
            for kind in work_items["kinds"].values():
                work = kind.get("departments", {}).get(name)
                if work is None:
                    continue
                kept = [item for item in work.get("tools", []) if item not in change.tools.remove]
                kept.extend(item for item in change.tools.add if item not in kept)
                work["tools"] = kept
            _sync_contract(roles, contracts, work_items, tools, name)

    # 第 3 条：事项的来源整项替换（种类由发布给出，这里只改接它的部门）
    if changes.sources is not None:
        organization["sources"] = dict(changes.sources)
    # 第 1 条：轮转方式与核验声明整项替换
    if changes.routing is not None:
        organization["routing"] = changes.routing
    if changes.verification is not None:
        organization["verification"] = _declaration_contents(changes.verification)

    # 第 4 条：新增部门与它的角色，改动里写全部内容；Prompt 没有写时由三样说明生成底稿
    for added in changes.add_departments:
        organization["departments"].append({
            "id": added.id, "label": added.label, "roles": [added.id],
            "target": added.target, "evidence": added.evidence, "work": added.work,
            "watched": list(added.watched)})
        roles[added.id] = {"prompt": added.prompt or _prompt(added), "tools": list(added.tools),
                           "visibility": list(added.visibility)}
        contracts["roles"][added.id] = {"submit_tools": [], "kinds": {}, "notes": []}
        _sync_contract(roles, contracts, work_items, tools, added.id)

    # 第 4、5 条：成果种类的增加与去掉。新增的种类只进定义的清单（outcome_kinds.kinds）：
    # 它要能被关注与提交，还要进路由认得的那一组并有一个提交它的工具，那是发布带的事（见交付说明的边界）
    if outcome_kinds is not None:
        for name in changes.outcome_kinds.remove:
            outcome_kinds["kinds"] = [item for item in outcome_kinds["kinds"] if item["id"] != name]
            for group in outcome_kinds["groups"]:
                group["kinds"] = [item for item in group["kinds"] if item != name]
        outcome_kinds["kinds"].extend({"id": kind.id, "label": kind.label, "why": kind.why}
                                      for kind in changes.outcome_kinds.add)

    # 第 5 条：去掉部门与它的角色；它在别的文件里的登记一起去掉
    for name in changes.remove_departments:
        if _find(organization["departments"], name) is None:
            continue
        organization["departments"] = [item for item in organization["departments"] if item["id"] != name]
        roles.pop(name, None)
        contracts["roles"].pop(name, None)
        for kind in work_items["kinds"].values():
            kind.get("departments", {}).pop(name, None)
        if rules is not None:
            for key in [key for key in rules if key.split(".")[:2] == ["roles", name]]:
                rules.pop(key)
        _drop_from_conditions(contracts, name)
        _drop_from_verification(organization, name)

    # 路由自己那份定义里的部门清单跟着组织走：合成结果接上路由实现时，它按这份清单核对
    _sync_routing_departments(organization, routings, changes.routing if changes.routing is not None else form.routing)

    return definitions_from_contents(contents)


def finish_statement(definitions: Definitions) -> tuple[str, bool | None]:
    """「这样改以后事项怎么结束」：由合成结果得出，看轮转方式写明的最后采纳的成果有没有核验角色核验。

    第二项是开环与否：这份轮转方式没有写明最后采纳的成果时为空（结束原因由它自己给）。
    """
    routing = definitions.routing_definition()
    final = routing.final_outcome
    if final is None:
        return "事项怎么结束由轮转方式自己的结束原因决定。", None
    labels = definitions.department_labels
    verifiers = list(definitions.verified_by(final))
    if verifiers:
        pairs = list(dict.fromkeys(definitions.verification_pairs(final)))
        verified = list(dict.fromkeys(verified for _verifier, verified in pairs))
        return (f"{_labels(labels, verifiers)}放行才算完成，打回时{_labels(labels, verified)}返工。", False)
    return (f"最后采纳的成果（{_outcome_label(definitions, final)}）没有核验角色核验，"
            f"事项以开环完成结束。", True)


def reminders(definitions: Definitions) -> list[Reminder]:
    """可以采用但要提醒的几处（设计说明「拒绝与提醒」的提醒一段），这一版只算得出由合成结果得出的三条。"""
    found: list[Reminder] = []
    final = definitions.routing_definition().final_outcome
    if final is not None and not definitions.verified_by(final):
        label = _outcome_label(definitions, final)
        if definitions.verifier_roles():
            found.append(Reminder("midway_verifier",
                                  f"核验角色只核验中途的成果，事项最后采纳的成果（{label}）没有人核验，"
                                  f"同样以开环完成结束。"))
        else:
            found.append(Reminder("open_loop",
                                  f"事项最后采纳的成果（{label}）没有核验角色核验，事项以开环完成结束。"))
    labels = definitions.department_labels
    for department in definitions.departments:
        if not submitted_outcomes(definitions.roles, definitions.tools, definitions.work_items, department):
            found.append(Reminder("no_outcomes", f"部门 {labels.get(department, department)} 不交出任何成果。"))
    return found


def write_scopes(definitions: Definitions) -> dict[str, str]:
    """每个部门的写入范围（页面显示与「运行工作区有两个写入者」的核对用同一份读法）。"""
    declaration = definitions.organization.verification or LEGACY_VERIFICATION
    return {department: declaration.write_scopes.get(department, WORKSPACE_WRITE_SCOPE).scope
            for department in definitions.departments}


def _find(departments: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return next((item for item in departments if item["id"] == name), None)


def _prompt(department: Any) -> str:
    # 三样说明同时是这个部门角色的 Prompt 底稿（设计说明「加部门」）
    return (f"它对什么负责：{department.target}。凭什么判断：{department.evidence}。"
            f"怎么工作：{department.work}。")


def _declaration_contents(declaration: Any) -> dict[str, Any]:
    # 改动里的核验声明换回定义文件的内容形状：写入口冻结过的那几个映射不能直接序列化成 JSON
    return {
        "verifiers": [{"role": verifier.role,
                       "verifies": [{"role": item.role, "outcomes": list(item.outcomes)}
                                    for item in verifier.verifies]}
                      for verifier in declaration.verifiers],
        "write_scopes": {role: {"scope": scope.scope, "paths": list(scope.paths)}
                         for role, scope in declaration.write_scopes.items()},
    }


def _sync_contract(roles: dict[str, Any], contracts: dict[str, Any], work_items: dict[str, Any],
                   tools: dict[str, Any], department: str) -> None:
    # 角色的提案合同必须恰好说明它在这个发布里能提交的那些成果（内核的合同核对）：工具变了以后
    # 按工具的 proposal 重算；原来写过的说明保留，新加的工具用一份空的说明（页面在「编辑定义」里补）
    names = list(roles[department]["tools"])
    for kind in work_items["kinds"].values():
        work = kind.get("departments", {}).get(department)
        if work is not None:
            names.extend(work.get("tools", []))
    host = sorted({name for name in names
                   if name in tools and tools[name].get("kind") == "host" and tools[name].get("proposal")})
    contract = contracts["roles"].setdefault(department, {"submit_tools": [], "kinds": {}, "notes": []})
    described = dict(contract.get("kinds", {}))
    contract["submit_tools"] = host
    contract["kinds"] = {kind: described.get(kind, {}) for kind in sorted({tools[name]["proposal"] for name in host})}


def _drop_from_conditions(contracts: dict[str, Any], name: str) -> None:
    # 去掉一个部门时，提案合同里按部门核对回执的条件一起去掉：它核验的那个部门不在了，
    # 这条条件对任何一种成果都不再有意义
    for kind, conditions in contracts.get("conditions", {}).items():
        contracts["conditions"][kind] = [item for item in conditions if item.get("department") != name]


def _drop_from_verification(organization: dict[str, Any], name: str) -> None:
    # 去掉一个部门时，核验声明里它核验别人、别人核验它的两项一起去掉，它的写入范围一起去掉
    declaration = organization.get("verification")
    if declaration is None:
        return
    kept = []
    for verifier in declaration.get("verifiers", []):
        if verifier.get("role") == name:
            continue
        verifier["verifies"] = [item for item in verifier.get("verifies", []) if item.get("role") != name]
        if verifier["verifies"]:
            kept.append(verifier)
    declaration["verifiers"] = kept
    declaration.get("write_scopes", {}).pop(name, None)


def _sync_routing_departments(organization: dict[str, Any], routings: dict[str, Any], routing: str) -> None:
    # 路由定义里的部门清单按组织定义核对（路由实现自己的校验），合成以后按合成结果的部门与顺序写
    order = [item["id"] for item in organization["departments"]]
    for entry in routings["routings"]:
        if entry.get("id") == routing:
            entry["departments"] = order


def routing_issues(definitions: Definitions) -> list[tuple[str, str, str]]:
    """路由自己那份定义的内容校验：与加载时接上路由实现走同一处（`routing_contract.select` 调
    `check_definition`）。名称指向的部门、成果种类与提议方式对不上时逐项交回（文件、字段、说明），
    草稿因此看到与加载相同的拒绝项（设计说明「草稿与校验」「拒绝与提醒」第 10 条）。"""
    try:
        routing_contract.select(definitions.routing, definitions)
    except InvalidRoutingDefinition as exc:
        return [("routings.json", *_split_issue(issue)) for issue in exc.issues]
    return []


def _split_issue(issue: str) -> tuple[str, str]:
    # 路由的说明写成「字段：原因」；拆成内核与页面用的那一套（字段、说明）
    field, _, message = issue.partition("：")
    return (field, message) if message else ("（这一份定义）", issue)


def _labels(labels: dict[str, str], names: list[str]) -> str:
    return "、".join(labels.get(name, name) for name in names)


def _outcome_label(definitions: Definitions, kind: str) -> str:
    for item in definitions.outcome_kinds.kinds:
        if item.id == kind:
            return item.label or kind
    return kind
