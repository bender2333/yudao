// 画面的构建（画面与播放 docs/design/visualization.md「搬出：画面成为单独的应用」的构建与发布一节；
// 网页界面的提供与发布 docs/design/web-interface-and-release.md「接口层提供页面文件」）。
// 构建结果是一组静态文件：Yudao 服务在服务地址下的 /view/ 按文件路径提供它们，
// 画面与页面同一来源，读接口不需要跨来源。
//
// 构建的基路径是 /view/：入口页面的脚本与样式写的是 /view/ 下的绝对路径，发布时整组文件放进
// 发布资源目录的 view/ 子目录，服务按文件路径返回。开发服务器与画面的测试用根路径 /，
// 它们直接按 /src/… 取画面自己的模块。

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig(({ command }) => ({
  base: command === "build" ? "/view/" : "/",
  plugins: [react()],
  build: {
    outDir: "out",
    emptyOutDir: true,
  },
}));
