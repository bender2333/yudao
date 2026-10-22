// 读取失败的说明与处理（工单 #728、#777）：查询失败时服务端给的说明按原文带出来，
// 界面才能把它与「本来就没有内容」分开。
// 页面不自己造中文说明：拿到什么显示什么（2026-10-22 的决定「页面直接显示原始标识与原文，不再要求翻译」）。

/** 服务端的错误体里的说明：文本直接用，对象取 error 或 detail 字段，再没有就把整个原文写出来。 */
function failureDetail(error: unknown): string {
  if (typeof error === "string") {
    return error.trim();
  }
  if (error === null || error === undefined) {
    return "";
  }
  if (typeof error === "object") {
    const record = error as Record<string, unknown>;
    for (const key of ["error", "detail", "message"]) {
      const value = record[key];
      if (typeof value === "string" && value.trim() !== "") {
        return value.trim();
      }
    }
    return JSON.stringify(error);
  }
  return String(error);
}

/**
 * 查询失败时的一句话：服务端给了说明就带上它的原文，没有就写清是哪个查询没有返回数据。
 * 这是事实，不是对原因的猜测——失败的原因由服务端说。
 */
export function queryFailureText(name: string, error: unknown): string {
  const detail = failureDetail(error);
  return detail === "" ? `查询 ${name} 没有返回数据` : `查询 ${name} 没有返回数据：${detail}`;
}

/**
 * 读取失败时给用户的一句（失败的原因原样带出）。
 */
export function readFailureText(error: string): string {
  return `读取失败：${error}`;
}

/**
 * 失败的原因：服务端给的原文优先；没有原文就写清这次读取没有成功。
 * 「读不出来」与「本来就没有内容」是两句话（工单 #728、#777）——空的原因不能写成空串，
 * 空串到了界面上与「没有失败」分不开。
 */
export function failureReason(error: unknown): string {
  if (error instanceof Error) {
    return error.message.trim() === "" ? "这次读取没有成功" : error.message.trim();
  }
  const detail = failureDetail(error);
  return detail === "" ? "这次读取没有成功" : detail;
}

/**
 * 一次按需读取：读成了就把结果交给调用处，读不出来就把失败原因交给调用处——
 * 失败有去处，不产生未处理的拒绝（工单 #777）。
 * 服务整体不可达由连接层说明（页面写「正在重新连接」），这里只说这次读取没有成功。
 */
export function optionalRead<T>(
  read: Promise<T>,
  onSuccess: (value: T) => void,
  onFailure: (reason: string) => void,
): void {
  void read.then(onSuccess, (error: unknown) => onFailure(failureReason(error)));
}

/**
 * 空态文案：读不出来时给失败提示，读出来且为空时给原来的空态文案。
 * 判据是「这个查询本来应该有内容吗」——本来就该是空的（还没有项目时）仍然写空态。
 */
export function emptyOrFailureText(error: string | null, empty: string): string {
  return error === null || error === "" ? empty : readFailureText(error);
}
