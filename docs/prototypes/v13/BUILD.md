# 原型 v13 构建约定

本文件只写跟 [v12 BUILD.md](../../archive/prototypes/v12/BUILD.md) 不一样的地方，其余照旧：v13 沿用 v12，依次往前。画面与交互见 [design.md](design.md)。

命名随版本改名：v13 的全局对象是 `window.Y13`，CSS 类名以 `y13-` 开头，存储键以 `y13.` 开头，脚本是 `js/y13.js`，页面标题与顶栏的标签写「v13 原型」。前几版 BUILD.md 里的 `Y12`、`y12-`、`js/y12.js` 在 v13 读作 `Y13`、`y13-`、`js/y13.js`。

## 1. 脚本顺序与目录

`index.html` 在 `js/pixel/engine.js`、`ecs.js` 之后加载：

| 脚本 | 内容 |
| --- | --- |
| `js/pixel/timeline.js` | 播放时间线：`P.timeline.create`（含 `rate()`：限时演完的关键动作要求画面时间加快的倍率）、`P.timeline.settings`（落后上限、最短时长、倍率） |
| `js/pixel/contract.js` | 画面合同的取值表与校验：`P.contract` |
| `js/pixel/say.js` | 只管怎么画气泡（说什么由翻译层写） |
| `js/pixel/floor-decl.js`、`room-decl.js`、`building-decl.js` | 三张声明表：级别与最短时长 |
| `js/translate/say.js`、`translate.js`、`sources.js` | 翻译层：说话目录、状态与动作的翻译、动作图鉴要用的两张说明表 |

`js/pixel/` 不引用 `Y13.pixel`、`Y13.LEVELS` 以外的 Y13 成员（`checks/playback.js` 核对）。

## 2. 画面的接口

| 场景 | 创建 | 接口 |
| --- | --- | --- |
| 项目楼层 | `P.createFloorScene(canvas, opts)` | `setState(s)`、`jump(s)`、`play(a)`、`setDecisions(list)`、`stream(who, text)`、`focus(id)`、`setOverlay(id, data)`、`openFact(kind)`、`inspect()`、`destroy()` |
| 部门房间 | `P.createRoomScene(canvas, { department })` | `setState(s)`、`jump(s)`、`play(a)`、`stream(who, text)`、`inspect()`、`destroy()` |
| 楼 | `P.createBuildingScene(canvas, opts)` | `setState(s)`、`jump(s)`、`play(a)`、`inspect()`、`destroy()` |
| 机房 | `P.createMachineRoomScene(canvas, opts)` | 同楼，另有 `highlight(ids)` |

v12 的 `setModel`、`playEvent` 删除。`opts` 的回调：`onDecide`、`onGo`、`onDoorClick`、`onSeek`、`describe(position)`（来源卡片的事件说明，代替 v12 的 `fetchEvent`）、`onFloorClick`、`onMachineClick`。

`ecs.js`：`ECS.enqueue` 不再有队列上限与 `front`、`must`；`ECS.dispatch(world, action, make)` 吃画面合同的动作；新增 `ECS.doerOf`、`ECS.peerOf`、`ECS.dropAction`（时间线立刻结束一个普通动作或跳到最新时去掉它的任务与包裹）、`ECS.progressOf`；`world.catalog` 不再有 `keyOf`。

`engine.js`：场景多了 `scene.wallT`（真实经过的时间，三个场景的播放时间线用它做时钟）与 `scene.rate`（画面时间相对真实时间的倍率，默认 1，楼层与房间每帧取 `tl.rate()`）；每帧把画面时间分成不超过 50 毫秒的小段推进，倍率为 1 时与原来相同。

页面一侧（`js/ui/scenes.js`）：`mountBuilding`、`mountMachineRoom`、`mountFloor`、`mountRoom`；`buildingStates(at)`；`panels()`。`pixelEvents`、`playOn`、`buildingModels` 删除。`js/ui/app.js` 收到事件时先交给页面的画面（事件翻成动作，进时间线），再按事件刷新查询。

## 3. 场景与工具条

场景总数由 23 增加到 25，都在 `data/p-metro.js`：

| 编号 | 场景 | 档位 |
| --- | --- | --- |
| 24 | 短时间内大量事件堆积 | S5 |
| 25 | 标签页在后台放几分钟以后切回 | S5 |

场景的步骤多一种 `burst`（同一刻到达的一批事件）。`js/contract/backend.js` 的检查认 `event`、`burst`、`act` 与带 `label` 的跳转。

工具条：「模拟」里多一项「标签页在后台」（`P.hidden`，画面的时钟停住；取消勾选时挂着的画面跳到最新）；多一个「节奏」按钮，打开调节面板（落后上限、最短时长、时长倍率与读数，设置存在 `y13.playback`）。

## 4. 测试

环境变量与 v12 相同（`PLAYWRIGHT_PATH`、`CHROMIUM_EXE`）；输出目录是 `.tmp/v13-checks/`。

| 脚本 | 通过的条件 |
| --- | --- |
| `timeline.js` | 不开浏览器：播放时间线的规则（排队、状态等动作、时长、丢弃、合并、缩短、强制上画面、跳到最新、倍率），含四组确定种子的堆积下的 H8 与 H9 |
| `playback.js` | H3（画面层不导入 Yudao 的代码）、翻译覆盖、三个场景的 H8 与 H9、调节面板、状态等动作、实时内容不等、跳到最新、页面上的场景 24 与 25 |
| `scenarios.js` | 二十五个场景全部按步骤播到最后一步，零错误 |
| `behaviors.js` | 沿用 v12 的全部检查，调用形状改为经过翻译层的画面合同（检查文件里的适配函数 `adaptFloor`、`adaptRoom`、`adaptBuilding`） |
| `record.js` + `replay.js` | 在 v12 上录制，回放给 v12 与 v13（v13 经翻译层），时钟与小人的动画计时固定。每段录制的最后一个检查点（时间线放空以后）与 v12 逐像素、逐个小人相同；中间的检查点（事件刚演的时候、静置以后）与 v13 自己的基线（`.tmp/v13-checks/replay-golden/`，`--rebaseline` 生成）相同。`--free-anim` 不固定动画计时，用来看与 v12 的差异是否只在动画相位 |
| `identity-building.js`、`walkers.js` | 楼与机房与 v9 逐像素相同；楼里小人的走位 |
| `matrix-home.js`、`matrix-floor.js` | 照旧，零错误、没有横向溢出 |
| `life.js`、`sheets.js` | 事件过程的截图联系表与截图联系表：`life.js` 默认对 v13 回放（录制的查询结果与事件经翻译层再交给画面），`--root` 指向 v12 时用 v12 的调用形状；零页面错误 |
