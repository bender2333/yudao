// 请求详情「引用」一行的取值（工单 #745）：工件引用是对象（种类、内容摘要、工件路径、媒体类型），
// 不是文字。这一行以前用只认字符串的 optionalText 读对象，于是每一项都写成「未上报」，
// 而四项工件引用其实都在。显示口径与验收标准：
// 有引用给可核对的标识，没有引用写「未上报」，有引用但取不出标识写「取不出」；
// 页面上不出现英文内部标识与开发者措辞。
// 用 node --test 运行，不依赖 Electron 与网络。

import { test } from "node:test";
import assert from "node:assert/strict";
import { artifactRefText, artifactRefsRow, artifactRefsText } from "../../src/renderer/src/views/project/artifact-ref.ts";

// 服务端给出的工件引用：种类、内容摘要、工件路径与媒体类型
function ref(hash: string, kind: string): Record<string, unknown> {
  return {
    kind,
    content_hash: hash,
    path: `run_e43746f560e44403/b4/${hash.replace("sha256:", "")}`,
    media_type: "application/json",
  };
}

// 四项都在的一次请求（用户使用记录 U94 的形状）
function allRefs(): Record<string, unknown> {
  return {
    request: ref("sha256:b407eb8c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8", "sdk_request"),
    response: ref("sha256:2d1d4f66a8b3c5d6e7f8091a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6", "sdk_response"),
    events: ref("sha256:4e3463db9071e2f3a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3", "sdk_stream_events"),
    usage: ref("sha256:1c9f0e77aa52b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f708192a3b4c5", "raw_usage"),
  };
}

test("工件引用是对象时给出内容摘要，不写未上报", () => {
  assert.equal(
    artifactRefsText(allRefs()),
    "请求 内容摘要 b407eb8c1d2e，响应 内容摘要 2d1d4f66a8b3，原始流 内容摘要 4e3463db9071，用量 内容摘要 1c9f0e77aa52",
  );
});

test("四项都在时这一行不出现未上报", () => {
  assert.equal(artifactRefsText(allRefs()).includes("未上报"), false);
});

test("真的没有某一项引用时只写明是哪一项没有", () => {
  const refs = allRefs();
  refs.response = null;
  refs.usage = null;
  assert.equal(
    artifactRefsText(refs),
    "请求 内容摘要 b407eb8c1d2e，响应 未上报，原始流 内容摘要 4e3463db9071，用量 未上报",
  );
});

test("有引用但取不出标识时写取不出，与未上报分开", () => {
  assert.equal(artifactRefText({ kind: "sdk_response" }), "取不出");
  assert.equal(artifactRefText({ kind: "sdk_response", content_hash: "", path: "" }), "取不出");
  assert.equal(artifactRefText({ kind: "sdk_response", content_hash: null }), "取不出");
  // 形状不对（写成列表或数字）同样按取不出处理，不抛错
  assert.equal(artifactRefText([]), "取不出");
  assert.equal(artifactRefText(7), "取不出");
});

test("没有内容摘要时给工件路径", () => {
  assert.equal(artifactRefText({ kind: "raw_usage", path: "run_1/2d/2d1d4f66" }), "工件路径 run_1/2d/2d1d4f66");
});

test("整份引用没有时四项都写未上报", () => {
  const expected = "请求 未上报，响应 未上报，原始流 未上报，用量 未上报";
  assert.equal(artifactRefsText(undefined), expected);
  assert.equal(artifactRefsText(null), expected);
  assert.equal(artifactRefsText({}), expected);
});

test("页面上不出现英文内部标识与开发者措辞", () => {
  const text = artifactRefsText(allRefs());
  for (const forbidden of ["sdk_request", "sdk_response", "sdk_stream_events", "raw_usage",
    "application/json", "sha256", "[object Object]", "content_hash", "artifact_refs"]) {
    assert.equal(text.includes(forbidden), false, `这一行里出现了 ${forbidden}`);
  }
});

test("详情页里这一行的名字与内容", () => {
  assert.deepEqual(artifactRefsRow(allRefs()), ["引用", artifactRefsText(allRefs())]);
});
