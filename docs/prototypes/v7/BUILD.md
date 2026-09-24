# 原型 v7 构建约定

本文件约定原型的文件结构、模块接口与示例数据形状，供并行制作原型的执行者使用。界面内容与规则以 [设计说明](design.md) 为准；两者不一致时以设计说明为准，并在本文件中修正。

## 1. 基本要求

- 浏览器直接打开 `index.html` 即可运行（`file://`），不需要编译、服务端口或外部脚本、外部字体、外部图片。
- 只用普通 `<script src>` 按顺序加载，不用 ES module（`file://` 下模块会被浏览器拦截）。
- 所有代码挂在全局对象 `window.Y7` 下，不再新增其他全局变量。
- 注释使用中文，术语保留英文，不过度注释。界面文字使用中文，用词遵守设计说明第 10 节与 `CONTEXT.md`。
- 页面顶部固定显示「原型示例数据」。
- 支持浅色与深色：颜色全部来自 `styles/base.css` 中 `:root` 的变量，使用 `light-dark()`（沿用 v6 的色板）。像素画面有自己的画面色板，两种主题下相同。
- 宽度 1440 与 390 两种情况下都可用：390 时左侧栏收为抽屉，标签可换行，表格改为卡片，页面不出现横向滚动条。
- 系统设置为减少动画（`prefers-reduced-motion: reduce`）时，像素画面停在当前状态对应的姿势，不做循环动画与移动动画。
- 出错时让错误直接出现在控制台，不用 try/catch 吞掉错误。

## 2. 文件结构与加载顺序

```
docs/prototypes/v7/
  index.html            外壳：左侧栏、顶栏、标签、内容区、浮动工具条；按下列顺序加载脚本
  design.md             设计说明
  BUILD.md              本文件
  styles/base.css       变量、布局、通用组件、窄屏规则、外壳与工具条
  styles/system.css     系统页的样式
  styles/project.css    概览、恢复、资料的样式
  styles/department.css 部门工作间、观测、设置的样式
  styles/gallery.css    动作图鉴的样式
  js/core.js            Y7 命名空间、路由、状态、事件总线、查询与命令注册、界面辅助函数、工具条、场景播放器
  js/data.js            全部示例数据与场景
  js/pixel/sprites.js   像素小人、物件与字体的点阵定义
  js/pixel/engine.js    画布渲染、动画循环、缓动与路径移动、事件到动作的对照表
  js/pixel/room.js      部门房间画面
  js/pixel/loop.js      循环画面
  js/views/shell.js     左侧栏、顶栏、标签、事项选择框
  js/views/overview.js  概览
  js/views/recovery.js  恢复与动作核实
  js/views/materials.js 资料
  js/views/department.js 部门工作间、部门设置弹窗
  js/views/observe.js   观测与请求详情
  js/views/settings.js  设置
  js/views/system.js    模型管理、运行与执行槽位、工具与扩展、元观察、三个预留入口
  js/views/gallery.js   动作图鉴
  js/main.js            启动：注册完成后渲染第一个页面
```

`index.html` 中样式与脚本的加载顺序与上表相同，`js/main.js` 最后加载。

每个文件只有一个负责者，其他人不修改：

| 负责者 | 文件 |
| --- | --- |
| 外壳与数据 | `index.html`、`styles/base.css`、`styles/system.css`、`js/core.js`、`js/data.js`、`js/views/shell.js`、`js/views/system.js`、`js/main.js` |
| 像素画面 | `js/pixel/*.js`、`js/views/gallery.js`、`styles/gallery.css` |
| 项目页面 | `js/views/overview.js`、`js/views/recovery.js`、`js/views/materials.js`、`styles/project.css` |
| 部门页面 | `js/views/department.js`、`js/views/observe.js`、`js/views/settings.js`、`styles/department.css` |

需要修改别人负责的文件时，在交付说明中写明需要的改动，由负责者修改。

## 3. core.js 接口

### 3.1 状态

```js
Y7.state = {
  level: 'now',          // 'now' | 's3' | 's4' | 's5'，阶段显示档位
  annotate: false,       // 标注模式
  route: { name, params, query }, // 由路由解析
  projectId: 'p-report', // 当前项目
  workItemId: null,      // 事项范围；null 表示整个项目
  drafts: {},            // 未提交的输入草稿，键为输入框标识
  scenario: { id: null, step: 0, playing: false }
};
Y7.LEVELS = ['now', 's3', 's4', 's5'];
Y7.LEVEL_LABELS = { now: '当前', s3: 'Stage 3 与 D24', s4: 'Stage 4', s5: 'Stage 5' };
Y7.atLeast(level)        // 当前档位是否不低于 level
```

### 3.2 事件总线

```js
Y7.bus.on(type, fn); Y7.bus.off(type, fn); Y7.bus.emit(type, payload);
```

总线上的类型：

- `route-changed`：路由变化后。
- `level-changed`、`annotate-changed`。
- `data-changed`：示例数据被命令或场景修改后，参数为修改的路径列表。
- `domain-event`：场景播放器发出的领域事件，参数为第 6 节的事件对象。

### 3.3 路由

- 路径形式见设计说明第 3.3 节。`Y7.go(hash)` 跳转；`Y7.router.current()` 返回 `{ name, params, query }`。
- 页面名称：`overview`、`dept`、`recovery`、`materials`、`observe`、`observe-detail`、`settings`、`sys-models`、`sys-runtime`、`sys-tools`、`sys-meta`、`sys-reserved`（参数 `which` 为 `nodes`、`evolution`、`lessons`）、`gallery`。
- 进入系统页时记录来源页面，`Y7.back()` 回到来源页面（D24 第 9.1 节「返回原界面」）。
- 查询参数 `w` 表示事项范围。

### 3.4 页面注册

```js
Y7.views.register('overview', {
  title: (ctx) => '概览',          // 顶栏路径最后一段
  render: (ctx) => htmlString,     // 返回内容区的 HTML
  mount: (ctx, root) => {},        // 可选：插入 DOM 后调用，用于创建画布画面、绑定事件
  update: (ctx, root, paths) => {},// 可选：data-changed 时调用；没有时整页重新渲染
  unmount: (ctx, root) => {}       // 可选：离开页面时调用，销毁画面
});
```

`ctx = { state, route, project, workItem, level }`，其中 `project`、`workItem` 为当前对象（没有时为 null）。

### 3.5 查询与命令

```js
Y7.queries.register(name, (params) => result);
Y7.query(name, params)            // 调用已注册的查询；未注册时抛出错误
Y7.commands.register(name, (params) => ({ ok, message, paths }));
Y7.command(name, params)          // 执行命令，修改 Y7.data，发出 data-changed，并用提示条显示 message
```

查询名称与设计说明第 7.1 节一致；命令名称使用第 7.2 节的中文名称对应的英文标识，在注册处用注释写出中文名称。各查询由使用它的页面文件注册：

| 注册者 | 查询 |
| --- | --- |
| `core.js` | `projects.list`、`project.overview` |
| `views/overview.js` | `project.loop`、`project.flow`、`work_item.inputs` |
| `views/recovery.js` | `run.recovery` |
| `views/materials.js` | `work_item.materials`、`semantic.records` |
| `views/department.js` | `department.workspace`、`run.actions`、`ops.status` |
| `views/observe.js` | `project.attempts`、`project.usage`、`run.attempt` |
| `views/settings.js` | `project.settings` |
| `views/system.js` | `catalog`、`runtime.slots`、`tools.registry`、`meta.observations` |

查询返回的内容必须来自 `Y7.data`，并按当前档位过滤：档位未到的字段不返回。

命令的注册者：

| 注册者 | 命令 |
| --- | --- |
| `core.js` | `createProject` 新建项目、`renameProject` 重命名、`pinProject` 置顶、`archiveProject` 归档、`restoreProject` 恢复项目、`recordMaterial` 记录原文、`createWorkItem` 新建事项、`addInput` 追加需求、`cancelWorkItem` 取消事项 |
| `views/recovery.js` | `resumeRun` 继续执行 |
| `views/overview.js` | `retrieveCandidate` 取回未采纳候选、`startIntegration` 以候选开始集成事项 |
| `views/department.js` | `sendGuidance` 发送部门指导、`saveDepartmentSettings` 保存项目部门设置、`authorizeOpsAction` 授权外部动作、`acceptResponsibility` 接收运行责任 |
| `views/settings.js` | `saveCommand` 登记与修改命令、`authorizeTool` 授权网络与工具、`approveOnce` 逐次批准、`saveRoleSettings` 保存角色设置 |
| `views/system.js` | 模型管理的全部命令（保存与删除 Provider 配置、连接测试、模型测试、获取模型列表、接受容量、保存编辑 JSON、导入、导出、保存与清除凭据、保存部门默认、保存角色默认）、`setSlots` 设置执行槽位数、`cancelQueued` 取消排队、`decideJudgment` 对判定作出决定 |

### 3.6 界面辅助函数

```js
Y7.esc(text)                                   // HTML 转义
Y7.ui.block({ level, tag, title, query, command, body, className, actions })
// 区块。level 未到时返回空字符串；tag 为显示的阶段标签，例如 '3.1'、'D24'、'Stage 4'；
// 标注模式打开时，在右上角显示「查询：… · 命令：… · 阶段：…」
Y7.ui.tag(text)                                // 阶段标签
Y7.ui.status(kind, text)                       // 状态标记；kind 见第 5.2 节，文字与图标同时显示
Y7.ui.table({ columns, rows, empty })          // 表格；窄屏时改为带字段名的卡片
Y7.ui.tabs({ id, items, active })              // 页签；items 为 { id, label, level }
Y7.ui.modal({ title, body, actions })          // 打开弹窗；Y7.ui.closeModal()
Y7.ui.toast(message)                           // 提示条
Y7.ui.empty(text)                              // 空状态
Y7.ui.time(iso)、Y7.ui.duration(sec)           // 时间与时长显示
```

事件委托：元素上的 `data-go="#/..."` 点击后跳转；`data-cmd="名称"` 点击后调用 `Y7.command(名称, 元素的 dataset)`；`data-act="名称"` 调用页面自己用 `Y7.actions.register(名称, (el, ev) => {})` 注册的处理函数。

### 3.7 浮动工具条与场景播放器

工具条固定在页面底部中央，与界面样式明显区分（深色胶囊、阴影），包括：阶段四档按钮、标注开关、场景选择、单步、播放或暂停、重置、当前事件说明（事件类型与中文说明）、「动作图鉴」链接、主题切换（跟随系统、浅色、深色）。

场景播放器：选择场景时把数据恢复到场景开始的状态（`Y7.data` 在启动时深拷贝保存一份初始数据），切换到场景指定的项目、事项与页面，档位低于场景要求时自动切到要求的档位。每一步先按 `patch` 修改数据并发出 `data-changed`，再发出 `domain-event`。连续播放时按每步的 `delay` 间隔推进。

## 4. 示例数据（data.js）

`Y7.data` 的形状如下。时间使用 ISO 字符串；所有字段名为英文，显示文字为中文。带 `level` 的对象或字段只在该档位及以上出现。

```js
Y7.data = {
  now: '2026-09-24T15:30:00+08:00',
  service: { restartedAt, pendingResumeCount },            // level s3

  projects: [{
    id, name, goal, pinned, archived,
    adoption: { version: 'r2', summary, adoptedAt } | null,
    workItemIds: []
  }],

  workItems: [{
    id, projectId, title, colorIndex,                       // colorIndex 0-5
    status,        // 'not_started'|'queued'|'in_progress'|'adopted'|'held'|'released_unsettled'|'stopped'
    runId,
    queuePos,      // level s3，排队中时的顺序
    heldReason     // level s3，未采纳候选的原因
  }],

  runs: [{
    id, workItemId, phase,   // 'PRODUCT_SPEC'|'ENGINEERING'|'DELIVERY'|'QUALITY'|'REWORK_PRODUCT'|'REWORK_ENGINEERING'|'DONE'|'PAUSED'|'FAILED'
    department,              // 当前部门 'product'|'engineering'|'quality'|'operations'|null
    cycle, startedAt, elapsedSec, limitSec,               // limitSec 默认 7200
    stopReason,              // 终态时的停止原因代码与中文说明 { code, text }
    recovery: {              // level s3
      state,                 // 'running'|'interrupted'|'pending_verification'|'waiting_resume'|'terminated'
      reason,                // 中文说明
      unusable: { department, model, problem } | null,    // 模型引用无法使用时
      lastConfirmed: { seq, text },
      canResume, resumeBlockedReason,
      owner: { id, since }, lateResults: [{ at, text }],
      verifications: [{ at, actionId, basis, result }],
      nextActions: [{ id, label }]
    },
    inputs: [{ version, kind, text, at, progress }],        // kind 'user'|'command'；progress 'received'|'assigned'|'accepted'
    flow: [{ seq, at, from, to, kind, content, status, eventId }],
    requests: [{ id, from, to, kind, question, status, answer }],
    guidance: [{ id, department, version, text, status, response, at }],
    messages: { product: [], engineering: [], quality: [], operations: [] },
                             // 每条 { seq, at, source: 'user'|'self'|'other', from, text, eventId }
    actions: [{              // 动作与回执
      id, department, role, tool, // tool: 'search'|'read_range'|'read_file'|'edit_range'|'write_file'|'run_command'|...
      summary, input,         // 输入依据的中文说明
      state,                  // level s3：'not_sent'|'done'|'unknown'；当前档位只有已完成的动作
      receipt: { command, argv, exitCode, output, truncated, timedOut, durationMs, snapshot } | null,
      before, after,          // level s3，前后快照摘要
      at
    }],
    contexts: { product: [], engineering: [], quality: [] },
                             // 每条 { id, at, sources: [{ label, version, included }] }
    prompts: { product: { configVersion, requestVersion, text }, engineering: {…}, quality: {…} },
    effectiveModel: {        // level s3（D24）
      product: { definition, connection, protocol, source: '项目设置'|'部门默认', level, sentLevel, unusable }, …
    },
    roles: {                 // level s4
      engineering: [{ id, name, kind, status, model, task }], …
                             // kind 'manager'|'architect'|'developer'|'explorer'|'tester'
                             // status 'idle'|'assigned'|'working'|'returned'|'failed'|'away'
    },
    ledger: {                // level s4
      engineering: { items: [{ id, text, assignee, status, result }], facts: [], questions: [], progress: [] }, …
    },
    attempts: [{
      id, logicalCallId, department, role, n, of, status,  // 'preparing'|'requesting'|'running'|'succeeded'|'failed'|'cancelled'
      startedAt, durationMs, provider, requestedModel, actualModel,
      usage: { input, output, cacheRead, total, cost } ,    // 未上报的项为 null，不写 0
      error: { category, code, http, text } | null,
      target: { connection, protocol, baseUrl, model, window, maxOutput, credentialRef, source, requestLevel, sentLevel, promptVersion }, // level s3
      semanticUnits: []      // level s4
    }]
  }],

  materials: [{ id, projectId, workItemId, kind, version, title, text, at, files, verdict }],
                             // kind 'intend'|'prd'|'plan'|'delivery'|'qa'|'note'；delivery 带 files: [{ path, bytes }]

  semantic: {                // level s4
    'p-report': { units: [{ id, type, scope, text, status, source, supersededBy, reason, at }],
                  conflicts: [{ a, b, text }],
                  dataflow: [{ id, label, ok, missing: [] }] }
  },

  projectSettings: {
    'p-report': {
      departments: { product: { model, level, promptVersion, promptText }, … },  // model 与 level 为 level s3
      roles: { engineering: [{ roleId, model, level, promptText }] },          // level s4
      commands: [{ name, argv, args, timeoutSec, outputLimit, version }],      // level s3 显示入口
      tools: [{ id, label, scope, approval }]                                  // level s3
    }
  },

  catalog: {                 // D24，level s3；当前档位使用 current 字段表示现有实现的模型页
    presets: { revision, source, schemes: [{ id, name, protocols: [{ protocol, baseUrl }], modelsUrl, docsUrl }] },
    connections: [{ id, name, scheme, protocol, baseUrl, credentialRef, timeoutSec, modelsUrl }],
    definitions: [{ id, connectionId, upstreamModel, window, maxOutput,
                    reasoning: { levels: [], defaultLevel, method } | null,
                    capacityAccepted,
                    admission: { testedAt, actualModel, protocol } | null }],
    candidates: { [connectionId]: { source, collectedAt, ids: [], unknownReason } },
    credentials: [{ ref, state: 'missing'|'memory'|'env'|'dotenv', note }],
    departmentDefaults: { product: { definition, level }, engineering: {…}, quality: {…} },
    roleDefaults: { … },     // level s4
    current: { … }           // 现有实现的数据，供「当前」档显示现有模型页
  },

  runtime: {                 // level s3
    slots: { total: 3, used: [{ workItemId, department, role }] },
    queue: [{ workItemId, since, position }],
    restartNote
  },

  tools: {                   // level s3
    network: { scope, recent: [{ at, url, workItemId, result }] },
    mcp: [{ id, name, tools: [{ name, recovery, retry }] }],
    hooks: [{ id, name, effect }], observers: [{ id, name, scope }]
  },

  ops: {                     // level s5
    'p-shift': { responsibility: { version, env, acceptedAt, owner },
                 releases: [{ version, adoptionDigest, releaseDigest, at, state }],
                 incidents: [{ id, title, steps: [{ label, state, at }], workItemId }],
                 indicators: [{ label, value, numerator, denominator, window }],
                 pendingActions: [{ id, kind, target, reason, requestedAt }] }
  },

  meta: {                    // level s5
    flowStats: [{ label, count, avgIntervalSec }],
    findings: [{ id, projectId, workItemId, rule, text, at }],
    judgmentPoints: [{ id, question, calibrated, lastResult, probability, confidence, route }],
    pendingDecisions: [{ id, judgmentPointId, question, options }]
  },

  scenarios: [ /* 第 6.2 节 */ ]
};
```

### 4.1 示例内容

| 项目 | 事项 | 内容 |
| --- | --- | --- |
| `p-report` 文本报表工具（代码项目） | `w-base` 建立基线（已采纳 r1）、`w-sum` 按类别汇总（已采纳 r2）、`w-cat` 类别按首次出现顺序输出（进行中，工程，第 3 轮）、`w-empty` 空输入时给出提示（s3 起排队中）、`w-head` 表头改为中文（s3 起为未采纳候选，基线已变） | 工程的动作包括搜索、按区间阅读、按区间编辑、执行登记命令 `unit_tests` 与 `report_categorized`（一次退出 1，修改后退出 0）；s4 起工程有工程经理、工程架构师、开发者、工程探索者 |
| `p-cargo` 货物装载规划 | `w-weight` 超重箱子单独列出 | 当前档为工程进行中；s3 起为待核实：`run_command unit_tests` 已开始、没有回执，结果未知 |
| `p-lab` 实验记录助手 | `w-export` 导出 CSV | 当前档为执行失败（`provider_error`，HTTP 401）；s3 起为待恢复：质检部门，模型 `mimo-v2.5`（Provider 配置 `opencode-go-chat`），凭据被上游拒绝 |
| `p-shift` 门店排班（level s5） | `w-timeout` 排班页面加载超时（产品，运维提出） | 已采纳 r3 并在运行；故障链路进行到「修复进入事项」 |

模型目录示例：Provider 配置 `opencode-go-responses`（OpenCode Go，Responses）、`opencode-go-chat`（OpenCode Go，Chat Completions）、`local-custom`（自定义，Chat Completions，`http://127.0.0.1:8080/v1`，无需凭据）；模型访问定义包括 `mimo-v2.5`、`glm-5`、`kimi-k2.6` 等，其中一个只有候选、一个准入已作废。

## 5. 像素画面接口

### 5.1 画面对象

```js
const room = Y7.pixel.createRoomScene(canvas, { department, level });
room.setModel(roomModel);   // 状态驱动：灯光、角色、姿势、牌子
room.playEvent(event);      // 事件驱动：播放一次性动作，播放完回到 setModel 给出的状态
room.resize();              // 容器尺寸变化时调用
room.destroy();

const loop = Y7.pixel.createLoopScene(canvas, { level });
loop.setModel(loopModel);
loop.playEvent(event);
loop.focus(workItemId);     // null 取消聚焦
loop.resize(); loop.destroy();

Y7.pixel.EVENT_ACTIONS       // 事件类型到动作名称的对照表，内容与设计说明第 6.3 节一致
Y7.pixel.ACTIONS             // 动作名称到 { label, fact, level } 的说明，供动作图鉴使用
Y7.pixel.renderSprite(canvas, spriteId, action, frame) // 动作图鉴用的单个小人渲染
```

画布的逻辑尺寸：房间 480×240，循环画面 640×300。按容器宽度取整数倍缩放，小于 1 倍时按比例缩小；处理 `devicePixelRatio`；`imageSmoothingEnabled = false`。画面下方由页面提供同样内容的文字列表（窄屏与读屏使用）。

### 5.2 模型

```js
roomModel = {
  department, level,
  status,        // 'idle'|'working'|'asking'|'paused'|'failed'|'done'|'cancelled'|'interrupted'|'pending_verification'|'waiting_resume'
  crt: { target, model, protocol, status, cycle },
  roles: [{ id, name, kind, status, task }],  // 当前与 s3 档只有一个 kind 'agent'；运维为 'ops'
  pose: { roleId, action } | null,            // 持续动作，例如 'typing'
  door: '已暂停' | '中断' | '待恢复' | … | null,
  holdCard: '凭据被上游拒绝：OPENCODE_GO_KEY' | null,
  pendingTool: 'run_command' | null,          // 待核实时闪烁的物件
  mailbox: 0,                                 // 未读指导数量
  summaries: 0                                // 摘要档案盒编号
};

loopModel = {
  level,
  items: [{ id, title, colorIndex, status, department, cycle, elapsedSec, limitSec, queuePos }],
  // status: 'queued'|'running'|'asking'|'paused'|'failed'|'done'|'cancelled'|'interrupted'|'pending_verification'|'waiting_resume'|'adopted'|'held'
  focusId,
  slots: { total, used },
  shelves: { adopted: ['r1', 'r2'], held: [{ id, label }] },
  openRequests: [{ from, to, workItemId }],
  ops: { running, alarm, version } | null,        // level s5
  observer: { active, last: { result, confidence } } | null   // level s5
};
```

### 5.3 状态标记的种类

`Y7.ui.status(kind, text)` 的 `kind`：`running`、`queued`、`asking`、`paused`、`failed`、`done`、`cancelled`、`interrupted`、`pending`（待核实）、`waiting`（待恢复）、`adopted`、`held`、`released`、`candidate`、`admitted`、`unusable`、`unknown`。每种有自己的图标与颜色，文字始终显示。

## 6. 领域事件与场景

### 6.1 事件对象

```js
{ seq, type, at, projectId, workItemId, department, role, tool, label, payload }
```

`label` 是一句中文说明，工具条显示它。`type` 取值：

- 事件库中已有的：`user_input_received`、`work_item_created`、`department_activated`、`context_assembled`、`model_requested`、`model_request_serialized`、`model_stream_progress`、`model_attempt_finished`、`model_retry_scheduled`、`model_attempt_failed`、`tool_started`、`tool_called`、`tool_skipped`、`proposal_submitted`、`proposal_rejected`、`spec_accepted`、`contract_accepted`、`plan_accepted`、`delivery_accepted`、`qa_submitted`、`collaboration_requested`、`collaboration_responded`、`collaboration_closed`、`department_guidance_received`、`department_guidance_applied`、`department_guidance_responded`、`compaction_recorded`、`compaction_failed`、`transition`、`run_paused`、`run_failed`、`run_done`、`deliverable_adopted`、`adoption_held`。
- 原型临时名称（以 `x_` 开头，事件名由对应工作包的设计确定）：`x_run_interrupted`、`x_action_unknown`、`x_waiting_resume`、`x_resume_accepted`（3.1）；`x_queued`、`x_slot_acquired`、`x_queue_cancelled`（3.4A）；`x_role_task_assigned`、`x_role_result_returned`、`x_explorer_fetch`、`x_replanned`、`x_semantic_recorded`（Stage 4）；`x_ops_released`、`x_ops_alarm`、`x_ops_action_requested`（Stage 5 运维）；`x_judgment_recorded`（Stage 5 元观察）。

`transition` 的 `payload` 为 `{ from, to, artifact }`，`artifact` 取 `prd`、`box`、`defect`、`release`。`qa_submitted` 的 `payload.verdict` 取 `release`、`rework_engineering`、`rework_product`。

### 6.2 场景

```js
{ id, name, level, projectId, workItemId, view: 'overview'|'dept'|'recovery', department,
  steps: [{ delay: 1200, event: { … }, patch: [{ path: 'runs.0.recovery.state', value: 'interrupted' }] }] }
```

`patch.path` 用点号分隔，数组下标用数字；也可以用 `runs[id=r-cat].department` 的形式按 `id` 找对象。场景共 12 个：正常循环、返工、询问与回答、部门指导、压缩、中断与待核实、模型不可用与继续执行、并行排队、采纳竞争、部门内多角色、运维故障、元观察判定。每个场景 8 到 20 步，覆盖设计说明第 5.2 与 6.3 节中对应的事实。

## 7. 测试

- 用 Playwright（安装在会话临时目录，不写入仓库）打开 `index.html` 的每个页面，在 1440×900 与 390×844 两种尺寸、浅色与深色两种主题下截图，并收集控制台错误；控制台错误必须为零。
- 每个场景从头播放到最后一步，截图检查画面变化，控制台错误为零。
- 检查 390 宽度下 `document.documentElement.scrollWidth <= 390`。
- 检查四档切换后各页面都能渲染，档位未到的区块不出现。
