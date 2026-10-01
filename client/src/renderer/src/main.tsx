// 渲染进程的入口：挂载 React 应用。

import { createRoot } from "react-dom/client";
import { App } from "./app";
// 像素字体：Fusion Pixel 是自带中文字形的像素字体（OFL），像素画面与图鉴统一用它
import "@fontsource/fusion-pixel-10px-proportional-sc/400.css";
import "./styles.css";

const container = document.getElementById("root");
if (container === null) {
  throw new Error("找不到根元素 #root");
}
createRoot(container).render(<App />);
