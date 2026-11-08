// 事件种类的来源：接口描述（画面与播放 docs/design/visualization.md「翻译层」、测试分层
// docs/design/test-pyramid.md「前端与浏览器测试」；工单 #1419）。
//
// 画面要认的事件种类取自接口：运行时的来源是能力清单的 event_types（view/src/shell.ts），
// 测试里的来源是同一份接口描述（harness/tests/openapi/openapi.json）。服务端不为画面维护
// 事件种类的清单或夹具；画面的作业本来就在接口描述改了时运行。
//
// 这不是产品代码：只在 view/tests/unit 下被测试文件共用。

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));

/** 接口描述的位置：服务端每次改接口合同时重写的那一份（harness/tests/test_openapi_snapshot.py 核对）。 */
export const INTERFACE_DESCRIPTION = resolve(here, "..", "..", "..", "harness", "tests", "openapi", "openapi.json");

/** 接口描述里的事件种类：EventObject 的 discriminator.mapping 的键（服务端的事实种类，按字母序）。 */
export function eventTypesFromInterface(path: string = INTERFACE_DESCRIPTION): string[] {
  const document = JSON.parse(readFileSync(path, "utf8")) as {
    components?: { schemas?: { EventObject?: { discriminator?: { mapping?: Record<string, string> } } } };
  };
  const mapping = document.components?.schemas?.EventObject?.discriminator?.mapping;
  if (mapping === undefined) {
    throw new Error(`接口描述里没有事件种类：${path} 的 components.schemas.EventObject.discriminator.mapping`);
  }
  const types = Object.keys(mapping);
  if (types.length === 0) throw new Error(`接口描述里的事件种类是空的：${path}`);
  return types;
}
