// 设置页「模型请求与用量」这一节的筛选（工单 #1710）：筛选条件写在地址里、从地址读回来；
// 职能选项与用量分组的显示名取自项目现在的组织（不再写死产品、工程、质检三个）。
// 观测页与设置页这一节用的是同一组函数（observe-filter.ts），这里核对的是其中纯粹的取值与转换。
// 用 node --test 运行。

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  EMPTY_FILTERS,
  departmentFilterNote,
  departmentOptions,
  filtersFromQuery,
  filtersQuery,
  mergeAddressFilters,
  seedFilters,
  usageGroupName,
} from "../../src/renderer/src/views/project/observe-filter.ts";
import type { Filters } from "../../src/renderer/src/views/project/observe-filter.ts";

function fullFilters(): Filters {
  return {
    department: "engineering",
    status: "failed",
    provider: "proxy-a",
    requestedModel: "gpt-5",
    actualModel: "gpt-5-mini",
    q: "压缩",
  };
}

test("筛选条件与地址往返：六格都写回、都读回", () => {
  const filters = fullFilters();
  assert.deepEqual(filtersFromQuery(new URLSearchParams(filtersQuery(filters))), filters);
});

test("没有筛选时不写参数，地址里不留空的键", () => {
  assert.deepEqual(filtersQuery(EMPTY_FILTERS), []);
  assert.deepEqual(filtersFromQuery(new URLSearchParams("")), EMPTY_FILTERS);
  // 空串与空白按没有筛选处理，不把空值发给服务端
  assert.deepEqual(filtersFromQuery(new URLSearchParams("dept=&status=%20&q=")), EMPTY_FILTERS);
});

test("地址里的职能按原样读出：项目职能清单里有、默认三个里没有的职能也生效", () => {
  const filters = filtersFromQuery(new URLSearchParams("dept=analysis"));
  assert.equal(filters.department, "analysis");
  assert.equal(seedFilters("analysis").department, "analysis");
  // 其余几格不受影响
  assert.equal(filters.status, "");
  assert.equal(filters.requestedModel, "");
});

test("职能选项取自项目现在的组织：只有一个职能的项目只有一项", () => {
  assert.deepEqual(departmentOptions([{ id: "engineering", label: "工程" }]), [{ value: "engineering", label: "工程" }]);
  assert.deepEqual(
    departmentOptions([{ id: "a", label: "甲" }, { id: "b", label: "乙" }]).map((option) => [option.value, option.label]),
    [["a", "甲"], ["b", "乙"]],
  );
  // 组织还没有数据时没有选项，不拿默认的三个补位
  assert.deepEqual(departmentOptions([]), []);
});

test("说明当前筛选的是哪个职能：用显示名，不出现内部标识", () => {
  assert.equal(departmentFilterNote("", { engineering: "工程" }), "");
  assert.equal(departmentFilterNote("engineering", { engineering: "工程" }), "只看工程的请求");
  // 旧数据里的职能不在当前组织里：用页面原有的写法，没有名字时原样写标识
  assert.equal(departmentFilterNote("quality", {}), "只看质检的请求");
  assert.equal(departmentFilterNote("legacy", {}), "只看legacy的请求");
});

test("用量按职能分组时把职能标识换成显示名", () => {
  const labels = { engineering: "工程" };
  assert.equal(usageGroupName({ key: "engineering", label: "engineering" }, labels), "工程");
  // 不在当前组织里的旧分组用后端给的名字，再没有就用标识
  assert.equal(usageGroupName({ key: "quality", label: "质检" }, labels), "质检");
  assert.equal(usageGroupName({ key: "legacy", label: null }, labels), "legacy");
  assert.equal(usageGroupName({ key: "legacy", label: "" }, labels), "legacy");
});

test("地址带来的筛选只改它带来的那几格：换职能不丢状态与模型", () => {
  const applied: Filters = { ...EMPTY_FILTERS, status: "failed", provider: "proxy-a" };
  const address: Filters = { ...EMPTY_FILTERS, department: "engineering" };
  assert.deepEqual(mergeAddressFilters(applied, address, EMPTY_FILTERS), { ...applied, department: "engineering" });
  // 地址没有变时原样返回同一个对象：页面不用重新渲染
  const same = mergeAddressFilters(applied, address, address);
  assert.equal(same, applied);
  // 地址里删掉的那一格跟着清空
  assert.deepEqual(mergeAddressFilters({ ...applied, department: "engineering" }, EMPTY_FILTERS, address), applied);
});
