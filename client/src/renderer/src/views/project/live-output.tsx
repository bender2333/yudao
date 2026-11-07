// 部门页的实时模型输出（工单 #1416）：文字写在页面上，来源与画面的思考气泡相同——attempt.live 已有的
// 文字作为起点，再按 offset 接上事件流里的输出片段。拼接规则在 floor-text.ts 的纯函数里，这里只订阅。
// 打开页面时不补播（没有新的进度事件就没有这一段文字），与画面同一做法。
//
// 画面搬出（画面与播放 docs/design/visualization.md「搬出：画面成为单独的应用」，工单 #1418）：
// 这段文字原来与房间画布在同一个组件文件里，画布随画面搬进 view/ 以后，页面侧的这段文字单独留在页面。
// 页面不导入画面与翻译层。

import { useEffect, useState } from "react";
import type { ClientApp } from "../../contract/client-app";
import { liveOutputAbsorb, liveOutputObserve, liveOutputSeed, type LiveOutputView } from "./floor-text";

export function RoomLiveOutput(props: { app: ClientApp; department: string }): React.JSX.Element {
  const [output, setOutput] = useState<{ view: LiveOutputView; live: boolean } | null>(null);

  useEffect(() => {
    setOutput(null);
    const offEvents = props.app.subscribeEvents((event) => {
      // 别的部门的事件不属于这一页
      if (event.department !== null && event.department !== props.department) {
        return;
      }
      const payload = event.payload as unknown as Record<string, unknown>;
      const payloadAttempt = typeof payload.attempt_id === "string" ? payload.attempt_id : null;
      // 这次调用结束了：文字留着，状态改回「最近一次输出」
      if (event.type === "model_attempt_finished" || event.type === "model_attempt_failed") {
        if (payloadAttempt !== null) {
          setOutput((current) => current !== null && current.view.attemptId === payloadAttempt
            ? { ...current, live: false }
            : current);
        }
        return;
      }
      if (event.type !== "model_stream_progress") {
        return;
      }
      const attemptId = payloadAttempt;
      if (attemptId === null) {
        return;
      }
      setOutput((current) => ({
        view: liveOutputObserve(current?.view ?? null, attemptId),
        live: true,
      }));
      // 页面打开以前已经收到的文字经 attempt.live 取回（一次查询，不登记视图）
      void props.app.queryOne<{ live: boolean; channels: Record<string, string> }>(
        "attempt.live", { attempt_id: attemptId },
      ).then((result) => {
        setOutput((current) => ({
          view: liveOutputSeed(current?.view ?? null, attemptId, result.data.channels.output ?? ""),
          live: result.data.live,
        }));
      }).catch(() => {
        // 读不到已有的文字：只按随后到达的片段拼接，不打断页面
      });
    });
    const offDeltas = props.app.subscribeDeltas((delta) => {
      if (delta.department !== props.department) {
        return;
      }
      setOutput((current) => {
        const view = liveOutputAbsorb(current?.view ?? null, {
          attemptId: delta.attempt_id, channel: delta.channel, offset: delta.offset, text: delta.text,
        });
        return view === null ? current : { view, live: true };
      });
    });
    return () => {
      offEvents();
      offDeltas();
    };
  }, [props.app, props.department]);

  const text = output?.view.text ?? "";
  return (
    <div className="y10-ws-output" data-ws-output>
      <span className="y10-ws-k">实时的模型输出</span>
      <span className="y10-status y10-ws-output-state">
        {output === null ? "还没有输出" : output.live ? "正在输出" : "最近一次输出"}
      </span>
      {text === "" ? (
        <p className="y10-note note">这个部门现在没有正在输出的模型文字</p>
      ) : (
        <p className="y10-ws-guidance p msg-text" data-ws-output-text>{text}</p>
      )}
    </div>
  );
}
