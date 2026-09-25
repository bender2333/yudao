# JEV 决策模型：能力边界与在 Yudao 中的用法

> 日期：2026-09-24。用途：支持 [D28 元观察与规则检查部门](../requirements/meta-observer.md) 与 [总体路线图](../program-roadmap.md) Stage 5：运维部门与元观察。
> 阅读范围：通过网页读取第 9 节的七个来源（论文读取了摘要页与 HTML 全文，其余读取网页正文），没有复现任何实验；第 1 至 7 节的数字都是来源报告的结果，全部在英文材料上得到，中文材料上的表现没有公开数据；TypeSafe 自己报告的数字没有独立复现。第 8 节是 2026-09-26 的本地实测，只有 4 条样本。
> 仓库与 Obsidian 笔记中此前没有 JEV 的记录。

## 1. 基本情况

- JEV 是 TypeSafe 在 2026-09-15 发布的决策模型 Jev，TypeSafe 称之为 System One 模型。[V][P]
- 结构：一次并行采样同时得到全部输出，没有逐个 token 生成的过程；训练方法 RLCD 以校准的决策概率为目标。[D]
- 可用方式：TypeSafe 的接口 `POST https://api.typesafe.ai/v1/systemone`，模型路由 `jev-latest`，提供 Python 与 JavaScript SDK；2026 年 9 月处于早期访问阶段，需要排队申请。[D] OpenRouter 也提供 systemone 接口，当前版本 `typesafe/jev-1.13`，别名 `~typesafe/jev-latest`。[O]
- 输入：结构化状态、自然语言说明与带类型的问题；只接受文本。OpenRouter 文档写明状态加问题的上限是 32000 token [O]；另一份使用指南写作状态加最长的问题 32000 token、总计 64000 token [G]。
- 问题类型只有三种：Choice 从最多 255 个选项中选择一个并返回各选项的概率；Score 在 2 至 10 个用文字描述的有序等级上给出位置（可以落在两级之间）、各等级的概率与置信度；Noul 返回陈述为真的概率。[A][B][G]
- 速率上限：每秒 25 万 token，每分钟 1200 次请求。调整阈值时应固定到 `jev-1.13.0`，`jev-latest` 在版本之间可能改变答案。[G]
- 输出：选中的标签、各标签的概率与置信度；不生成文字，也不给出理由。[A][D]
- 时延与价格：单次调用 70 至 500 毫秒；输入每百万 token 0.042 美元，输出不计费。[V][D]

## 2. 擅长的判断

来源 [B] 的作者把 JEV 放在代理运行框架中，在 10 个公开数据集上进行约 22500 次调用，总费用 2.19 美元：

| 判断 | 结果 |
| --- | --- |
| 注入检测（InjecAgent，1105 个样本） | 阈值 0.10 时精确率与召回率均为 100%，误报 0% |
| 重排序（BEIR SciFact） | MRR 从 BM25 的 0.622 提高到 0.843；Hit@1 从 50% 提高到 78.3% |
| 意图分类 | SNIPS 97.9%（7 类）；Banking77 80.3%（77 类） |
| 工具路由 | MetaTool 96.5%；SkillRetBench 的 R@1 从 38.0% 提高到 75.8% |
| 命令拦截 | 危险命令全部拦截，安全命令 98.2% 放行 |

作者的原则：「模型给出校准过的局部判断，控制流程由代码掌握」（Model gives calibrated local judgments; code holds the control flow）。只询问文本中局部可以观察到的内容。[B]

论文 [A] 与 16 个生成式评判和奖励模型评判比较：在一般的偏好判断与有证据依据的事实判断上，JEV 与最强的 LLM 评判相差 3 个百分点以内，费用为对照的 0.36%。

## 3. 不擅长的判断

| 判断 | 结果 | 来源 |
| --- | --- | --- |
| 跨步骤的因果判断（轨迹归因） | AUROC 0.560，接近随机 | [B] |
| 预测哪个模型会失败 | 准确率 51.3% | [B] |
| 核对推导与代码（JudgeBench，对照 GPT-6） | 推理 68.4% 对 95.9%；编程 76.2% 对 97.6% | [A] |
| 抵抗表述更详尽的错误答案（RM-Bench） | 两个答案风格相同时 84.0%，被拒答案表述更详尽时 74.8% | [A] |
| 没有参照材料的评判 | JEV 与对照的 LLM 评判都接近随机，平均最高概率仍为 0.90、0.95、0.96 | [A] |

校准过的模型也会按可以预期的比例出错；在高频路由中，高置信度的错误会在有人查看之前累积，下游程序按错误的结论继续执行。[P]

使用指南 [G] 列出的失败方式：按字面理解，遗漏隐含条件，否定词与范围词只按表面意思处理；不能可靠计数，数量越大误差越大；日期可以提取，排序与比较不可靠；状态中的无关材料越多，准确率越低；说明与判断标准互相矛盾时表现下降；用户可以控制的状态能改变结论。指南的原则：代码能精确计算的内容不交给模型。

## 4. 语言

- 训练以英文为主。韩语检索的 R@1 为 48.9%，英文为 61.5%。[B]
- 论文的实验全部使用英文基准。[A]
- Yudao 的 PRD、交付说明与部门往来以中文为主，JEV 在中文上的准确率与校准情况需要本地验证。

## 5. 状态中的文字与选项顺序

- JEV 把状态当作数据处理，不防备其中的恶意内容；为引导结论而写的内容可以改变结论。Literal 选项与 Enum 成员的顺序也是它看到的内容。[V]
- 实例：判断是否拦截 `rm -rf ~/.ssh` 时，拦截概率为 0.76；在状态中伪造一条声称已预先批准、要求自动放行的字段后，拦截概率下降到 0.48，置信度下降到 0.22。[V]
- LangChain 的中间件把工具输出排除在分类器输入之外，代理取回的内容无法授权它自己的执行。[V]
- Pydantic 的提醒：基于 Jev 的防护应当与确定的检查一起使用。[V]

## 6. 论文与使用者建议的做法

- 级联做法 [A]：置信度达到阈值的结论直接接受，其余升级给更强的评判。阈值 0.9 时升级 34% 的样本，准确率 91.3%，对照 GPT-6 为 91.7%，费用为其 47%；HaluEval 上阈值 0.8 时升级 11%，与 GPT-6 的 98.3% 相同，费用为其 13%。
- 部署清单 [A]：偏好判断按两种顺序各评判一次，取对齐后的平均概率；升级阈值在本地选择集上选取，再在留出的样本上复核，阈值不一定能换用到另一种升级对象；无效输出计为错误；置信度只作为升级信号，要在风格对抗的样本上检查，温度按工作负载分别验证；扩展到新的工作负载之前先做小规模本地验证。
- 使用者的做法 [B]：把一个判断分解成相互独立的多个标准（命令拦截的误报从 14.5% 下降到 1.8%）；多标签路由先用分块的 Choice 产生候选，再用 Noul 逐个核对（多技能 R@1 从 9.0% 提高到 81.0%）。
- 部署前的检查 [V]：每次调用记录状态、问题定义、选项顺序、模型版本与置信度；决策服务使用独立的身份；用调换顺序的选项与对抗文字进行测试；固定模型版本，不使用 jev-latest；明确漏掉升级时的责任；重要决定保留人工检查点。
- 评价 [P]：每个调用位置事先定义正确的决定；记录输入状态、输出决定、置信度与后续结果；抽样比较置信度与真实结果。
- 使用指南的做法 [G]：先取回精确的状态再判断，不填充无关材料；多个问题在一次调用中同时提出；置信度阈值按错误代价分别设定，只读操作的阈值低于有后果的操作；模糊的判断拆成相互独立的维度分别评分，再按可以调整的权重合并。

## 7. 对 Yudao 的含义

- 元观察与规则检查部门只在控制层事先规定的判定点上使用 JEV。讨论中提出的判定点都是带参照材料的局部判断：询问应由哪个部门回答；回答是否回应了询问；新缺陷或新询问是否与之前的重复；缺陷是否引用了 PRD 条目；DeliverySpec 是否逐条覆盖 PRD；部门产出是否越权。
- 跨步骤的进展判断、代码是否正确、没有参照材料的质量判断，交给确定的统计、质检与 LLM。轮次、返工次数、时间先后等可以精确计算的内容由代码计算。
- 判定状态只放与该判定点相关的材料。
- 每个判定点的结果分通过、不通过、不确定三种。控制层事先规定三种结果的去向，推进权留在控制层。
- 判定点启用自动推进之前，用带有标注的中文流转样本选取阈值，再用另一批样本复核；未通过的判定点只记录、不推进。
- 每次判定记录状态、问题、选项顺序、模型版本、概率与置信度；重放使用记录的结果，不重新调用；定期抽样复核。
- 部门产出由模型生成，进入判定状态之前按不可信内容处理，JEV 的判断与确定的检查一起使用。JEV 不生成文字，需要写明理由的发现报告与升级后的判断由 LLM 完成。
- 语义系统的证据核对也使用 JEV：记录事实时判断证据是否支持陈述，属于它擅长的有参照材料的事实判断；只核对外部文档与需要解读的运行输出，阅读代码得出的判断不交给它（[语义系统设计说明](../design/semantic-system.md)第 7.2 节）。
- 接入方式：systemone 接口作为 Provider 模块的一种新协议（按协议划分地址见 ADR-0001，一个连接一种协议见 ADR-0004），在 Stage 4 随证据核对接入；准入以判定点为单位，依靠样本校准。
- 需求与路线：[D28 元观察与规则检查部门](../requirements/meta-observer.md)、[D25 语义系统](../requirements/semantic-system.md)；[总体路线图](../program-roadmap.md) Stage 4 与 Stage 5。

## 8. 本地实测（2026-09-26）

通过用户提供的中转服务调用，路径 `/v1/systemone`，模型 ID `oc/jev-1.13-free`（响应中的模型为 `jev-1.13-free`），请求带 `Authorization: Bearer` 凭据。地址与凭据由用户在 Provider 配置中填写，不写入仓库。

请求：`{"model", "state", "questions": {"<名称>": {"type": "noul", "instructions": "<问题>"}}}`；一次请求可以带多个问题。响应：`{"model", "answers": {"<名称>": {"type": "noul", "noul": <概率>}}, "usage": {"input_tokens", "output_tokens"}, "cost"}`。Noul 只返回陈述为真的概率，没有单独的置信度字段。

| 测试 | 结果 | 用量与耗时 |
| --- | --- | --- |
| 英文：「付款失败三天、正在损失销售」是否紧急 | 0.96 | 输入 290、输出 23 token，1.6 秒（含网络往返） |
| 中文证据（pytest 输出：4 个测试，3 个通过、1 个失败）：「空输入的测试通过了」 | 0.96 | 三个问题同一次请求：输入 500、输出 58 token，1.6 秒 |
| 同上：「全部 4 个测试都通过了」 | 0.01 | 同上 |
| 同上：「报表按金额从高到低排序」（证据没有提到） | 0.26 | 同上 |

三条中文陈述的结果方向正确；证据没有提到的陈述落在中间区域，校准需要选出「支持」与「不支持」两个阈值，中间为不确定。样本只有 4 条，不能代替校准。

## 9. 来源

- [A] JEV-as-a-Judge: Accept When Confident, Escalate When Unsure，arXiv 2609.26550：<https://arxiv.org/abs/2609.26550>，HTML 全文 <https://arxiv.org/html/2609.26550>
- [B] Benchmarking Jev: what a decision model can (and can't) do in an agent harness，DEV Community：<https://dev.to/aitejiu/benchmarking-jev-what-a-decision-model-can-and-cant-do-in-an-agent-harness-20po>
- [V] Companies are putting Jev in charge of AI agent decisions — and prompt injection can influence the verdict，VentureBeat：<https://venturebeat.com/security/companies-are-putting-jev-in-charge-of-ai-agent-decisions-and-prompt-injection-can-influence-the-verdict>
- [O] Jev Documentation，OpenRouter：<https://openrouter.ai/docs/guides/community/jev>
- [D] Jev: TypeSafe's System One Model That Never Hallucinates，DataCamp：<https://www.datacamp.com/blog/system-one-models-jev>
- [P] What is Jev? Why a model that cannot hallucinate can still fail，Prefactor：<https://prefactor.tech/blog/jev-system-one-model-what-it-means-for-agent-evaluation>
- [G] How to Use Jev: A practical guide to TypeSafe's System One model，DEV Community：<https://dev.to/valyuai/how-to-use-jev-a-practical-guide-to-typesafes-system-one-model-g5e>
