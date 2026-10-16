// 回放时的原型兼容映射（工单 #491）。
//
// 录下的调用序列是原型时代的事实（ADR-0021）：那时登记命令的工具名叫 run_command。
// #479 起真实系统的工具名改成 bash，画面代码只认 bash。
// 这里在把录下的调用送进客户端画面之前，把原型时代的名字显式换成真实系统的名字，
// 回放核对的就是「同一批调用在客户端画面上的结果与原型录下的相同」。
//
// 只映射原型时代独有的名字，不映射已登记的工具名；没登记的工具名留给画面按默认分支处理。

/** 原型时代与真实系统不同的工具名（工单 #491：其余名字两边一致）。 */
const RECORDED_TOOL_ALIASES: Record<string, string> = { run_command: "bash" };

/** 把录下的一帧调用里的原型时代工具名换成真实系统的名字；没有原型时代的名字就原样返回。 */
export function adaptRecordedArg(arg: unknown): unknown {
  if (!arg || typeof arg !== "object") return arg;
  const rec = arg as Record<string, unknown>;
  const out: Record<string, unknown> = { ...rec };
  // setModel 的 pending_tool：房间画面按它决定待命位置（原型 room.js 的 toolSpot）
  if (typeof rec.pending_tool === "string" && rec.pending_tool in RECORDED_TOOL_ALIASES) {
    out.pending_tool = RECORDED_TOOL_ALIASES[rec.pending_tool];
  }
  // playEvent 的载荷里的 tool：只有开工具（tool_started）会按工具名落到具体任务与座位上，
  // 收尾（tool_called）只看结果（原型 say.js 的 tool_called、画面 keyOf 同口径），名字不参与
  if (rec.type === "tool_started") {
    const pl = rec.payload;
    if (pl && typeof pl === "object") {
      const p = pl as Record<string, unknown>;
      if (typeof p.tool === "string" && p.tool in RECORDED_TOOL_ALIASES) {
        out.payload = { ...p, tool: RECORDED_TOOL_ALIASES[p.tool] };
      }
    }
  }
  return out;
}
