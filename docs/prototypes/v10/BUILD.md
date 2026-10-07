# 原型 v10 构建约定

本文件只写跟 [v9 BUILD.md](../v9/BUILD.md) 不一样的地方，其余（以及 v9 BUILD.md 引用的 [v8 BUILD.md](../v8/BUILD.md) 各节）照旧。画面与交互见 [design.md](design.md)。

命名随版本改名：v10 的全局对象是 `window.Y10`，CSS 类名以 `y10-` 开头，存储键以 `y10.` 开头，脚本是 `js/y10.js`，页面标题与顶栏的标签写「v10 原型」。v9 BUILD.md 里出现的 `Y9`、`y9-`、`js/y9.js` 在 v10 读作 `Y10`、`y10-`、`js/y10.js`。验收脚本以 v9 为对照页面、v10 为被检查的页面（`checks/env.js` 的 `spaceOf`）。

## 1. 档位

```js
Y10.LEVELS = ['ui', '3.1', '3.2C', '3.4A', '3.8', '3.2B', '3.2D', 'pilot', 'S4', 'S5'];
Y10.LEVEL_LABELS.pilot = '自举试点';
Y10.LEVEL_TAGS.pilot = '试点';
```

三处都要加（`js/y10.js`）。`checks/matrix-home.js`、`checks/matrix-floor.js` 写死的档位数组同样加上 `pilot`。注意 `backend.js` 的 `resolveTree` 会删掉值为合法档位的 `level`、`until` 键，数据里其他含义的 `level` 字段不能取 `pilot`。

## 2. 接口层（示例后端）

### 2.1 登记（`js/contract/registry.js`）

| 种类 | 名称 | 档位 | 说明 |
| --- | --- | --- | --- |
| 查询 | `acceptance.coverage` | `3.2D` | 可回放 |
| 查询 | `run.loops` | `pilot` | 可回放 |
| 覆盖层 | `loops` | `pilot` | 依赖 `run.loops` |
| 覆盖层 | `sources` | `pilot` | 依赖 `project.loop`（事实元素的来源事件由它给出） |
| 覆盖层 | `coverage` | `pilot` | 依赖 `acceptance.coverage` |

事件种类的登记增加来源种类：每个已登记的事件种类对应 `rule`、`decision_model`、`role_statement`、`host_measurement`、`user` 之一（个别种类按载荷区分时写成函数）。对应的原则：

- `rule`：控制核心与流程编排的判断——交接、采纳、停止与结算、决定请求的发出、排队与槽位。
- `host_measurement`：主机执行与测量得到的——检查与命令的回执、工具的结果、已用时间、心跳、机器上线下线、结果未知的核实。
- `role_statement`：部门提交与说出的——PRD、计划、交付说明、质检结论、询问与回答、模型的输出、角色任务的结果。
- `user`：用户的命令——新要求、决定的回答、指导、设置的修改。
- `decision_model`：判定点（`S5` 档的证据核对），载荷带 `probability`。

`backend.js` 的 `validate` 增加一项：每个已登记的事件种类都有来源种类。

### 2.2 事件对象

`strip()` 的字段列表增加 `source`，档位达到 `pilot` 时由登记表给出，日志条目上不写；未到 `pilot` 时事件对象没有这个字段。

### 2.3 查询的结果

`run.loops`，请求 `{ project_id }`：

```js
{
  project: Instance,                       // 项目循环，一个项目一个
  items: [{ work_item_id, title, color_index, instances: [Instance] }]
}
// Instance
{
  id, parent,                              // parent 为上一层实例的 id，项目循环为 null
  layer: 'project' | 'run' | 'activation' | 'step',
  label,                                   // 例如「工程 · 第 3 次激活」「工程 · 步骤循环」
  department, role,                        // run 与项目循环为 null
  round,                                   // 当前或最后一轮
  used: [{ name, value, limit, unit, at_bound }],
  state: 'converging' | 'stalled' | 'oscillating' | 'drifting' | 'at_bound' | 'not_judged',
  missing,                                 // state 为 not_judged 时：缺少的事实与开始判定的阶段，其余为 null
  stop_reason,                             // 已停止时的停止原因，其余为 null
  measure: { name, series: [{ round, value, position }] } | null,   // 进展度量每一轮的数值与给出它的事件位置
  basis                                    // 判定依据的一句话，例如「最近 3 轮未满足数 2 → 2 → 2 不变，交付的树摘要在变」
}
```

`acceptance.coverage`，请求 `{ project_id, work_item_id? }`：

```js
{ items: [{
  work_item_id, snapshot,                  // 当前交付快照的摘要
  criteria: [{ id, text, method, result, open, position }],
  // method：command_check | trial_case | host_measurement | judgement | human | open
  // result：pass | fail | not_run；open 为 true 表示没有可执行的检验
  covered, total, model_read, open_count,
  release: { position, ratio } | null      // 最近一次放行与它的覆盖比例
}] }
```

`project.loop`（`pilot` 档起）：事项增加 `refs: { round, time, sign }`，停放的包裹、质检的盖章、成果库的箱子各带 `ref`，值是给出这条事实的事件位置。

`home.away_report`（`pilot` 档起）：汇总项增加两项，形状与现有汇总项相同（`label`、`count`、`refs`），另带明细：收敛状态的变化 `changes: [{ work_item_id, title, layer, from, to, position }]`；带开环条件的放行 `releases: [{ work_item_id, title, open: [{ id, text }], position }]`。

质检材料（`3.2D` 档起）：QAReview 增加 `criteria: [{ criterion, text, method, result, checks, trial_cases, note }]`，`copyMaterial` 透传。

### 2.4 处理函数

`run.loops`、`acceptance.coverage` 写在 `js/contract/handlers/project.js`；`home.away_report` 的两项写在 `handlers/core.js`；数据来自种子与事件补丁（v8 BUILD.md 第 5.5 节）。收敛状态按 [design.md](design.md) 第 8.1 节与[循环与收敛设计说明](../../design/loops-and-convergence.md)第 5 节由事件折叠得到；示例数据可以把序列写进种子，但状态、依据与 `missing` 由处理函数按规则算出，不在种子里写死。

## 3. 界面层

| 文件 | 改动 |
| --- | --- |
| `js/ui/scenes.js` | `overlayData` 增加 `loops`、`sources`、`coverage` 三支；楼层的点击回调增加 `onSeek(position)`（时间轴跳到这条事件） |
| `js/pixel/floor.js` | `drawOverlay` 增加三个覆盖层的画法（design.md 第 3、5.2、6.1 节）；每帧收集事实元素 `facts: [{ kind, rect, position, source }]`，供覆盖层「来源」、点击与验收脚本（`inspect()`）使用；点击顺序为决定卡片、决定板、通往机房的门、事实元素 |
| `js/pixel/source-card.js` | 新增：来源卡片，写法照 `decision-card.js`（`P.createSourceCard(scene, canvas, { onSeek, fetchEvent })`，`open(fact)`、`openList(title, rows)`、`close`、`isOpen`、`draw`、`click`、`cursor`）；覆盖层「检验」的逐条清单用 `openList` |
| `js/ui/variant-bar.js` | 新增：页面底部中央的切换条，读写地址的 `?variant=`，左右方向键切换（输入框、文本框与可编辑元素获得焦点时不处理）；只在覆盖层「来源」打开时显示；`Y10.variant()` 返回当前的形式 |
| `js/ui/views/observe.js` | 「请求记录与用量」区块之后新增「循环」区块（`ui.block({ id: 'obs-loop', title: '循环', query: 'run.loops', body })`，不写进页面的 `needs`）；`update` 时按 id 替换这个区块 |
| `js/ui/views/home.js` | 两个新汇总项展开时先列明细再列来源事件；来源事件每条旁写来源种类 |
| `js/ui/views/materials.js` | `qaBlock`：有 `criteria` 时画逐条结论表（`Y10.ui.table`），列为验收条件、检验方式、结果、证据、截图；表头写快照摘要与覆盖比例；开环的行带「开环」标记 |
| `js/ui/views/gallery.js` 用到的 `P.FLOOR_VIEWS`（`floor.js`） | 三个覆盖层各加一行，档位 `pilot` |
| `index.html` | `pixel/decision-card.js` 之后加载 `pixel/source-card.js`；`ui/` 的脚本里加载 `ui/variant-bar.js` |

画面上的标签沿用 `P.sign` 与现有覆盖层的位置算法（房间中央、角色工位上方、信息条）。颜色取自 `engine.js` 的调色板，六种状态的颜色在 `floor.js` 里定义一张表，覆盖层「循环」的图例、观测页与报告共用同一组文字。

## 4. 示例数据与场景

- `data/p-todo.js`：新增事项「导入 CSV」（`pilot` 档出现，带 `born_at` 与同一时间的 `work_item_created`），四轮质检，停滞、开环条件 AC-6、工程角色的步骤循环停滞；`S5` 档激活层的漂移。`w-todo-base` 的质检结论在 `3.2D` 档带 `criteria`，放行带一条开环条件。
- `data/p-metro.js`：新增事项「夜间票价」（`pilot` 档出现），AC-2 结论翻转（震荡），run 用完运行时间（达到边界），工程角色同名同参数的工具调用重复 3 次（步骤循环震荡）。
- `data/p-sensor.js`：`S4` 档项目循环按故障 F-4 的重复出现判定。
- `S5` 档一条决策模型给出的事件（证据核对），载荷带 `probability`。
- 新增两个场景（design.md 第 8.2 节），编号 20、21，档位 `pilot`；`checks/scenarios.js` 的场景数改为 21。

## 5. 验收

| 脚本 | 检查什么 |
| --- | --- |
| `matrix-home.js`、`matrix-floor.js` | 十档；其余同 v9 |
| `scenarios.js` | 二十一个场景全部按步骤播到最后一步，零错误 |
| `identity-building.js`、`record.js`、`replay.js` | 同 v9，对照页面为 v9：覆盖层不打开时，楼、机房与项目楼层的静止画面与 v9 逐像素相同 |
| `behaviors.js` | v9 的全部检查，加上 design.md 第 9 节的行为检查（覆盖层的档位、H1、H4、H5、`?variant=`） |
| `sheets.js` | 新增：按 design.md 第 9 节的清单截图，两种宽度（1440、1920）与两种主题，存进 `.tmp/v10-checks/sheets/`，并拼成每个画面一张的联系表 |

运行需要 Playwright：`PLAYWRIGHT_PATH` 指向一个已安装的 Playwright（例如 `C:/project/yudao-worktrees/integration/client/node_modules/playwright`）。
