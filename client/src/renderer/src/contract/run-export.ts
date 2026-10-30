// run.export 查询的合同侧（工单 #814）：文件名与文件组装抽成纯函数，单元测试直接调用。
// 查询本身由生成的客户端提供（queryRunExport / app.queryOne），这里只负责拿到结果以后
// 组出用户拿得到的那个文件：文件名带事项与 run 的标识，内容是 run.export 给出的整包。
// 整包不含上下文与封存树：封存树里的文件另走 delivery.file 逐个读取（工单正文）。

/** run.export 查询返回的整包（生成的 RunExportResult 的窄化形状） */
export type RunExportData = {
  run_id: string;
  projection: Record<string, unknown>;
  events: Record<string, unknown>[];
  attempts: Record<string, unknown>[];
  usage: Record<string, unknown>;
};

/** 文件名里放得下的部分：去掉在文件名里不允许出现的字符，空白换成连字符 */
function fileNamePart(value: string): string {
  return value.replace(/[\r\n\t\\/:*?"<>|]+/g, "-").replace(/\s+/g, " ").trim();
}

/** run 标识的短写：run_ 后面的 16 位十六进制取前 8 位；形状不符时原样保留 */
export function shortRunId(runId: string): string {
  const match = /^run_([0-9a-f]+)$/.exec(runId);
  if (match === null) {
    return runId;
  }
  return `run-${match[1].slice(0, 8)}`;
}

/** 文件名里的事项部分：标题带事项标识，标题缺失时用事项标识；两者都没有时省略 */
export function workItemPart(title: string | null | undefined, workItemId: string | null | undefined): string {
  const name = fileNamePart(title ?? "").replace(/^[-.]+|[-.]+$/g, "");
  if (name !== "") {
    return `${name}_${workItemId ?? ""}`;
  }
  const id = fileNamePart(workItemId ?? "").replace(/^[-.]+|[-.]+$/g, "");
  return id;
}

/**
 * 导出文件的名称：事项在前（用户按事项找文件），run 的短标识在后（同一次运行重新导出时覆盖），
 * 扩展名 .json。事项与 run 的信息都缺失时仍是合法文件名（run-export.json）。
 */
export function runExportFileName(
  data: Pick<RunExportData, "run_id" | "projection">,
  workItemTitle: string | null | undefined,
): string {
  const projection = data.projection ?? {};
  const workItemId = typeof projection.work_item_id === "string" ? projection.work_item_id : null;
  const item = workItemPart(workItemTitle ?? (typeof projection.task === "string" ? projection.task : null), workItemId);
  const run = shortRunId(data.run_id);
  const parts = [item, run].filter((part) => part !== "");
  return `${parts.length === 0 ? "run-export" : parts.join("-")}.json`;
}

/** 整包的文件内容：缩进 2 的 JSON，字段按 run.export 返回的原样给出 */
export function runExportJson(data: RunExportData): string {
  return JSON.stringify(data, null, 2);
}

/** 整包作为文件：文本内容转成 UTF-8 字节的 JSON 文件（Blob 由调用处保存或交给下载入口） */
export function runExportBlob(data: RunExportData): Blob {
  return new Blob([runExportJson(data)], { type: "application/json" });
}
