# 该做什么了 · main 5c25e1b（2026-11-08）

模型最后对齐 37e9d68，对这个提交没跟上：原句 154 句，对不上 52 句（另有 1 句是拼接，分开核对都在）；对齐以后新加、模型还没抽的：模型挂过的节里 80 行，模型没挂过的节里 35 行（多半在范围外，例如页面怎么画）。
覆盖：范围（A）：骨架、定义、裁决、路由、循环、组织、缝与环；产品怎么做、页面怎么画不在模型里。模型读的文档：docs/architecture.html、docs/design/department-roles.md、docs/design/forms-and-verifier-role.md、docs/design/independent-verification.md、docs/design/skeleton-and-application.md。没列的文档模型不知道，这里不说它们没问题。
- 对不上：c-decision-request 「四层：事实与裁决只认事项、事件、某种成果的某一版及其依据、提案、回执、角色的写入范围、上限与决定请求；循环只认一轮工作，」 · docs/architecture.html
- 对不上：c-department 「四层：事实与裁决只认事项、事件、某种成果的某一版及其依据、提案、回执、角色的写入范围、上限与决定请求；循环只认一轮工作，」 · docs/architecture.html
- 对不上：c-event 「四层：事实与裁决只认事项、事件、某种成果的某一版及其依据、提案、回执、角色的写入范围、上限与决定请求；循环只认一轮工作，」 · docs/architecture.html
- 对不上：c-limit 「四层：事实与裁决只认事项、事件、某种成果的某一版及其依据、提案、回执、角色的写入范围、上限与决定请求；循环只认一轮工作，」 · docs/architecture.html
- 对不上：c-outcome-version 「四层：事实与裁决只认事项、事件、某种成果的某一版及其依据、提案、回执、角色的写入范围、上限与决定请求；循环只认一轮工作，」 · docs/architecture.html
- 没抽：docs/architecture.html「」19 行，例如第 157 行「全局总图与方程职能围着一份事实转，薄驱动连着三个共用的槽位」
- 没抽：docs/design/department-roles.md「4.1 角色清单」6 行，例如第 93 行「三个职能同构，各职能的中心角色与分工如下，运维按同一做法，不展开：」
- 没抽：docs/design/department-roles.md「4.2 子组织怎样被指向」1 行，例如第 114 行「职能的角色定义可以指向一份子组织形态，默认是中心型小组。指向了，这个角色的一轮工作开一个子事项；不指向，就是一个模型或一个外包会话。」
- 没抽：docs/design/department-roles.md「4.3 直做与审查者的核验」2 行，例如第 124 行「主程接询问时可以写工作区，因为写入范围是角色的性质。[产品 · 工程 · 质检的循环结构](department-loop.md)「回答能做」
- 没抽：docs/design/department-roles.md「4.4 审查者的上下文」1 行，例如第 138 行「审查者先下判断再看作者的解释，见[验证的独立性设计说明](independent-verification.md)「先判断后看解释」。是否看」
- 没抽：docs/design/department-roles.md「4.7 模型与 Prompt 设置」1 行，例如第 158 行「角色设置优先于职能设置，解析顺序见[模型管理设计说明](model-management.md)「职能与角色的模型选择」。职能 Prompt」
- 模型没挂过的节里新加的（只提一句）：department-roles.md 等，「职能内多角色设计说明」、「1. 功能与依据」、「2. 边界与范围」、「3. 接口」、「4.6 预测性探索」、「4.8 与已有结构的对应」、「5. 验收」、「6. 未决问题」、「形态与核验角色设计说明」、「4.1 四层各认识什么」、「4.4 开环完成」、「验证的独立性设计说明」、「1. 要解决的问题」、「2. 共享的与隔开的」、「6. 共享上下文的一组对照」、「8. 边界的一致」、「12. 与现有设计的关系」
- 没抽：另有 21 节

## 零、对齐以后的变动（37e9d68 → 5c25e1b，全文见 reports/changes/37e9d68..5c25e1b.md）
- 模型读的文档与术语表改了 7 份；推出的改名确定 5 条，要你点 5 条
- 原句对不上 52 条：换词接上 44 条（不用确认），改写 2 句，删掉 2 句
- 手写的名字与出处里用旧词 30 处；定义文件与代码生成的事实加 31、少 19
- 「部门」→「职能」还没跟上的：469 份文件 3133 行（harness 2109、client 412、view 385、docs/research 68）
- 「模板」→「形态」还没跟上的：26 份文件 48 行（.claude 19、harness 19、docs/research 6、tools 2）

## 一、内部不一致的设计（违例）（3）
1. 部门：用了词表里写明要避免的词
   「四层：事实与裁决只认事项、事件、某种成果的某一版及其依据、提案、回执、角色的写入范围、上限与决定请求；循环只认一轮工作，谁开工、怎么结束都问路由；路由各自写轮转的规矩，核验从核验角色取；组织（定义）往里填部门与角色。」
   总图 第二节「四层」
2. harness/definitions/__init__.py：内核模块的判断里出现职能名或成果种类名（形态与核验角色 验收第 3 条） · 工单草稿一
   harness/definitions/__init__.py:274 顶层集合 LEGACY_VERIFICATION里的「quality」（职能名）
   harness/definitions/__init__.py:275 顶层集合 LEGACY_VERIFICATION里的「delivery_spec」（成果种类名）
   harness/definitions/__init__.py:275 顶层集合 LEGACY_VERIFICATION里的「engineering」（职能名）
   harness/definitions/__init__.py:276 顶层集合 LEGACY_VERIFICATION里的「quality」（职能名）
3. 判开环的几条规则对同一份定义给相反的判定（1 种组合） · 工单草稿二
   「指定的角色交了完成，事项结束：没有核验角色核验它，结束原因是开环完成」 · 第 4.3 节第 3 条：交完成的角色没有核验角色核验它，结束原因是开环完成
   「按冻结的定义看事项最后采纳的成果（直做下是交完成的那一份，成果驱动下是交付）有没有核验角色核验；没有，事项标为开环」 · 第 4.7 节第 4 条：按最后采纳的成果判开环
   「标记说的是最后采纳的东西有没有经过独立核验」 · 第 4.7 节第 4 条：按最后采纳的成果判开环
   「有核验角色、但它不核验事项最后采纳的那种成果（只核验中途的成果）时，事项创建时标为开环，以开环完成结束」 · 验收第 12 条（改写后）：按最后采纳的成果判开环
   代码：orchestrator.py 按最后采纳的成果判，direct.py 按交完成的角色判

## 二、设计了还没实现（确实缺）（2）
1. 工程的中心型小组：设计里有这份形态，发布的定义文件里没有
   「部门的角色定义可以指向一份子组织形态，默认是中心型小组。指向了，这个角色的一轮工作开一个子事项」
   部门内多角色设计说明 4.1、4.2
2. 一个外包角色直做：设计里有这份形态，发布的定义文件里没有
   「一个外包角色直做 | 一个外包角色 | 直做 | 没有 | 外包交回快照，开环完成并注明外包」
   形态与核验角色设计说明 第 1 节

## 三、照现状还要考虑的：推出的空位（推理，不是类比）（0）
   已由设计填上的推理链 4 条，例如：工程 → 内部要协作的部门必有一份部门内的核验 → 审查者核验工程架构师交的完成

## 三、照现状还要考虑的：定义文件里有、设计没写（对照，不是推理）（14）
1. 三部门（默认）：工程 产出 结构说明（default）（定义文件有，设计没写）
2. 三部门（默认）：产品 产出 产品决定（default）（定义文件有，设计没写）
3. 三部门（默认）：产品 关注 基线核验（default）（定义文件有，设计没写）
4. 三部门（默认）：质检 产出 基线核验（default）（定义文件有，设计没写）
5. 三部门（默认）：质检 产出 独立判断（default）（定义文件有，设计没写）
   另有 9 条，见 .json

## 四、不知道（23）
- name-unknown：6 条，例如 部门：词表与 name-map 里都没有这个词，正名对不上
- planned：1 条，例如 运维（以后）：文档写的是「以后」（写法规范第 5 条）
- planned-source：1 条，例如 运维发现的故障（以后）：文档写的是「以后」（写法规范第 5 条）
- seam-unsettled：1 条，例如 看门狗：这道缝标为未定（写法规范第 5 条：未定就是不知道）
- source-received：3 条，例如 建档：每种事项的来源有人接
- checkdef-per-item：1 条，例如 核验的通用定义：每个事项具体查什么来自检查材料，设计说明没写
- halfopen-depends：1 条，例如 审查者核验工程架构师交的完成：这份核验有两种结论：有主机回执的算已核验，只靠读的按半开环的假定不该写成放行（这一次靠哪种，设计里看不出）
- term-unmapped：9 条，例如 事件：总图的词在 name-map 里没有对应的代码

## 建议（按先后）
1. 先跑 heal.py 5c25e1b --apply：自动接上 44 条原句、换 30 处名字，三道检查过了才写回，不用人
2. 点一下改名：三部门 → 「产品 · 工程 · 质检」；三部门 → 产品 · 工程 · 质检；一个角色直做 → 「工程」；几个角色直做 → 「产品 · 工程」；三部门 → 默认形态（renames.py confirm 或 reject）
3. 判 2 句改写：意思没变就 heal.py --accept 序号；变了就当删掉重抽
4. 先把模型跟上：52 句原句对不上；模型挂过的节里新加了 80 行（architecture 、department-roles 4.1、department-roles 4.2、department-roles 4.3、department-roles 4.4、department-roles 4.7、forms-and-verifier-role 1、forms-and-verifier-role 4.3、forms-and-verifier-role 4.5、forms-and-verifier-role 4.6、forms-and-verifier-role 4.7、forms-and-verifier-role 5、independent-verification 4、skeleton-and-application 骨架与应用设计说明、skeleton-and-application 3.1、skeleton-and-application 4、skeleton-and-application 5.1、skeleton-and-application 5.2、skeleton-and-application 5.3、skeleton-and-application 5.4、skeleton-and-application 5.5、skeleton-and-application 6、skeleton-and-application 7、skeleton-and-application 8、skeleton-and-application 12、skeleton-and-application 13、skeleton-and-application 14），要重抽；下面的结论只到模型对齐的那一版
5. 先定：部门：用了词表里写明要避免的词（几句说法冲突，先定以哪一句为准）
6. 先定：harness/definitions/__init__.py：内核模块的判断里出现职能名或成果种类名（形态与核验角色 验收第 3 条）（工单草稿一已写好，等你开）
