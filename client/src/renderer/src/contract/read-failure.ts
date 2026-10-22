// 读取失败的说明（工单 #728）：查询失败时服务端给的说明按原文带出来，界面才能把它与「本来就没有内容」分开。
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

/** 读取失败时给用户的一句（失败的原因原样带出）。 */
export function readFailureText(error: string): string {
  return `读取失败：${error}`;
}

/**
 * 空态文案：读不出来时给失败提示，读出来且为空时给原来的空态文案。
 * 判据是「这个查询本来应该有内容吗」——本来就该是空的（还没有项目时）仍然写空态。
 */
export function emptyOrFailureText(error: string | null, empty: string): string {
  return error === null || error === "" ? empty : readFailureText(error);
}
