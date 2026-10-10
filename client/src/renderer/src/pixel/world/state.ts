// 角色与管道的状态机（ADR-0021、原型 v10 设计说明第 4、5 节与 BUILD.md 第 3.5 节，工单 #82）。
//
// 每个有行为的实体各有一个 XState 状态机：角色按持续状态摆放、走向任务位置、做任务、待机活动、外出；
// 管道流动、空闲、停止。包裹、房间与设备不需要状态机。
// 世界的推进只把「这一步到了哪个状态」用 STATE 事件告诉机器，机器的当前值就是画面读取的状态。

import { assign, createMachine, type AnyStateMachine } from "xstate";
import type { CharacterMachineInput, PipeMachineInput } from "./types.ts";

/** 角色状态机的状态：外出、等待、走动、做事、待机、闲置。 */
export type CharacterStateName = "away" | "waiting" | "going" | "working" | "resting" | "choosing";

export interface CharacterMachineContext {
  id: string;
  department: string | null;
  roleKind: string;
  /** 进入当前状态的时刻（毫秒）。 */
  since: number;
}

/** 建立角色的状态机：初次进入 choosing（空闲的角色自己挑事情做）。 */
export function characterMachine(input: CharacterMachineInput): AnyStateMachine {
  return createMachine({
    id: `character:${input.id}`,
    initial: "choosing",
    context: { id: input.id, department: input.department, roleKind: input.roleKind, since: 0 },
    types: {} as { context: CharacterMachineContext; events: { type: "STATE"; value: CharacterStateName; at: number } },
    on: {
      STATE: {
        actions: assign({
          since: ({ event }) => event.at,
        }),
      },
    },
    states: {
      away: {},
      waiting: {},
      going: {},
      working: {},
      resting: {},
      choosing: {},
    },
  });
}

/** 角色当前状态（画面与测试读取）。 */
export function characterStateName(machine: { getSnapshot: () => { value: unknown } }): string {
  const value = machine.getSnapshot().value;
  return typeof value === "string" ? value : JSON.stringify(value);
}

/** 管道状态机的状态：流动、空闲、停止。 */
export type PipeStateName = "flowing" | "idle" | "stopped";

export interface PipeMachineContext {
  id: string;
  from: string;
  to: string;
  linkKind: string;
}

export function pipeMachine(input: PipeMachineInput): AnyStateMachine {
  return createMachine({
    id: `pipe:${input.id}`,
    initial: "idle",
    context: { id: input.id, from: input.from, to: input.to, linkKind: input.linkKind },
    types: {} as { context: PipeMachineContext; events: { type: "STATE"; value: PipeStateName; at: number } },
    states: {
      flowing: {},
      idle: {},
      stopped: {},
    },
  });
}

/** 管道当前状态。 */
export function pipeStateName(machine: { getSnapshot: () => { value: unknown } }): string {
  const value = machine.getSnapshot().value;
  return typeof value === "string" ? value : JSON.stringify(value);
}
