# Aider Polyglot 题库 — Solo vs Multi 对比实验协议

> 状态：**SUPERSEDED / HISTORICAL**
> 新方案：`three-department-work-order-validation-design.md`
> 旧命令仅用于解释历史结果，当前运行时已移除。

> 状态：**协议 + Runner 已实现**  
> 日期：2026-07-10  
> 分支：`exp/native-harness`  
> 约束：**不使用 Docker**；题来自公开 Aider polyglot 集；执行与判分在本机 Python 环境完成。  
> Runner：`scripts/aider_polyglot_runner.py`；题清单：`docs/native-harness/aider-polyglot-tasklist.md`

---

## 0. 一句话

用 **Aider 公开的 Exercism 练习子集**做题库，用本仓库 **`run_solo` / `run_multi`** 当两种 agent，用题自带的 **pytest 测试**当唯一对错标准。  
**不是**复刻 Aider 编辑器，也**不能**直接声称「Aider 官方榜同分」。

---

## 1. 公开材料放哪里

| 内容 | 位置 |
|---|---|
| 题库（练习文件） | https://github.com/Aider-AI/polyglot-benchmark |
| 基准介绍 | https://aider.chat/2024/12/21/polyglot.html |
| 官方榜（仅对照业界，非本实验目标） | https://aider.chat/docs/leaderboards/ |
| 本协议 | `docs/native-harness/aider-polyglot-protocol.md` |
| 本仓库 runner（待实现） | 见 §7（建议路径 `scripts/aider_polyglot_runner.py` 或 `harness/bench/`） |
| 本地题库克隆（建议） | `third_party/polyglot-benchmark/`（可 gitignore） |
| 跑分产物 | `runs/aider/<batch_id>/...` |

题库内单题典型结构（Python）：

```text
python/exercises/practice/<slug>/
  <impl>.py          # 待实现 / 骨架
  <slug>_test.py     # 测试 = 判分标准
  .docs/ 或 instructions  # 题面
  ...
```

---

## 2. 研究问题与处理臂

### 2.1 问题

在 **同一公开题、同一隐藏测试、同一 run 级预算**下：

- **S（solo）**：单 loop 自驱完成  
- **P（multi-persistent）**：U→P→V 常驻会话 multi（本仓库默认）  

谁的 **测试通过率** 更高？成本差多少？

可选第三臂（预注册次要消融，不替代主结论）：

- **C（multi-cold）**：`--session-model cold`

主比较：**P vs S**。

### 2.2 明确非目标

- 不提交 Aider 官方 leaderboard  
- 不测 Aider 的 diff 编辑格式  
- 不装 Docker、不用 Aider 自带 `benchmark/docker.sh`  
- 第一轮不做 C++/Go/Java/Rust/JS 全语言（见 §4）

---

## 3. 判断标准（怎么算对）

### 3.1 唯一真值：题自带测试

| 判定 | 定义 |
|---|---|
| **PASS** | 在 **判分区** 对 agent 交付代码跑该题 `*_test.py`，**退出码 0 且无失败用例** |
| **FAIL** | 测试失败、超时、无交付、导入错误、runner 异常等 |

- 不引入第二套手写 oracle（除非某题测试跑不起来，整题剔除并记录）。  
- harness 的 `outcome=done` **不等于** PASS；只报「过程是否收口」。  
- **主指标 = 测试 PASS**；过程指标单独列。

### 3.2 测试命令（Python 默认）

在判分区根目录（含实现与测试的目录）执行：

```bash
python -m pytest <slug>_test.py -q --tb=no
```

若题要求特定 runner，以该题目录 README / Exercism 惯例为准，**整批统一写进题清单表**，禁止临场改命令。

### 3.3 Agent 可见 vs 不可见（防泄题）

| 区域 | Agent 可见？ | 说明 |
|---|---|---|
| 题面 / instructions / 公开说明 | ✅ | 写入 task 文本或 workspace 文档 |
| 实现骨架（stub） | ✅ | 拷入 agent workspace |
| 示例 / 题面中的公开例子 | ✅ | 题面自带的可以保留 |
| **完整 `*_test.py` 内容** | ❌ **禁止** | 不得拷入 agent workspace，不得贴进 prompt |
| pytest 输出（跑完后） | ❌ 不在 agent 回合内 | 仅 runner 判分区使用 |

> 若 Exercism 骨架默认把测试放同目录：runner **必须拆分**——  
> agent workspace 只有实现相关文件；测试留在 `judge/` 副本。  
> 判分时把 agent 产出的实现文件 **覆盖拷入** `judge/` 再测。

### 3.4 可报告指标

每个 run 至少记录：

| 字段 | 含义 |
|---|---|
| `task_slug` | 题目录名 |
| `arm` | `S` / `P` / `C` |
| `rep` | 重复序号 1..R |
| `pass` | bool |
| `pytest_exit` | 进程退出码 |
| `harness_outcome` | multi 的 done/escalated；solo 的 stopped_reason |
| `calls` / `prompt_tokens` / `completion_tokens` | 来自 summary |
| `duration_ms` | summary 或 runner 墙钟 |
| `run_dir` | 路径 |
| `error` | 若 runner 失败 |

批次汇总：

- 每臂 **通过率** = PASS 数 / 计划 run 数（intention-to-treat：崩溃计 FAIL）  
- 每题每臂中位数成本  
- 可选：P−S 通过率差、McNemar / 配对描述（n 小时诚实标注）

### 3.5 「谁赢」预注册（冻结后不得改）

正式批只允许三种结论之一：

1. **支持 P**：P 通过率 − S 通过率 ≥ **+10 个百分点**（且 P 至少赢过 **半数题** 的题级多数票），或通过率差 ≥5pp 且平均 token ≤ 2×S。  
2. **不支持 P**：通过率差 ≤ 0，或 P 只在 ≤1/3 的题上更好。  
3. **证据不足**：介于中间；可按规则补样，**不得**改题或改 prompt。

（阈值可在 **冻结题清单前** 微调一次并写入本文版本号；冻结后锁死。）

---

## 4. 题库范围与选题规则

### 4.1 第一轮范围

- **语言：仅 Python**  
- **来源**：`polyglot-benchmark/python/exercises/practice/*`  
- **规模（建议 pilot → 正式）**：  
  - Pilot：**5 题 × 2 臂 × 1 重复**（不计入正式结论）  
  - 正式：**15 题 × 2 臂 × 2 重复** = 60 runs（若加 C：15×3×2=90）

### 4.2 入选条件

- 目录内有可运行的 `*_test.py`  
- **仅依赖标准库 + pytest**（无网络、无原生编译、无付费 API）  
- 题面为自然语言，可用 1 段 task 说清  
- 本地单测在空实现上应 **失败**，在参考解（若有）上应 **通过**（抽样校验）

### 4.3 排除条件

- 需要 Docker / 系统服务 / GPU  
- 测试不稳定（flaky）  
- 依赖本机未装的额外重型工具  
- 在调 prompt / 调 runner 时用过的题 → **不得**进正式题清单（可进 pilot）

### 4.4 题清单表（冻结时填）

正式批前在本文附录或 `docs/native-harness/aider-polyglot-tasklist.md` 固定：

| slug | 难度主观 | 备注 |
|---|---|---|
| （冻结时填写） | easy/med/hard | |

并记录：`polyglot-benchmark` 的 **git commit SHA**。

---

## 5. Runner：职责与目录约定

### 5.1 Runner 是什么

Runner = **实验编排脚本**（待实现），**不是** agent 本体。职责：

1. 读题清单与臂配置  
2. 为每个 `(slug, arm, rep)` 建隔离目录  
3. 组装 agent 可见 workspace + 不可见 judge 区  
4. 调用 `harness.run_solo` 或 `harness.run_multi`  
5. 拷贝产物 → 跑 pytest → 写 `result.json`  
6. 汇总 batch 表  

Agent **不得**自己调 pytest 作为「官方得分」；agent 可在 workspace 内自测，但 **官方分只认 runner 判分区**。

### 5.2 建议目录布局

```text
third_party/polyglot-benchmark/     # git clone，固定 SHA
runs/aider/<batch_id>/
  batch_config.json                 # 模型、预算、SHA、臂、题列表
  results.csv                       # 汇总
  results.jsonl                     # 每 run 一行
  tasks/<slug>/
    source/                         # 只读：从 polyglot 拷来的原始题
    S_r1/
      agent_workspace/              # agent 可写（无完整测试文件）
      judge/                        # 含测试 + agent 交付的实现
      harness_run/                  # run_solo/run_multi 的 run-dir
        events.jsonl
        summary.json
        workspace/                  # 与 agent_workspace 可同一或同步
      result.json                   # pass、pytest 日志路径等
      pytest.log
    P_r1/
      ...
```

### 5.3 单次 run 流水线（必须按序）

```text
1. 校验 run 目录不存在（fail-fast，禁止复用）
2. 从 third_party 拷贝题目到 source/（只读权限更佳）
3. 构建 agent_workspace：
     - 题面 instructions → TASK.md 或 prompt 字符串
     - 实现 stub 文件（无 *_test.py）
4. 构建 judge/：
     - 完整原题（含 *_test.py）
5. 调用 harness（§6 CLI 参数）
     - cwd/workspace = agent_workspace 或 harness_run/workspace
6. 将 agent 产出的实现文件同步到 judge/
     - 同步规则见 §5.4
7. 在 judge/ 执行 pytest（§3.2）
8. 写 result.json；无论 PASS/FAIL 保留全部日志
```

### 5.4 文件同步规则（judge）

- **白名单同步**：仅同步题声明的实现文件名（如 `main.py` / `xxx.py`）；由题清单表配置。  
- **禁止**把 agent 的随意文件（`err.txt`、临时脚本）默认算交付，除非测试依赖。  
- 若 agent 未生成必填文件 → 直接 FAIL，`error=missing_deliverable`，仍写 result。  
- 同步后 **不得**再让 agent 改 judge/。

### 5.5 Task 文本规则（给 agent 的 prompt）

统一模板（中英文随题面；默认中文壳 + 保留题面原文）：

```text
你在独立工作区中完成一道编程练习。

# 任务说明
{instructions 全文}

# 要求
- 实现工作区内的目标源文件，使功能符合说明。
- 可用工具读写文件、运行命令做自检。
- 不要假设存在隐藏测试文件；以说明中的行为为准。
- 完成后停止。

# 工作区文件
（由 harness 列出，或 runner 写入 TASK.md）
```

- **S/P/C 必须使用同一 task 字符串**（除 arm 名写入 meta，不进 prompt）。  
- 禁止在 prompt 中粘贴测试用例或断言源码。

---

## 6. Harness / CLI 设置（Runner 必须遵守）

### 6.1 调用入口

| 臂 | 命令形态 |
|---|---|
| S | `python -m harness.run_solo "<task>" --run-dir <harness_run> ...` |
| P | `python -m harness.run_multi "<task>" --run-dir <harness_run> --session-model persistent ...` |
| C | `python -m harness.run_multi "<task>" --run-dir <harness_run> --session-model cold ...` |

`run-dir` 必须指向本 run 的 `harness_run/`，且 **事先不存在**。

### 6.2 共享预算（两臂相同，禁止给 multi 多开步数优势）

正式批冻结示例（可在 `batch_config.json` 改一次后锁定）：

| 参数 | 含义 | 建议默认 |
|---|---|---|
| `--max-calls` | 成功 API 调用上限 | **60** |
| `--max-tokens` | prompt+completion 累计上限 | **200000** |
| `--max-seconds` | 协作式墙钟上限 | **300** |
| `--max-steps` | **单次 loop/activate 步数**，非总预算 | solo **40**；multi 每阶段默认与现网一致，但 **总消耗仍受 max-calls/tokens/seconds 约束** |
| multi `--max-rounds` | 验证打回轮数 | **3** |

规则：

1. **S 与 P（与 C）必须同一套 max-calls / max-tokens / max-seconds。**  
2. 禁止「只给 multi 更大 max-steps、却不设 max-calls」的不公平配置。  
3. 预算耗尽 → harness 应收口为 escalated/budget 类 outcome；runner 仍跑 pytest（通常 FAIL），计入样本。  
4. `provider.md` 全批同一模型；`batch_config.json` 记录 model 字符串。

### 6.3 环境变量与密钥

- 仅 runner/harness 读 `provider.md`；**禁止**拷入 workspace。  
- agent 的 bash **不应**被设计成读取仓库根密钥（已知 bash 沙箱弱：正式结论需知悉该限制；本协议 **不假装** 已 Docker 隔离）。

### 6.4 网络

- 默认：任务与测试 **不需要外网**。  
- agent 若 curl 外网：不额外加分；正式批可在文档声明「不禁止但不依赖」。  
- 不把「能上网」当通过条件。

### 6.5 并发

- Pilot：串行，一题一臂跑完再下一。  
- 正式：默认可串行；若并行，**禁止**共享 workspace；每 run 独立目录与独立进程。

### 6.6 随机顺序

- 每个 `slug` 的一个 block 内，臂顺序由 **batch seed** 洗牌（如先 P 后 S 或相反），写入 config。  
- 避免总是先跑完所有 S 再跑 P 带来的时间/额度偏差。

---

## 7. Runner 实现规格（给写代码的人）

### 7.1 建议入口

```text
python scripts/aider_polyglot_runner.py \
  --batch-id pilot-001 \
  --exercises-root third_party/polyglot-benchmark \
  --tasklist docs/native-harness/aider-polyglot-tasklist.md \
  --arms S,P \
  --reps 1 \
  --max-calls 60 \
  --max-tokens 200000 \
  --max-seconds 300 \
  --session-model-p persistent
```

（文件名可调整，但 CLI 语义应覆盖上表。）

### 7.2 必做行为

| # | 行为 |
|---|---|
| R1 | 启动时记录 polyglot-benchmark 的 git SHA 与 harness 代码 git SHA |
| R2 | run 目录已存在 → **立即失败**，不覆盖 |
| R3 | agent workspace **剥离** `*_test.py` 与测试夹具中明确标为 hidden 的材料 |
| R4 | 调用 harness 前后校验 `summary.json` 存在 |
| R5 | pytest 超时（如 60s）→ FAIL，`error=pytest_timeout` |
| R6 | 任何异常 → 该 run FAIL 并写 error，**不中断整批**（除非 `--fail-fast`） |
| R7 | 输出 `results.jsonl` + `results.csv` |
| R8 | 不修改 `third_party/polyglot-benchmark` 源树（只读拷贝） |

### 7.3 禁止行为

| # | 禁止 |
|---|---|
| X1 | 把测试文件放进 agent prompt 或 workspace |
| X2 | 因 FAIL 而改测试或改题面 |
| X3 | 复用上一 run 的 workspace |
| X4 | S/P 使用不同 model 或不同 max-calls |
| X5 | 用 harness `outcome=done` 代替 pytest 作为主指标 |
| X6 | 在正式批中途改 task 模板或 system prompt |

### 7.4 result.json schema（最小）

```json
{
  "batch_id": "pilot-001",
  "task_slug": "example-slug",
  "arm": "S",
  "rep": 1,
  "pass": false,
  "pytest_exit": 1,
  "harness_outcome": "natural",
  "calls": 0,
  "prompt_tokens": 0,
  "completion_tokens": 0,
  "duration_ms": 0,
  "run_dir": "runs/aider/pilot-001/tasks/example-slug/S_r1",
  "error": null,
  "polyglot_sha": "...",
  "harness_sha": "..."
}
```

---

## 8. 批次类型

### 8.1 Pilot（开发用）

- 目的：打通 runner、估成本、修同步规则  
- 题：≤5，**不得**进入正式题清单  
- 结论：只写 engineering note，**不写「P 优于 S」科学结论**

### 8.2 正式批（可写结论）

- 题清单 + SHA + 预算 + prompt 模板 **预先冻结**  
- 完整 intention-to-treat 表  
- 结论仅允许 §3.5 三类之一  

### 8.3 与 M4 协议关系

- M4（复杂 fixture / Terminal-Bench 等）**并行存在**，不互相替代。  
- 本协议是 **无 Docker 条件下的公开题对比**；M4 仍可服务更重隔离实验。  
- 控制文件 `NEXT.md` 可同时挂两条线：本协议 pilot / M4 BLOCK 项。

---

## 9. 执行检查清单（开跑前）

- [ ] 已 clone `polyglot-benchmark` 并记录 SHA  
- [ ] 本机 `python -m pytest --version` 可用  
- [ ] Pilot 5 题手动：stub 测挂、同步假实现测过（抽 1 题）  
- [ ] agent workspace 中 **无** `*_test.py`（抽查）  
- [ ] S/P 的 max-calls/tokens/seconds 一致  
- [ ] `provider.md` 可用且不在 workspace  
- [ ] batch_config 已写入  
- [ ] 正式批：题清单已冻结且无 pilot 污染  

---

## 10. 报告模板（跑完最小集）

```markdown
# Aider Polyglot Solo vs Multi — <batch_id>

- polyglot SHA / harness SHA
- model / 预算
- N 题 × 臂 × 重复

## 通过率
| 臂 | PASS | 总数 | 率 |
| S | | | |
| P | | | |

## 成本均值
| 臂 | calls | prompt tokens | 墙钟 |
...

## 题级明细
（表）

## 结论（仅三类之一）
支持 P / 不支持 P / 证据不足

## 局限
- 非 Aider 官方 harness；无 Docker 隔离
- bash 沙箱非 OS 级
- 仅 Python 子集
```

---

## 11. 版本与变更

| 版本 | 日期 | 说明 |
|---|---|---|
| 0.1 | 2026-07-10 | 初稿：无 Docker、Aider 题库、runner 规则、S/P 对比 |

冻结正式题清单时 bump 为 **1.0**，并锁 §3.5 阈值与附录 slug 表。

---

## 附录 A. 参考命令（人工 smoke，runner 未就绪时）

```bash
# 1) 题库
git clone https://github.com/Aider-AI/polyglot-benchmark third_party/polyglot-benchmark

# 2) 假设已手工准备 agent_workspace 与 task 文本
python -m harness.run_solo "$(cat task.txt)" --run-dir runs/aider/smoke/S --max-calls 60 --max-seconds 300

python -m harness.run_multi "$(cat task.txt)" --run-dir runs/aider/smoke/P --session-model persistent --max-calls 60 --max-seconds 300 --max-rounds 3

# 3) 同步实现到 judge 后
cd path/to/judge && python -m pytest *_test.py -q
```

## 附录 B. 实现状态

| 项 | 状态 |
|---|---|
| `scripts/aider_polyglot_runner.py` | ✅ 已实现（含 `--dry-run`） |
| `harness` `--seed-dir` / `harness.seed` | ✅ 预置 stub 进 workspace |
| Pilot 题清单（5 题） | ✅ `aider-polyglot-tasklist.md` |
| 正式 15 题表 | ⏳ 待冻结 |
| Live pilot（真 LLM） | ⏳ 需 `provider.md` + 额度 |
| 正式批报告 | ⏳ |

离线验收：`python scripts/aider_polyglot_runner.py --batch-id dry-… --dry-run` 应对 pilot 题 5/5 PASS。

---

**文档状态**：协议 + runner 规则已落地；live 对比仍待授权后跑。
