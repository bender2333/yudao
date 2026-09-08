# S3 联合验收报告（W5 / W7 / P4）

日期：2026-09-08。被测应用冻结：`cdcdce5`（`fix: send object-typed change_record schema on Responses tools`）。其后文档提交不改变应用身份；本机 `git diff --stat cdcdce5 -- harness/` 为空。

结论：**PARTIAL**。基础三部门浏览器闭环、同一 run 连续输入、部门指导、观察/材料/视觉矩阵已取得真实证据；小窗压缩已触发摘要，但模型摘要夹带非 summary 内容，未能继续到最终 QA。不把测试总数当成通过。

旧 400 run `run_506da3ee67304de7` 未改写。API happy `run_7c4ea172110841cc` 只作 API 证据，不算浏览器证据。

## 1. 被测身份

| 项 | 值 |
| --- | --- |
| 冻结 SHA | `cdcdce5f33dcca73c956dc486af9faa206e378ac` |
| 分支 | `harness_1` |
| 控制台 | `http://127.0.0.1:8878` |
| 独立数据目录 | `.yudao/s3-acceptance-20260908/data` |
| 原始日志 | `.yudao/s3-acceptance-20260908/`（gitignore） |
| Provider 目录 | `.yudao/providers.p4.json`，凭据只进环境 `YUDAO_P4_KEY` |
| 协议 / 地址 / 模型 | Responses / `https://penguinapi.vip/v1` / `gemini-2.5-flash` |
| 限制 | 窗口 32000，输出 4096，超时 600 秒，尝试上限 3，未扩大重试 |
| 适配器 | `directory`，`fake_used=false` |
| 浏览器 | Playwright 1.60，Chromium 1223 |
| 原型对照 | `http://127.0.0.1:8881/department-workspace.html` |

首次拉起 serve 时，创建任务返回 `Git version is unavailable or invalid`（当时进程 PATH 未包含 Git）。未改应用。用当前 shell 把 `C:\Program Files\Git\cmd` 加入 PATH 后重启同一端口/数据目录，Git 可用。此前失败创建只留下工件、没有正式 run。另有一次 API 诊断 `run_d4e130cad2cf407e`（只 `create_run`、未跑循环），不算浏览器自然运行。

等待阶段用了 `/api/runs/{id}` 轮询，一律标为 API 编排等待，不是纯浏览器自然等待。压缩 run 的 `large.txt` 是脚本写入工作区，不是浏览器写入。

## 2. 场景表

| 场景 | 结果 | 证据 |
| --- | --- | --- |
| 基础三部门交付 | **PASS** | 浏览器新建 `run_cb69cec4c1f74100`，`DONE / released`，质检 `release`。封存恢复后公开检查通过。 |
| 同一 run 连续输入 | **PASS** | v1 字节 `[0,441)`，v2 `[441,576)`，原文拼接 576 字节与 `intend.md` 一致。产品处理 `processed_input_version=2`，有效合同/PRD r2，交付输出含 `status` 列，最终 QA release。 |
| 部门指导 | **PASS** | 工程页发送解释指导与动作指导；状态分别为 `explained` / `explained`，未把未核实动作标成 `completed`。产品私有消息未混入工程指导原文。后续交付文件含 `# export-format: csv`。 |
| 小窗压缩 | **PARTIAL** | `run_2268b511fece4392`，窗口 8000，确有 1 次 `compaction_recorded`，该失败轨迹的模型输入审计 `verified`。随后 `FAILED / compaction_failed`：摘要输出夹带了非 summary 内容，未到交付/QA。 |
| 观察与历史 | **PASS**（输入审计附注） | Context 精确跳到 `act_e779a7b32e5048a5:root-1:work:attempt-1`；请求/返回身份分开显示；SSE `/stream` 已请求；后退可用；导出 JSON 已保存。组合 run 的 smoke `model_input_audit` 为 unverified，见第 4 节。 |
| 视觉与移动端 | **PASS**（64KB 注入为 PARTIAL） | 冻结原型与生产页 1440/1024/390/360，生产空页另有 320；浅/深色无横向溢出。320 Raw 实测 `max-height:360px; overflow:auto; scrollHeight=13443`。脚本注入的 64KB 详情未稳定落到 JSON 容器。 |
| 终态与材料 | **PASS** | 取消对话框保留草稿；显式新建才创建 run；终态拒收全局输入。总览可见 PRD/PLAN/Git/封存；Prompt 原文可查看，终态后编辑入口关闭。 |
| 本地确定性故障 | **PASS** | pytest 215，1 个既有 timeout flake。覆盖取消、迟到、429、过载、断流、重试耗尽。Node UI 34/34。 |

## 3. 浏览器主 run：`run_cb69cec4c1f74100`

**输入（浏览器发送）**

1. 新建任务，`max_cycles=16`，`context_window=32000`。任务：实现 `src/export_orders.py`，打印 `id,name` / `1,alpha`。
2. 工程阶段通过部门页发送：
   - 解释：`请说明当前 CSV 是否给字段加引号。不要修改任何文件。`
   - 动作：`请在 src/export_orders.py 文件开头增加一行注释：# export-format: csv`
3. 总览追加 v2：`Also include a status column. ... header id,name,status ... 1,alpha,open`。

**结果**

- 阶段 `DONE`，停止 `released`，质检 `release`。
- 15 次模型请求，0 次重试，8 个激活。实际模型 `gemini-2.5-flash`。
- 有效合同 r2 / 产品 spec r2（含 status 列）。工程 PLAN r1 在 v2 合同之后形成，目标已含 status 与注释。
- 交付文件 `src/export_orders.py`。独立恢复后执行：

```
id,name,status
1,alpha,open
```

退出码 0。文件首行是 `# export-format: csv`。

- 宿主检查：工程 `verify_export_orders`、质检 `qa_verify_export_orders`，均为 exit=0，快照 `sha256:788a0021cc2d23a26a0cf883572b5d54800bbd3512239cba482f1f622a85e763`。
- Git 7 个正式版本，`verified`。封存 `verified`。事件 replay 一致。
- 指导：两条都是 `explained`。解释指导没有改文件；动作指导当时回应为将在实现时加入注释，宿主未标 `completed`。最终交付含该注释，产品部门消息未出现这两条工程指导原文。

浏览器操作记录：`.yudao/s3-acceptance-20260908/browser-evidence.json`，截图 31 张。等待使用 API 轮询，主 run 约 64 秒到达终态。

## 4. 观察、导出与审计附注

- Context「查看模型请求」跳到工程尝试 `act_e779a7b32e5048a5:root-1:work:attempt-1`，URL 含该 attempt。
- 观测列表同时显示「请求：p4-primary / gemini-2.5-flash」和「返回：…」。
- 导出：`.yudao/s3-acceptance-20260908/runs/run_cb69cec4c1f74100-export.json`。
- SSE：页面请求了 `/stream`。
- 320px Request JSON：可滚动，无横向溢出。

smoke 审计器对这个组合 run 给出 `model_input_audit=unverified`，备注是部门输入/钉住材料/历史与“当前允许材料”不完全一致（事件 56、57、71、88、89、129、147、160、173）。跨部门 transcript 排除项仍通过。这不能推翻部门页私有历史检查，也不能当成 API happy smoke 的审计失败；happy smoke `run_7c4ea172110841cc` 仍是 `verified`。若要关闭“组合 run 的逐字节输入审计”，需要在同一冻结上对指导/连续输入路径核对审计器口径。

## 5. 小窗压缩：`run_2268b511fece4392`

- 浏览器新建，窗口 8000，循环上限 20。
- 脚本写入 `workspaces/run_2268b511fece4392/large.txt`（156599 字节），任务要求工程先完整读取再写 `src/echo.py`。
- 4 次真实模型请求，其中 1 次压缩。`fake_used=false`，压缩 run 的模型输入审计 `verified`，跨部门隔离通过。
- 停止：`compaction_failed` / `Compaction output must contain only an assistant summary and optional reasoning`。无交付、无 QA。

恢复条件：同一冻结、同一模型与 Prompt，压缩响应只含 assistant summary（及可选 reasoning），不要夹带工具或工作输出；然后继续到独立 QA。不要靠加大重试或换模型制造通过。本次已证明摘要会被触发，也证明宿主会拒绝不合格摘要。

## 6. 视觉 / 终态 / 本地故障

视觉令牌与冻结原型一致：`--dw-accent light-dark(#087f69, #56d1b3)` 等。1440/1024/390/360 浅色，1440/390 深色，空页另有 320。无横向溢出。长错误用脚本 503 创建失败可见；长身份/64KB 用脚本观测载荷，未稳定进入 JSON 滚动容器，故 64KB 注入标 PARTIAL。Node UI 已覆盖 64KB Raw 选择器与请求/返回身份。

终态：草稿保留、失败创建不丢原文、只有「新建」创建 run。材料区可打开 PRD/PLAN/Git/封存。Prompt 可查看；终态后编辑关闭，符合终态拒收。

本地 pytest（冻结应用，无真实模型）：

```
python -m pytest harness/tests/test_provider_retry_engine.py \
  harness/tests/test_retry_input_boundaries.py \
  harness/tests/test_activation_accounting.py \
  harness/tests/test_department_guidance.py \
  harness/tests/test_compaction_engine.py \
  harness/tests/test_observability.py \
  harness/tests/test_web.py \
  harness/tests/test_responses.py
```

215 通过，1 失败：`test_local_http_transient_failure_retries_same_input_then_succeeds[timeout]`，为已记录 flake，未改断言。429 / 过载 / 断流 / 重试耗尽 / 取消 / 迟到由同批其余用例覆盖。Node `harness/tests/test_web_ui.js` 34 通过。

浏览器脚本：`harness/tests/test_s3_acceptance_browser.spec.js`。不是生产运行器，也不是新的循环实现。

## 7. 独立核对

无凭据新进程：`python .yudao/s3-acceptance-20260908/independent_check.py`。

| 项 | 主 run | 压缩 run |
| --- | --- | --- |
| replay | 一致 | 一致 |
| Git | verified（7） | verified（1，仅原文） |
| 封存恢复 | verified，公开检查通过 | 无交付 |
| 输入来源 | v1+v2 字节连续 | 仅 v1 |
| 真实模型 | 是 | 是 |
| 密钥扫描 | 0 | 0 |

## 8. 未关闭项与恢复条件

1. 小窗压缩后最终 QA：需合格摘要输出，见第 5 节。
2. 64KB 注入详情页：脚本路由未落到 Request JSON；真实 320 Raw 已滚动。若要关闭该项，需在详情页稳定渲染 64KB 文本并测量容器滚动。
3. 组合 run 的 smoke 输入审计 unverified：指导/连续输入路径与审计器口径需单独核对。不因此否定本次 QA 放行与封存恢复。
4. 本机 `test_responses.py` timeout 参数化 flake 仍在。

未换服务、模型或 Prompt，未扩大重试，未把 Playwright 加进生产依赖。阶段总体仍为 PARTIAL。
