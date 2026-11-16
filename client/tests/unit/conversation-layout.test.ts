// 对话页布局顺序回归测试（工单 #1807）：
// 事项主视图的从上到下顺序固定为：
// 循环蓝图 -> 展开的详情面板（panelRef：全部事项 / 事项面板 / 节点与箭头面板）-> 时序图（sequenceRef）-> 对话线程与输入框。
// 用 node --test 运行，不依赖 Electron。

import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const ts = require("typescript") as typeof import("typescript");

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const CONVERSATION_PATH = path.join(ROOT, "src/renderer/src/views/project/conversation.tsx");

function collectComponentMarkers(source: string): Array<{ tag: string; pos: number; text: string }> {
  const sf = ts.createSourceFile(CONVERSATION_PATH, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const markers: Array<{ tag: string; pos: number; text: string }> = [];

  function visit(node: import("typescript").Node) {
    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
      const name = node.tagName.getText(sf);
      const text = node.getText(sf);
      if (
        name === "ItemPicker" ||
        name === "LoopGraphView" ||
        name === "AllItems" ||
        name === "ItemPanel" ||
        name === "LoopPanel" ||
        name === "SequenceView" ||
        name === "ThreadView" ||
        name === "Composer" ||
        (name === "div" && (text.includes("ref={panelRef}") || text.includes("ref={sequenceRef}")))
      ) {
        markers.push({ tag: name, pos: node.getStart(sf), text });
      }
    }
    ts.forEachChild(node, visit);
  }

  visit(sf);
  return markers.sort((left, right) => left.pos - right.pos);
}

test("对话页主区布局顺序为：循环图 -> 详情面板 -> 时序图 -> 线程与输入框", () => {
  // R3：设计说明 docs/design/project-organization.md「节点面板与箭头面板接住的内容」：详情面板展在循环图正下方、时序图上方
  const source = fs.readFileSync(CONVERSATION_PATH, "utf8");
  const markers = collectComponentMarkers(source);
  const picker = markers.find((m) => m.tag === "ItemPicker");
  assert.ok(picker !== undefined, "conversation.tsx 中未找到 ItemPicker");
  const activeMarkers = markers.filter((m) => m.pos > picker.pos);

  const posOf = (predicate: (entry: { tag: string; pos: number; text: string }) => boolean, label: string): number => {
    const found = activeMarkers.find(predicate);
    assert.ok(found !== undefined, `conversation.tsx 已有事项分支中未找到 ${label}`);
    return found.pos;
  };

  const loopPos = posOf((m) => m.tag === "LoopGraphView", "LoopGraphView");
  const panelDivPos = posOf((m) => m.tag === "div" && m.text.includes("ref={panelRef}"), "div[ref={panelRef}]");
  const allItemsPos = posOf((m) => m.tag === "AllItems", "AllItems");
  const itemPanelPos = posOf((m) => m.tag === "ItemPanel", "ItemPanel");
  const loopPanelPos = posOf((m) => m.tag === "LoopPanel", "LoopPanel");
  const sequenceDivPos = posOf((m) => m.tag === "div" && m.text.includes("ref={sequenceRef}"), "div[ref={sequenceRef}]");
  const sequenceViewPos = posOf((m) => m.tag === "SequenceView", "SequenceView");
  const threadPos = posOf((m) => m.tag === "ThreadView", "ThreadView");
  const composerPos = posOf((m) => m.tag === "Composer", "Composer");

  assert.ok(loopPos < panelDivPos, "LoopGraphView 必须位于详情面板（panelRef）之前");
  assert.ok(panelDivPos < allItemsPos, "AllItems 必须在 panelRef 容器内");
  assert.ok(panelDivPos < itemPanelPos, "ItemPanel 必须在 panelRef 容器内");
  assert.ok(panelDivPos < loopPanelPos, "LoopPanel（节点/箭头面板）必须在 panelRef 容器内");
  assert.ok(loopPanelPos < sequenceDivPos, "详情面板（含节点/箭头/事项面板）必须在 SequenceView 容器之前");
  assert.ok(sequenceDivPos < sequenceViewPos, "SequenceView 必须在 sequenceRef 容器内");
  assert.ok(sequenceViewPos < threadPos, "SequenceView 必须位于 ThreadView 之前");
  assert.ok(threadPos < composerPos, "ThreadView 必须位于 Composer 之前");
});
