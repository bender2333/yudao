// 项目页面读写真实数据的共用部分（原型 v8 设计说明第 3 至 7 节，工单 #80）。
// 查询经视图同步发出：立即读取一次快照，相关事件到达时按能力清单声明的种类重新查询；
// 命令经 ClientApp 提交，接受以后显示「已提交」，快照出现新内容以后恢复，拒绝时显示原因。

import { useCallback, useEffect, useRef, useState } from "react";
import type { ClientApp } from "../../contract/client-app";
import { type CommandProblem } from "../../contract/command-problem.ts";
import { newCommandId } from "../../contract/command-id.ts";

export type SnapshotState<T> = {
  data: T | null;
  loading: boolean;
  // 这次读取失败时的原因；null 表示没有失败（工单 #728）。
  // 有这个字段，界面才能把「读不出来」与「本来就没有内容」分开说。
  error: string | null;
};

// 一处视图在当前参数下页面能看到什么（纯函数，单元测试直接调用）：
// 参数为 null 或 undefined 时不发送（查询按省略处理），key 就是去掉它们以后的参数签名；
// skip 为真时这一处视图没有打开（例如项目还没有事项，department.workspace 缺事项标识），
// 没有打开就没有读取：加载状态为假，调用处据此显示空态，不显示「正在读取数据」（工单 #295 第 3 项）。
// 参数变了以后、新快照到达之前仍算读取中，且上一处（别的项目、别的事项）的数据不能接着用，
// 否则调用处会拿它去发下一次查询（换项目以后用旧事项标识发查询会被服务端按找不到拒绝）
export function snapshotView<T>(
  state: { data: T | null; loading: boolean; error: string | null; key: string | null },
  key: string,
  skip: boolean,
): SnapshotState<T> {
  if (skip) {
    return { data: null, loading: false, error: null };
  }
  if (state.key !== key) {
    return { data: null, loading: true, error: null };
  }
  return { data: state.data, loading: state.loading, error: state.error };
}

// 打开一个视图：viewId 唯一标识这一处数据；skip 为真时不打开
export function useSnapshot<T>(
  app: ClientApp | null,
  viewId: string,
  query: string,
  params: Record<string, unknown>,
  skip = false,
): SnapshotState<T> {
  const key = JSON.stringify(params, (_name, value) => (value === null || value === undefined ? undefined : value));
  const [state, setState] = useState<{ data: T | null; loading: boolean; error: string | null; key: string | null }>(
    { data: null, loading: true, error: null, key: null },
  );

  useEffect(() => {
    const views = app?.viewSync ?? null;
    if (!views || skip) {
      return;
    }
    setState({ data: null, loading: true, error: null, key });
    void views.open<T>(viewId, { query, params: JSON.parse(key) as Record<string, unknown> }, (data) => {
      setState({ data, loading: false, error: null, key });
    }, (reason) => {
      // 查询失败（例如服务不可达）：读取结束，不一直显示「正在读取数据」；
      // 失败的原因带出来（工单 #728），调用处据此说「读不出来」而不是「本来就没有内容」
      setState({ data: null, loading: false, error: reason, key });
    });
    return () => {
      views.close(viewId);
    };
  }, [app, viewId, query, key, skip]);

  return snapshotView(state, key, skip);
}

// 一条命令的提交状态（工单验收：提交后显示「已提交」，事件到达以后显示最终状态，拒绝时显示原因）
export type CommandState = {
  busy: boolean;
  submitted: boolean;
  // 命令没有成功时页面上要显示的那句话的来源（工单 #740）：三种形状由 contract/command-problem.ts 给出
  problem: CommandProblem | null;
  // 最近一次被接受时应用层带回的受理回执（例如保存部门设置带回的建议能力提醒）
  accepted: Record<string, unknown> | null;
  submit: (name: string, body: Record<string, unknown>) => Promise<boolean>;
};

// dataKey 是本页数据的签名：快照出现新内容以后清除「已提交」提示，改由数据本身显示最终状态
export function useCommand(app: ClientApp | null, dataKey: string): CommandState {
  const [busy, setBusy] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [problem, setProblem] = useState<CommandProblem | null>(null);
  const [accepted, setAccepted] = useState<Record<string, unknown> | null>(null);
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
        setProblem({
          kind: "rejected",
          rejection: { command_id: "", reason: "not_allowed", message: "尚未连接控制主机", current_version: null },
        });
        return false;
      }
      setBusy(true);
      setProblem(null);
      try {
        const outcome = await app.command(name, { command_id: newCommandId(), ...body });
        if (outcome.ok) {
          setSubmitted(true);
          setAccepted(outcome.accepted);
          return true;
        }
        setProblem(outcome.problem);
        return false;
      } catch {
        // 命令调用本身抛出（连接断了、命令名字不在能力清单里）：也给用户一句说明，
        // 不留一个空的错误框（工单 #740）
        setProblem({ kind: "failed", status: 0 });
        return false;
      } finally {
        setBusy(false);
      }
    },
    [app],
  );

  return { busy, submitted, problem, accepted, submit };
}

// 命令被拒绝以后给用户的去处（工单 #319 第 6 项）：部门没有选模型时给两个地方，
// 一处是全系统的部门默认，一处是这个项目的部门设置；其余拒绝原因不给去处
export function rejectionLinks(problem: CommandProblem | null, projectId: string): { label: string; hash: string }[] {
  if (problem === null || problem.kind !== "rejected" || problem.rejection.reason !== "provider_unavailable") {
    return [];
  }
  return [
    { label: "去模型管理页设置部门默认", hash: "/sys/models" },
    { label: "在本项目的设置页选择模型", hash: `/p/${projectId}/settings` },
  ];
}
