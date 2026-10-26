// 询问一行的文字（原型 v12 设计说明第 3.3 节，工单 #904）：概览「当前事项」的「询问」一节用它，
// 部门工作间那张工单（#905）用同一份，因此单独一个文件。
//
// 一次询问写：状态（进行中、已回答、没能回答，取值由查询 run.asks 给出）、询问链、回问标记、时间与问题；
// 有回答时写回答，回答附带了 PRD 新版本时标「附带 PRD rN」；没能回答时写原因。
// 回问按深度在调用处缩进（ask-line 的 data-depth），这里只写文字。

import type { AskView } from "../../api/generated/types.gen";
import { departmentName, formatTime } from "./labels.ts";

// 询问链：从最外层的提问方起经过的部门，例如「工程 → 产品 → 工程」。
// 查询给的是每一层的提问方（工单 #903 的 run.asks），最内层被询问的部门不在里面，这里把它接上；
// 已经在链上时不再重复。
export function askChain(ask: AskView): string[] {
  const chain = [...ask.chain];
  if (ask.recipient !== "" && chain[chain.length - 1] !== ask.recipient) {
    chain.push(ask.recipient);
  }
  return chain.map((department) => departmentName(department));
}

// 一次询问写成的这一行：各部分用「 · 」隔开（状态 · 询问链 · 回问 · 时间 · 问题 · 回答 · 原因）
export function askLine(ask: AskView): string {
  const parts: string[] = [ask.status, askChain(ask).join(" → ")];
  if (ask.parent) {
    parts.push("回问");
  }
  parts.push(formatTime(ask.started_at));
  parts.push(ask.question);
  if (ask.answer) {
    const prd = ask.prd_revision === null || ask.prd_revision === undefined ? "" : ` 附带 PRD r${ask.prd_revision}`;
    parts.push(`回答：${ask.answer}${prd}`);
  }
  if (ask.reason) {
    parts.push(`没能回答：${ask.reason}`);
  }
  return parts.join(" · ");
}

// 回问的缩进（原型 v12 的 asksList 按 depth 缩进）：最外层的询问不缩进，每深一层多一格
export function askIndent(ask: AskView): string {
  const depth = Number.isFinite(ask.depth) && ask.depth > 1 ? Math.floor(ask.depth) - 1 : 0;
  return `${depth * 16}px`;
}
