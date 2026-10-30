// 导出一次运行的证据（工单 #814）：运行详情页的「导出这次运行」按需读取 run.export 查询，
// 在内存里组出整包文件并触发浏览器的下载，用户拿到文件以后不再需要打开接口。
// 组名与组包的纯函数在 contract/run-export.ts；这里只负责查询、下载与失败原因的呈现。

import type { ClientApp } from "../../contract/client-app";
import { runExportBlob, runExportFileName, type RunExportData } from "../../contract/run-export.ts";
import { failureReason } from "../../contract/read-failure.ts";

/** 一次导出的结果：成功带文件名（页面上说明导出了什么），失败带给用户看的原因 */
export type RunExportOutcome =
  | { ok: true; fileName: string }
  | { ok: false; reason: string };

/** 触发浏览器下载的入口：放在对象层，单元测试替换它核对交给浏览器的东西 */
export type SaveFile = (blob: Blob, fileName: string) => void;

// 真正的下载：建临时链接，点一下，随后释放这次的对象地址
function saveWithAnchor(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  anchor.click();
  URL.revokeObjectURL(url);
}

/**
 * 读取 run.export 并把整包下载为 JSON 文件。
 * 文件名带事项与 run 的标识（事项标题由调用处按 project.overview 解析后传入，
 * 标题缺失时回退到整包里的事项任务与事项标识）。
 */
export async function downloadRunExport(
  app: ClientApp,
  runId: string,
  workItemTitle: string | null | undefined,
  saveFile: SaveFile = saveWithAnchor,
): Promise<RunExportOutcome> {
  try {
    const { data } = await app.queryOne<RunExportData>("run.export", { run_id: runId });
    const fileName = runExportFileName(data, workItemTitle);
    saveFile(runExportBlob(data), fileName);
    return { ok: true, fileName };
  } catch (error) {
    return { ok: false, reason: failureReason(error) };
  }
}
