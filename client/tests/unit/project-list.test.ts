// 项目列表的查询参数与可见性（工单 #672）：侧栏的「显示归档的项目」开关要真的作用到查询上，
// 勾上时用 include_archived=true 取数，已归档的项目才出现在列表里、菜单里才有「恢复项目」。

import { test } from "node:test";
import assert from "node:assert/strict";
import { projectsListParams, visibleProjects } from "../../src/renderer/src/views/project/project-list.ts";
import type { ProjectRow } from "../../src/renderer/src/api/generated/types.gen.ts";

function project(overrides: Partial<ProjectRow> & { project_id: string }): ProjectRow {
  return {
    name: "项目",
    goal: "做一件事",
    status: "",
    archived: false,
    pinned: false,
    ...overrides,
  } as ProjectRow;
}

test("勾上开关时项目列表的查询带上 include_archived", () => {
  assert.deepEqual(projectsListParams(true), { include_archived: true });
  assert.deepEqual(projectsListParams(false), { include_archived: false });
});

test("开关关闭时已归档的项目不列出", () => {
  const projects = [project({ project_id: "p1" }), project({ project_id: "p2", archived: true })];
  const visible = visibleProjects(projects, { search: "", includeArchived: false });
  assert.deepEqual(visible.map((row) => row.project_id), ["p1"]);
});

test("开关打开时已归档的项目出现在列表里", () => {
  const projects = [project({ project_id: "p1" }), project({ project_id: "p2", archived: true })];
  const visible = visibleProjects(projects, { search: "", includeArchived: true });
  assert.deepEqual(visible.map((row) => row.project_id), ["p1", "p2"]);
});

