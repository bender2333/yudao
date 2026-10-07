// 截图联系表的页面清单与截图矩阵（工单 #376）：清单覆盖原型 v9 的全部页面，
// 每一项写明原型与真实系统的路由；每种页面与主题一张联系表，每张固定六行。

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  LEVELS,
  PAGES,
  THEMES,
  sheetFileName,
  shotConfigs,
} from "../../scripts/page-contact-sheet-pages.ts";

const REQUIRED_PAGES = [
  "首页（含决定卡片）",
  "机器",
  "运行",
  "工具",
  "项目概览与楼层",
  "部门工作间",
  "资料",
  "观测",
  "项目设置",
  "恢复",
  "模型管理",
];

test("页面清单覆盖工单列出的全部页面", () => {
  assert.deepEqual(PAGES.map((page) => page.name).slice().sort(), REQUIRED_PAGES.slice().sort());
  assert.equal(new Set(PAGES.map((page) => page.slug)).size, PAGES.length);
});

test("每一项都写明原型与真实系统的路由，以及真实系统一侧的预置项目", () => {
  for (const page of PAGES) {
    assert.ok(page.prototypeHash.startsWith("#/"), `${page.slug} 的原型路由以 #/ 开头`);
    assert.ok(page.systemHash.startsWith("#/"), `${page.slug} 的真实系统路由以 #/ 开头`);
    assert.ok(LEVELS.includes(page.prototypeLevel), `${page.slug} 的档位要在原型的档位表里`);
    assert.ok(typeof page.systemProject === "string" || page.systemProject === null, `${page.slug} 要写明预置项目`);
    if (page.systemProject !== null) {
      assert.ok(page.systemProject.length > 0, `${page.slug} 要写明预置项目名`);
    }
  }
});

test("真实系统的系统页不带项目，项目页带项目", () => {
  const systemPages = PAGES.filter((page) => page.slug === "home" || page.systemHash.startsWith("#/sys/"));
  for (const page of systemPages) {
    assert.equal(page.systemProject, null, `${page.slug} 是系统页，不选预置项目`);
    assert.equal(page.systemHash, page.systemHash.replace("{project}", "x"), `${page.slug} 的路径里没有项目占位`);
  }
  for (const page of PAGES.filter((item) => !systemPages.includes(item))) {
    assert.ok(typeof page.systemProject === "string", `${page.slug} 是项目页，要写明预置项目`);
    assert.ok(page.systemHash.includes("{project}"), `${page.slug} 的路径里带项目占位`);
  }
});

test("恢复页的路径带事项占位，其余项目页面不带", () => {
  assert.equal(PAGES.filter((page) => page.systemWorkItem).map((page) => page.slug).join(","), "recovery");
  assert.ok(PAGES.find((page) => page.slug === "recovery")!.systemHash.includes("{workItem}"));
});

test("一张联系表固定六行：两种窗口乘三种设备像素比", () => {
  const configs = shotConfigs();
  assert.equal(configs.length, 6);
  assert.deepEqual(
    configs.map((config) => `${config.width}x${config.height}@${config.scaleFactor}`),
    ["1440x900@1", "1440x900@1.25", "1440x900@1.5", "1920x1080@1", "1920x1080@1.25", "1920x1080@1.5"],
  );
  assert.deepEqual(
    configs.map((config) => config.label),
    [
      "1440×900 · DPR 1",
      "1440×900 · DPR 1.25",
      "1440×900 · DPR 1.5",
      "1920×1080 · DPR 1",
      "1920×1080 · DPR 1.25",
      "1920×1080 · DPR 1.5",
    ],
  );
});

test("每个页面与主题一张图片，浅色与深色两种主题", () => {
  assert.deepEqual([...THEMES], ["light", "dark"]);
  assert.equal(sheetFileName("home", "light"), "home-light.png");
  assert.equal(new Set(PAGES.flatMap((page) => THEMES.map((theme) => sheetFileName(page.slug, theme)))).size, PAGES.length * 2);
});