// 时序图（工单 #1641，项目的组织设计说明 4.14「项目页是循环图加对话」的「时序图（经过）」一节、
// 4.15「循环图跟着组织长」的时序图一行）：把 sequence-model 推出的事实画成一行一条消息的经过。
//
// 左边一列时间，右边是「你 + 这个事项冻结的组织里的职能」几列：一行一条消息，从发的那一列画到收的那一列，
// 询问与回答是虚线，其余（成果、你的输入、指导、决定）是实线；同一版同时给几个职能时画成一条带几个去向的消息。
// 放行与打回标在那一版那一行上，不单独占一行；询问里又问的缩进一层。
// 提问方等着的时段在它那一列上画一段色条，等你决定也一样；还没等到的画到「现在」。
// 按轮折起来，只展开最新一轮，折起来的一行写这一轮的摘要。
// 窗口窄到 800px 以下时换成按时间排的列表，每行写谁到谁与那句标题（样式里换，见 v10-project.css）。
//
// 这一层只画，不做判断：列、行、轮、摘要与色条全部由模型给出，单元测试在 sequence-model.test.ts。

import { Fragment } from "react";
import { formatTime } from "./labels";
import type { SequenceRow, SequenceView } from "./sequence-model";

/** 列的中心在整条轨道上的百分比位置；不在列里时（例如旧组织的职能）为 null。 */
function centerOf(view: SequenceView, id: string): number | null {
  const index = view.columns.findIndex((column) => column.id === id);
  return index < 0 ? null : ((index + 0.5) / view.columns.length) * 100;
}

/** 时间那一列写什么：同一天里只写时分，跨天的内容在窄屏列表里写全。 */
function clockText(at: string): string {
  const parsed = new Date(at);
  return Number.isNaN(parsed.getTime())
    ? "未知时间"
    : parsed.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

/** 每一条线都要的两样：几条职能的竖线（生命线）与这一行上正在等的色条。 */
function Lane(props: { view: SequenceView; bars: SequenceRow["bars"] }): React.JSX.Element {
  return (
    <>
      {props.view.columns.map((column) => (
        <i key={column.id} className="y10-sq-life" style={{ left: `${centerOf(props.view, column.id) ?? 0}%` }} aria-hidden="true" />
      ))}
      {props.bars.map((bar) => {
        const at = centerOf(props.view, bar.column);
        return at === null ? null : (
          <i key={`${bar.column}-${bar.kind}`} className={`y10-sq-bar is-${bar.kind}`} style={{ left: `${at}%` }} title={bar.tip} />
        );
      })}
    </>
  );
}

/** 一行：从谁那一列到谁那一列，虚线还是实线，那句话说在线的哪一头。 */
function Row(props: { view: SequenceView; row: SequenceRow }): React.JSX.Element {
  const { view, row } = props;
  const from = centerOf(view, row.from);
  const targets = row.to
    .map((id) => centerOf(view, id))
    .filter((value): value is number => value !== null);
  const points = from === null ? targets : [from, ...targets];
  const lo = points.length === 0 ? 0 : Math.min(...points);
  const hi = points.length === 0 ? 0 : Math.max(...points);
  // 离出发点最远的那个去向画箭头；中间的收件人画点
  const far = from === null ? null : targets.reduce(
    (best, value) => (Math.abs(value - from) > Math.abs(best - from) ? value : best),
    targets[0] ?? from,
  );
  const indent = row.depth * 14;
  const linked = from !== null && targets.length > 0;
  const text = lo < 50
    ? { left: `${lo}%`, right: 0, paddingLeft: indent }
    : { left: 0, right: `${100 - hi}%`, textAlign: "right" as const, paddingRight: indent };
  return (
    <div className="y10-sq-row" data-testid={`sequence-row-${row.key}`}>
      <span className="y10-sq-time">{clockText(row.at)}</span>
      <span className="y10-sq-track">
        <Lane view={view} bars={row.bars} />
        {linked && far !== null ? (
          <i
            className={`y10-sq-line${row.dashed ? " is-dash" : ""}${far > from ? " is-r" : " is-l"}`}
            style={{ left: `${lo}%`, width: `${hi - lo}%` }}
            aria-hidden="true"
          />
        ) : null}
        {linked ? targets.filter((value) => value !== far).map((value) => (
          <i key={value} className="y10-sq-dot" style={{ left: `${value}%` }} aria-hidden="true" />
        )) : null}
        <span className="y10-sq-text" style={text} title={row.title}>
          <span>
            {row.depth === 0 ? "" : "↳ "}
            {row.title}
            {row.verdict === null ? null : (
              <span className={`y10-sq-verdict is-${row.verdict.tone}`}> {row.verdict.text}</span>
            )}
          </span>
        </span>
      </span>
    </div>
  );
}

/** 还没等到的色条画到这里：图上最后多这一行。 */
function NowRow(props: { view: SequenceView; bars: SequenceRow["bars"] }): React.JSX.Element {
  return (
    <div className="y10-sq-row is-now">
      <span className="y10-sq-time">现在</span>
      <span className="y10-sq-track">
        <Lane view={props.view} bars={props.bars} />
      </span>
    </div>
  );
}

/** 窄屏那一条：谁到谁，加上那句标题；还没回答、等你决定写在同一行上。 */
function whoNote(row: SequenceRow): string {
  if (!row.open) {
    return "";
  }
  return row.kind === "decide" ? " · 等你决定" : " · 还没回答";
}

export function SequenceView(props: {
  view: SequenceView;
  onClose: () => void;
  onToggleRound: (round: number) => void;
}): React.JSX.Element {
  const { view } = props;
  const roundHead = (round: number, open: boolean, summary: string): React.ReactNode => (
    <button
      type="button"
      className="y10-sq-round"
      aria-expanded={open}
      data-testid={`sequence-round-${round}`}
      onClick={() => props.onToggleRound(round)}
    >
      <span aria-hidden="true">{open ? "▾" : "▸"}</span> 第 {round} 轮{open || summary === "" ? "" : ` · ${summary}`}
    </button>
  );
  const latest = view.rounds.find((round) => round.round === view.latestRound);
  const nowBars = latest?.rows.at(-1)?.bars ?? [];
  return (
    <section className="y10-sq" aria-label="时序图" data-testid="sequence">
      <div className="y10-sq-head">
        <b>经过</b>
        <span className="y10-sq-scope">整件事</span>
        <span className="y10-sq-legend">
          <i className="y10-sq-key is-dash" aria-hidden="true" />询问与回答
          <i className="y10-sq-key is-ask" aria-hidden="true" />在等回答
          <i className="y10-sq-key is-user" aria-hidden="true" />等你决定
        </span>
        <button type="button" className="y10-sq-close" aria-label="收起时序图" onClick={props.onClose}>×</button>
      </div>
      {view.empty ? (
        <p className="y10-note">这件事项还没有往来，图上没有可画的一行。</p>
      ) : (
        <>
          <div className="y10-sq-wide">
            <div className="y10-sq-row is-cols">
              <span className="y10-sq-time" />
              <span className="y10-sq-track">
                {view.columns.map((column) => (
                  <b key={column.id} style={{ left: `${centerOf(view, column.id) ?? 0}%` }}>{column.label}</b>
                ))}
              </span>
            </div>
            {view.rounds.map((round) => (
              <Fragment key={round.round}>
                {roundHead(round.round, round.open, round.summary)}
                {round.open
                  ? round.rows.map((row) => <Row key={row.key} view={view} row={row} />)
                  : null}
                {/* 还没等到的色条画到这里：紧跟最新一轮的最后一行（这一轮折起来时不画，免得底下留下一段没有来处的色条） */}
                {round.open && round.round === view.latestRound && view.now !== null
                  ? <NowRow view={view} bars={nowBars} />
                  : null}
              </Fragment>
            ))}
          </div>
          <ol className="y10-sq-list">
            {view.rounds.map((round) => (
              <li key={round.round}>
                {roundHead(round.round, round.open, round.summary)}
                {round.open ? (
                  <ol>
                    {round.rows.map((row) => (
                      <li key={row.key} className={`y10-sq-item${row.dashed ? " is-dash" : ""}`}>
                        <small>{formatTime(row.at)} · {row.who}{whoNote(row)}</small>
                        <span>
                          {row.depth === 0 ? "" : "↳ "}
                          {row.title}
                          {row.verdict === null ? null : ` · ${row.verdict.text}`}
                        </span>
                      </li>
                    ))}
                  </ol>
                ) : null}
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}
