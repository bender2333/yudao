# Yudao 本体方案（第二版）：现在只建 Yudao 自己

> 日期：2026-11-05 起草；2026-11-06 按用户的区分拆开重写，并对照 main 的 32753a3 改对；同日按用户的决定改用 OWL 表示（第 4 至 6、9 节）。分支 `research/yudao-ontology`，只是方案，没有改代码，也没有动 main。
> 起因：用户 2026-11-05 的话「遇到的本体不是开发用的本体，而是遇到自己的概念」；2026-11-06 早上又理清了范围：两半不能放在一起。Yudao 自己的骨架、定义、裁决、路由是一套完整的逻辑；Yudao 定义的软件工程通用方法（比如缺陷）是另一回事，真实项目借它发散出自己的领域模型；以后领域建模加符号推理会成为 Yudao 流程里的一步。
> 取代：[第一版](yudao-ontology.md)第 10.1、11 节，以及本文 11-05 那一稿里把「加工的软件工程对象」和 Yudao 自己放进同一份本体的写法。
> 依据：main 的 32753a3 上读了[总图](../architecture.html)、[D38 系统意图](../requirements/system-intent.md)、`CONTEXT.md`、[总图与代码的名字对照](../design/architecture/name-map.md)、[语义系统设计说明](../design/semantic-system.md)第 5、10 节、`harness/definitions/` 与其下 `forms/`、`harness/runtime.py` 的形态登记、`harness/direct.py`、`harness/kernel_events.py`。

## 0. 一句话

现在建的是 **Yudao 自己的本体**：这座楼本身，也就是它的骨架、定义、裁决、路由、循环、组织，以及把它们隔开的缝与环。它自成一套逻辑，以总图为准、对到代码。现在是自举，这份本体挂在上面一层，和脚手架接在一起（放在 `tools/doc-consistency/` 旁边，给开发 Yudao 的人和 agent 用），不嵌进 Yudao 运行时的流程。

现在不建两样东西：一是 Yudao 定义的**软件工程通用方法模板**（要求、验收条件、缺陷、交付这些概念的含义和它们之间的链），二是以后放进 Yudao 流程里的**领域建模加符号推理**这一步。第 8 节只讲清它们和现在这份的边界、以后怎么接。

表示用 OWL（用户 2026-11-06 定：先试最成熟的，出问题再换）。OWL 管建模：种类是类，关系是属性，定义文件里的部门、成果种类是个体；推理机查模型自洽、自动分类，并查分层。覆盖、闭合、无环这些「没有就算缺」的检查是封闭世界的，交给 SHACL，结果分违例、确实缺、不知道三栏。clingo 现在不接。

第一步：手写 OWL 的类与属性，从 name-map、三份形态的定义文件和代码机械编出个体，再让大模型从总图抽一小批对比手写的；然后跑推理机与 SHACL。成功标准见第 9 节。

## 1. 三样东西各在哪

| | 是什么 | 现在 | 放在哪 |
| --- | --- | --- | --- |
| (A) Yudao 自己的本体 | 楼本身：骨架、定义、裁决、路由、循环、组织、缝与环 | **建** | 上面一层，和脚手架接着，不进运行时 |
| (B) 软件工程通用方法模板 | Yudao 给所有项目用的通用概念：要求、验收条件、设计、计划任务、交付、检查结果、缺陷、实体类型，以及要求链 | 不建 | 以后在 Yudao 里，作为运行时的模板 |
| (C) 流程里的领域建模一步 | 给用户项目先描述、建领域模型、用符号推理查全边角，再走 Yudao 的流程与裁决 | 不建 | 以后是 Yudao 流程里的一步 |

用 MOF 的说法：(A) 描述的是 Yudao 这台机器；(B) 是 Yudao 提供给项目的元模型；一个记事本项目在 (C) 里借 (B) 长出自己的领域模型（M1），比如 DDD 的笔记、标签、同步。

(A) 和 (B) 之所以不能放在一起：(A) 随 Yudao 的架构变，由总图管，答的是「这台机器由什么构成、哪段代码实现了哪句总图」；(B) 随软件工程方法变，由 Yudao 的定义与语义系统管，答的是「一个项目里的一条缺陷意味着什么」。绑在一起，改一边就得动另一边，而且会把机器的结构和它加工的内容混成一层。

Yudao 自己的建模和别的项目不一样，原因也在这里：别的项目的模型以后在 Yudao 流程里由 (C) 生成，经裁决；Yudao 自己的模型 (A) 现在由脚手架这一层维护，因为被迭代的系统改不了评价它的标准（基础规则 3）。

## 2. (A) 的种类

每个种类写：它是什么、出自总图哪里、对到哪段代码、属于哪一层。状态以 32753a3 的代码为准；name-map 落后于代码的地方单独标出。四层用总图第一节的分法：事实与裁决（内核）、循环、路由、组织；另一组缝与环不归某一层。

### 2.1 事实与裁决（内核）

总图说内核只认：事项、事件、某种成果的某一版及其依据、提案、回执、角色的写入范围、上限、决定请求。本层的种类从这句话来。

| 种类 | 是什么 | 总图 | 代码 | 状态 |
| --- | --- | --- | --- | --- |
| 事件 | 事实的唯一载体，带序号，只追加 | 第一节「一份事实」、方程 | `kernel_events.py` 的 `SkeletonEventType`、`event_store.py` | 一致 |
| 流 | 事件的分组：项目流、事项一次执行的流 | 第四节投影 | `run_stream`、项目流 | 一致 |
| 事项 | 一件要做成的事 | 第一、三节 | 项目流里叫 `work_item`，一次执行叫 `run` | 不一致（两个名字并存） |
| 执行权 | 此刻由谁推进这个事项 | 方程 | `claim_execution_right` | 一致 |
| 派发编号 | 一次派发的编号，防止旧派发写进来 | 方程 | 事件 `dispatch_number_acquired` | 一致 |
| 提案 | 模型的输出，只能提议 | 第一节；基础规则 3 | `proposal_submitted`、`proposal_rejected`；`proposal_contracts.json` | 一致 |
| 回执 | 主机产生的证据：动作回执、检查回执 | 第一节「独立的证据」 | `actions.py` 的 `ActionReceipt`、`CheckReceipt` | 一致 |
| 成果版本 | 某种成果的某一版，带依据 | 内核那句话 | `artifact_accepted`、`artifact_invalidated` 等接纳事件 | 一致 |
| 快照 | 封存的一份工作区 | 第一节「一份事实」 | `snapshot.py`、`WorkspaceSnapshot` | 一致 |
| 写入范围 | 一个角色能写到哪里 | 第四节定义 | `WriteScope`；裁决按 `definition.write_scope(department)` 读声明（#1390） | 一致；name-map 过时 |
| 上限 | 边界，撞到记为失败 | 第四节定义；基础规则 3、6 | `rules.json`、`parameters.py` | 一致 |
| 决定请求 | 等用户决定的一件事 | 第三节「等用户」 | `decisions.py`、`DecisionRequest` | 一致 |
| 停止原因 | 停下的原因，封闭清单 | 第三节「停止」 | `stop_reasons.json`、`StopReason` | 一致 |
| 裁决 | 接纳或拒绝提案；手段按顺序：规则、判定点、升级 | 第一节「裁决」；D38 N-J1 | `adjudication.py` | 一致（判定点见 2.3） |

### 2.2 循环

| 种类 | 是什么 | 总图 | 代码 | 状态 |
| --- | --- | --- | --- | --- |
| 一轮工作 | 一个部门被叫起来做的一次 | 第三节外环；方程 | 叫 activation：`department_activated`、`activation_finished` | 不一致（名字） |
| 外环状态 | 一个部门所处的九个状态之一 | 第三节外环 | 只有 run 的四个 `RUN_STATUSES`，部门状态部分有 | 不一致（name-map 第 3 节） |
| 内环步 | 一轮工作里的六步 | 第三节内环 | `engine.py` 的 `StepDriver` | 一致 |
| 安全节点 | 中途介入只在这里生效 | 第三节；D38 N-C5 | `execution_contract.py` 的 `SafeNode`（契约第三版，#1511） | 一致 |
| 询问 | 一个部门问另一个部门 | 第三节「询问中」 | `ask_started`、`ask_answered` | 一致 |
| 指导 | 用户中途给部门的话 | 第三节 | `DepartmentGuidance` | 一致 |
| 压缩 | 上下文逼近上限时的收拢 | 第三节 | `compaction.py` | 一致 |
| 子事项 | 角色在自己边界内起的子循环 | 第三节「子组织」；D38 N-A2 | 没有 | 未建 |
| 收敛状态 | 收敛中、震荡、停滞、漂移、达到边界 | 第三节；D38 N-C3 | `app/loops_queries.py` 一带，未逐项核对 | 待核对 |

### 2.3 路由

| 种类 | 是什么 | 总图 | 代码 | 状态 |
| --- | --- | --- | --- | --- |
| 轮转方式 | 直做、按成果、任务池 | 第一节「轮转方式」 | 按成果：`watched_outputs.py`；直做：`direct.py`（#1395、#1396、#1454）；任务池没有 | 直做已建，name-map 过时；任务池未建 |
| 关注的成果 | 一个部门等哪些成果出现才开工 | 第一节「按成果」 | 部门的 `watched` | 一致 |
| 交完成 | 直做时由能交完成的角色交回完成 | 第一节「轮转方式」 | `direct.py`、`proposals.py` 的交完成提案 | 已建；name-map 过时 |
| 工作单元、认领 | 任务池里的一份活和领走它 | 第一节；外环「待认领」 | 没有 | 未建 |
| 核验关系 | 哪个角色核验哪个角色的哪种成果 | 第一节「质检」 | `verification.verifiers`；直做加核验角色走 #1396 | 一致 |
| 放行 | 核验角色认可，事项完成 | 第三节外环 | `QAReview.verdict`；直做里交完成以后等核验结论（#1396） | 一致 |
| 开环完成 | 没有核验角色时的完成 | 第三节；基础规则 2 | `Definitions.is_open_loop`；直做按创建事件里的开环标记（#1394） | 一致 |
| 判定点 | 规则判不了时让决策模型选，有合同 | 第三节「判定点」 | 没有 | 未建 |
| 路由实现 | 槽位里接上的那一种路由 | 第一节「槽位：路由」 | `routing_contract.py` 的 `register`、`select` | 一致 |

### 2.4 组织

| 种类 | 是什么 | 总图 | 代码 | 状态 |
| --- | --- | --- | --- | --- |
| 形态 | 一套完整的定义：部门、角色、核验、路由、成果种类、来源 | 第一节；第六节「三部门、子组织都只换下面两层」 | `runtime.py` 的 `FORM_REGISTRY`；发布带三份：默认三部门、`single_role_direct`、`several_roles_direct` | 一致 |
| 部门 | 围绕一个目标函数聚在一起的信息与工作过程 | 第一节；D38 N-I1 | `Department`；各形态的 `organization.json` | 一致 |
| 角色 | 部门里的一个成员 | 第四节定义 | `Role`、`DepartmentSession` | 一致 |
| 成果种类 | 部门产出、别的部门关注的那类东西 | 第四节定义 | 各形态的 `outcome_kinds.json`、`OutcomeKind`（#1456） | 一致；name-map 过时 |
| 事项种类 | 改动、接入已有项目 | 第一节 | `work_items.json`、`WorkItemKind` | 一致 |
| 事项的来源 | 事项从哪里来，每种来源由哪个部门接 | 第一节 | `event_sources.json`；没有部门接时加载拒绝（#1455） | 一致 |
| 定义版本 | 全部定义文件的摘要；事项冻结它创建时的那一份（#1381） | 第四节定义；基础规则 3 | `Definitions` 的摘要；事项冻结组织 | 一致 |
| 外包角色 | 交给外部 agent 做的角色 | 第一节「工程」 | 没有 | 未建 |
| 观察者 | 循环之外订阅事件、只以提案回来 | 第一节「观察者」 | 没有 | 未建 |
| 登记的机器 | 可以派活去的机器 | 第四节定义 | 没有 | 未建 |
| 限定采用的范围 | 第二层自举采用一项修改的范围 | 第五节 | 没有 | 未建 |

### 2.5 缝与环

| 种类 | 是什么 | 总图 | 代码 | 状态 |
| --- | --- | --- | --- | --- |
| 缝 | 两侧可以各自换掉的接口：内侧 9 道，外侧 4 道（评价、观察者、画面、看门狗） | 第四节 | name-map 第 1、2 节 | 各道不同 |
| 契约 | 一道缝的约定，带当前与上一版本 | 第四节 | 路由、装配、执行契约文件的 `CURRENT_VERSION`、`PREVIOUS_VERSION` | 一致 |
| 环 | 可以整体重写 / 只能向后兼容 / 只由你批准 | 第二节 | `definitions/kernel-manifest.json` 管最里面一环 | 部分 |
| 骨架事件、应用事件 | 前者只能向后兼容 | 第二节 | `SkeletonEventType`、`ProjectEventType` | 一致 |
| 自举层 | 第一层把自己当普通项目；第二层按运行证据改自己 | 第五节 | D35 | 第一层试点中，第二层未建 |

外侧的缝只当作「缝」的实例，不展开里面的元件（画面的元件、评价的场景）。

## 3. (A) 的关系

| 关系 | 连接 | 出处 | 来源 |
| --- | --- | --- | --- |
| 属于 | 角色 → 部门；部门 → 形态 | 第一节 | 各形态的 `organization.json` |
| 产出 | 部门 → 成果种类 | 第四节定义 | `proposal_contracts.json` |
| 关注 | 部门 → 成果种类 | 第一节 | `watched` |
| 核验 | 角色 → 角色，限一种成果 | 第一节 | `verification.verifiers` |
| 能拒绝 | 部门 → 部门（由核验推出） | 第四节定义 | `Definitions.rejection_edges` |
| 接 | 部门 → 事项的来源 | 第一节 | `event_sources.json` |
| 能交完成 | 角色 → 形态（直做时） | 第一节「轮转方式」 | 直做形态的定义 |
| 用路由 | 形态 → 路由实现 | 第一节 | `routings.json` |
| 写入限于 | 角色 → 路径范围 | 第四节定义 | `write_scopes` |
| 冻结 | 事项 → 定义版本 | 第四节定义 | #1381 |
| 依据 | 成果版本 → 成果版本 | 内核那句话 | 接纳事件 |
| 产生于 | 成果版本、回执 → 事件 | 方程 | 事件序号 |
| 受限于 | 事项、一轮工作 → 上限 | 第四节定义 | `rules.json` |
| 停于 | 一次执行 → 停止原因 | 第三节 | `Event.stop_reason` |
| 在层 | 种类 → 四层之一 | 第一节 | 本文第 2 节 |
| 在环 | 代码模块 → 三环之一 | 第二节 | `kernel-manifest.json` 只给最里面一环 |
| 跨 | 契约 → 缝；缝 → 内侧、外侧 | 第四节 | 契约文件 |
| 实现 | 代码名 → 总图里的词，附状态 | — | name-map 的表，加上从代码直接读 |

成果种类在 (A) 里只是结构上的一个节点：谁产出、谁关注、谁核验、属于哪个形态。PRD 里有什么、缺陷违反什么，属于 (B)，(A) 不建。

## 4. 用 OWL 怎么表示

用户 2026-11-06 定：先试 OWL，当一个成熟的锚点，出了问题再换。这一节写 (A) 用 OWL 写出来是什么样。

### 4.1 和第一版的说法怎么对上

第一版第 4 节说 OWL「不适合当检查用」，理由是开放世界：没写的事实不算假，而我们的检查要的是「没写就算没有」。这个理由对检查仍然成立，但它不妨碍用 OWL 来**建模**。分开以后就不矛盾了：

- **建模用 OWL**：类、属性、类之间的关系、不相交这些有标准语义，工具成熟（Protégé 能看能改，HermiT 能推），模型写宽写窄有个公认的参照。大模型也熟 OWL 与 Turtle，这对以后从文档抽取有帮助。
- **封闭世界的检查用 SHACL**：W3C 的标准，直接跑在同一张 RDF 图上，不用另抄一份事实。第一版嫌它「要整套 RDF 工具链」，既然用了 OWL，这套工具链已经在了，这条顾虑就没了。

我的看法，有三点要先说清，免得期望错位：

1. OWL 推理机本身能替我们查的东西不多（第 5 节）。大部分检查的价值在 SHACL，OWL 的价值在给模型一个有语义的锚点，和自动分类。
2. 有两处要用固定的写法绕：三元关系（「谁核验谁的哪种成果」）要写成一个声明类；「成果种类」是类还是个体要定一个规矩（4.3）。
3. OWL 解决不了「文本难抽」。降低抽取难度靠的是第 6 节的写法规范，OWL 只是给了抽取一个明确的目标格式。

### 4.2 三样东西各对到 OWL 的什么

| (A) 里的 | OWL 里的 | 例子 |
| --- | --- | --- |
| 种类（第 2 节） | 类 `owl:Class`，`rdfs:label` 用中文正名 | `yd:Department`「部门」、`yd:OutcomeKind`「成果种类」、`yd:Seam`「缝」 |
| 种类之间「是一种」 | `rdfs:subClassOf` | 核验角色是一种角色 |
| 关系（第 3 节） | 对象属性 `owl:ObjectProperty`，带定义域与值域 | `yd:belongsTo`「属于」：角色 → 部门 |
| 只有一个 | `owl:FunctionalProperty` 或基数限制 | 一个角色只属于一个部门 |
| 互不重叠 | `owl:disjointWith` | 部门与角色不相交；内核模块与提到外层实例的模块不相交 |
| 总图位置、层、状态 | 注解属性 | `yd:archRef "第一节「轮转方式」"`、`yd:layer yd:RoutingLayer` |
| 定义文件里的部门、成果种类 | 个体，按形态分 | `yd:form/default/quality a yd:Department` |
| 代码模块、代码名 | 个体 | `yd:code/harness/direct.py a yd:CodeModule` |
| 来源 | PROV-O 的 `prov:wasDerivedFrom`，加原句 | 每条从文档抽出的断言记节号和原句 |

标识用英文局部名、中文做标签，因为推理机和 SHACL 工具对非 ASCII 的 IRI 支持不齐；页面和报告上显示中文。

### 4.3 三个具体例子

**部门与成果种类。**

```turtle
@prefix yd:   <https://yudao.dev/onto#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

yd:Department a owl:Class ; rdfs:label "部门"@zh ;
    yd:layer yd:OrganizationLayer ; yd:archRef "第一节" .
yd:Role a owl:Class ; rdfs:label "角色"@zh ; owl:disjointWith yd:Department .
yd:OutcomeKind a owl:Class ; rdfs:label "成果种类"@zh ; yd:layer yd:OrganizationLayer .
yd:Form a owl:Class ; rdfs:label "形态"@zh .

yd:belongsTo a owl:ObjectProperty, owl:FunctionalProperty ;
    rdfs:domain yd:Role ; rdfs:range yd:Department .
yd:produces a owl:ObjectProperty ; rdfs:domain yd:Department ; rdfs:range yd:OutcomeKind .
yd:watches  a owl:ObjectProperty ; rdfs:domain yd:Department ; rdfs:range yd:OutcomeKind .
yd:inForm   a owl:ObjectProperty, owl:FunctionalProperty ; rdfs:range yd:Form .

# 实例，从默认形态的 organization.json、outcome_kinds.json 机械编出
yd:f-default-quality a yd:Department ; rdfs:label "quality" ; yd:inForm yd:form-default ;
    yd:watches yd:f-default-delivery_spec .
yd:f-default-delivery_spec a yd:OutcomeKind ; yd:inForm yd:form-default .
```

成果种类的规矩：在 (A) 里，`product_spec`、`delivery_spec` 这些是 `yd:OutcomeKind` 的**个体**，按形态各一份。它们作为「一类内容」的含义（PRD 里有要求和验收条件）属于 (B)，以后在 (B) 里另有同名的类，两者用一条 `yd:correspondsTo` 相连，不在 (A) 里把个体又当成类用。

**核验：三元关系写成声明。**

```turtle
yd:VerificationDecl a owl:Class ; rdfs:label "核验声明"@zh .
yd:verifier a owl:ObjectProperty, owl:FunctionalProperty ; rdfs:domain yd:VerificationDecl ; rdfs:range yd:Role .
yd:verified a owl:ObjectProperty, owl:FunctionalProperty ; rdfs:domain yd:VerificationDecl ; rdfs:range yd:Role .
yd:forOutcome a owl:ObjectProperty, owl:FunctionalProperty ; rdfs:domain yd:VerificationDecl ; rdfs:range yd:OutcomeKind .

# 核验角色不用手写，由推理机分出来
yd:VerifierRole owl:equivalentClass [ a owl:Restriction ;
    owl:onProperty [ owl:inverseOf yd:verifier ] ; owl:someValuesFrom yd:VerificationDecl ] .

# 有核验的形态、开环的形态也由推理机分
yd:VerifiedForm owl:equivalentClass [ a owl:Restriction ;
    owl:onProperty [ owl:inverseOf yd:inForm ] ; owl:someValuesFrom yd:VerificationDecl ] .
```

「开环形态」是「没有核验声明的形态」，这是一句否定，开放世界里推不出来（没写不等于没有）。它放到 SHACL 里，在「三份形态的定义文件已经整份读过」这个封闭范围内判断（第 5.2 节）。

**内核与外圈的缝。**

```turtle
yd:Seam a owl:Class ; rdfs:label "缝"@zh ; yd:archRef "第四节" .
yd:Contract a owl:Class ; rdfs:label "契约"@zh .
yd:CodeModule a owl:Class .
yd:KernelModule rdfs:subClassOf yd:CodeModule ; rdfs:label "内核模块"@zh .
yd:mentions a owl:ObjectProperty ; rdfs:domain yd:CodeModule .

yd:routingSeam a yd:Seam ; rdfs:label "路由"@zh ; yd:guardedBy yd:routingContract .
yd:routingContract a yd:Contract ; yd:currentVersion 3 ;
    yd:definedIn yd:code-harness-routing_contract.py .

# 分层：提到外层实例的模块，和内核模块不相交
yd:OuterAwareModule owl:equivalentClass [ a owl:Restriction ; owl:onProperty yd:mentions ;
    owl:someValuesFrom [ owl:unionOf ( yd:Department yd:OutcomeKind yd:Form ) ] ] ;
    owl:disjointWith yd:KernelModule .
```

`kernel-manifest.json` 里的模块标成 `yd:KernelModule`，代码扫描写出 `yd:mentions`。哪个内核模块提了一个部门名，推理机就报不一致。这条是正面的事实推出矛盾，开放世界也查得出，所以分层可以由 OWL 自己查。契约版本号这类值从代码里读（`routing_contract.py` 现在是第 3 版）。

## 5. 推理分工，和「不知道」怎么标

### 5.1 谁查什么

| 检查 | 谁来查 | 为什么 |
| --- | --- | --- |
| 模型自洽：没有推不出实例的类、定义域值域不打架 | OWL 推理机（HermiT） | 这正是 OWL 推理的本行 |
| 自动分类：核验角色、有核验的形态、提到外层实例的模块 | OWL 推理机 | 由定义推出，不用手写，写错定义会在这里暴露 |
| 分层：内核模块不提外层实例名 | OWL 推理机报不一致，SHACL 出逐条报告 | 正面事实推出矛盾，开放世界也成立 |
| 覆盖：每个种类有实现、确实未建或不知道 | SHACL | 「没有实现」是否定，要封闭世界 |
| 闭合：被关注的成果有人产出、被核验的成果有核验者、每种来源有人接、直做形态有角色能交完成，按形态分别查 | SHACL（SPARQL 约束） | 「没有人产出」是否定；按形态分组要计数 |
| 核验无环 | SHACL（SPARQL 属性路径 `yd:canReject+`） | OWL 一般表达不了「没有环」 |
| 来源之间打架：name-map 写未建，代码里却有 | SHACL | 两份正面断言对不上，逐条报出，过时的 name-map 行就是这样找到的 |

OWL 在开放世界下做不了的：所有「没有」「缺」「只有这些」的判断，计数，环。这些全给 SHACL。

### 5.2 三种结果：违例、确实缺、不知道

用户说得对：没写不能直接算缺，「不知道」本身是合理的结果，但要标出来。做法是每条检查只给三种结果之一：

| 结果 | 什么时候 | 例子 |
| --- | --- | --- |
| 违例 | 两份正面断言互相矛盾 | name-map 说直做「代码里还没有」，代码里 `direct.py` 登记了直做路由 |
| 确实缺 | 有正面断言说没有，或者落在一个声明过的封闭范围里 | name-map 写判定点未建，代码扫描也没找到；某份形态的定义文件整份读过，里面没有任何角色能交完成 |
| 不知道 | 两样都没有 | 收敛状态：没有人写它建了没有，代码也没扫到那一处 |

「封闭范围」写成图里的显式声明，例如：

```turtle
yd:scope-forms a yd:ClosedScope ; rdfs:label "三份发布形态的定义文件，整份读过"@zh ;
    yd:covers yd:Department, yd:OutcomeKind, yd:VerificationDecl, yd:Form .
yd:scope-kernel-mentions a yd:ClosedScope ;
    rdfs:label "内核清单里每个模块的名字引用，整份扫过"@zh ; yd:covers yd:mentions .
```

SHACL 的形状先看断言落不落在某个封闭范围里：在里面，没有就是确实缺；不在里面，没有就是不知道。报告分三栏列出。这样「不知道」不会被误报成缺，也不会悄悄消失。

### 5.3 和 clingo 规则事实线怎么接

建议现在不接。

- 规则事实线在 main 上已经用 clingo 做完，查的是脚手架的规则；(A) 查的是楼。两者的重叠只剩同名词（第 8.1 节那张表），用一张表标出来就够，不用共享事实。
- 两边真要互通时代价很小：RDF 三元组导成 clingo 的 `triple(S,P,O).` 是一个函数的事，反过来也一样。等真有需要再接。
- clingo 以后可能在 (C) 里更有用：「查全边边角角」本质上是找反例，要求解器去搜一个满足约束的反面情况，这是 ASP 和 Alloy 的本行，OWL 推理机不做这种搜索。所以到 (C) 时，很可能是 OWL 管模型、SHACL 管检查、clingo 或 Alloy 管找反例。这是以后的判断，现在只记下来。

## 6. 架构文档的写法规范（草案）与第一批抽取

### 6.1 写法规范的要点

用户的想法：文本很难直接抽成模型，所以定一份写法规范，以后写架构时往这个靠，抽取就容易。草案要点如下，这次只写在这里，不改 main 上的任何文档：

1. **一个概念只在一处定义，带标识。** 总图是 HTML，可以直接用 `<dfn data-concept="Department" data-layer="organization">部门</dfn>` 标出定义处，抽取时按标记读，不用猜。
2. **定义句用固定句式。** 「部门是围绕一个目标函数聚在一起的……」，「X 是一种 Y」对应 `rdfs:subClassOf`。
3. **关系只用登记过的动词。** 属于、产出、关注、核验、接、冻结、受限于……用到新动词就是新属性，要先在属性表里登记。
4. **数量写明。** 「一个角色只属于一个部门」对应函数属性；「可以多份」对应没有上限。
5. **不知道和未定写明。** 用「未定」「开环」这样的固定词，抽出来就是「不知道」或开环标记，不会被当成缺。
6. **一个概念一个正名。** 别名单列一处（比如 `work_item` 与 `run` 都对到「事项」），不在正文里换着叫。
7. **代码名不进总图正文。** 代码对照只写在 name-map；name-map 的状态列在「一致、不一致、代码里还没有」之外加一个「没核对」，好和「不知道」对上。
8. **每条断言能回链。** 抽出的断言记下节号和原句，人审时一眼对得上。

### 6.2 第一批从哪抽、怎么抽

| 来源 | 抽什么 | 怎么抽 |
| --- | --- | --- |
| name-map 第 1 至 3 节的表 | 总图的词、总图位置、代码名、归哪道缝、状态 | 机械读表，不用模型 |
| 三份发布形态的定义文件 | 部门、角色、成果种类、核验声明、来源、路由、能交完成 | 机械读 JSON |
| `kernel-manifest.json`、`runtime.py` 的形态登记、路由登记名、`SkeletonEventType` | 内核模块、形态、路由实现、骨架事件 | 机械读，ast 扫描 |
| 代码扫描 | 内核模块提到的名字（`yd:mentions`） | 沿用分支上 `layering.py` 的 ast 写法 |
| `architecture.html` 的五处：内核只认的那句话、四层、十三道缝及两侧、三环、外环九个状态 | 类、属性与它们的总图位置 | 大模型抽成 Turtle，每条附节号与原句；人逐条确认 |

最后一行是对用户那个担心的直接测量：拿大模型抽出的结果去和手写的第 2、3 节比，记下抽对了多少、漏了多少、抽错了多少。规则事实线以前试过开放抽取，召回只有四分之一；这次有明确的目标格式，看能好多少。数据出来，就知道写法规范要定得多严。

## 7. (A) 怎样服务两个用途

两个用途都在上面一层，为开发 Yudao 服务。

### 7.1 用途一：规格驱动的一致性

1. 总图对代码。每个种类要么有「实现」，要么标未建。name-map 是人工维护的这份对照；本体把它变成可以算的事实，再从代码直接读一遍去复核。这已经证明有用：name-map 最后改于 11 月 3 日，现在至少有 4 行落后于代码（写入范围、成果种类、直做、交完成）。
2. 分层。内核层的代码不提外层的实例名（部门名、成果种类名、形态名）。这就是「不变的放内核，变的放外圈」。11 月 4 日还能找到的两处写死已被 #1456、#1390 改掉，这条检查的用处变成守住它。
3. 总图自身与定义的矛盾，**按形态分别查**。三份形态的形状不一样：默认三部门有核验；两份直做形态默认没有核验，按设计以开环完成结束。所以闭合检查写成：被关注的成果有部门产出；被核验的成果有核验者；核验无环；每种来源有部门接；直做形态至少有一个角色能交完成。不写「每种成果都要有核验者」，否则会把直做形态误报成断头。
4. 术语表的缺口。总图内核那句话里的词，`CONTEXT.md` 都应有词条；现在缺事项、提案、回执、成果、执行权、上限、停止原因等。

### 7.2 用途二：给开发 Yudao 的 agent 装上下文

一张工单碰到某个种类，按本体就能取齐：总图里那一节、name-map 那一行、实现它的代码、它的测试、引用它的 D38 需求编号。例如碰到直做：总图第一节「轮转方式」、`direct.py`、`test_direct_routing.py` 与 `test_direct_with_verifier.py`、三份形态里用直做的两份。连线是写下来的，比按文本相似度检索准。

运行时给项目部门装上下文（语义系统第 10 节）要的是 (B) 的类型表，不是 (A)，不在这次范围。

## 8. 和 (B)、(C) 的边界，以后怎么接

### 8.1 (B) 软件工程通用方法模板

内容大致已经写在[语义系统设计说明](../design/semantic-system.md)第 5 节：内容种类（证据、事实、决定、要求等）、实体类型（项目、模块、文件、接口、页面、数据表、外部服务、术语、用户角色）、要求链（细化、实现、完成、验证、违反、处理）。代码里没有。

和 (A) 的接口只有两处，都只是引用，不绑在一起：

- (A) 的成果种类是「部门交出来的那一版」，(B) 的内容种类是「从接纳的那一版里拆出来的条目」。两者用「产生于」相连：主机从接纳的 PRD 生成要求条目，语义 5.1 已经这样写。
- (B) 由装配那道缝消费。(A) 只知道有装配这道缝，不知道 (B) 里有哪些种类。

脚手架和 (A) 同名的词，(A) 只取楼里的意思：

| 词 | (A) 里的意思 | 不进 (A) 的意思 |
| --- | --- | --- |
| 审查者 | 部门里的运行时角色 | 开发流程 `roles.json` 的审查角色 |
| 检查 | 项目检查定义与检查回执 | CI、文档一致性检查 |
| 提案 | 模型输出，等裁决 | 开发流程里提一个 ADR |
| 放行 | 质检结论 `release` | 合并、发布脚本 |
| 子事项 | 运行时的子循环 | 子工单 |
| 交付、缺陷、证据 | 只作为成果种类的名字出现 | 含义属于 (B) |

只属于脚手架的词整个排除：父工单、子工单、试用工单、里程碑、阶段工单、桶、道、薄片、清理单、标签。name-map 表里的「道」一栏也不取。

### 8.2 (C) 流程里的领域建模一步

用户说的以后：做一个记事本项目，Yudao 先做描述，建领域模型，用现在这套符号推理查全边边角角，再走 Yudao 的流程、裁决和循环。按总图现有的部件，它最自然的落点是：

- 领域模型是一种新的成果种类，由产品部门产出，工程与质检关注。
- 符号推理的检查由主机跑，结果是检查回执。这是「把东西实际跑一遍」那一种独立证据（基础规则 1），模型不能自己宣布模型完整。找反例这一类可能要 clingo 或 Alloy（第 5.3 节）。
- 领域模型的写法借 (B) 的实体类型与要求链。

现在不建。它要等 (B) 有了代码，和一份新的成果种类定义。(A) 的第一步在这之前就能做，也不会挡它。

### 8.3 自举时两份模型的关系

Yudao 开发 Yudao 时，那个项目以后在 (C) 里也会有一份 M1，写的正是 Yudao 的模块、文件、接口。它和 (A) 描述同一座楼，但来源不同：(A) 由上面一层维护，是评价的锚点；M1 由 Yudao 自己的流程生成，要经裁决。两者用「对应」关系相连，不合并，被迭代的系统改不了评价它的那一份。

## 9. 第一步

只在这个分支上做，等你点头。工具先在一处小例子上试通再用：`rdflib`、`pySHACL`、`owlrl`（纯 Python 的 OWL RL），推理机用 HermiT（要 Java，环境里有）。

1. 手写类与属性：一份 `yudao.ttl`，第 2 节的种类与第 3 节的关系，每个类带中文标签、总图位置、层。
2. 机械编出个体：第 6.2 节表里前四行，三份形态各编一份。
3. 抽取试验：让大模型从总图的五处抽 Turtle，附原句，人逐条确认，再和第 1 步手写的比。
4. 跑推理机（自洽、分类、分层）和 SHACL（覆盖、闭合、无环、来源打架），报告分违例、确实缺、不知道三栏。

成功标准（对着 32753a3）：

- 推理机：模型自洽；不用手写，就把三部门形态分进「有核验的形态」，把核验角色分出来。
- 确实缺：任务池与工作单元、判定点、子事项、外包角色、观察者、登记的机器、限定采用的范围，这 7 样都在，直做与交完成不在。
- 违例：name-map 落后于代码的 4 行（写入范围、成果种类、直做、交完成）全都报出来。
- 不知道：这一栏不空，而且每一条都说得出为什么不知道（比如收敛状态没人写、代码也没扫到）。
- 闭合：三份形态都通过；故意从一份直做形态里删掉「能交完成」，要报出来；两份直做形态不被报成缺核验者。
- 分层：故意在一个内核模块里写一个部门名，推理机要报不一致，SHACL 要指出是哪个模块哪一行。
- 抽取：记下大模型抽取对手写结果的对、漏、错各多少。这一条不设门槛，是给写法规范定多严用的数据。
- 另外至少找出一条 name-map 里没写、人也还不知道的。

什么情况下考虑换掉 OWL：类与属性里需要绕的写法（声明类、个体当类用）多到第 2、3 节一半以上的种类都要绕；或者推理机在这个规模上跑不进一次检查该有的时间。到时把数据带回来再定，不自己换。

## 10. 分支上现有的那份编译怎么处理

第一版第 11 节做的代码建模的是脚手架，又是 clingo 写的。在第一步里：

- 删掉 `compile.py`、`overlay.json`、`rules/ontology/` 下的 clingo 规则与对应的测试。分支上删，git 留着历史。
- 留下 `layering.py` 的 ast 扫描，改成输出 `yd:mentions` 三元组，名单换成三份形态的实例。

这次只改方案，没有动这些文件。

## 11. 还要你定的

1. 第 9 节的第一步可以开始做吗。
2. (A) 的 OWL 文件放在 `tools/doc-consistency/` 旁边，和规则事实线分开放，现在不互通（第 5.3 节）。这样可以吗。
3. 第 6.1 节的写法规范是只当草案留着，还是等第一步的抽取数据出来以后，再拿去改 main 上写架构的规矩。
