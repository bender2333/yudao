// 资料页读到的内容：读不出来与「本来就没有内容」要分开说（工单 #714）。
// 读取层给出的是「这一处有没有读到」（工单 #728 带出来的失败信息）；读到以后内容为空是另一件事，
// 由调用处按内容自己说。两者在页面上是两句不同的话。

/** 一次读取的结果：读取中、读不出来、读成功但没有数据、读到了。 */
export type ReadView<T> =
  | { kind: "loading" }
  | { kind: "failed"; reason: string }
  | { kind: "empty" }
  | { kind: "ready"; data: T };

/** 一次读取的结果：失败与空分开。 */
export function readView<T>(state: { data: T | null; loading: boolean; error: string | null }): ReadView<T> {
  if (state.error !== null) {
    return { kind: "failed", reason: state.error };
  }
  if (state.data === null) {
    return state.loading ? { kind: "loading" } : { kind: "empty" };
  }
  return { kind: "ready", data: state.data };
}

/** 一段原文的显示：读取中、读不出来、没有原文、有原文。 */
export type OriginalView =
  | { kind: "loading" }
  | { kind: "failed"; reason: string }
  | { kind: "empty" }
  | { kind: "content"; text: string };

/**
 * 一段原文的显示：pick 从读到的数据里取出原文，取不出（空）时是「没有原文」，
 * 读不出来时是「读取失败」——两者不是同一句话（工单 #714）。
 */
export function originalView<T>(
  state: { data: T | null; loading: boolean; error: string | null },
  pick: (data: T) => string,
): OriginalView {
  const view = readView(state);
  if (view.kind !== "ready") {
    return view;
  }
  const content = pick(view.data);
  return content === "" ? { kind: "empty" } : { kind: "content", text: content };
}
