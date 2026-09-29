# 原型 v9 构建约定

本文件只写跟 [v8 BUILD.md](../v8/BUILD.md) 不一样的地方。第 1 节（基本要求）、第 4 节（档位）、第 5 节（接口层／示例后端）、第 6 节（界面层：路由、`kit.js`、决定卡片）、第 8 节（示例数据的登记方式与形状、世界设定、跨文件标识、截图）、第 9 节（场景）、第 10 节（测试）、第 11 节（交付）跟 v8 完全相同，直接照抄 v8 对应文件，不重新写一遍；`js/contract/`、`js/ui/`（像素画面以外）、`styles/` 全部原样搬过来，一个字符都不改。变的只是第 2、3、7 节：像素引擎内部从"一个部门一个角色、按状态切姿势"改成实体—组件—系统。

## 1. 分层（对照 v8 BUILD.md 第 2 节）

```mermaid
flowchart TB
    subgraph UI["界面层 js/ui（跟 v8 完全相同，不改）"]
        App["app.js、shell.js、views/*、cards.js、replay.js、scenes.js、toolbar.js"]
    end
    subgraph Pixel["像素画面 js/pixel"]
        Ecs["ecs.js：实体、组件、系统（新增）"]
        Floor["floor.js：项目楼层（改写为调用 ecs.js）"]
        Room["room.js：部门房间（改写为调用 ecs.js）"]
        Building["building.js：楼与机房（改写为调用 ecs.js）"]
        Engine["engine.js：画布、动画循环、缓动、粒子、共用画法（跟 v8 完全相同，不改）"]
    end
    App -->|"setModel(query 结果) · playEvent(事件)"| Floor
    App -->|"同上"| Room
    App -->|"同上"| Building
    Floor -->|"声明房间与管道 · 派发事件"| Ecs
    Room -->|"同上"| Ecs
    Building -->|"同上"| Ecs
    Ecs -->|"actor、画布原语"| Engine
```

`floor.js`、`room.js`、`building.js` 对外的 `setModel`/`playEvent`/`resize`/`destroy` 接口跟 v8 完全一样（第 7.2 至 7.4 节的函数签名不变），界面层不知道下面换了引擎，这是这次改造唯一要守住的边界。

## 2. 文件结构与负责者（对照 v8 BUILD.md 第 3 节）

```
docs/prototypes/v9/            由 docs/prototypes/v8/ 整份复制而来
  js/pixel/ecs.js               新增：实体、组件、系统、房间与管道的图结构声明、任务派发、对话框
  js/pixel/engine.js            原样保留
  js/pixel/sprites.js           原样保留
  js/pixel/room.js              改写：调用 ecs.js，不再是原地叠临时姿势
  js/pixel/floor.js             改写：调用 ecs.js，不再是 layoutFor/pipesFor 写死坐标
  js/pixel/building.js          改写：楼层小人的待机行为改用 ecs.js 的待机系统，机房不变（机房本来就没有"一部门一角色"的问题，见第 7.4 节）
  其余文件                      原样保留
```

`index.html` 的脚本加载顺序在 `pixel/sprites.js` 之后、`pixel/room.js` 之前插入 `pixel/ecs.js`。

负责者：

| 负责者 | 文件 |
| --- | --- |
| 架构师 | `BUILD.md`、`js/pixel/ecs.js`、`js/pixel/floor.js`、`js/pixel/building.js` |
| 任务 R 部门房间 | `js/pixel/room.js`（按第 7.2 节改写，调用架构师写好的 `ecs.js`） |
| 任务 T 任务目录与场景复核 | 第 3.3 节的任务目录表（新文件 `js/pixel/tasks.js`）、十九个场景逐一复核（截图对比 v8，行为不一致时登记，不擅自改画法） |
| 任务 A1／A2／A3／B／C／D（除像素房间外）／E | 跟 v8 完全相同的负责范围，不需要重新做（v8 的交付原样保留） |

v8 的 `docs/prototypes/v8/` 整份复制到 `docs/prototypes/v9/` 作为起点，任务 R、T 与架构师只改上表列出的文件。

## 3. 像素引擎（`ecs.js`）

### 3.1 实体与组件

四种实体，每种实体是一个普通对象，字段就是它的组件：

```js
// 角色：一个部门当前只有一个（跟 v8 相同，Stage 5 的部门内多角色不在这一版引入）
{ kind: 'character', id, department, spot: {x, y}, facing, queue: [task…], current: task | null, bubble: {text, kind, until} | null }

// 包裹：PRD 卷轴、交付箱、返工单、放行单、信件；创建时生成，采纳或归档时销毁
{ kind: 'package', id, workItemId, colorIndex, artifact, atRest: {roomId, spotKind} | null, transit: {linkKey, from, progress, ms} | null }

// 房间：由第 3.2 节的声明生成，运行时加上算好的位置
{ kind: 'room', id, label, roomKind, x, y, w, desk, inPort, outPort, door }

// 管道：由第 3.2 节的声明生成
{ kind: 'pipe', id, from, to, linkKind, pts }
```

`P.ecs.world()` 建一个世界，持有这四类实体的集合；`world.rooms`、`world.pipes`、`world.characters`、`world.packages` 各是一个按 `id` 索引的 map。

### 3.2 房间与管道的声明

```js
P.ecs.declareRooms(world, [
  { id: 'hall', label: '大厅', roomKind: 'hall' },
  { id: 'product', label: '产品', roomKind: 'dept' },
  { id: 'engineering', label: '工程', roomKind: 'dept' },
  { id: 'quality', label: '质检', roomKind: 'dept' },
  { id: 'library', label: '成果库', roomKind: 'shelf' },
  { id: 'operations', label: '运维', roomKind: 'dept', optional: true }
], { hasOps });

P.ecs.declareLinks(world, [
  { from: 'hall', to: 'product', kind: 'handoff' },
  { from: 'product', to: 'engineering', kind: 'handoff' },
  { from: 'engineering', to: 'quality', kind: 'handoff' },
  { from: 'quality', to: 'library', kind: 'handoff' },
  { from: 'quality', to: 'product', kind: 'return' },
  { from: 'product', to: 'engineering', kind: 'tube' },
  { from: 'engineering', to: 'quality', kind: 'tube' },
  { from: 'product', to: 'quality', kind: 'tube' },
  { from: 'library', to: 'operations', kind: 'handoff', optional: true },
  { from: 'operations', to: 'machine_room', kind: 'handoff', optional: true },
  { from: 'operations', to: 'hall', kind: 'return', optional: true }
]);
```

`declareRooms` 按声明顺序从左到右排布（沿用 v8 `floor.js` 的常量：`TOP`、`ROOM_B`、`DESK_Y`、`PORT_STAND`、每个房间宽 110、大厅宽 100，与 v8 现在的画面像素级一致），`optional: true` 的房间在对应开关为假时不生成。`declareLinks` 按 `kind` 对应的路由规则（`handoff`/`tube` 走水平线，`return` 走天花板）算出折线，`from`/`to` 引用 `declareRooms` 里的 `id`；两条声明的顺序不能颠倒（先房间后管道）。这两个函数替换 v8 `floor.js` 里的 `layoutFor`/`pipesFor`，v9 阶段声明的内容与 v8 现在画出来的完全一致，用来验证"排布能不能从声明生成"，不引入新房间。

### 3.3 任务目录

一份任务定义表，替代 v8 `floor.js` 的 `restFor`/`tempWorker` 与 v8 design.md 第 5.4、8.3 节两张表的角色：

```js
P.ecs.TASKS = {
  // 键取自驱动它的事件类型；一个事件类型可能对应多种任务，用 payload 再分支（例如 qa_submitted 按 verdict）
  model_requested: { label: '打字', spot: 'desk', pose: 'type', bubble: 'think' },
  tool_started_search: { label: '翻找资料', spot: 'cabinet', pose: 'read_sit', bubble: 'say' },
  tool_started_run_command: { label: '执行登记命令', spot: 'terminal', pose: 'pull', bubble: 'say' },
  qa_submitted_release: { label: '放行', spot: 'inspect', pose: 'stamp_green', bubble: 'say' },
  // …按 v8 design.md 第 8.3 节逐行补全，任务 T 的工作范围
};
```

`spot` 是房间里的一个命名位置（`desk` 工位、`cabinet` 文件柜、`terminal` 终端、`inspect` 检验台、`port_in`/`port_out` 管道口……），由 `declareRooms` 生成房间时一并算出具体坐标（沿用 v8 `floor.js` 里 `desk`、`inPort`、`outPort` 的算法）。`bubble` 为 `'say'` 时头顶显示说话气泡、内容为 `label`（模型请求类任务在流式输出到达时用事件的 `payload.text` 逐字追加，覆盖默认的 `label`）；为 `'think'` 时不在当前任务上显示气泡，只在存在下一个已知任务时对下一项显示思考气泡；不出现在这张表里的事件类型按第 3.4 节归为信号，不生成任务。

### 3.4 系统

```js
P.ecs.dispatch(world, event)    // 事件到达：查 TASKS，命中则向 event.department 对应角色的 queue 追加一个任务；否则按 v8 design.md 5.4 节的规则更新房间/管道的信号字段（不经过 queue）
P.ecs.stepCharacters(world, dt) // 每帧调用：角色 current 为空且 queue 非空时取队首为 current；current 有 spot 时走向该位置，到达后播放 pose；current 完成（一次性动作播完，或者收到"完成"事件）时清空 current；current 为空且 queue 为空时执行待机行为（沿用 v8 5.4 节第一行：坐在工位偶尔起身走动）
P.ecs.stepPackages(world, dt)   // 每帧调用：transit 不为空的包裹沿 pts 移动，到达终点时 atRest，transit 置空
P.ecs.bubbleFor(character)      // 返回当前应显示的气泡（第 3.3 节规则），供渲染读取，不改变任何状态
```

`stepCharacters`、`stepPackages` 只读 `world` 的状态往下推进，不产生新的事实；一个域事件必须先经过 `dispatch` 变成任务或者信号，`stepCharacters`/`stepPackages` 才会有反应，两者之间没有另一条路径。

### 3.5 渲染

`ecs.js` 不新增画布原语，画一个实体时按它当前的组件值调用 `engine.js` 已有的函数（`P.drawActor`、`paint.chair`、`paint.desk`、`P.drawBitmap`、`drawPipe` 的画法不变，只是把"这条管道通不通"的判断从"两端有没有活跃事项"改成"这条管道上有没有 `transit` 不为空的包裹"）。`floor.js`、`room.js`、`building.js` 在各自的 `draw()` 里遍历 `world.rooms`/`world.pipes`/`world.characters`/`world.packages`，调用画法，不直接操作 `scene.actors`（角色对应的 `scene.actor` 由 `ecs.js` 内部维护，跟 v7/v8 的做法一样复用 `scene.addActor`/`scene.run`）。

## 4. 验收

跟 v8 BUILD.md 第 10 节相同的检查（九档 × 页面 × 两种宽度 × 两种主题控制台错误为零，十九个场景全部播放完），额外加一条：同一批截图跟 v8 的截图逐页对比，房间位置、管道走向、小人外形、颜色不应该有肉眼可见的差异——这一版验证的是"背后从快照加动画换成实体与任务队列，画面看起来不变"，不是"画面变好看"。
