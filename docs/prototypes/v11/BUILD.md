# 原型 v11 构建约定

本文件只写跟 [v10 BUILD.md](../v10/BUILD.md) 不一样的地方，其余（以及 v10 BUILD.md 引用的 [v9 BUILD.md](../v9/BUILD.md) 各节）照旧。画面与交互见 [design.md](design.md)。

命名随版本改名：v11 的全局对象是 `window.Y11`，CSS 类名以 `y11-` 开头，存储键以 `y11.` 开头，脚本是 `js/y11.js`，页面标题与顶栏的标签写「v11 原型」。v10 BUILD.md 里出现的 `Y10`、`y10-`、`js/y10.js` 在 v11 读作 `Y11`、`y11-`、`js/y11.js`。验收脚本以 v9 为对照页面、v11 为被检查的页面（`checks/env.js` 的 `spaceOf`，与 v10 的验收脚本同一份对照页面）：这一版只改部门房间的两条规则（见 design.md 第 2 节），楼、机房与项目楼层的静止画面与 v9 仍然逐像素相同。

## 1. 房间的两条规则在代码里的位置

- `js/pixel/room.js` 的 `transition`：收件方在动作开始时说话。
- `js/pixel/room.js` 的 `KEEP_ACTIONS` 与 `keepPending`：交接与盖章先做完；状态类动作排在它们后面，普通的排队动作仍然清掉。
- `js/pixel/room.js` 的 `setModel`：房间进入停止态时清队，交接与盖章与状态类动作保留。
- `js/pixel/room.js` 的 `update`：交接与盖章在做的时候不打断排队里的动作。

## 2. 录制的重新生成

房间的调用录制在客户端一侧（`client/scripts/record-room-calls.mjs`），这一版按 v11 的页面重新录：`node client/scripts/record-room-calls.mjs --write`。原型的 `checks/record.js` 录的是楼层的调用序列，楼层没有变化，照旧。
