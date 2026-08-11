# Open-endedness 形式定义核验

日期：2026-08-11
范围：只核验 Hughes、Dennis、Rocktäschel 等人在 2024 年论文中提出的 observer-relative novelty / learnability 定义，并提取对动态 Harness 有约束力的边界；不修改现有架构。

## 结论

用户给出的概括“持续产生新颖且可学习的产物”基本准确，但“越来越难预测、同时越来越容易理解”容易被误读成逐步单调变化。论文的严格定义是：

1. **新颖性（novelty）**：固定观察者在时刻 `t` 已学得的模型后，对任意未来产物 `X_T`，总能在更远未来找到一个期望预测损失更高的产物 `X_T'`。
2. **可学习性（learnability）**：固定任意目标产物 `X_T`，观察者使用更长的历史后，其期望预测损失必须严格降低。
3. **开放性（open-endedness）**：相对于给定观察者，产物序列当且仅当同时满足上述两项才是 open-ended。

因此，这不是系统脱离观察者后的内禀标签，而是一个至少由 **系统、产物划分、观察者、预测模型、损失函数和观察时域** 共同确定的关系。

## 一手来源与版本

目标论文为：

> Edward Hughes, Michael Dennis, Jack Parker-Holder, Feryal Behbahani, Aditi Mavalankar, Yuge Shi, Tom Schaul, Tim Rocktäschel. **Open-Endedness is Essential for Artificial Superhuman Intelligence**. arXiv:2406.04268v1, 2024.

- arXiv 摘要与提交记录：[arXiv:2406.04268v1](https://arxiv.org/abs/2406.04268v1)
- 官方 HTML 全文：[arXiv HTML](https://arxiv.org/html/2406.04268)
- PDF：[arXiv PDF](https://arxiv.org/pdf/2406.04268)

核验时，arXiv 提交历史只有 `v1`，提交时间为 2024-06-06；arXiv 记录未列 DOI。论文自称 position paper。以下定义均以该版本第 2.1、2.3 节及附录 A.2、B、C 为准。

## 形式定义

系统 `S` 按时间生成产物序列 `X_t`。观察者 `O` 在看过历史 `X_{1:t}` 后，持有统计模型 `\hat{X}_t`，用于预测任意未来产物 `X_T`。预测由损失函数

\[
\ell(\hat{X}_t, X_T) = \ell(t,T)
\]

评价；期望对系统产物中的随机性取值。

### 新颖性

\[
\forall t,\ \forall T>t,\ \exists T'>T:\quad
\mathbb{E}[\ell(t,T')] > \mathbb{E}[\ell(t,T)].
\]

含义是：对固定在历史 `t` 的观察者模型，未来永远还会出现一个比当前目标 `T` 更难预测的产物。

这**不要求**预测损失逐步单调上升，也**不自动推出**损失数值无界；有界但不断出现更高值的序列也可能满足该量词结构。它要求的是未来不存在一个最终的“最难产物”。

### 可学习性

\[
\forall T,\ \forall t<T,\ \forall\ T>t'>t:\quad
\mathbb{E}[\ell(t',T)] < \mathbb{E}[\ell(t,T)].
\]

含义是：对同一个未来目标 `X_T`，增加任何一段历史都必须使观察者严格预测得更好。这比“长期趋势上可学习”强得多。作者在附录 A.2 明确称其为较严格的定义，并提出尚待研究的概率弱化形式：

\[
\mathbb{P}\!\left(\ell(t',T)\geq\ell(t,T)\right)<\delta.
\]

论文没有给出通用的 `\delta` 取值或可直接用于有限实验的统一检验程序。

## Artifact 与 Observer

### Artifact

`artifact` 是系统按时间交给观察者的分析单位，而不是被限定为某种数据类型。论文示例包括训练中的策略、能力或行为检查点、环境与 Agent 的配对、设计和发现。因而“什么算一个产物”、产物时间粒度和表示方式都属于测量协议；改变这些定义，open-endedness 判断也可能改变。

### Observer

观察者通过历史训练或更新自己的统计预测模型，并用选定损失判断未来产物。它可以是个人、人类群体、组织、AI 系统或理想化 oracle。论文要求损失函数平等地比较真实产物与预测，并在不了解被测系统 `S` 的情况下预先固定，否则观察者可以通过重定义关注对象人为制造开放性。

论文把“interestingness”编码在观察者选择的损失函数中，而没有把它设成第三个独立条件。因此，所谓“有意义”只表示观察者选择学习的特征；它本身不保证真实性、效用、安全性或与外部目标一致。

系统可以观察自身。但当观察结果反过来改进生成系统时，论文称该观察者为 **proxy observer**，因为它已不再处于系统外部。对动态 Harness，这意味着内部 surprise detector 可以驱动学习，却不能同时充当无偏的最终证明者。

## 关键限制

1. **新颖性单独不够。** 不可预测的随机切换源可以持续制造惊讶，却因历史不能帮助预测下一分布而不可学习。仅优化 novelty 会奖励噪声或“随机陷阱”。
2. **可学习性单独不够。** 固定分布可以被观察者逐渐学会，但模型收敛后不再产生新的 epistemic uncertainty，因此不具备持续 novelty。
3. **有限观测不能证明无限开放。** 论文定义有限时域 `t,T<\tau`；在该窗口内满足条件称为 finitely open-ended。只有对任意趋向无穷的时域仍成立，才称 infinitely open-ended。任何有限实验最多支持“在时域 `\tau` 内观察到开放性”，不能证成“持续、无上限”。
4. **形式 novelty 不等于数值无界。** 严格不等式保证未来总有更难预测的产物，但允许损失趋近有限上界。将其翻译成“复杂度无上限”属于额外主张。
5. **不保证覆盖、正确或有价值。** 论文明确指出 novelty 与 learnability 不保证完整探索问题空间。正确性、任务价值和安全性若重要，必须由定义之外的评价与约束提供。
6. **观察者能力形成窗口。** 观察者过强时产物可能不再新颖；过弱时产物可能不可学习。系统只在仍能“教育”该观察者期间相对它保持开放。
7. **严格 learnability 很难直接实测。** 它要求所有相关 `t,t',T` 上严格改善；有限、含噪数据只能做统计估计。作者给出弱化方向，但没有完成实用标准。
8. **固定数据通常只有有限开放性。** 一旦观察者吸收其 epistemic uncertainty，novelty 会耗尽；宽领域数据可能因观察者记忆有限而暂时显得开放，但这不是系统无限开放的证据。

## 与 Open-ended Learning 的关系

最接近且被目标论文直接比较的一手来源是：

> Olivier Sigaud et al. **A Definition of Open-Ended Learning Problems for Goal-Conditioned Agents**. arXiv:2311.00344, 2023. [arXiv](https://arxiv.org/abs/2311.00344)

Sigaud 等人的核心表述是：对任意时间 `t`，都存在更晚时间 `t'>t`，过程产生一个相对观察者为新的 token。Hughes 等人继承了“观察者相对”和“序列中未来持续出现新项”的结构，进一步把“新”规定为当前历史条件模型下的不可预测性，并增加整条产物序列的 learnability 条件，以排除纯噪声。

因此，open-endedness 是 **系统相对观察者所产生序列的性质**；open-ended learning 是试图构造这种序列的一类学习问题或方法。持续训练、continual RL 或“Agent 永不停止学习”都不充分：策略可能只在有限集合中循环，而没有累积新的、可学习的产物。反过来，一个窄领域系统也可能在有限时域内满足该定义，并不因此成为通用学习系统。

## 对动态 Harness 的测量约束

以下是由论文定义推导出的架构约束，不是论文已经验证的 Harness 方案：

- Open-endedness 检测记录必须版本化 `observer`、`artifact schema`、`loss`、历史范围和时域 `\tau`；缺少其中任何一项，指标不可复查。
- novelty 与 learnability 应分别报告。把二者先压成单一 surprise 分数，会掩盖“高 novelty、零 learnability”的噪声退化解。
- 内部观察者可以作为学习控制器，但外部正确性、价值、安全和权限门禁不能由该指标替代。
- 实验结论应写成“相对观察者 `O`，在时域 `\tau`、损失 `\ell` 下支持/不支持有限开放性”，不得从有限窗口直接宣称无限 open-endedness。
- 若观察者模型、损失或 artifact 粒度发生变化，应视为测量协议变化，而不是同一曲线上的连续进步。

## 来源

1. Hughes et al. (2024), *Open-Endedness is Essential for Artificial Superhuman Intelligence*, arXiv:2406.04268v1. [摘要与版本](https://arxiv.org/abs/2406.04268v1)；[HTML 全文](https://arxiv.org/html/2406.04268)。重点：§2.1、§2.3、Appendix A.2、B、C。
2. Sigaud et al. (2023), *A Definition of Open-Ended Learning Problems for Goal-Conditioned Agents*, arXiv:2311.00344. [arXiv](https://arxiv.org/abs/2311.00344)。仅用于解释目标论文所承接的 open-ended learning 定义脉络。
