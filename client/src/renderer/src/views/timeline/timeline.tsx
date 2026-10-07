// 时间轴（原型 v8 设计说明第 5.5 节、原型 v9 的 ui/replay.js，工单 #180）：
// 首页放在离开期间的报告下方，概览放在循环画面下方。刻度只取关键事实（首页取 home.away_report 的
// 关键事实列表，概览按项目筛选），按种类着色；刻度之间相隔超过阈值时画折断符号。
//
// 播放：从所选范围的起点状态开始，逐个播放关键事实；支持暂停、单步、三档速度；
// 拖到任意刻度时画面直接显示该时刻的状态。回放中的位置通过 onPosition 交给宿主：
// 宿主按位置带 at 重新查询可回放的查询，并把它交给画面。
//
// 报告与时间轴互相跳转：点击报告项时高亮它的刻度（highlight），点击刻度时把位置交给 onSelect。

import { useEffect, useMemo, useRef, useState } from "react";
import type { ReportFact } from "../../api/generated/types.gen";
import { formatTime } from "../project/labels";
import {
  BASE_MS,
  SPEEDS,
  KEY_KINDS,
  durationText,
  partsOf,
  ticksOf,
  type FactTick,
  type KeyKind,
  type Speed,
} from "./logic";

// 播放定时器的句柄：渲染进程同时有 DOM 与 Node 的类型（tsconfig 的 types 含 node），
// 用明确的别名而不是 ReturnType 表达它
export type TimerHandle = NodeJS.Timeout;

export interface TimelineProps {
  // 关键事实列表与所选范围（起点位置）；回放从 from_position 开始
  facts: ReportFact[];
  fromPosition: number;
  fromAt: string;
  // 概览按项目筛选刻度；首页为 null
  project?: string | null;
  // 回放位置变化（null 表示回到现在）
  onPosition: (position: number | null) => void;
  // 点击刻度（与 onPosition 一起发出，供报告高亮）
  onSelect: (position: number) => void;
  // 当前高亮的刻度位置（报告项展开时给出）
  highlight: number[];
  // 实时查看时的说明文字
  liveNote: string;
}

export function Timeline(props: TimelineProps) {
  const ticks = useMemo(() => ticksOf(props.facts, props.project), [props.facts, props.project]);
  const parts = useMemo(() => partsOf(ticks), [ticks]);
  const [index, setIndex] = useState(-1);
  const [position, setPosition] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<Speed>(1);
  const timer = useRef<TimerHandle | null>(null);

  // 位置一起发出：宿主按位置带 at 重新查询；null 表示回到现在
  const move = (nextPosition: number | null) => {
    setPosition(nextPosition);
    props.onPosition(nextPosition);
  };

  const stopTimer = () => {
    if (timer.current !== null) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    setPlaying(false);
  };

  const step = (): boolean => {
    if (index + 1 >= ticks.length) {
      // 播放到最后一条以后回到现在（设计说明第 5.5 节：结束或点击「回到现在」以后恢复实时画面）
      live();
      return false;
    }
    const next = index + 1;
    const tick = ticks[next];
    if (tick === undefined) {
      // 数据变化使刻度收缩：回到现在，不读不存在的刻度
      live();
      return false;
    }
    setIndex(next);
    move(tick.position);
    return true;
  };

  const play = () => {
    if (position === null || index + 1 >= ticks.length) {
      setIndex(-1);
      move(props.fromPosition);
    }
    setPlaying(true);
    tick();
  };

  function tick(): void {
    timer.current = setTimeout(() => {
      timer.current = null;
      if (!playingRef.current) {
        return;
      }
      if (step() && playingRef.current) {
        tick();
      }
    }, BASE_MS / speedRef.current);
  }

  // 定时器回调里读的是最新的播放状态与速度（放在 ref 中，避免闭包读到旧值）
  const playingRef = useRef(false);
  const speedRef = useRef<Speed>(1);
  playingRef.current = playing;
  speedRef.current = speed;

  const pause = () => {
    stopTimer();
  };

  const seek = (nextIndex: number) => {
    const tick = ticks[nextIndex];
    if (tick === undefined) {
      return;
    }
    stopTimer();
    setIndex(nextIndex);
    move(tick.position);
    props.onSelect(tick.position);
  };

  const live = () => {
    stopTimer();
    setIndex(-1);
    move(null);
  };

  // 组件卸载时清掉定时器
  useEffect(() => stopTimer, []);

  const current = index >= 0 && index < ticks.length ? ticks[index] : null;
  const legend = legendKinds(ticks);

  return (
    <div className="timeline">
      <div className="timeline-bar">
        <button type="button" className="small" disabled={ticks.length === 0} onClick={() => (playing ? pause() : play())}>
          {playing ? "暂停" : "播放"}
        </button>
        <button type="button" className="small" disabled={ticks.length === 0} onClick={() => step()}>
          单步
        </button>
        <span className="speed-seg" role="group" aria-label="播放速度">
          {SPEEDS.map((option) => (
            <button key={option} type="button" className={option === speed ? "active" : ""} onClick={() => setSpeed(option)}>
              {option}×
            </button>
          ))}
        </span>
        <button type="button" className="small" disabled={position === null} onClick={live}>
          回到现在
        </button>
        {position !== null ? (
          <span className="replay-status">
            回放中 · {formatTime(current ? current.at : props.fromAt)}
          </span>
        ) : (
          <span className="note">{props.liveNote}</span>
        )}
      </div>
      <div className="ticks" role="list" aria-label="关键事实的时间轴">
        {parts.length === 0 ? (
          <span className="note">所选范围内没有关键事实</span>
        ) : (
          parts.map((part, partIndex) => {
            if (part.kind === "break") {
              return (
                <span key={`break-${part.gapSec}-${partIndex}`} className="tick-break" title={`跳过 ${durationText(part.gapSec)}`}>
                  ⫽<small>{durationText(part.gapSec)}</small>
                </span>
              );
            }
            const tick = part.tick;
            const current = part.index === index;
            const past = part.index < index;
            const highlighted = props.highlight.includes(tick.position);
            return (
              <button
                key={tick.position}
                type="button"
                className={`tick${current ? " current" : ""}${past ? " past" : ""}${highlighted ? " highlight" : ""}`}
                style={{ ["--tick" as string]: KEY_KINDS[tick.kind].color }}
                data-position={tick.position}
                data-kind={tick.kind}
                title={`${formatTime(tick.at)} · ${KEY_KINDS[tick.kind].label} · ${tick.label}`}
                onClick={() => seek(part.index)}
              >
                <span />
              </button>
            );
          })
        )}
      </div>
      {legend.length > 0 ? (
        <div className="timeline-legends">
          {legend.map((kind) => (
            <span key={kind} className="legend" style={{ ["--tick" as string]: KEY_KINDS[kind].color }}>
              <i />
              {KEY_KINDS[kind].label}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

// 图例：范围内出现过的关键事实种类，按 KEY_KINDS 的固定顺序排列
function legendKinds(ticks: FactTick[]): KeyKind[] {
  const present = new Set(ticks.map((tick) => tick.kind));
  return (Object.keys(KEY_KINDS) as KeyKind[]).filter((kind) => present.has(kind));
}

export type { FactTick };
