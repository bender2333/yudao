# 原型 v12 构建约定

本文件只写跟 [v11 BUILD.md](../v11/BUILD.md) 不一样的地方，其余照旧：v12 沿用 v11，v11 沿用 [v10 BUILD.md](../v10/BUILD.md)，v10 沿用 [v9 BUILD.md](../v9/BUILD.md)，v9 沿用 [v8 BUILD.md](../v8/BUILD.md)。画面与交互见 [design.md](design.md)。

命名随版本改名：v12 的全局对象是 `window.Y12`，CSS 类名以 `y12-` 开头，存储键以 `y12.` 开头，脚本是 `js/y12.js`，页面标题与顶栏的标签写「v12 原型」。前几版 BUILD.md 里出现的 `Y11`、`y11-`、`js/y11.js`（以及更早的 `Y10`、`Y9`、`Y8`）在 v12 读作 `Y12`、`y12-`、`js/y12.js`。验收脚本以 v9 为对照页面、v12 为被检查的页面（`checks/env.js` 的 `spaceOf`）。
