---
name: trial
description: 试用 Yudao：像真实用户一样用一个从 main 打包安装的实例，分新手段（只读 README 与页面，边做边说）与专家段（读导出，把每处卡点追到具体一步），跑一个评测场景的固定任务与一个配错凭据、有歧义、中途指导、离开再回来、改主意的模拟用户任务；交付交给 evals 的隐藏检查打分，画面对账、报错对账与覆盖核对逐条做，问题经查重、换路复测与另一个模型的独立复现才进列表，合成一篇帖子发到 GitHub Discussions，并把需要用户先定的事摆出来。试用的过程不改被测对象，也不建工单。
argument-hint: "[试用工单号] [备注，例如「只跑固定任务」]"
---

# 试用

这份技能是一份能照做到底的运行手册：从核对环境到发出帖子，每一步都有命令、有判据、有产出文件。读它的人是架构师会话，动手的是它起的几个子代理。工具命令集中在第 13 节。

试用回答六个问题，每个问题只用一种证据：

| 问题 | 证据 | 谁判断 |
| --- | --- | --- |
| 交付得好不好 | `evals/scorer` 的隐藏检查 | 评分器 |
| 新手能不能自己走通 | 新手段带时间戳的出声记录 | 新手段记录，专家段核对 |
| 配错凭据、中途指导、改了主意、离开再回来，还接得住吗 | 模拟用户任务的事件与页面状态 | 专家段 |
| 卡住时查得出原因吗 | 专家段把卡点追到具体一步，以及花了多久 | 专家段 |
| 画面与事实一致吗 | 关键时刻的直播截图、回放截图、页面读数与事件 | 专家段（第 5 节画面对账） |
| 这个薄片承诺用户能做到的，做得到吗 | 试用工单「用户要能做到」的每一条与证明它的事件 | 专家段（第 5 节覆盖核对） |

成本（墙钟、请求数、用量、费用）是读数，不另成维度。试用不判断交付对错，也不评论代码风格。

试用的对象是从 main 打包安装的实例，试用过程只读被测对象：不改源码与仓库工作树、不提交、不当场修缺陷、不建工单、不动规则文件与设计说明。可以改的是试用环境自己的配置（服务地址、凭据、数据目录）。

## 1. 准入与预算

开始前把这几件摆到桌面上，缺一项就问，不猜、不沿用上一次：

| 要什么 | 为什么要 | 谁来给 |
| --- | --- | --- |
| 试用工单号 | 覆盖核对对照它的「用户要能做到」 | 用户 |
| 两个模型 | `provider.md` 的 model1（`wb/cn:deepseek-v4.1-flash`）给产品与工程，model2（`ag/gemini-3.8-flash-high`）给质检与看图；被试部门的毛病不会被同一双眼睛复制 | 已在 `provider.md`，这个文件被 git 忽略，内容不进帖子 |
| 服务地址与 Key | 部门跑真实模型；演练配错凭据用的就是它；只从环境变量读 | 用户，当场给，不写进文件与日记 |
| 时间窗 | 一次约 4 小时 45 分，中途不能被打断 | 用户确认什么时候开始 |
| 发现的问题怎么处置 | 本技能只把问题写进帖子，不建工单 | 用户决定要不要转成工单 |

环境逐项查，缺项就停，不降级硬跑。命令是第 13 节那条 `preflight.ps1`，级别为「阻断」的补齐了才往下走，「警告」记进帖子的「环境与前提」。

预算（一次一轮，多轮留给以后的 benchmark 优化）：

| 部分 | 上限 |
| --- | --- |
| 安装与准备 | 25 分钟（上次实测，原估 15 分钟） |
| 固定任务 F1 | 120 分钟（与评测一致） |
| 模拟用户任务 R1 | 55 分钟 |
| 专家段与评分 | 50 分钟（含画面对账） |
| 覆盖核对的补做 | 15 分钟 |
| 独立复现 | 30 分钟 |

合计约 4 小时 45 分，另有子代理自己操作页面与记录的用量。超预算时按这个顺序删减，删掉的部分写进帖子：

1. 覆盖核对不补做，没覆盖到的写进「没测到的部分」；
2. R1 只做「离开再回来」，不做第二句改主意；
3. 独立复现只做排在前面的问题，其余标「未经复现」，进观察。

F1 与新手段不删减。单 agent 一方不跑（第 6 节），预算里没有它。

**谁动手**。三段各起一个子代理，每个只看得到自己那一段需要的东西；会让它预先知道答案的材料不给它：

| 子代理 | 模型 | 给什么 | 不给什么 | 产出 |
| --- | --- | --- | --- | --- |
| F1 新手段 | model2 | 起始文件夹路径、输入文本路径、归档目录、[method/novice.md](method/novice.md) | 不给 `docs/`、导出、本文第 5 节以后的任何内容 | `novice.md`、`shots/`、`text/` |
| R1 新手段 | model2 | 同上，任务换成任务集 R1 的步骤与两段指导原话 | 同上 | `novice-r1.md`、`shots/`、`text/` |
| 专家段 | model2 | 两段记录、导出、`errors.log`、试用工单、[method/expert.md](method/expert.md)、[method/probes.md](method/probes.md) | 不给结论与建议，让它自己查 | `expert.md` |
| 看图（`vision.mjs`，不是子代理） | model2 | 截图的绝对路径与要回答的问题 | 不给结论，也不给「这里应该是什么样」 | 每张一段「看到什么」 |
| 独立复现 | model1 | 帖子草稿里每条问题的复现步骤、同一个 wheel、一个全新数据目录 | 不给记录、结论、`expert.md` | 每条一份「复现到 / 没复现到」 |

两个模型时做不到三处互不相同。质检本来就跑 model2，找问题与看图的也是 model2，所以质检自己的输出要靠 model1 的复现子代理去查；产品与工程的输出由 model2 的找问题子代理查。帖子的「环境与前提」里写明这条分工与两个模型的名称。

## 2. 判据先核对

1. 读 `docs/decision.md` 里上一篇试用帖子以后的用户决定，记下与判据相关的几条。
2. 读[任务集](../../../docs/trial/tasks.md)，确认版本与本次要跑的一致（现在 `trial-tasks@3`）。任务集属于评价标准，只由用户修改；试用中觉得任务本身有问题，写进帖子，不在本地改。
3. 与用户决定冲突的判据不用，在帖子里写明是哪一条、被哪个决定取代。

例：2026-10-22 用户决定页面直接显示原始标识与原文。页面上出现 `provider_unavailable`、英文报错原文都不是缺陷。

## 3. 试用实例

记下已有的安装（`yudao --version`、`uv tool list`），然后从 main 构建 wheel，装进仓库外的独立虚拟环境。**用干净克隆构建**：工作区里正在写的东西不能混进包里。

```powershell
git clone --no-tags <仓库地址> $env:TEMP\yudao-trial-src
cd $env:TEMP\yudao-trial-src; git checkout <main 的提交>
uv run python scripts/release.py                 # 输出 wheel 路径与 SHA-256，记进帖子
uv venv $env:TEMP\yudao-trial-venv
uv pip install --python $env:TEMP\yudao-trial-venv\Scripts\python.exe <wheel 路径>
$env:TEMP\yudao-trial-venv\Scripts\python.exe -m harness api --data-dir $env:TEMP\yudao-trial-data --port 8766 --no-browser
```

- 其他系统解释器在 `bin/`；不用默认数据目录。
- 起服务时把当前目录设在仓库之外（`-WorkingDirectory $env:TEMP` 或先 `cd` 出去）。在仓库根目录下运行会导入仓库里的 `harness` 包，页面文件找不到，服务只回「没有页面文件」。
- 一次试用固定一个数据目录，重启服务时用同一个，R1 第 3 步要的就是这一点。
- 不带 `--publish` 时 `release.py` 只核对工作区干净、这个提交在 main 上并已推送、`node` ≥ 22.12，然后构建并输出 wheel 的路径与 SHA-256。带 `--publish` 才打标签、推送并上传 Release，标签已存在会报错。试用一律不加 `--publish`，不改发布脚本。
- 起服务以后核对一次 `http://127.0.0.1:8766/api/capabilities` 返回 200 才继续。构建失败就停：源码直跑没有页面文件。
- 服务进程号、端口、数据目录、wheel 与 SHA-256 写进 `state.md`（第 12 节）。

### 3.1 把两个模型配进产品

页面上做（`#/sys/models`），顺序是：连接 → 凭据 → 模型测试 → 部门默认。实测过的四个坑：

- **凭据引用必须是合法键名**：大写字母、数字与下划线，例如 `MODEL1_KEY`。用连字符的名字（`trial-model-key`）勾「写入 .env」会写坏 `.yudao/.env` 并让服务回 500，之后保存与清除都报「.env 第 N 行键名非法」，只能手工删掉这个文件才恢复（2026-10-28 实测，已作为问题候选记下）。
- **模型测试准入要先过**：没通过的模型不能绑给部门，页面会拒，提示「该模型访问定义尚未通过模型测试准入」。
- **准入记录写得比命令返回晚一两秒**：测完立刻保存部门默认可能被同样的话挡住，等两秒重试即过。
- **质检要图像输入**：质检绑文本模型时页面在「部门默认」下给黄色提醒，说依赖外观的验收条件无法核验。把质检绑到声明了「支持图像输入」的模型，提醒消失。

两个模型分工：产品与工程用 model1；质检用 model2（`ag/gemini-3.8-flash-high`，模型访问定义里把「支持图像输入」勾上）。地址 `https://9router.huiju.asia/v1`，Key 只填进凭据表单，不进帖子、不进日记。

## 4. 新手段

方法与记录格式见 [method/novice.md](method/novice.md)。要点三条：只读 README 与页面；每一步一行，四问都过；觉得不对的地方只记现象，不写原因。

等待期按 [method/probes.md](method/probes.md) 的**页面类**探针做。F1 运行中不做任何打扰；配错凭据、两段指导、停服务与改主意都集中在 R1，按任务集的原话提交，不改写、不加提示。

## 5. 专家段

方法与完成标准见 [method/expert.md](method/expert.md)。六件事：卡点归因、R1 八件过程事实、画面对账、报错对账、覆盖核对、机械扫描与接口类探针。

两个任务的新手段都结束以后才开始这一段，中间不回头看页面。

**看图**：用 `scripts/vision.mjs` 把截图发给 model2，要它逐张说看到什么：有没有内容、布局错位、文字被截断、颜色与对比、按钮在哪、报错长什么样。它的原话记进画面对账那一行的「截图证据」，不转述成结论。要它看图之前不给它期望的样子。

```powershell
$env:YUDAO_VISION_API_KEY = <Key>
node .claude\skills\trial\scripts\vision.mjs --image shots/models.png --prompt "页面每个区块的标题与字段逐条抄下来；有没有红黄提醒，原文是什么" --max-tokens 1500
```

会话里的看图子代理这条路在这台机器上走不通：`ag/gemini-3.8-flash-high` 在 harness 的模型声明里只有文本输入，子代理调 `read_image` 会回「model does not declare image input」。要让它走通，得在本机 harness 配置里给这个模型加 `inputModalities: [text, image]`；不加就用脚本这条路，同一份 Key、同一个模型。

## 6. 读数与对照

读数用 `evals/runner/yudao_metrics.py` 的 `collect(export, outcome, replay)` 算。`outcome` 写 `{"timed_out": ..., "elapsed_seconds": ..., "hidden_failures": [评分器里失败的检查]}`，`replay` 是 `replay.check` 的返回。用量没上报的写「未知」，不算 0。

F1 的交付按评测运行器的方式取回，再交给评分器：

```bash
uv run python -c "import sys, json; sys.path.insert(0, 'evals/runner'); import yudao; e = json.load(open('<导出文件>', encoding='utf-8')); print(yudao.fetch_delivery(yudao.YudaoClient('http://127.0.0.1:8766'), yudao.last_archived_delivery(e), '<交付目录>'))"
uv run python evals/scorer/scorer.py --delivery <交付目录> --result <结果文件>
```

**单 agent 一方不跑**（用户 2026-10-28 决定）。帖子里的「交付与对照」只写 Yudao 一侧的评分与读数，并写一行「单 agent 对照本轮未运行」，不让读者以为没有差别。R1 要停服务、追加输入，单 agent 的一次性运行本来就做不了同样的操作。

**可比性**：专家段记下部门所用的模型、上下文窗口与输出上限。三样都与评测相同时，F1 的评分可以与同一提交在 `docs/evaluation/` 的场景 3 读数并排列出；有一样不同，读数只在试用之间比较。上一轮的读数与问题编号从上一篇帖子读，不凭记忆。

## 7. 问题的门槛与排序

一条问题进列表之前过三道：

1. **查重**：`gh issue list --state open --limit 300 --json number,title,body`，逐条比。重复的，在原工单下评论补证据（脱敏规则同第 9 节），不进列表，在帖子里列出补了哪几张。
2. **换路复测**：换浏览器、换新数据目录，或者改用接口做同一件事。换了路就不出现的，归为试用环境的问题，写进「环境与前提」。
3. **单独复现**：在全新实例上照复现步骤再做一次，由第 1 节表格里那个复现子代理做。

每条问题写：编号 `T<提交短号>-NN`、标题、复现步骤、期望、实际、证据（run id、事件 id、截图或 `.txt` 文件名、命令与输出）、专家段的分类。另外标三样，按这个顺序排：

- 影响：挡住目标 > 拖慢 > 只干扰；
- 能不能绕过：不能 > 能（写明代价）；
- 频率：两段、两个任务、两条路中一共出现几次。

偏好、猜测、main 上还没承诺的能力进「观察」，不进问题列表。**本技能不建工单**：问题写在帖子里，由维护者决定转成哪几张工单。

## 8. 建议

每条建议写四样：挡住了用户的哪个目标；证据（链到问题编号）；与上一轮的同一项比是更好、更差、看不出差别还是不可比；对应路线图「进入可迭代状态」五条判据中的哪一条（有负载、能度量、改动便宜可撤回、看得见、锚点受保护）。对不上任何一条的，不写成建议。

## 9. 帖子

一次试用一篇，发到 Discussions 的 **General** 分类（仓库 `bender2333/yudao`，仓库 id `R_kgDOSpFnRw`，分类 id `DIC_kwDOSpFnR84DIxLV`）。标题：`试用：<一句话结论> — <提交短号> <任务集版本>`。

```
本帖由 Yudao 仓库的 /trial skill 生成与发布，试用过程由 agent 执行。

## 环境与前提
系统、Yudao 版本与 main 提交、部门模型与看图的模型、哪一段用哪个模型、任务集与材料版本、试用工单号、耗时、用量、费用、单 agent 对照未运行、删减的部分、试用环境的问题、不再使用的判据

## 交付与对照
F1 的评分（完成度、正确性、做错与没做的检查）与读数；单 agent 对照本轮未运行

## 新手段
两个任务的卡点表（时间、哪一步、四问中答「否」的）

## 专家段
每处卡点的原因、分类与定位用时；R1 的八件过程事实；画面对账（每个时刻一行：时刻、事件 id、两方证据、结论）；报错的去向；覆盖核对（试用工单每一条：证明它的事件 id，或「没测到」）

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

**发帖**用用户自己的 `gh` 账号。标题写进 `title.txt`，正文写进 `body.md`，都用 UTF-8 无 BOM。PowerShell 下用文件形式传参：

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

发帖失败时，帖子停在草稿，把文件与命令交给用户，不用别的账号代发。发完回报链接，并说明帖子可以自己改或删。

## 10. 命中率

维护者把问题转成工单时，在工单正文里写上问题编号。下一次试用读上一篇帖子的问题列表，逐条查 `gh issue list --state all --search "<编号>" --json number,state,stateReason`：

- **确认**：工单按完成关闭；
- **误报**：工单按 `not planned` 或 `wontfix` 关闭，或者维护者在帖子下说明不成立。另记原因，比如判据过期；
- 还开着、或者没建工单的，不计。

命中率 = 确认 ÷（确认 + 误报），写进帖子，和以前几次的数字放在一起。任务集版本不同的两次，读数不比较，命中率照算。

## 11. 本地归档与收尾

原始材料留在仓库外，不进版本控制：`.yudao/trial/<提交短号>-<年月日-时分>/`。里面放：两份 `novice*.md`、`expert.md`、`errors.log`、`state.md`、每个任务的 `run.export`、评分结果、`shots/`、`text/`、复现子代理的输出、草稿与发帖回执。

收尾：按 `state.md` 关掉浏览器与服务进程；只删这次建的虚拟环境、干净克隆与数据目录；归档目录留着，帖子发出以后它不再变。

## 12. 断点续跑

一次跑四个多小时，中途会被打断。归档目录里维护 `state.md`，每换一段更新：

```
提交：<短号>  任务集：trial-tasks@3  试用工单：#<号>
wheel：<路径>  SHA-256：<值>
数据目录：<路径>  端口：8766  服务进程号：<号>
浏览器：Chrome @9222、Edge @9223  归档：<目录>
进度：F1 新手段 已完成 / R1 新手段 进行到第 2 步 / 专家段 未完
下一步：<一句话>
读数：F1 <分数> / R1 <八件事实到第几条>
```

被打断以后按它接着做：

- 服务还在跑就不要再起一个，先 `Get-NetTCPConnection -LocalPort 8766` 看进程号。
- 浏览器被关了就重新 `start`，用同一个 `--profile`，登录态与数据目录都不受影响，再 `open`。
- 某一步超过 15 分钟没有进展，记一条「查不出原因」的卡点，跳到下一段，不在这里耗。

## 13. 工具与浏览器通道

环境核对，只读、不改动任何东西：

```powershell
pwsh -NoProfile -File .claude/skills/trial/scripts/preflight.ps1 -Ticket <工单号> -TaskSet trial-tasks@3 -Port 8766
```

它打印「项 / 值 / 级别」，核对仓库与提交、工作区是否干净、git / python / uv / node / npm / gh / omp 的版本、gh 登录的账号、服务地址与凭据是否在环境变量里、三个端口是否空闲、Chrome 与 Edge 是否都在、磁盘余量、试用工单读不读得到、任务集版本。

页面操作、截图、错误收集用 `.claude/skills/trial/scripts/browser.mjs`，不依赖会话里有什么工具：

| 命令 | 用途 |
| --- | --- |
| `start --browser chrome --port 9222 --profile <目录>` | 起专用浏览器；`--browser edge --port 9223` 起第二个，换路复测用 |
| `open --url <地址>` / `tabs` / `stop` | 打开或复用标签页、列标签页、关掉 |
| `text`、`text --css <选择器>` | 取页面文字，存成 `.txt` 作证据 |
| `shot --out <文件.png> --full` | 整页截图 |
| `audit` | 视觉读数：横向溢出、画布是否空白、低对比度文字、图片、被截断的文字、可见元素计数 |
| `click --text <文字>` / `--css <选择器>`、`type`、`press` | 点击、输入、按键 |
| `eval --expr '<JavaScript>'` | 读页面状态（只读） |
| `watch --out <errors.log>` | 后台记录控制台报错与 4xx、5xx 请求，一直跑到被停 |

看图用 `scripts/vision.mjs`（Node 内置模块，不加依赖）：

| 参数 | 说明 |
| --- | --- |
| `--image <文件.png>` | 可以给多张，一次问一件事 |
| `--prompt <要求>` / `--prompt-file <文件>` | 要它看什么、回答成什么形状 |
| `--model` / `--base-url` | 默认 `ag/gemini-3.8-flash-high` 与 `https://9router.huiju.asia/v1` |
| `--max-tokens` | 默认 1200；要它逐条抄整页文字时加到 1500 以上 |

Key 从 `YUDAO_VISION_API_KEY` 读（没设时读 `YUDAO_EVAL_API_KEY`），不写进文件。

两条约定：

- **截图自己看不了就交给 `vision.mjs`**（第 5 节「看图」），给它图片路径与要回答的问题，拿回它看到的具体内容。机械读数（`audit` 的溢出、对比度、截断、画布空白）与它的说法不一致时，以重新看那张截图为准，两边都记进帖子的画面对账。
- 换路复测用第二个浏览器（Chrome 与 Edge 各一个），不用同一个浏览器的第二个标签页。
