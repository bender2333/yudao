# Stage 2 日常可用性验收（2.6）

日期：2026-09-15。计划 `docs/stage-2-implementation-plan.md` §2.6.1–2.6.5。  
冻结：`frozen_sha=041eaa1b15e406e1fffde5b2aa4ba421e8ee87ed`（启动 isolated serve 前 `git rev-parse HEAD`，短 SHA `041eaa1`）。  
控制台：`http://127.0.0.1:50983`（进程 `s26-serve`）。  
目录副本：`.yudao/stage2-validation/providers.json`（从 `.yudao/providers.stage2-a1-back.json` 复制；验收结束时与源文件字节一致，UI 编辑未回写 A1 目录）。  
凭据：只注入环境变量 `YUDAO_BACK_KEY`（provider.md `back` 段 `key`），未写入本报告或其它证据文件。  
数据目录：`.yudao/stage2-validation/data/`（与 2.1.3 `.yudao/stage1-final-validation/` 隔离）。  
未改 `harness/*`。未使用 FakeAdapter。未关闭 TLS。未使用 8000 任务窗。

明细：`.yudao/stage2-validation/report.md`、`progress.json`、`runs/`、`traces/`、`screenshots/`。

## 结论

| 项 | 标准 | 结果 |
| --- | --- | --- |
| 2.6.1 | 连续 10 次真实任务，至少 8 次 DONE/released | **PASS** 9/10 |
| 2.6.2 | 失败可通过 Context/Trace View 追溯 | **PASS** 计划取消 `run_048a07d909474063` |
| 2.6.3 | Provider 配置可通过界面完成，≤10 min，不贴密钥 | **PASS** 21 s；测试连接成功 |
| 2.6.4 | 桌面 1440 + 手机 390 可用 | **PASS** 截图见下 |
| 2.6.5 | 核心功能不弱于 OMP | **PASS** 见 `docs/stage-2-omp-feature-comparison.md`（P0 空，核心 have） |

`fake_used=false`。全部成功场次 `actual_provider=p4-back`、`actual_model=agnes-3.0-flash`。失败未改写。

## 2.6.1 连续十场

| # | 场景 | project_id | work_item_id | run_id | phase / stop | 压缩 | 分类 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 简单 echo hello | `proj_7546308a2d784299` | `wi_954f6c634bb846cd` | `run_0e6439e2a80d42ab` | DONE / released | 0 | —（工程 attempt-1 `provider_error`/`stream_incomplete` 后内核重试，任务仍放行） |
| 2 | 简单 echo ping | `proj_58c28858743f4c28` | `wi_5d1f9ebf9a5941b9` | `run_ed78bbe985e84ae4` | DONE / released | 0 | — |
| 3 | 方向调整 hello→HELLO | `proj_ce28ea8c4c4345a4` | `wi_cb92f6ca965e4fd9` | `run_0a2eff1aee184099` | DONE / released | 1 | —（QUALITY 时追加 v2，`followup_ok=true`） |
| 4 | 参考笔记 + echo ref | `proj_e9f7cb37a1224705` | `wi_372800f2b31f4ce7` | `run_12bfa40844034c7a` | DONE / released | 0 | —（廉价参考：intend 内 NOTE-0001…0040；目录窗未强制压缩） |
| 5 | 简单 echo alpha | `proj_5053daa3454e4429` | `wi_a64443b421ee4f96` | `run_db2b2082c3844599` | DONE / released | 0 | — |
| 6 | 计划取消 | `proj_aca3e2b248ca4613` | `wi_3cf8fbe22f544b0c` | `run_048a07d909474063` | FAILED / cancelled | 0 | **user_cancel**（PRODUCT_SPEC 时 `POST /cancel` 200） |
| 7 | 简单 echo beta | `proj_5d20d7d1f9f349e1` | `wi_cba5d200a6854f2a` | `run_3eac0693422a4d93` | DONE / released | 0 | — |
| 8 | 简单 echo gamma | `proj_468616d3fde04b8f` | `wi_4ecdc649f1114a99` | `run_396f01a8adaf4998` | DONE / released | 0 | — |
| 9 | 简单 echo delta | `proj_41a5f026d4094d18` | `wi_5e83a88ba0ae4fce` | `run_fa99237f6b8f47f4` | DONE / released | 0 | —（产品 attempt-1 `provider_error`/`stream_incomplete` 后恢复） |
| 10 | 简单 echo omega | `proj_543f4be49d944f72` | `wi_b160ef2b907c4b90` | `run_635d8f7c41744afa` | DONE / released | 0 | — |

事项状态：1–5、7–10 `adopted`；6 `stopped`。适配器 `directory`。窗口为目录 512000，未使用 8000。运行窗口 UTC `2026-09-15T04:36:48Z`–`05:04:29Z`。

## 2.6.2 失败可追溯

计划取消场次保留原状，未重写事件。

- 工作台产品部：范围「echo cancel-me · 已停止」，状态「产品部 · 失败」。检查区 Context 快照 `evt_8d3f0189d27d4138`，模型输入「第 1 次 cancelled」，可见 Developer 指令 / 部门历史 / 工具 schema / 用户原文，并有「查看模型请求」。
- 观测 Trace 详情：`act_5d6b1cb6e75b4ab2:root-1:work:attempt-1`，状态已取消，**错误分类 `cancelled`**，文案 `Model request cancelled`，尝试 1/1，部分输出，Provider/模型 `p4-back` / `agnes-3.0-flash`。
- API：`GET /api/runs/run_048a07d909474063/model-attempts` 与 attempt 详情、`GET /api/runs/.../departments/product` 均 200。`error_class=cancelled`，`reason=cancelled`，`attempt=1`，`diagnostics={}`（取消无传输诊断，属该类预期）。

截图：

- `.yudao/stage2-validation/screenshots/cancel-context-desktop-1440.png`
- `.yudao/stage2-validation/screenshots/cancel-trace-desktop-1440.png`
- `.yudao/stage2-validation/screenshots/cancel-trace-detail-1440.png`
- API 摘录：`.yudao/stage2-validation/traces/task6-cancel.json`

第 1、9 场中已恢复的 `provider_error`（`error_type=stream_incomplete`，`transport_phase=response_closed`）同样留在 attempt 列表，未当任务失败改写。

## 2.6.3 配置易用性

从工作台点「模型与 Provider」（`?view=providers`）：

- 列表：Stage2 A1 back / responses / `https://api.agnes-ai.cn/v1` / 凭据引用 `YUDAO_BACK_KEY` / 已配置。
- 模型：agnes-flash / agnes-3.0-flash / 窗口 512000 / 输出 65536。
- 三部门绑定：产品、工程、质检均为 Stage2 A1 back / agnes-flash。
- 「测试连接」：**连接成功 · agnes-3.0-flash · 20752 ms**。表单不保存密钥，页面无密钥原文。

计时：打开配置页 107 ms，测试连接 20788 ms，合计 **0.35 min**（目标 ≤10 min）。未手改 JSON。计时记录 `.yudao/stage2-validation/config-ux.json`。

## 2.6.4 界面流畅性

| 表面 | 文件 | 观察 |
| --- | --- | --- |
| 工作台 1440 | `screenshots/workbench-desktop-1440.png` | 三栏可用；事项在「完成 / 已采纳」；无横向溢出 |
| 工作台 390 | `screenshots/workbench-mobile-390.png` | 单列；输入框与「作为新事项开始」可点 |
| 配置 1440 | `screenshots/config-desktop-1440.png` | 列表、表单、绑定、测试结果同屏 |
| 配置 390 | `screenshots/config-mobile-390.png` | 单列可滚动；表格单元格截断但无横向滚动 |

首页进入配置页 107 ms（远低于 2 s）。未观察到卡死或按钮重叠。

## 2.6.5 OMP 对标

依据 `docs/stage-2-omp-feature-comparison.md`（2.4 审查）：**P0 清单为空**。日常路径核心项均为 `have`：

| 核心 | 本场对照 |
| --- | --- |
| 任务管理：创建、取消、历史 | 10 个项目/事项；第 6 场取消；侧栏历史 |
| 模型配置：Provider、部门绑定 | 配置页列表 + 三部门绑定 + 测试连接 |
| 上下文：压缩、窗口限制 | 第 3 场 `compaction_count=1`；目录窗 512000 |
| 工具：读写、检查、Git | 成功场次均有工程写入与质检独立检查后 release |
| 观测：请求、用量、Context/Trace | 取消场次 Context 快照 + Trace 错误分类 |
| 界面：响应式、实时更新 | 1440 / 390 截图；SSE 工作台 |

弱于 OMP 的编码工具面与 `--resume` 属 Stage 3 / P3，不是本阶段 P0。

## 2.6.6 回归

- Python：`python -m pytest harness/tests -q --tb=line -p no:cacheprovider` 在缺凭据 CLI 断言改为检查环境变量名与部门后，**958 passed, 1 skipped**（收集 959），1423 s。计划下限 ≥683。
- JavaScript：`node --test harness/tests/test_web_ui.js` **29 passed**。计划写的 ≥50 是 D18 时期口径；当前工作台 Node 文件是这一份，全部通过。
- 浏览器：2.6.4 桌面 1440 / 手机 390 真实截图；未再跑 Fake 矩阵。
- 未做独立性能测试。未观察到相对 2.1.3 的明显退化。

## 边界

- 第 4 场为廉价参考资料，未再开 8000/小窗压测；压缩证据来自第 3 场方向调整。
- 未复用 2.1.3 数据目录。
