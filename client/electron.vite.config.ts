// electron-vite 的构建配置：主进程、预加载与渲染进程三段（对照 OpenCode 桌面版 0027387
// packages/desktop/electron.vite.config.ts）。渲染进程的输入是 src/renderer/index.html。

import react from "@vitejs/plugin-react";
import { defineConfig } from "electron-vite";

export default defineConfig({
  main: {
    build: {
      rollupOptions: { input: { index: "src/main/index.ts" } },
    },
  },
  preload: {
    build: {
      rollupOptions: {
        input: { index: "src/preload/index.ts" },
        output: { format: "cjs", entryFileNames: "[name].js" },
      },
    },
  },
  renderer: {
    root: "src/renderer",
    plugins: [react()],
    build: {
      rollupOptions: { input: { index: "src/renderer/index.html" } },
    },
  },
});
