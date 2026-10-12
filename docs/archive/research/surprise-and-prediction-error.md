# 惊讶与预测误差：参照调研

日期：2026-09-25。用途：为 [D25 语义系统](../requirements/semantic-system.md)「TODO：惊讶机制与教训发现模块」专题讨论提供参照。本文只记录查证到的定义、机制与出处，没有运行或复现这些系统。论文地址格式为 `https://arxiv.org/abs/<编号>`；网络来源的访问日期均为 2026-09-25。

## 1. 惊讶的定义与学习的关系

- **惊讶值（surprisal）**：一个结果的概率取负对数，即 −ln p(o)，结果越不可能，惊讶值越高。自由能是惊讶的上界，主体最小化自由能，也就间接压低了惊讶；感知通过更新信念减小预测误差，行动通过改变采样减小预测误差。出处：Friston 2010，Nat Rev Neurosci，doi:10.1038/nrn2787，第 2 页术语表与 Box 1。
- **惊讶与学习**：同文第 6 页「The cell assembly and correlation theory」一节，状态推断（感知）与参数推断（学习）都在最小化预测误差。
- **学习的计数方式**：Friston 等 2016，doi:10.1016/j.neubiorev.2016.06.022，§2.1、§2.4。模型参数是 Dirichlet 浓度参数，数值等于过去观察到的共现次数，每轮试验结束后累加，经常出现的状态会主导后验。
- **贝叶斯惊讶**：Itti 与 Baldi，NIPS 2005，§1。
  - 定义为观察前后信念分布的 KL 散度：S(D,M) = KL(P(M|D), P(M))。数据不改变信念，就没有惊讶；惊讶的大小取决于先验。
  - 离群点与惊讶不同：一个数据在两个候选假设下都极不可能时，它是强离群点，却几乎不能区分这两个假设，惊讶很小。按离群点检测会把它当成重要数据，造成误报。
  - 引言引用已有研究：惊讶是学习与记忆形成的核心，被认为是联想学习的必要触发条件。

## 2. 大模型记忆中用惊讶决定记什么

| 方法 | 惊讶的定义与用法 | 需要的内部信息 |
| --- | --- | --- |
| EM-LLM（2407.09450v3，ICLR 2025） | §3.2：惊讶为 −log P(x_t \| x_1..x_{t−1})，超过阈值 μ+γσ（滑动窗口的均值与标准差）的词元成为候选事件边界；§3.3 用注意力键的相似度细化边界；§3.4 按相似度与相邻关系取回事件，放进每层注意力的上下文 | 输入词元的概率、各层注意力键、KV 缓存；§4 使用开放权重模型 |
| Titans（2501.00663v1） | §3.1：动机是「违背预期的事件更容易被记住」；惊讶为关联记忆损失的梯度；更新时同时保留过去的惊讶（动量项）与当前的惊讶，并有遗忘项。单独保留过去的惊讶，是因为连续几次大的惊讶之后梯度变小，后面的信息会漏记 | 测试时用梯度更新记忆模块的参数；一种新的模型结构，§5.1 从头训练 170M 至 760M 参数 |
| Nemori（2508.03341v1） | §3.2 Predict-Calibrate，受自由能原理启发：先用已有的语义记忆预测一段对话的内容，再与原文比较，只把没有预测到的部分提炼成新知识；§4.3 消融：gpt-4o-mini 下预测后校准 0.615，直接抽取 0.518（由 LLM 评分） | 只通过 API 调用模型（§4.1.4：gpt-4o-mini、gpt-4.1-mini） |

只通过 API 调用模型时，EM-LLM 与 Titans 需要的内部信息取不到：Anthropic 不返回 token 概率，OpenAI 只返回输出词元的概率（第 5 节），所查的 API 参数中没有注意力、KV 缓存或梯度相关的字段。

## 3. Agent 执行前写出预期、执行后比较

- **PreAct**（2402.11534v2）：§2.2 要求模型每一步都预测后续观察，并把预测保留在历史中；附录 B.1 的提示词规定，实际反馈不在预测范围内时，要在下一轮思考中分析差异原因，并据此修改计划。实验使用 GPT-3.5 与 GPT-4 的 API。
- **WebDreamer**（2411.06559v2，只读摘要）：用 LLM 作为世界模型，在执行前模拟每个候选动作的结果，再选定动作。执行后是否比较预测与实际：未查证。
- **Voyager**（2305.16291v2）：§2.3 有环境反馈、执行错误、自我验证三类反馈；另一个 GPT-4 作为评审判断任务是否完成，评审确认成功后程序才加入技能库，最多尝试 4 轮。
- **Generative Agents**（2304.03442v2）：§4.1 由 LLM 给每条记忆的重要性打 1 至 10 分；§4.2 最近事件的重要性总和超过 150 时生成反思。打分看事件本身的重要程度，与预期偏差无关。
- 成熟 Agent 产品中是否有这类机制：未查证。

## 4. 从失败中提取教训，以及怎样避开偶然失败

- **Reflexion**（2303.11366v4）：
  - §3：执行者、评估者、自我反思三个模型；每次试验后把反思文本加入记忆，记忆最多保留 1 至 3 条。
  - §4.1：同一动作得到同一回应超过 3 次，或动作超过 30 步，就触发反思。
  - §4.3：自己生成的测试可能不可靠，MBPP 上的误报率为 16.3%；§5 列出非确定性函数、调用外部 API 的函数等难以用测试准确描述的情况。
  - 没有专门区分偶然失败的机制。
- **ExpeL**（2308.10144v3）：
  - §4.1 用 Reflexion 式的重试收集成功与失败轨迹。
  - §4.2 比较同一任务的失败与成功轨迹，以及多个任务的成功轨迹，对洞见执行新增、编辑、赞成、反对：新洞见计数从 2 开始，赞成或编辑加一，反对减一，归零即删除；原文说明这样更稳健，因为成功轨迹也可能不是最优，会误导洞见。
  - §4.3 评估时把洞见拼进任务说明，并取回相似的成功轨迹作为示例。
- **CLIN**（2310.10134v1）：
  - §3.2 每次试验后写成「X 是 Y 的必要条件」或「X 对 Y 没有贡献」的因果抽象，用「may」「should」表示不确定性的高低；更新记忆时输入最近一次试验，以及最近三次试验的记忆。
  - §3.3 生成跨任务记忆时，只取以往表现最好的试验的记忆。

## 5. 各家 API 是否返回 token 概率

| 协议 | 是否返回 | 出处 |
| --- | --- | --- |
| Anthropic Messages | 不返回 | `https://platform.claude.com/docs/en/api/messages.md` 全文没有 logprob；OpenAI 兼容层文档把请求中的 logprobs、top_logprobs 列为 Ignored，响应中的 logprobs 列为 Always empty（`https://platform.claude.com/docs/en/api/openai-sdk.md`） |
| OpenAI Chat Completions | 返回输出词元的对数概率；top_logprobs 取 0 至 20 | openai-python 提交 `6e4a79c`，`src/openai/types/chat/completion_create_params.py:110-115,351-357` |
| OpenAI Responses | 返回；在 include 中加 `message.output_text.logprobs`，top_logprobs 取 0 至 20 | 同一提交，`response_create_params.py:80,307-312`、`response_includable.py:15`、`response_output_text.py:107-116,131` |

developers.openai.com 访问失败（TLS 错误），OpenAI 部分以官方 SDK 源码为准。推理模型是否支持 logprobs：未查证。

## 6. 本地参考实现

- **OpenCode**（提交 `0027387`）：没有找到相关机制。
- **OMP**（提交 `fdfeef1f78`，下文路径在 `packages/coding-agent/src/` 下）：没有基于惊讶值或预测误差的机制，相关的有：
  - **sharpshooter 记忆**：`prompts/memories/sharpshooter-consolidate-system.md:5-13` 规定记忆靠「摩擦」进入，只有出过回归、从代码上看不出来、或跨会话被纠正两次以上的决定才写入；只出现一次、之后没有再出错的决定不写入，理由是「storing detail from a single exchange is how factually wrong memories are born」。三个标签 corrective、regression、subtle 定义在 `sharpshooter/types.ts:25-37`；`sharpshooter/extract.ts:262-265` 要求证据必须是用户当前输入的原文子串，否则拒绝。
  - **learn 工具**：`tools/learn.ts:9-18,51-96`，由模型主动调用，把教训写入长期记忆；`autolearn/controller.ts:21,113-115` 规定一轮对话中工具调用不少于 5 次时才可以自动运行记录回合。
  - **执行前的预期输出**：`prompts/system/prewalk-plan.md:5` 要求计划写出验证命令和预期输出；没有找到执行后自动比较预期与实际的代码。
  - **mnemopi**：`packages/mnemopi/src/core/typed-memory.ts:188-198` 用正则表达式把含「lesson」「surprisingly」「turns out」等词的文本归为 learning 类型。
