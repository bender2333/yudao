// 新建项目的入口说明与表单说明（工单 #1240，试用问题 Te28ea596-04）。
// 试用看到：首页「从想法新建」「接入已有项目」两个入口没有任何场景说明；新建项目弹窗只写
// 「新建项目不调用模型」，没有一句说需求材料在下一步作为事项输入提交。拿 16KB 需求正文的新手
// 不知道走哪个入口、材料放在哪一步。这两处的文字抽在 shell/new-project-text.ts，这里按文案判。

import { test } from "node:test";
import assert from "node:assert/strict";
import {
PROJECT_ENTRY_NOTES,
PROJECT_FORM_NOTES,
projectEntryNote,
projectFormNote
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

test("从想法新建的表单说明写清需求材料在下一步作为事项输入提交", () => {
  const note = projectFormNote("idea");
  assert.ok(note !== null);
  assert.match(note, /新建项目不调用模型/);
  assert.match(note, /需求材料/);
  assert.match(note, /原文或文件/);
  assert.match(note, /概览/);
  assert.match(note, /作为新事项开始时提交/);
  // 旧的那一句不再单独出现：材料在哪一步交要说清，不能只说「之后在概览中记录原文或作为新事项开始」
  assert.doesNotMatch(note, /；之后在概览中记录原文或作为新事项开始/);
});

test("接入已有项目的表单另有自己的说明，这里不加第二段", () => {
  assert.equal(projectFormNote("existing"), null);
  assert.equal(PROJECT_FORM_NOTES.existing, "");
});
