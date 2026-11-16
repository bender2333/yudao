// 新建项目的入口说明与表单说明（工单 #1240，试用问题 Te28ea596-04；工单 #1648 按两页改成对话的说法）。
// 试用看到：首页「从想法新建」「接入已有项目」两个入口没有任何场景说明；新建项目弹窗只写
// 「新建项目不调用模型」，没有一句说需求材料在哪一步交。拿 16KB 需求正文的新手
// 不知道走哪个入口、材料放在哪一步。这两处的文字抽在 shell/new-project-text.ts，这里按文案判。

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  PROJECT_ENTRY_NOTES,
  PROJECT_FORM_NOTES,
  cancelNewProjectHash,
  isNewProjectEntryRoute,
  newProjectPageMeta,
  newProjectRouteName,
  projectEntryNote,
  projectFormNote,
  sidebarEntryItems,
} from "../../src/renderer/src/shell/new-project-text.ts";

test("两个入口各带一行场景说明：一个从想法或需求文字开始，一个把已有的代码目录接进来", () => {
  assert.match(projectEntryNote("idea"), /从一段想法或需求文字开始/);
  assert.match(projectEntryNote("idea"), /可以先建一个空项目/);
  assert.match(projectEntryNote("existing"), /电脑上已有的代码目录/);
  assert.match(projectEntryNote("existing"), /先建档再做事项/);
  // 两行说的是两件事，不会让人以为两个入口一样
  assert.notEqual(projectEntryNote("idea"), projectEntryNote("existing"));
  assert.deepEqual(Object.keys(PROJECT_ENTRY_NOTES).sort(), ["existing", "idea"]);
  for (const note of Object.values(PROJECT_ENTRY_NOTES)) {
    assert.ok(note.trim() !== "", "入口说明不能是空串");
  }
});

test("从想法新建的表单说明写清建好以后在对话里写要求、长材料也在那里发", () => {
  const note = projectFormNote("idea");
  assert.ok(note !== null);
  assert.match(note, /新建项目不调用模型/);
  assert.match(note, /建好以后在对话里写要求/);
  assert.match(note, /长材料也在那里发/);
  // 项目页只剩对话与设置两页（工单 #1648 的依据）：材料不再写到已经收掉的概览页去
  assert.doesNotMatch(note, /概览/);
  // 旧的那一句不再单独出现：材料在哪一步交要说清，不能只说「之后在概览中记录原文或作为新事项开始」
  assert.doesNotMatch(note, /；之后在概览中记录原文或作为新事项开始/);
});

test("接入已有项目的表单另有自己的说明，这里不加第二段", () => {
  assert.equal(projectFormNote("existing"), null);
  assert.equal(PROJECT_FORM_NOTES.existing, "");
});

// 工单 #1806（保护 R2）：侧栏新建/接入入口只生成导航目标与当前活动页标记，按权限出现。
test("侧栏新建与接入入口按能力列出、指向独立路径并仅高亮当前页", () => {
  const onIdea = sidebarEntryItems({ activeName: "new-project", canCreate: true, canOnboard: true });
  assert.equal(onIdea.length, 2);
  assert.deepEqual(
    onIdea.map((item) => ({ mode: item.mode, hash: item.hash, active: item.active })),
    [
      { mode: "idea", hash: "#/projects/new", active: true },
      { mode: "existing", hash: "#/projects/onboard", active: false },
    ],
  );

  const onExisting = sidebarEntryItems({ activeName: "onboard-project", canCreate: true, canOnboard: true });
  assert.equal(onExisting[0].active, false);
  assert.equal(onExisting[1].active, true);

  const onHome = sidebarEntryItems({ activeName: "home", canCreate: false, canOnboard: true });
  assert.equal(onHome.length, 1);
  assert.equal(onHome[0].mode, "existing");
  assert.equal(onHome[0].active, false);
});

// 工单 #1806（保护 R2）：独立页面的模式元数据与取消返回地址规则
test("独立页面模式元数据区分命令与字段，取消返回进入前的非入口页或回落首页", () => {
  assert.equal(newProjectRouteName("idea"), "new-project");
  assert.equal(newProjectRouteName("existing"), "onboard-project");
  assert.equal(isNewProjectEntryRoute("new-project"), true);
  assert.equal(isNewProjectEntryRoute("onboard-project"), true);
  assert.equal(isNewProjectEntryRoute("home"), false);

  const ideaMeta = newProjectPageMeta("idea");
  assert.equal(ideaMeta.commandName, "project.create");
  assert.equal(ideaMeta.requiredCapability, "project.create");
  assert.equal(ideaMeta.showInitialDirectory, true);
  assert.equal(ideaMeta.showSourceDirectory, false);
  assert.ok(ideaMeta.formNote !== null);

  const existingMeta = newProjectPageMeta("existing");
  assert.equal(existingMeta.commandName, "project.onboard");
  assert.equal(existingMeta.requiredCapability, "project.onboard");
  assert.equal(existingMeta.showInitialDirectory, false);
  assert.equal(existingMeta.showSourceDirectory, true);
  assert.equal(existingMeta.formNote, null);

  assert.equal(cancelNewProjectHash("#/p/demo/conversation?w=w1"), "#/p/demo/conversation?w=w1");
  assert.equal(cancelNewProjectHash(null), "#/home");
  assert.equal(cancelNewProjectHash(""), "#/home");
  assert.equal(cancelNewProjectHash("#/projects/new"), "#/home");
  assert.equal(cancelNewProjectHash("#/onboard"), "#/home");
  assert.equal(cancelNewProjectHash("#/unknown-path"), "#/home");
});
