// 画面的入口（画面与播放 docs/design/visualization.md「搬出：画面成为单独的应用」）。
// 第一张把画面层、翻译层与图鉴搬进 view/，构建与测试随之独立；楼、楼层与房间三个场景接上
// 画面的壳在第二张做，入口那时换成壳。这里先挂图鉴页：它是画面的整页，按声明表画出全部公开画法，
// 不需要接口，构建与打开都能验证画面自己的画法（工单 #176）。

import { createRoot } from "react-dom/client";
import { GalleryPage } from "./gallery";

const container = document.getElementById("root");
if (container === null) {
  throw new Error("找不到根元素 #root");
}
createRoot(container).render(<GalleryPage />);
