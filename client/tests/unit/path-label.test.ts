// 顶栏的路径（设计说明第 3.4、9.1 节，工单 #702）：项目内页面写「项目名 / 页名」，
// 系统页只写它自己的页名。系统页的页名与页面里的标题一致，不是路由里的英文段名。

import { test } from "node:test";
import assert from "node:assert/strict";
import { parseRoute, pathLabel } from "../../src/renderer/src/shell/routing.ts";

const PROJECTS = [{ project_id: "p1", name: "示例项目" }];

test("系统页的顶栏路径是中文页名，与页面里的标题一致", () => {
  assert.equal(pathLabel(parseRoute("#/sys/models"), PROJECTS), "模型管理");
  assert.equal(pathLabel(parseRoute("#/sys/machines"), PROJECTS), "机房");
  assert.equal(pathLabel(parseRoute("#/sys/runtime"), PROJECTS), "执行槽位");
  assert.equal(pathLabel(parseRoute("#/sys/tools"), PROJECTS), "工具登记");
});

test("项目内页面与部门页的路径写法不变", () => {
  assert.equal(pathLabel(parseRoute("#/p/p1/overview"), PROJECTS), "示例项目 / 概览");
  assert.equal(pathLabel(parseRoute("#/p/p1/materials"), PROJECTS), "示例项目 / 资料");
  assert.equal(pathLabel(parseRoute("#/p/p1/observe"), PROJECTS), "示例项目 / 观测");
  assert.equal(pathLabel(parseRoute("#/p/p1/settings"), PROJECTS), "示例项目 / 设置");
  assert.equal(pathLabel(parseRoute("#/p/p1/dept/product"), PROJECTS), "示例项目 / 产品");
  assert.equal(pathLabel(parseRoute("#/home"), PROJECTS), "首页");
});
