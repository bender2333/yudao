// 新建项目的入口说明与表单说明（工单 #1240，试用问题 Te28ea596-04；工单 #1648 按两页改成对话的说法）。
// 拿着一段需求正文的新手在首页看到「从想法新建」「接入已有项目」两个入口，原来没有任何说明，
// 不知道走哪一个、材料放在哪一步；表单原来只写「新建项目不调用模型」。
// 这里把两处文字抽成常量与纯函数：入口旁的说明答「什么时候用这个入口」，表单里的说明写清
// 需求材料不在新建这一步提交，建好项目以后在对话里写要求、发长材料（项目的组织设计说明「新建的入口」）。
// 原型 v13（js/ui/shell.js）的两个入口没有说明、表单写的是旧的一句，按工单正文取代原型的说法。

import { parseRoute, paths } from "./routing.ts";

export type NewProjectMode = "idea" | "existing";

// 入口旁的场景说明：答「什么时候用这个入口」，不写实现细节
export const PROJECT_ENTRY_NOTES: Record<NewProjectMode, string> = {
  idea: "从一段想法或需求文字开始，可以先建一个空项目。",
  existing: "把电脑上已有的代码目录接进来，先建档再做事项。",
};

// 表单里的说明：材料不在新建这一步交，建好项目以后到对话里写要求、发长材料。
// 接入已有项目的表单另有自己的说明（登记源目录、采集代码快照、开始建档事项），这里不重复。
export const PROJECT_FORM_NOTES: Record<NewProjectMode, string> = {
  idea: "新建项目不调用模型。建好以后在对话里写要求，长材料也在那里发。",
  existing: "",
};

// 入口旁的那一行说明
export function projectEntryNote(mode: NewProjectMode): string {
  return PROJECT_ENTRY_NOTES[mode];
}

// 表单里的那一段说明；这一版的表单没有说明时返回 null（不渲染空段落）
export function projectFormNote(mode: NewProjectMode): string | null {
  const note = PROJECT_FORM_NOTES[mode];
  return note === "" ? null : note;
}

export type NewProjectRouteName = "new-project" | "onboard-project";

export function newProjectRouteName(mode: NewProjectMode): NewProjectRouteName {
  return mode === "idea" ? "new-project" : "onboard-project";
}

export function isNewProjectEntryRoute(routeName: string): boolean {
  return routeName === "new-project" || routeName === "onboard-project";
}

export type SidebarEntryItem = {
  mode: NewProjectMode;
  label: string;
  note: string;
  hash: string;
  active: boolean;
};

/** 左侧栏的新建/接入导航项（工单 #1806）：只跳转独立页面并标出当前活动页，不再展开内联表单。 */
export function sidebarEntryItems(options: {
  activeName: string;
  canCreate: boolean;
  canOnboard: boolean;
}): SidebarEntryItem[] {
  const items: SidebarEntryItem[] = [];
  if (options.canCreate) {
    items.push({
      mode: "idea",
      label: "从想法新建",
      note: projectEntryNote("idea"),
      hash: paths.newProject(),
      active: options.activeName === "new-project",
    });
  }
  if (options.canOnboard) {
    items.push({
      mode: "existing",
      label: "接入已有项目",
      note: projectEntryNote("existing"),
      hash: paths.onboardProject(),
      active: options.activeName === "onboard-project",
    });
  }
  return items;
}

export type NewProjectPageMeta = {
  mode: NewProjectMode;
  title: string;
  subtitle: string;
  commandName: "project.create" | "project.onboard";
  requiredCapability: "project.create" | "project.onboard";
  cardsHeading: string;
  cardsHint: string;
  formNote: string | null;
  missingCapabilityText: string;
  showInitialDirectory: boolean;
  showSourceDirectory: boolean;
};

export function newProjectPageMeta(mode: NewProjectMode): NewProjectPageMeta {
  if (mode === "idea") {
    return {
      mode,
      title: "从想法新建项目",
      subtitle: projectEntryNote("idea"),
      commandName: "project.create",
      requiredCapability: "project.create",
      cardsHeading: "选择起步组织形态",
      cardsHint: "选好名称后点一张形态卡即可建好项目；建好以后还能在设置里调。",
      formNote: projectFormNote("idea"),
      missingCapabilityText: "当前服务不支持在这里新建项目。",
      showInitialDirectory: true,
      showSourceDirectory: false,
    };
  }
  return {
    mode,
    title: "接入已有项目",
    subtitle: projectEntryNote("existing"),
    commandName: "project.onboard",
    requiredCapability: "project.onboard",
    cardsHeading: "选择起步组织形态",
    cardsHint: "选好名称与源目录后点一张形态卡即可接入项目。",
    formNote: projectFormNote("existing"),
    missingCapabilityText: "当前服务不支持在这里接入已有项目。",
    showInitialDirectory: false,
    showSourceDirectory: true,
  };
}

/** 点「取消」返回进入新建/接入前的那一页；直接输入地址进来或前一页仍是入口页时回到首页。 */
export function cancelNewProjectHash(previousHash: string | null | undefined): string {
  if (!previousHash) {
    return paths.home();
  }
  const prior = parseRoute(previousHash);
  if (isNewProjectEntryRoute(prior.name) || prior.name === "not-found") {
    return paths.home();
  }
  return previousHash;
}
