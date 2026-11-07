// 渲染进程的入口：挂载 React 应用。

import { createRoot } from "react-dom/client";
import { App } from "./app";
import "./styles.css";

const container = document.getElementById("root");
if (container === null) {
  throw new Error("找不到根元素 #root");
}
createRoot(container).render(<App />);
