// 职能详情页的正文（工单 #1713 验收第 1 条）：项目的组织设计说明 4.9「职能详情」里
// 「发布带的那一版」——职责与写入范围只读，取自项目现在的组织；模型与 Prompt 那一组
// 每项写明跟随发布还是本项目写入（模型管理设计说明 9.2）。
// 用 node --test 运行，不依赖 Electron 与网络。

import { test } from "node:test";
import assert from "node:assert/strict";

import type { DepartmentSetting, DraftOrganization } from "../../src/renderer/src/api/generated/types.gen.ts";
import {
  FOLLOW_SOURCE,
  OWN_SOURCE,
  askingText,
  dutyRows,
  requestsPath,
  scopeRows,
  settingSourceRows,
  sourceText,
  verificationText,
  writeScopeText,
} from "../../src/renderer/src/views/project/department-detail-model.ts";
import { parseRoute } from "../../src/renderer/src/shell/routing.ts";

// 项目现在的组织：三个职能，质检核验工程的交付
function organization(overrides: Partial<DraftOrganization> = {}): DraftOrganization {
  return {
    version: "v7",
    form: "flow",
    routing: "cycle",
    routing_label: "循环",
    departments: [
      {
        id: "product",
        label: "产品",
        target: "把用户的意图写成要求",
        evidence: "要求能验收",
        work: "写要求、读反馈",
        watched: ["requirement"],
        outcomes: ["requirement"],
        verifier: false,
        write_scope: "workspace",
      },
      {
        id: "engineering",
        label: "工程",
        target: "把要求做成可核验的交付",
        evidence: "测试通过",
        work: "写代码、跑测试",
        watched: ["delivery"],
        outcomes: ["delivery"],
        verifier: false,
        write_scope: "workspace",
      },
      {
        id: "quality",
        label: "质检",
        target: "独立核验交付",
        evidence: "拿得到独立证据",
        work: "读交付、跑自己的检查",
        watched: [],
        outcomes: [],
        verifier: true,
        write_scope: "check_materials",
      },
    ],
    outcome_kinds: [
      { id: "requirement", label: "要求" },
      { id: "delivery", label: "交付" },
    ],
    verification: [{ verifier: "quality", verified: "engineering", outcome: "delivery" }],
    sources: {},
    ...overrides,
  } as DraftOrganization;
}

function setting(overrides: Partial<DepartmentSetting> = {}): DepartmentSetting {
  return {
    department: "engineering",
    version: 4,
    text: "",
    source: "configured",
    provider_id: null,
    model_id: null,
    requested_tier: null,
    department_setting_configured: true,
    ...overrides,
  } as DepartmentSetting;
}

test("职责的各行取自组织：显示名、负责什么、凭什么判断、怎么工作、关注与交出的成果", () => {
  const rows = dutyRows(organization(), "engineering");
  const value = (label: string) => rows.find((row) => row.label === label)?.value;
  assert.equal(value("显示名"), "工程");
  assert.equal(value("它对什么负责"), "把要求做成可核验的交付");
  assert.equal(value("凭什么判断"), "测试通过");
  assert.equal(value("怎么工作"), "写代码、跑测试");
  // 成果按组织里的名字写，不写内部标识
  assert.equal(value("关注的成果"), "交付");
  assert.equal(value("交出的成果"), "交付");
  // 组织里有几个职能时，「可以询问谁」写默认的「其余职能」
  assert.equal(value("可以询问谁"), "其余职能");
  assert.equal(askingText(organization()), "其余职能");
});

test("核验角色写明核验谁的哪种成果，不核验的职能写「不核验」", () => {
  assert.equal(verificationText(organization(), "quality"), "核验「工程」的「交付」");
  assert.equal(verificationText(organization(), "engineering"), "不核验");
  // 没有核验边时不写空白
  const noEdges = organization({ verification: [] });
  assert.equal(verificationText(noEdges, "quality"), "不核验");
});

test("只有一个职能时没有「可以询问谁」这一行，交出的成果为空时写明只回答询问", () => {
  const single = organization({
    departments: [
      {
        id: "operations", label: "运维", target: "守住线上", evidence: "告警能解释", work: "看日志",
        watched: [], outcomes: [], verifier: false, write_scope: "workspace",
      },
    ],
    verification: [],
  });
  assert.equal(askingText(single), null);
  const rows = dutyRows(single, "operations");
  assert.ok(!rows.some((row) => row.label === "可以询问谁"), "只有一个职能时不出现「可以询问谁」");
  assert.equal(rows.find((row) => row.label === "交出的成果")?.value, "不交出成果，只回答询问");
  assert.equal(rows.find((row) => row.label === "关注的成果")?.value, "无");
});

test("写入范围只读：两种取值都有中文，认不出的照原样写", () => {
  const scope = (id: string) => scopeRows(organization(), id)[0]?.value;
  assert.equal(scope("engineering"), "运行工作区");
  assert.equal(scope("quality"), "只写检查材料");
  assert.equal(writeScopeText(""), "未上报");
  assert.equal(writeScopeText("check_materials"), "只写检查材料");
  // 表里没有的取值不猜，照原样写出来
  assert.equal(writeScopeText("elsewhere"), "elsewhere");
});

test("模型与 Prompt 每项写明跟随发布还是本项目写入，按这一项有没有写入判断", () => {
  const rows = (value: DepartmentSetting | null) => settingSourceRows(value);
  const value = (rows2: { label: string; value: string }[], label: string) =>
    rows2.find((row) => row.label === label)?.value;
  // 三样都没写：都跟随发布
  const follow = rows(setting());
  assert.equal(value(follow, "模型"), FOLLOW_SOURCE);
  assert.equal(value(follow, "推理档位"), FOLLOW_SOURCE);
  assert.equal(value(follow, "职能 Prompt"), FOLLOW_SOURCE);
  // 只写了模型：模型是本项目写入，另两样仍跟随发布
  const onlyModel = rows(setting({ provider_id: "proxy-a", model_id: "glm-4.6" }));
  assert.equal(value(onlyModel, "模型"), OWN_SOURCE);
  assert.equal(value(onlyModel, "推理档位"), FOLLOW_SOURCE);
  assert.equal(value(onlyModel, "职能 Prompt"), FOLLOW_SOURCE);
  // 档位与 Prompt 写了各自算
  const written = rows(setting({ requested_tier: "高", text: "先写测试" }));
  assert.equal(value(written, "推理档位"), OWN_SOURCE);
  assert.equal(value(written, "职能 Prompt"), OWN_SOURCE);
  // 有设置记录但没写职能 Prompt：文字是内置默认 Prompt（工单 #1701 以后服务端会填上），仍写跟随发布
  const defaultPrompt = rows(setting({ text: "内置默认的工程 Prompt", department_setting_configured: false }));
  assert.equal(value(defaultPrompt, "职能 Prompt"), FOLLOW_SOURCE);
  // 没有设置记录时按没写处理，仍写跟随发布
  assert.equal(value(rows(null), "模型"), FOLLOW_SOURCE);
  assert.equal(value(rows(null), "职能 Prompt"), FOLLOW_SOURCE);
  assert.equal(sourceText(true), OWN_SOURCE);
  assert.equal(sourceText(false), FOLLOW_SOURCE);
});

test("「本职能的模型请求」到设置页的「模型请求与用量」，带着这个职能进来就生效", () => {
  const hash = requestsPath("p1", "w1", "engineering");
  const route = parseRoute(hash);
  assert.equal(route.name, "settings");
  assert.equal(route.settingsSection, "requests");
  assert.equal(route.requestFilters.department, "engineering");
  assert.equal(route.workItemId, "w1");
  // 没有事项范围时不写 w
  assert.doesNotMatch(requestsPath("p1", "", "engineering"), /(^|[?&])w=/);
});
