---
name: trial
description: 试用 Yudao：像真实用户一样使用一个从 main 打包安装的实例，分新手段（只读 README 与页面，边做边说）与专家段（读导出，把每处卡点追到具体一步），跑一个评测场景的固定任务与一个有歧义、中途改主意、离开再回来的模拟用户任务；交付交给 evals 的隐藏检查打分并与单 agent 对照，问题经查重、换路复测与另一个模型的独立复现才进列表，合成一篇帖子发到 GitHub Discussions 的 General 分类。试用的过程不改被测对象。
argument-hint: "[备注，例如「只跑固定任务」]"
---

# 试用

试用回答四个问题，每个问题只用一种证据：

| 问题 | 证据 | 谁判断 |
| --- | --- | --- |
| 交付得好不好 | `evals/scorer` 的隐藏检查，Yudao 与单 agent 各一份 | 评分器 |
| 新手能不能自己走通 | 新手段带时间戳的出声记录 | 新手段记录，专家段核对 |
| 改了主意、离开再回来，还接得住吗 | 模拟用户任务的事件与页面状态 | 专家段 |
| 卡住时查得出原因吗 | 专家段把卡点追到具体一步，以及花了多久 | 专家段 |

成本（墙钟、请求数、用量、费用）是读数，不另成维度。试用 agent 不自己判断交付对错，也不评论代码风格。

试用的对象是从 main 打包安装的实例。试用过程只读被测对象：不改 Yudao 源码与仓库工作树、不提交、不当场修缺陷、不建工单、不动规则文件与设计说明。可以改试用者自己环境的配置（Provider、凭据）。

## 1. 准入与预算

逐项查，缺项就停，不降级硬跑：

| 需要什么 | 怎么查 |
| --- | --- |
| 这一次用的模型：Yudao 部门、试用 agent、复现 agent 各用哪个服务与模型 | 开始前问试用者，不沿用上一次，也不从固定的环境变量或配置文件取；凭据由试用者当场给出 |
| 三方的模型互不相同 | 对照三方的模型名；有相同的就停，两边的错误会一起漏掉 |
| Python ≥ 3.11、uv、Git、Node ≥ 22.12 | `--version`；没有 Node 就没有页面，新手段做不了 |
| 能操作浏览器的工具，另有第二个浏览器用于换路复测 | 试用环境的工具列表 |
| 检出干净、在 main 上 | `git status --porcelain`、`git rev-parse --abbrev-ref HEAD` |
| `gh` 已登录 | `gh auth status`；没登录，帖子停在草稿 |

预算（一次一轮，多轮留给以后的 benchmark 优化）：

| 部分 | 上限 |
| --- | --- |
| 安装与准备 | 15 分钟 |
| 固定任务 F1 | 90 分钟（与评测一致） |
| 模拟用户任务 R1 | 45 分钟 |
| 专家段与评分 | 30 分钟 |
| 独立复现 | 30 分钟 |

合计约 3.5 小时，另有试用 agent 自己操作浏览器与记录的用量。开始前把预计的时间与模型调用告诉试用者。超预算时按这个顺序砍，砍掉的写进帖子：

1. R1 只做「离开再回来」，不做第二句改主意；
2. 独立复现只做排在前面的问题，其余标「未经复现」，进观察。

F1 与新手段不砍。单 agent 一侧条件相同时复用已有读数（第 6 节），本来就不重跑。

## 2. 判据先核对

判缺陷之前，先读 `docs/decision.md` 中上一篇试用帖子以后的用户决定，再核对 [任务集](../../../docs/trial/tasks.md) 的判据与本文第 5 节的分类是否还有效。与用户决定冲突的判据不用，在帖子里写明是哪一条、被哪个决定取代。

例：2026-10-22 用户决定页面直接显示原始标识与原文。页面上出现 `provider_unavailable`、英文报错原文都不是缺陷。

## 3. 试用实例

记下试用者已有的安装（`yudao --version`、`uv tool list`），然后从 main 构建 wheel，装进仓库外的独立虚拟环境：

```bash
git rev-parse HEAD
uv run python scripts/release.py          # 输出 wheel 路径与 SHA-256
uv venv <仓库外目录>/trial-venv
uv pip install --python <仓库外目录>/trial-venv/Scripts/python.exe <wheel 路径>
<venv>/Scripts/python.exe -m harness api --data-dir <仓库外目录>/trial-data --port 8766
```

Windows 的解释器在 `Scripts\`，其他系统在 `bin\`。不用默认数据目录。构建失败就停：源码直跑没有页面文件。

## 4. 新手段

新手段只读 README 与页面，**不读 `docs/`、不调接口、不看导出**，也不用本文第 5 节以后的知识。从第一次打开页面开始，在页面上用试用者这一次给的服务与凭据配置模型（「模型管理」），这一段也算在内。任务的输入由试用者事先准备好（任务集「准备」一节），粘贴进页面。

每一步记一行，写进归档目录的 `novice.md`：

| 时间 | 看到什么 | 以为会怎样 | 实际怎样 | 犹豫或猜错 | 四问 |
| --- | --- | --- | --- | --- | --- |

四问是认知走查的四个问题，每步都过，答「否」的写出来：

1. 知不知道这一步要做什么？
2. 看不看得到能做这件事的地方？
3. 能不能把它和自己的目标对上？
4. 做完能不能看出事情在推进？

等部门工作时每 2 分钟看一次页面，一次算一步。有一问答「否」、或者犹豫、猜错的一步，就是一处**卡点**。新手段只记录，不解释原因。

## 5. 专家段

两个任务的新手段都结束以后，才打开 `run.export`、`run.attempt`、`project.attempts`、`run.asks`、`run.recovery`、`replay.check`。请求体以 `GET /api/openapi.json` 为准。

逐处卡点，按时间戳对到事件，归到一类，并记下定位用了多久：

- **该说的结论没说**：状态没显示；读取失败说成没有内容；原因说错了；没给下一步；结论没有范围（比如放行没说覆盖了哪些要求）。
- **系统出错**：事件里有错误、空转、状态讲不通。
- **试用者误解**：页面说清楚了，是新手段看漏了。不进问题列表。

定位不到具体一步的卡点，本身记一条「查不出原因」，属于可诊断的问题。

另做一次机械扫描：把导出写到文件，搜 `key`、`token`、`password`、`Authorization`、盘符开头与 `/home/` 开头的路径。命中就是问题。

## 6. 读数与对照

读数用 `evals/runner/yudao_metrics.py` 的 `collect(export, outcome, replay)` 算。`outcome` 写 `{"timed_out": ..., "elapsed_seconds": ..., "hidden_failures": [评分器里失败的检查]}`，`replay` 是 `replay.check` 的返回。用量没上报的写「未知」，不算 0。

F1 的交付按评测运行器的方式取回，再交给评分器：

```bash
uv run python -c "import sys, json; sys.path.insert(0, 'evals/runner'); import yudao; e = json.load(open('<导出文件>', encoding='utf-8')); print(yudao.fetch_delivery(yudao.YudaoClient('http://127.0.0.1:8766'), yudao.last_archived_delivery(e), '<交付目录>'))"
uv run python evals/scorer/scorer.py --delivery <交付目录> --result <结果文件>
```

**单 agent 对照**：材料版本、模型、OpenCode 版本都与已有读数相同时，复用 `docs/evaluation/` 下最近的一份 OpenCode 结果，写明出处；不同时，用 `evals/runner/run_eval.py --scenario scenario3 --runs 1` 跑一次，模型与 Yudao 三个部门相同；运行器从环境变量读服务（`evals/README.md`「运行一次评测」），在这次运行的进程里用试用者给的值设置，不写进文件。Yudao 一侧的历史读数也在同一目录，同样写明可不可比。对照只做 F1。R1 要停服务、追加输入，单 agent 的一次性运行做不了同样的操作。

## 7. 问题的门槛与排序

一条问题进列表之前过三道：

1. **查重**：`gh issue list --state open --limit 300 --json number,title,body`，逐条比。重复的，在原工单下评论补证据（脱敏规则同第 9 节），不进列表，在帖子里列出补了哪几张。
2. **换路复测**：换浏览器、换新数据目录，或者改用接口做同一件事。换了路就不出现的，归为试用环境的问题，写进「环境与前提」。
3. **单独复现**：在全新实例上照复现步骤再做一次。

每条问题写：编号 `T<提交短号>-NN`、标题、复现步骤、期望、实际、证据（run id、事件 id、截图、命令与输出）、专家段的分类。另外标三样，按这个顺序排：

- 影响：挡住目标 > 拖慢 > 只干扰；
- 能不能绕过：不能 > 能（写明代价）；
- 频率：两段、两个任务、两条路中一共出现几次。

偏好、猜测、main 上还没承诺的能力进「观察」，不进问题列表。

## 8. 建议与独立复现

每条建议写四样：挡住了用户的哪个目标；证据（链到问题编号）；与单 agent 对照是更好、更差、看不出差别还是不可比；对应路线图「进入可迭代状态」五条判据中的哪一条（有负载、能度量、改动便宜可撤回、看得见、锚点受保护）。对不上任何一条的不写成建议。

**独立复现**：帖子发出之前，用 omp 起一个 agent，模型用试用者这一次指定的复现模型（命令写法见 [运行配置](../../../docs/agents/autopilot-runtime.md) 的审查者一行，用 `--model` 指定）。只给它帖子草稿里每条问题的复现步骤、同一个 wheel 与一个全新数据目录，不给本次的记录与结论。复现不了的问题降为观察，并写明原因。

## 9. 帖子

一次试用一篇，发到 Discussions 的 **General** 分类（仓库 `bender2333/yudao`，仓库 id `R_kgDOSpFnRw`，分类 id `DIC_kwDOSpFnR84DIxLV`）。标题：`试用：<一句话结论> — <提交短号> <任务集版本>`。

```
本帖由 Yudao 仓库的 /trial skill 生成与发布，试用过程由 agent 执行。

## 环境与前提
系统、Yudao 版本与 main 提交、部门模型、试用 agent 模型、复现 agent 模型、任务集与材料版本、耗时、用量、费用、砍掉的部分、试用环境的问题、不再使用的判据

## 交付与对照
F1 两边的评分（完成度、正确性、做错与没做的检查）与读数

## 新手段
两个任务的卡点表（时间、哪一步、四问中答「否」的）

## 专家段
每处卡点的原因、分类与定位用时；R1 的过程事实

## 问题
排好序的列表，每条带编号与第 7 节各项；补过证据的已有工单

## 建议
每条带第 8 节的四样

## 观察
降级的问题、偏好、未承诺的能力、没测到的部分

## 命中率
上一次的问题编号回查结果（第 10 节）
```

**脱敏**，逐条机械检查：绝对路径换成 `<数据目录>`、`<仓库>`、`<运行目录>`；不出现用户名、机器名、主机名、内网地址；不出现凭据、Key、`.env` 内容、Authorization 头；材料片段不超过 20 行；截图检查地址栏、标签页标题、路径与账号名。保留提交号、run id、事件 id、版本号。

**发帖**用试用者自己的 `gh` 账号。标题写进 `title.txt`，正文写进 `body.md`，都用 UTF-8 无 BOM。PowerShell 下查询用变量形式：

```bash
# 找上一篇「试用：」帖子
gh api graphql -F owner='bender2333' -F name='yudao' -F first=50 \
  -f query='query($owner:String!,$name:String!,$first:Int!){ repository(owner:$owner,name:$name){ discussions(first:$first, orderBy:{field:CREATED_AT, direction:DESC}){ nodes { number title url createdAt category { name } } } } }' \
  --jq '.data.repository.discussions.nodes[] | select(.category.name=="General" and (.title|startswith("试用："))) | "\(.number)\t\(.url)\t\(.title)"'

# 发帖
gh api graphql -f query='mutation($repo:ID!,$cat:ID!,$title:String!,$body:String!){ createDiscussion(input:{repositoryId:$repo, categoryId:$cat, title:$title, body:$body}) { discussion { number url } } }' \
  -f repo='R_kgDOSpFnRw' -f cat='DIC_kwDOSpFnR84DIxLV' -F title=@<草稿目录>/title.txt -F body=@<草稿目录>/body.md

# 读回核对标题、分类与正文长度
gh api graphql -F owner='bender2333' -F name='yudao' -F n=<编号> \
  -f query='query($owner:String!,$name:String!,$n:Int!){ repository(owner:$owner,name:$name){ discussion(number:$n){ id title url category { name } body } } }'

# 改正文
gh api graphql -f query='mutation($id:ID!,$body:String!){ updateDiscussion(input:{discussionId:$id, body:$body}) { discussion { url } } }' -f id=<讨论的 id> -F body=@<草稿目录>/body.md
```

发帖失败时，帖子停在草稿，把文件与命令交给试用者，不用别的账号代发。发完回报链接，并说明帖子可以自己改或删。

## 10. 命中率

维护者把问题转成工单时，在工单正文里写上问题编号。下一次试用读上一篇帖子的问题列表，逐条查 `gh issue list --state all --search "<编号>" --json number,state,stateReason`：

- **确认**：工单按完成关闭；
- **误报**：工单按 `not planned` 或 `wontfix` 关闭，或者维护者在帖子下说明不成立。另记原因，比如判据过期；
- 还开着、或者没建工单的，不计。

命中率 = 确认 ÷（确认 + 误报），写进帖子，和以前几次的数字放在一起。任务集版本不同的两次，读数不比较，命中率照算。

## 11. 本地归档

原始材料留在仓库外，不进版本控制：`.yudao/trial/<提交短号>-<年月日-时分>/`。里面放：`novice.md`、每个任务的 `run.export`、评分结果、截图、复现 agent 的输出、草稿与发帖回执。清理时只删这次建的虚拟环境与数据目录。
