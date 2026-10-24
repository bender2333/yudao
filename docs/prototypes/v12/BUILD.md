# 原型 v12 构建约定

本文件只写跟 [v11 BUILD.md](../v11/BUILD.md) 不一样的地方，其余照旧：v12 沿用 v11，v11 沿用 [v10 BUILD.md](../v10/BUILD.md)，v10 沿用 [v9 BUILD.md](../v9/BUILD.md)，v9 沿用 [v8 BUILD.md](../v8/BUILD.md)。画面与交互见 [design.md](design.md)。

命名随版本改名：v12 的全局对象是 `window.Y12`，CSS 类名以 `y12-` 开头，存储键以 `y12.` 开头，脚本是 `js/y12.js`，页面标题与顶栏的标签写「v12 原型」。前几版 BUILD.md 里出现的 `Y11`、`y11-`、`js/y11.js`（以及更早的 `Y10`、`Y9`、`Y8`）在 v12 读作 `Y12`、`y12-`、`js/y12.js`。验收脚本以 v9 为对照页面、v12 为被检查的页面（`checks/env.js` 的 `spaceOf`）。

## 1. 登记表（registry.js）的变化

| 种类 | 新增 | 删除 |
| --- | --- | --- |
| 查询 | `run.asks`（ui）、`project.writeback`（3.8） | — |
| 命令 | `project.set_goal`（ui，拒绝原因多一个 `not_allowed`）、`writeback.execute`（3.8，`not_found`、`project_archived`、`not_allowed`） | `command_registration.save`、`tool_authorization.save` |
| 决定 | `paused_continue`（3.1）、`definitions_changed`（3.1）、`wait_limit`（3.2C）、`instance_upgrade`（pilot，`stream: 'catalog'`，不属于项目） | `unknown_action`、`tool_once` |
| 事件 | `ask_started`、`ask_answered`（关键事实「询问」「回答」）、`action_verified`（3.1）、`project_goal_changed`、`writeback_completed`、`writeback_verified`、`writeback_stopped`、`writeback_held`、`writeback_not_needed`（3.8）、`x_wait_restarted`（3.2C，等待超过上限以后继续等待、重新计时） | `transition`、`collaboration_requested`、`collaboration_responded`、`collaboration_closed`、`plan_accepted`、`command_configured`、`x_tool_authorization_saved` |

- `source_directory.save` 的拒绝原因是 `stale_base`、`not_found`、`project_archived` 与 `not_allowed`（打开写回而没有写远端或目标分支）；`project.create` 多一个 `source_invalid`（起始文件夹不可用）。
- 关键事实的种类删除 `handoff`；`rework` 的名称改为「缺陷记录」，键名不变。
- `backend.js` 的 `validate()` 另外核对：写在目录流里的决定请求（`stream: 'catalog'`）没有 `project_id`。`Y12.CLIENT_API_VERSION` 为 2，示例服务的 `deployment.api_version` 为 2。

## 2. 示例数据的形状

在 v8 BUILD.md 第 8.2 节的基础上：

```js
runs: [{
  …,
  asks: [{ id, requester, recipient, parent: null | 上一层询问的 id, question, status: 'open'|'answered'|'unable',
           answer, reason, prd_version: null | 'r2', born_at, answered_at }],          // 取代 requests
  departments: null | { quality: { state: 'working', note: '预测性探索：…' } },          // 写明了的部门状态；没写的由事实推出
  sessions: [{ id, department, kind: 'main'|'branch', label, elapsed_sec, activations, model_steps }],
  recovery: {
    state: 'running'|'interrupted'|'waiting_resume'|'completed'|'paused'|'cancelled'|'stopped',
    waiting_machine: null | { machine_id, since, problem },                                // 3.2C：等待机器
    unfinished: [{ id: 动作 id, label }],                                                 // 重新启动时结果未知的动作
    verifications: [{ action_id, handling: 'confirmed'|'returned', session, at, basis, result, returned }],
    …
  },
  actions: [{ …, tool: 'bash'|'edit_range'|'network_fetch'|'mcp:<工具>'|…,
              receipt: { command } | { target, artifact } + { exit_code, output, truncated, timed_out, duration_ms, snapshot } }],
  flow: [{ …, kind: 'input'|'prd'|'delivery'|'defect'|'ask'|'answer'|'release'|'adopt'|'structure'|'baseline' }],
  guidance: [{ …, status: 'received'|'in_input'|'answered' }]
}]
projects: [{ …, initial_snapshot: 没有起始文件夹时不写 | { source, files, tree_digest } }]   // project.create 写入
project_settings[项目]: {
  departments, roles, ops,
  machines: [{ machine_id, dirs, runtime_env, standing }],                                 // 没有 operations
  source_directories: { version, items: [{ name, path, writeback: { enabled, remote, target_branch }, check_commands: [] }] },
  writebacks: [{ id, adoption, work_item_id, status: 'completed'|'verified'|'stopped'|'held'|'not_needed', at,
                 target_branch, pushed_branch, merge_request: null | { title, local_only }, conflicts, stop_reason }],
  execution_placement: { version, workspace, checks }                                      // 没有 image
}
tools: { network: { scope, recent: [{ at, url, project_id, work_item_id, result }] },
         mcp: [{ id, project_id, name, transport, departments, last: { at, ok, text }, tools: [{ name, description }] }], browser, computer_use, observers }
```

`runs[].phase` 仍在数据里，只作为结束方式的内部标记（`DONE`、`PAUSED`、`FAILED`、`QUEUED`），查询不再给出阶段名称。

新的决定请求的 `materials`：

| 种类 | `materials` |
| --- | --- |
| `paused_continue` | `department`、`reason_code`（`no_tool_call`、`workspace_unrepresentable`）、`reason`、`guide`、`paths`、`links` |
| `definitions_changed` | `recorded_version`、`current_version`、`basis` |
| `wait_limit` | `wait`（等待的种类）、`target`、`machine_id`、`since`、`limit_sec`、`note` |
| `instance_upgrade` | `current`、`candidate`、`commit`、`checks: [{ name, ok, text }]` |

只在场景里发出的决定请求在种子里的 `status` 写 `withdrawn`、不写 `born_at`，由场景的 `x_decision_issued` 改为 `waiting`。

## 3. 查询给出的新字段

- `project.loop` 的事项多 `departments`：不等待工作的部门写成「部门 → 状态」（`working`、`answering`、`waiting_user`）；`open_requests` 由进行中的询问给出（形状沿用 v11，像素画面照旧读取）。
- `project.overview` 的事项多 `departments`（三个部门各自的 `{ state, text, kind, note }`）与 `progress`（`prd`、`delivery`、`delivery_basis`、`verdict`），去掉 `phase`；项目多 `start_point`、`source_directories` 与 `writeback`（3.8）。
- `department.workspace` 多 `states`（三个部门）与 `asks`（本部门发出或收到的询问）；`status` 多 `note`；房间模型的 `pending_tool` 恒为 `null`。
- `run.recovery` 去掉 `verifications` 与阶段，多 `waiting_machine`（带 `waited_sec`）、`unknown_actions`（每条带 `handling`、`handling_text`、`session`、`basis`、`result`、`returned`，3.2C 起带 `machine_id`）与 `sessions`；`upgrade` 多 `start_point`。
- `run.asks`：`{ work_item_id, run_id, asks: [{ …, status_text, chain: [部门…], depth }] }`。
- `project.writeback`：`{ project_id, enabled, source_name, target_branch, records }`，记录按时间从新到旧，时间相同时后写入的在前。
- `tools.registry`：`network` 与按项目过滤的 `mcp`；没有 `design_note` 与 `hooks`。
- `work_item.materials` 没有 `plan`；`old_runs` 的每条写 `state`（恢复观察状态），不写阶段。
- 观测页「运行限制」的每行写 `status_text`（事项状态），不写阶段。

## 4. 界面层与像素画面

| 位置 | 做什么 |
| --- | --- |
| `js/ui/scenes.js` 的 `pixelEvents`、`playOn` | 事件对照表（design.md 第 3.6 节）：把 v12 的事件转成像素画面认得的 v11 事件。项目楼层的实时事件与回放事件、部门工作间的房间（`views/department.js`）都经 `Y12.scenes.playOn` 交给画面；楼与机房不需要转换 |
| `js/pixel/floor.js` 的 `alsoIn`、`busyIn` | 事项停在别的房间、这个部门同时在工作中或回答询问时，房间亮灯、屏幕滚动、小人工作；包裹与小旗仍按 `department` |
| `js/pixel/floor-decl.js` 的 `deptRest`、`keyOf` | 同时工作的部门坐在桌前打字；工具 `bash` 走「执行命令」的任务 |
| `js/pixel/say.js` | `bash` 按命令原文说话 |
| `js/pixel/engine.js` | 动作图鉴删除「计划贴上白板」与「接过决定单照着做」，`bash` 映射到「走到终端拉下拉杆」，询问与取件的来源改写；部门状态的姿势删除待核实 |
| `js/ui/scenes.js` 的楼的模型 | 几个部门同时工作时，楼里几个房间都亮灯 |

像素画面里 v11 的事件词汇（`transition`、`collaboration_*`、`run_command`、`plan_accepted`）照旧可以识别：楼层回放用 v9 录下的调用比较两版的画法。

## 5. 场景

场景按 v8 BUILD.md 第 9 节登记。新增两个，都在 `data/p-metro.js`：

| 编号 | 场景 | 档位 | 所在文件 |
| --- | --- | --- | --- |
| 22 | 暂停以后继续与定义版本不同 | 3.1 | p-metro |
| 23 | 等待机器超过时长上限 | 3.2C | p-metro |

改名的场景：2「缺陷记录与重新交付」、8「结果未知的动作：核实与交还会话」、10「执行代理离线：等待机器与按尝试身份核实」。`checks/scenarios.js` 的场景数改为 23。

## 6. 测试

| 脚本 | 通过的条件 |
| --- | --- |
| `scenarios.js` | 二十三个场景全部按步骤播到最后一步，零错误 |
| `behaviors.js` | 沿用 v11 的全部检查，另加 `v12Checks`：事件对照表、登记表的增删、三个部门同时工作（状态、原因、楼与楼层的亮灯）、询问链与回问、恢复页七种状态与结果未知的处理（场景 8）、等待机器（3.2C 的种子与场景 10、23）、暂停以后继续与定义版本不同（场景 22）、设置页与工具页删掉的内容、成果写回（拒绝与写回完成）、长期目标、资料页没有 PLAN、标签页标题、接口版本按方向、没有托盘 |
| `matrix-home.js`、`matrix-floor.js` | 照旧，零错误、没有横向溢出 |
| `identity-building.js` | 照旧，楼与机房与 v9 逐像素相同 |
| `record.js` + `replay.js` | 照旧：在 v9 上录制，回放给 v9 与 v12，每个检查点逐像素相同 |
| `walkers.js` | 照旧 |
