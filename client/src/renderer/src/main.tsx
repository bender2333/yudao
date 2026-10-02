// 渲染进程的入口：挂载 React 应用。

import { createRoot } from "react-dom/client";
import { App } from "./app";
import { installDevMount } from "./pixel/floor/dev-mount";
// 像素字体：Fusion Pixel 是自带中文字形的像素字体（OFL），像素画面与图鉴统一用它
import "@fontsource/fusion-pixel-10px-proportional-sc/400.css";
import "./styles.css";

const container = document.getElementById("root");
if (container === null) {
  throw new Error("找不到根元素 #root");
}
createRoot(container).render(<App />);

// 开发构建里的像素画面测试入口：把项目楼层画面用给定的数据挂到一个独立容器上，供端到端测试
// 直接驱动世界、卡片与点击（对应原型 checks/behaviors.js 的运行方式）。生产构建里这一段被去掉。
if (import.meta.env.DEV) {
  installDevMount();
}
