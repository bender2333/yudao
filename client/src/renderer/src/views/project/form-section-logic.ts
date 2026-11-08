// 项目设置页「形态」一节的纯计算（工单 #1403，形态与核验角色设计说明「形态随事项冻结」；
// 项目的组织设计说明「采用与历史」「形态一键选用」；总图第一节「界面」：只读事实，命令从这里发）。
//
// 这一节只回答四件事，组件只负责摆位置：
//   1. 现在用哪一份：名字、组织版本；那一份已经不在发布里时照实写明，不拿别的形态顶替；
//   2. 发布带的几份各叫什么、一句说明：说明用查询给的那句（由那份定义得出，页面不另写），
//      没有核验角色的那一份另写一句「没有核验角色，事项以开环完成结束，不经过放行」；
//   3. 换成另一份：提交的形态名、理由与页面看到的当前值（组织版本）；
//   4. 历史与改回：每一次改动的原值、新值、理由、时间与谁改的；改回就是把那一条的原值再采用一次。
//
// 时间的写法沿用页面各处共用的 formatTime（labels.ts），这里只带出查询给的时间，不另发明一种写法。

import type {
  FormChange, FormChoice, ProjectOrganizationResult,
} from "../../api/generated/types.gen";
import { departmentName } from "./labels.ts";

// 没有核验角色的那一份在页面上另写的一句（工单验收第 3 条）：事项以开环完成结束，不经过放行。
// 这句是页面的说法，不取自查询的一句话说明（那一句只写「以开环完成结束」）
export const OPEN_LOOP_SENTENCE = "没有核验角色，事项以开环完成结束，不经过放行";

// 改动只对之后新建的事项生效（工单验收第 4 条）：正在跑的事项按创建时冻结的那一份跑完
export const FORM_CHANGE_HINT = "改动只对之后新建的事项生效，正在跑的事项按原来的形态跑完。";

// 这一次没有写理由时的写法：理由可以不写历史里仍记一条
export const NO_REASON = "没有写理由";

// 现在用的那一份不在这一版发布里（设计说明「冻结与升级」）：照实写明，不换一份顶替
export const NOT_IN_RELEASE = "不在这一版发布里";

// 发布带的一份形态在页面上的样子
export type FormChoiceView = {
  form: string;
  // 一句说明：查询给的那一句，原样显示
  description: string;
  // 没有核验角色时写 OPEN_LOOP_SENTENCE；有核验角色时为空（不写这一行）
  openLoop: string;
  // 现在用的是不是这一份
  isCurrent: boolean;
};

// 一份形态：一句说明照抄查询的说法，开环的那一句只按有没有核验角色写。
// 看核验角色是否为空，不看 open_loop 标记本身：两者说的是一件事，空清单是页面能看见的那一样
export function choiceView(choice: FormChoice, currentForm: string): FormChoiceView {
  return {
    form: choice.form,
    description: choice.description,
    openLoop: choice.verifier_roles.length === 0 ? OPEN_LOOP_SENTENCE : "",
    isCurrent: choice.form === currentForm,
  };
}

// 发布带的每一份，按查询给的顺序（登记顺序）
export function formChoices(organization: ProjectOrganizationResult): FormChoiceView[] {
  return organization.forms.map((choice) => choiceView(choice, organization.form));
}

// 「换成另一份」里的几份：现在用的这一份不在候选里（选它等于没改）。
// 现在这一份不在发布里时，发布带的每一份都能选回来（设计说明「冻结与升级」的修复那一条）
export function otherChoices(organization: ProjectOrganizationResult): FormChoice[] {
  return organization.forms.filter((choice) => choice.form !== organization.form);
}

// 现在用哪一份：名字与组织版本；那一份不在发布里时写明，并说清怎么修
export function currentFormText(organization: ProjectOrganizationResult): string {
  if (!organization.form_in_release) {
    return `现在用 ${organization.form}；这一份${NOT_IN_RELEASE}，选一份发布里的形态以后，之后新建的事项才有可用的组织`;
  }
  return `现在用 ${organization.form}（组织版本 ${organization.version ?? NOT_IN_RELEASE}）`;
}

// 组织版本：现在这一份不在发布里时没有版本，不写一个假的
export function versionText(organization: ProjectOrganizationResult): string {
  return organization.version ?? NOT_IN_RELEASE;
}

// 换一份的提交参数（命令 organization.adopt）：形态名、本项目的改动（这一版只接受空）、理由与
// 页面看到的组织版本；理由两端的空白去掉，全空白按没有写
export function adoptPayload(props: {
  projectId: string;
  form: string;
  reason: string;
  baseVersion: string | null;
}): Record<string, unknown> {
  const reason = props.reason.trim();
  return {
    project_id: props.projectId,
    form: props.form,
    changes: {},
    reason,
    base_version: props.baseVersion,
  };
}

// 能不能提交：选了一份，且不是现在用的这一份
export function canAdopt(props: { form: string; currentForm: string }): boolean {
  return props.form !== "" && props.form !== props.currentForm;
}

// 一次改动在页面上的一行
export type FormHistoryRow = {
  eventId: string;
  // 原值
  previous: string;
  // 新值
  form: string;
  // 理由：没有写时写 NO_REASON
  reason: string;
  // 时间：查询给的时刻，组件用页面共用的 formatTime 写出来
  at: string;
  // 谁改的：页面上的说法
  actor: string;
  // 这一行的一句话：原值换成新值
  text: string;
  // 「改回这一份」能不能点：原值就是现在这一份时等于没改，不给这一项
  canChangeBack: boolean;
};

// 理由的写法：只有空白也算没有写
export function reasonText(reason: string): string {
  return reason.trim() === "" ? NO_REASON : reason;
}

// 一次改动：原值、新值、理由、时间与谁改的；改回一项按现在用的是哪一份决定
export function historyRow(record: FormChange, currentForm: string): FormHistoryRow {
  return {
    eventId: record.event_id,
    previous: record.previous_form,
    form: record.form,
    reason: reasonText(record.reason),
    at: record.at,
    actor: actorText(record.actor),
    text: `${record.previous_form} → ${record.form}`,
    canChangeBack: canChangeBack(record.previous_form, currentForm),
  };
}

// 历史：按查询给的顺序（事件顺序，早的在前）
export function historyRows(organization: ProjectOrganizationResult): FormHistoryRow[] {
  return organization.history.map((record) => historyRow(record, organization.form));
}

// 「改回这一份」：原值不是现在用的这一份才有意义（等于没改时不给这一项）
export function canChangeBack(previousForm: string, currentForm: string): boolean {
  return previousForm !== currentForm;
}

// 改回：把那一条的原值再采用一次。理由不编一句，记为空；
// 页面看到的当前值照样带上，服务端按它对不上时照常拒绝
export function changeBackPayload(props: {
  projectId: string;
  previousForm: string;
  baseVersion: string | null;
}): Record<string, unknown> {
  return {
    project_id: props.projectId,
    form: props.previousForm,
    changes: {},
    reason: "",
    base_version: props.baseVersion,
  };
}

// 谁改的：与事件提出者在页面上的说法一致（你、系统、某部门）；认不出的照实写，不猜
export function actorText(actor: string): string {
  const separator = actor.indexOf(":");
  const kind = separator < 0 ? actor : actor.slice(0, separator);
  const value = separator < 0 ? "" : actor.slice(separator + 1);
  if (kind === "user") {
    return "你";
  }
  if (kind === "system") {
    return "系统";
  }
  if (kind === "department") {
    return `${departmentName(value)}部门`;
  }
  return actor;
}
