// 部门房间中的「阅读已有项目」动作（3.8，设计第 3.3 节）：建档事项里产品、工程与质检三个部门读取
// 代码快照时，房间中出现这个动作；它由 read_file、search 与 read_range 三种工具的 tool_started
// 事件驱动，不另设事件。房间的画面数据（部门状态、姿势与位置）由部门房间画面（#177）承担，
// 这里给出动作本身的内容与来源事实。
//
// 动作有两个来源（设计第 3.4 节：状态以查询为准）：页面打开以后发生的读取由事件订阅给出，
// 页面打开以前已经发生的读取由 run.actions 的动作列表读出。只靠订阅的话，页面在读取结束以后
// 打开就永远停在空态（工单 #332 的第一条用例）。

import { useEffect, useState } from "react";
import type { EventObject, RunActionsResult, WorkItemCard } from "../../api/generated/types.gen";
import type { ClientApp } from "../../contract/client-app";
import { Section } from "./common";
import { lastReadExistingAction, readExistingAction, type ReadAction } from "./onboarding";
import { departmentName, formatTime } from "./labels";
import { useSnapshot } from "./use-snapshot";

// 一次「阅读已有项目」的观察：工具、部门、开始时间与事件位置
export type ReadExistingCall = ReadAction & {
  position: number;
};

/** 从事件流里取出当前事项的「阅读已有项目」动作（纯函数，单元测试直接调用）。 */
export function readExistingCall(event: EventObject, runId: string | null): ReadExistingCall | null {
  const tool = readExistingAction(event);
  if (tool === null || runId === null || event.run_id !== runId) {
    return null;
  }
  return { tool, at: event.at, position: event.position, department: event.department };
}

/** 部门房间的「阅读已有项目」动作：显示这次 run 最近一次读取；还没有读取时写明由什么驱动。 */
export function ReadExisting(props: { app: ClientApp; runId: string | null; item: WorkItemCard | null }) {
  // 页面打开以前已经发生的读取：这次 run 的动作列表（run.actions）
  const history = useSnapshot<RunActionsResult>(
    props.app, "page.dept.read_existing", "run.actions", { run_id: props.runId ?? "" }, props.runId === null,
  );
  const [last, setLast] = useState<ReadExistingCall | null>(null);

  useEffect(() => {
    setLast(null);
    return props.app.subscribeEvents((event) => {
      const call = readExistingCall(event, props.runId);
      if (call !== null) {
        setLast(call);
      }
    });
  }, [props.app, props.runId]);

  if (props.item === null || props.item.kind !== "onboarding") {
    return null;
  }

  const recorded = lastReadExistingAction(history.data?.actions ?? []);
  const current: ReadAction | null = last === null ? recorded
    : recorded === null || last.at >= recorded.at ? last : recorded;

  return (
    <Section
      title="阅读已有项目"
      note="建档事项里部门读取代码快照的动作"
    >
      {current === null ? (
        <p className="y9-note note">这个部门还没有开始读取代码快照。</p>
      ) : (
        <p className="y9-note room-action" role="status">
          {departmentName(current.department)}正在阅读已有项目：工具 {current.tool}，开始于 {formatTime(current.at)}
        </p>
      )}
    </Section>
  );
}