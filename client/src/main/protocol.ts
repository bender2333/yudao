// yudao:// 协议的注册（docs/architecture-issues.md 中 #76 条目的处理，参照 OpenCode 0027387
// packages/desktop/src/main/windows.ts:22-45）：界面在开发与发布时都经注册的 yudao:// 协议加载，
// 页面的来源固定为 yudao://app，接口层的 CLIENT_ORIGINS 只放行这一个来源。

import { net, protocol } from "electron";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

export const RENDERER_SCHEME = "yudao";
export const RENDERER_HOST = "app";
export const RENDERER_ORIGIN = `${RENDERER_SCHEME}://${RENDERER_HOST}`;

// 渲染进程构建产物的根目录（electron-vite 输出到 out/renderer）
export const rendererRoot = join(__dirname, "../renderer");

// 必须在 app ready 之前登记：secure 与 standard 让页面按普通来源处理，来源才是 yudao://app
protocol.registerSchemesAsPrivileged([
  { scheme: RENDERER_SCHEME, privileges: { secure: true, standard: true, supportFetchAPI: true } },
]);

// ready 之后把请求映射到构建产物：yudao://app/ → out/renderer/index.html
export function serveRendererProtocol(): void {
  protocol.handle(RENDERER_SCHEME, (request) => {
    const url = new URL(request.url);
    const pathname = url.pathname === "/" || url.pathname === "" ? "/index.html" : url.pathname;
    return net.fetch(pathToFileURL(join(rendererRoot, pathname)).toString());
  });
}
