// 项目页面读写真实数据的共用部分（原型 v8 设计说明第 3 至 7 节，工单 #80）。
// 查询经视图同步发出：立即读取一次快照，相关事件到达时按能力清单声明的种类重新查询；
// 命令经 ClientApp 提交，接受以后显示「已提交」，快照出现新内容以后恢复，拒绝时显示原因。

import { useCallback, useEffect, useRef, useState } from "react";
import type { Rejected } from "../../api/generated/types.gen";
import type { ClientApp } from "../../contract/client-app";

export type SnapshotState<T> = {
  data: T | null;
  loading: boolean;
};

// 打开一个视图：viewId 唯一标识这一处数据；参数为 null 或 undefined 时不发送（查询按省略处理）；
// skip 为真时不打开，用于还没有事项标识的场合（切换事项以后丢弃迟到的结果）
export function useSnapshot<T>(
  app: ClientApp | null,
  viewId: string,
  query: string,
  params: Record<string, unknown>,
  skip = false,
): SnapshotState<T> {
  const key = JSON.stringify(params, (_name, value) => (value === null || value === undefined ? undefined : value));
  const [state, setState] = useState<{ data: T | null; loading: boolean; key: string | null }>(
    { data: null, loading: true, key: null },
  );

  useEffect(() => {
    const views = app?.viewSync ?? null;
    if (!views || skip) {
      return;
    }
    setState({ data: null, loading: true, key });
    void views.open<T>(viewId, { query, params: JSON.parse(key) as Record<string, unknown> }, (data) => {
      setState({ data, loading: false, key });
    });
    return () => {
      views.close(viewId);
    };
  }, [app, viewId, query, key, skip]);

  // 参数变了以后、新快照到达之前，页面拿到的是空数据：上一处（别的项目、别的事项）的数据不能接着用，
  // 否则调用处会拿它去发下一次查询（换项目以后用旧事项标识发查询会被服务端按找不到拒绝）
  if (skip || state.key !== key) {
    return { data: null, loading: true };
  }
  return { data: state.data, loading: state.loading };
}

// 一条命令的提交状态（工单验收：提交后显示「已提交」，事件到达以后显示最终状态，拒绝时显示原因）
export type CommandState = {
  busy: boolean;
  submitted: boolean;
  rejection: Rejected | null;
  submit: (name: string, body: Record<string, unknown>) => Promise<boolean>;
};

// dataKey 是本页数据的签名：快照出现新内容以后清除「已提交」提示，改由数据本身显示最终状态
export function useCommand(app: ClientApp | null, dataKey: string): CommandState {
  const [busy, setBusy] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [rejection, setRejection] = useState<Rejected | null>(null);
  const lastKey = useRef(dataKey);

  useEffect(() => {
    if (lastKey.current !== dataKey) {
      lastKey.current = dataKey;
      setSubmitted(false);
    }
  }, [dataKey]);

  const submit = useCallback(
    async (name: string, body: Record<string, unknown>): Promise<boolean> => {
      if (!app) {
        setRejection({ command_id: "", reason: "not_allowed", message: "尚未连接控制主机", current_version: null });
        return false;
      }
      setBusy(true);
      setRejection(null);
      try {
        const outcome = await app.command(name, { command_id: globalThis.crypto.randomUUID(), ...body });
        if (outcome.ok) {
          setSubmitted(true);
          return true;
        }
        setRejection(outcome.rejection);
        return false;
      } finally {
        setBusy(false);
      }
    },
    [app],
  );

  return { busy, submitted, rejection, submit };
}

// 命令被拒绝时的说明：基准版本过期时提示重新读取（工单验收第 3 条）
export function rejectionLabel(rejection: Rejected): string {
  if (rejection.reason === "stale_base") {
    const version = rejection.current_version === null || rejection.current_version === undefined
      ? "未知"
      : rejection.current_version;
    return `${rejection.message}（服务端当前版本 ${version}），请重新读取以后提交`;
  }
  return `${rejection.message}（原因 ${rejection.reason}）`;
}
