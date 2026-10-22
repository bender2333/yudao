// 请求详情里的工件引用（工单 #745）：四项工件引用是对象（种类、内容摘要、工件路径、媒体类型），
// 不是文字。页面按实际情况显示：有引用时给出可核对的标识（内容摘要的十六进制前 12 位，
// 没有摘要时给工件路径），真的没有这一项引用时写「未上报」，有引用但取不出标识时写「取不出」。
// 「未上报」只留给真的没有上报的情况，不再盖住「取不出来」这种情况。
// 纯函数，界面与单元测试都直接调用。

export const NOT_REPORTED = "未上报";
export const UNREADABLE = "取不出";

// 内容摘要显示的位数：只显示前 12 位十六进制，完整值由事件与工件路径给出
const DIGEST_LENGTH = 12;

// 内容摘要的十六进制部分：内容摘要是「sha256:十六进制」，界面只显示十六进制，
// 不显示算法前缀，也就没有英文标识
function digestText(value: unknown): string {
  if (typeof value !== "string") {
    return "";
  }
  const trimmed = value.trim();
  const hex = trimmed.startsWith("sha256:") ? trimmed.slice("sha256:".length) : trimmed;
  if (!/^[0-9a-f]+$/.test(hex)) {
    return "";
  }
  return hex.slice(0, DIGEST_LENGTH);
}

// 一项工件引用的显示：有引用给可核对的标识，没有引用写「未上报」，
// 引用在但取不出标识写「取不出」
export function artifactRefText(value: unknown): string {
  if (value === null || value === undefined) {
    return NOT_REPORTED;
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed === "" ? NOT_REPORTED : trimmed;
  }
  if (typeof value !== "object" || Array.isArray(value)) {
    return UNREADABLE;
  }
  const ref = value as Record<string, unknown>;
  const digest = digestText(ref.content_hash);
  if (digest !== "") {
    return `内容摘要 ${digest}`;
  }
  const path = typeof ref.path === "string" ? ref.path.trim() : "";
  if (path !== "") {
    return `工件路径 ${path}`;
  }
  return UNREADABLE;
}

// 详情页「引用」这一行的内容：四项工件引用各有各的显示，缺哪一项就写哪一项没有，
// 不把四项一起写成「未上报」
export function artifactRefsText(value: unknown): string {
  const refs = typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
  return [
    `请求 ${artifactRefText(refs.request)}`,
    `响应 ${artifactRefText(refs.response)}`,
    `原始流 ${artifactRefText(refs.events)}`,
    `用量 ${artifactRefText(refs.usage)}`,
  ].join("，");
}

// 详情页里「引用」这一行：名称与内容。界面直接用它，单元测试也直接调用它
export function artifactRefsRow(value: unknown): [string, string] {
  return ["引用", artifactRefsText(value)];
}
