# Web 原型视觉契约

日期：2026-09-06。本文是 W0 的可执行视觉与交互验收清单，依据冻结原型 [department-workspace.html](prototypes/2026-09-06/department-workspace.html) 编写。它服务于后续 W2-W7 的实现和截图对照，不表示 Web 已完成。

当前阶段顺序仍为 Provider 连接与部门绑定、第一阶段真实验收、OMP 审查、Context/Trace、Web 完善、Prompt 优化。Provider 配置、凭据管理、连接测试、部门模型选择和相关表单属于 W-P，等待对应原型；本契约只覆盖已确认的只读 Provider 检查区域。

## 1. 来源与不变量

- 原型源文件：docs/prototypes/2026-09-06/department-workspace.html。冻结 SHA-256：DA6EF90D8B2BDA4D69049BE266F8C8B3D48C2009FF0B269D7CF12AA526E3C03F。
- 预览文件：docs/prototypes/2026-09-06/department-workspace-preview.html。冻结 SHA-256：4EA621B64B5596F540A50D8DE2649BB0E65792F5696C14733E0CB6CFA2F03DBB。
- department-workspace.html 是样式、DOM 和示例交互的基线；department-workspace-preview.html 只是 iframe 包装器。生产页面不能复制外层 1rem 内边距、iframe 高度或预览容器。
- 原型中的任务、部门、Provider、模型、Prompt、请求、响应和 usage 都是示例数据。生产页面必须接入真实查询结果，缺失值显示未知或未上报，不能把示例值当默认配置。
- 原型发送只改变浏览器内存；生产命令仍由已有 API 和内核处理。页面查询不能推进部门、创建材料或自动重试。
- Tweak 的信息密度和检查区宽度滑块是原型调试工具，不进入产品 UI。
- 参考截图位于 .tmp/stage2-prototype-reference/，机器可读清单为 .tmp/stage2-prototype-reference/capture-report.json。截图通过本地 HTTP 服务器用 Edge 生成，只截 iframe 内层区域，未截预览包装器。捕获脚本在 iframe 内注入本地 Lucide UMD bundle，等待字体就绪和两帧绘制，并验证所有图标已转换为可见 SVG；报告同时记录命名视口、iframe 外框和原型根节点的实际尺寸。

## 2. 全局视觉令牌

根节点为 #department-workspace-prototype（原型源码第 2 行起）。以下值必须作为视觉对照基线：

| 令牌 | 浅色 | 深色 | 用途 |
| --- | --- | --- | --- |
| --dw-accent | #087f69 | #56d1b3 | 活动、选中、主要操作 |
| --dw-accent-soft | #e4f4ef | #17372f | 活动背景、选中背景 |
| --dw-background | #f3f4f3 | #171918 | 页面背景 |
| --dw-surface | #ffffff | #1d1f1e | 导航、卡片、检查区、输入 |
| --dw-surface-raised | #fafbfa | #242625 | 反馈详情、次级表面 |
| --dw-foreground | #262827 | #ecedeb | 正文和标题 |
| --dw-muted | #6f7472 | #a5a9a6 | 辅助文字 |
| --dw-subtle | #9da3a0 | #747a76 | 更弱的辅助信息 |
| --dw-border | #dfe2e0 | #383c3a | 普通边框和分隔线 |
| --dw-border-strong | #c6cbc8 | #515652 | 输入边框、连接线 |
| --dw-amber | #9a6200 | #f1b949 | 等待、进行中 |
| --dw-amber-soft | #fff4d8 | #443617 | 等待提示背景 |
| --dw-red | #b9473e | #ef8278 | 错误、失败 |
| --dw-blue | #356e9f | #83b8e4 | 用户消息标记 |

基础字体为 "Microsoft YaHei UI", "Microsoft YaHei", ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif，字号 14px、行高 1.5、字间距 0（源码第 4-42 行）。标题使用 font-weight: 500：h1 为 1.45rem、h2 为 1rem、h3 为 .9rem。数字和时间使用 font-variant-numeric: tabular-nums。

颜色采用 light-dark() 和浏览器 color-scheme，没有全页渐变、装饰球或高饱和背景。状态颜色只出现在状态点、状态文字、选中边框、等待条和错误事件等局部位置。

## 3. 共用布局与断点

### 桌面布局

源码第 55-80 行定义共用框架：

- .dw-shell 为两列 grid：左侧导航固定 68px，右侧为 minmax(0, 1fr)。
- .dw-sidebar 使用表面色和右边框，垂直内边距 12px * --dw-density，水平内边距 8px。
- .dw-main 上内边距 28px * --dw-density，下内边距 32px * --dw-density，水平内边距 clamp(16px, 3.4vw, 46px)。
- .dw-page 和 .dw-observation-page 最大宽度均为 1240px，水平居中。
- 普通页面头部使用左右分布的 flex；标题、状态、辅助说明之间保持约 18px 间隔。

### 导航

DOM 基线在源码第 413-425 行：

- 品牌图标 layers-3，文字“协作台”。
- 导航顺序固定为 总览 / 产品 / 工程 / 质检 / 观测。
- 图标使用 Lucide：layout-dashboard、clipboard-list、braces、check-check、activity。
- .dw-nav-item 最小高度 54px，内边距 7px 3px，圆角 7px，图标 17px，文字 .72rem，各项间距 5px。
- 活动项使用 --dw-accent、--dw-accent-soft 和混合边框；普通项只有 muted 文字，悬停时使用页面背景。
- 图标按钮使用 Lucide，不手绘新的 SVG；收起检查区使用 panel-right-close，展开使用 panel-right-open。

### 响应式

源码第 345-409 行是唯一断点基线：

- max-width: 760px：shell 变为单列；导航变为顶部条；导航五项等宽、最小高度 42px；主区内边距 22px 16px 28px；流转卡片变为纵向；部门工作区和检查区变为单列；观测筛选变为两列，搜索独占一行；请求列表变为时间/主体两列，指标放在主体下方。
- max-width: 430px：筛选框、搜索框和 textarea 使用 16px；主要按钮和检查区图标按钮最小高度 44px；品牌文字隐藏；头部状态下移；最近流转状态另起一行；观测筛选变为单列；请求行变为单列；详情字段、用量指标和总计区域变为两列；事件行采用时间/主体/查看原文三列，Raw 事件正文左缩进 62px。
- 必须检查 1440px、1024px、390px、360px，并在 320px 检查 Raw JSON 的换行和可滚动性。不能出现横向溢出、长模型名撑宽布局或按钮文字遮挡。

## 4. 总览页

由 .dw-overview-page、.dw-topline、.dw-section 和 renderOverview()（源码第 756-773 行）组成。

- 头部 eyebrow 为“示例任务 · 三部门协作”，标题为任务名，辅助文字为最近更新时间和当前协作节点；右侧是状态胶囊 .dw-current-state，圆角为 999px，内边距 6px 10px。
- 每个 section 上间距约 31px，section 标题和右侧说明在同一行，标题下间距 13px。
- 协作流转 .dw-flow-map 为五列：产品节点、需求连接、工程节点、交付连接、质检节点；节点最小高度 188px，内边距 15px，圆角 8px，边框加轻阴影。
- 节点内部顺序为序号/状态、部门名、部门角色、当前任务、当前材料、当前记录 / 进入工作区。状态点为 7px。
- 连接线使用细边线、短标签和 arrow-right 图标；返工反馈位于第三至第五列，以 corner-up-left 和 arrow-left 表示质检部回工程部。
- 点击返工记录后显示 .dw-detail：1fr auto 两列、上/下边框、raised 表面；窄屏变单列，路由文字允许换行。
- 最近流转 .dw-record-list 使用 62px / 1fr / auto 三列、13px 间距和每行 11px 垂直内边距；状态文字右对齐，等待使用琥珀色。
- 任务输入位于页面下段，当前接收方固定显示产品部入口；textarea 最小高度 76px、圆角 7px，发送按钮最小高度 36px、圆角 6px、带 send 图标。
- 全局输入追加后保留原消息，并显示“等待产品处理”琥珀提示；不能删除或编辑历史输入。

验收选择器： [data-view="overview"]、[data-department="product"]、[data-department="engineering"]、[data-department="quality"]、[data-handoff]、[data-global-draft]。

## 5. 部门工作区

由 .dw-department-page、.dw-work-grid、.dw-conversation、.dw-inspector 和 renderDepartment()（源码第 779-796 行）组成。

- 顶部有“回到总览”返回按钮和当前部门状态；下面依次是部门 eyebrow、当前部门任务标题、任务 · 部门工作区说明。
- .dw-task-strip 上下各一条边框，内边距 9px 12px，使用 route 图标；显示当前任务，不做成浮动卡片。
- 工作区默认 minmax(0, 1fr) 304px 两列，列间距为 clamp(22px, 3.2vw, 42px)，上间距 27px。检查区收起时右列固定 44px。
- 工作消息标题行显示记录数和部门状态；消息时间线左侧为 1px 强边框，消息左内边距 18px，消息下间距 20px。用户、本部门、其他部门分别由蓝色、绿色和灰色节点区分。
- 消息来源标题 .78rem，来源补充说明 .71rem，正文 .84rem 且最大宽度 70ch，正文保留换行。
- 检查区使用表面色、左边框和轻阴影；标题区内边距 12px 13px，内容区 13px。页签为三等分 segmented control，外层背景为页面背景，激活项为表面色和轻阴影。
- Context 页签显示“本次工作输入”、快照时间、三条可选来源、选中正文和“查看模型请求”；选中项使用 accent-soft 和混合边框。
- Provider 页签只读显示提供方、模型、温度、上下文窗等实际快照字段。这里不能新增配置输入、保存、凭据或连接测试。
- Prompt 页签显示当前版本/生效状态和只读原文；编辑和保存行为不从静态原型示例推断。
- 当前部门 textarea 最小高度 76px；按钮文字为“发送指导”，提交后追加用户消息并显示“等待{部门}处理”。

验收选择器： [data-department="engineering"]、[data-view="overview"]、[data-inspector-tab="context"]、[data-inspector-tab="provider"]、[data-inspector-tab="prompt"]、[data-context-id]、[data-observe-department]、[data-inspector-toggle]、[data-dept-draft]。

## 6. 观测页

### 请求列表

观测页由 .dw-observation-page 和 observationShellMarkup()（源码第 698 行）组成：

- 头部 eyebrow 为“观测 · 任务”，标题“模型请求”，副标题“请求 · 响应 · usage”，右侧显示当前进行中的请求。
- 任务范围条上边框和下边框，内边距 10px 12px，包含 activity 图标、任务、时间范围和尝试数。
- 主页签为“请求记录 / 用量统计”，顶部间距 27px，页签间距 22px，激活项底部为 2px accent 线。
- 筛选区桌面三列：部门、状态、搜索；列最小宽度分别约 120px / 120px / 210px，间距 12px。输入控件最小高度 36px、圆角 6px。
- 请求列表结果头上间距 22px；每行桌面三列为 116px / 1fr / 170px，间距 15px，垂直内边距 12px。行内展示时间、成功/失败/进行中状态、调用 ID、部门、Provider、模型请求 ID、尝试次序、工作轮次、Input/Output 和耗时。
- 失败尝试使用红色，进行中使用琥珀色；缺失 usage 显示“未上报”，进行中的输出显示“等待响应”，不能显示成零。

验收选择器： [data-view="observability"]、[data-ob-tab="requests"]、[data-obs-department]、[data-obs-status]、[data-obs-search]、[data-obs-request]。

### 请求详情

点击 [data-obs-request="attempt-7F3A-2"] 进入详情（源码第 745-754 行）：

- 顶部左右为“返回请求记录”和“返回质检部”；标题显示请求 ID 和状态。
- 关联条依次显示任务、部门、本轮工作、请求、尝试，使用上/下边框和可换行 flex。
- 尝试栏显示同次调用 call-7F3A，第 1 次失败和第 2 次成功都可点击，当前尝试使用 accent 边框/背景。
- 详情页签固定为“概览 / Request / Response / 事件”，间距 20px，激活项使用底部 2px accent 线。
- 概览先显示四项 usage，再以两列字段表显示 Provider、Model、耗时、成本、工作、步骤、Context、Prompt、数据来源和采集范围。
- Request/Response 使用 .dw-json：边框、表面色、圆角 6px、内边距 12px、等宽字体 .72rem、行高 1.55、pre-wrap 和断词。
- 没有响应时使用左侧琥珀边框和等待背景，文案为“等待模型响应”。
- 事件列表每行显示时间、事件类型、摘要和“查看原文”；展开后 Raw JSON 与所属尝试绑定，错误为红色，等待为琥珀色。

验收选择器： [data-obs-attempt]、[data-obs-back]、[data-department]、[data-ob-detail-tab="overview"]、[data-ob-detail-tab="request"]、[data-ob-detail-tab="response"]、[data-ob-detail-tab="events"]。

### 用量统计

点击 [data-ob-tab="usage"]：

- 结果头显示筛选结果数量和 usage 覆盖率。
- 覆盖条显示“已上报次数 / 总尝试次数”，并说明输入（含缓存）与缓存读取是包含关系，不能重复相加。
- 总计条先显示筛选总计，再显示输入（含缓存）、输出、缓存读取（输入子集）和总 Token；成本没有真实来源时显示“未上报”。
- 分组顺序为“按部门”“按模型”；每组显示覆盖率、水平进度条和相同四类 Token 指标及成本位置。
- 桌面 usage 行为“标签 / 指标”两列，指标五列；430px 以下变成单列标签和两列指标。
- 统计范围必须和请求列表筛选保持一致，重试每次单独计数，缓存属于输入子集，缺失字段不填零。

## 7. 状态与交互清单

原型脚本的状态入口在源码第 533-555 行，事件委托在第 808-855 行。生产实现必须保留下列用户可见关系：

| 操作 | 可见结果 | 生产边界 |
| --- | --- | --- |
| 点击总览/部门/观测导航 | 主工作区替换，活动导航项更新 | 不创建新任务，不改变内核状态 |
| 点击部门卡片 | 进入对应独立部门页 | 任务、草稿和查看对象按任务隔离 |
| 点击交接记录 | 显示交接详情 | 详情必须来自真实事件/材料 |
| 点击 Context 条目 | 切换选中输入正文 | 只能读取对应快照 |
| 点击“查看模型请求” | 进入该部门关联请求 | 必须绑定当次 Context 和实际模型尝试，不能用任意最新请求替代 |
| 输入总览需求并发送 | 保留历史、显示等待产品处理 | 通过全局输入 API，由产品处理 |
| 输入部门指导并发送 | 在当前部门追加用户消息、显示等待部门处理 | W6 先确定接收时机、原文范围和终态关系 |
| 点击观测请求 | 进入请求详情 | 逻辑调用、物理尝试、协作 request 必须区分 |
| 点击尝试 | 切换同一调用的失败/成功尝试 | 只读，不重新调用模型 |
| 点击 Request/Response/事件 | 切换详情内容 | Raw 内容安全转义，可滚动和换行 |
| 点击用量统计 | 切换同筛选范围统计 | 未上报和进行中独立显示 |
| 收起检查区 | 桌面右侧变 44px，移动端只隐藏内容 | 不丢失当前页签和选中 Context |

## 8. 截图验收矩阵

截图由 .tmp/stage2-prototype-reference/capture.cjs 生成，脚本在每次截图前重新加载预览并使用原型自身选择器切换状态。文件命名为 {view}-{viewport}-{color-scheme}.png：

| 视图状态 | 选择器和状态 | 浅色视口 | 深色关键视口 |
| --- | --- | --- | --- |
| 总览 | [data-view="overview"]，state.view=overview，默认质检→工程反馈 | overview-1440x900-light.png、overview-1024x768-light.png、overview-390x844-light.png、overview-360x800-light.png | overview-1440x900-dark.png |
| 工程工作区 | [data-department="engineering"]，inspectorTab=context、selectedContext=qa-feedback | engineering-1440x900-light.png、engineering-1024x768-light.png、engineering-390x844-light.png、engineering-360x800-light.png | engineering-390x844-dark.png |
| 请求列表 | [data-view="observability"]、[data-ob-tab="requests"]，显示 5 次示例尝试 | observability-requests-1440x900-light.png、observability-requests-1024x768-light.png、observability-requests-390x844-light.png、observability-requests-360x800-light.png | 通过详情深色图覆盖观测深色结构 |
| 请求详情 | [data-obs-request="attempt-7F3A-2"]，第 2/2 次成功，包含第 1 次失败 | observability-detail-1440x900-light.png、observability-detail-1024x768-light.png、observability-detail-390x844-light.png、observability-detail-360x800-light.png | observability-detail-1440x900-dark.png |
| 用量统计 | [data-ob-tab="usage"]，全部部门和模型 | observability-stats-1440x900-light.png、observability-stats-1024x768-light.png、observability-stats-390x844-light.png、observability-stats-360x800-light.png | 后续应用验收需补同视口深色统计 |
| Raw JSON | 请求详情后 [data-ob-detail-tab="request"]，宽度 320px | observability-raw-320-320x800-light.png | 后续应用验收需补深色 Raw |

本轮参考截图报告记录：24 张 PNG；Edge 路径为 C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe；Lucide bundle 路径和 SHA-256 记录在 capture-report.json；每张截图均满足内层视口与命名视口一致、字体状态为 loaded、未转换图标数为 0；Playwright 报告 ok: true，页面错误、HTTP 错误和非 GET 请求均为空；源文件和预览文件截图前后 SHA-256 未变化。

## 9. 与实施计划的衔接

- W0：以本文作为视觉基线，并补齐 D20 部门指导的处理时机、原文范围、版本审计和终态影响。
- W1：先统一请求采集和查询事实，分离协作请求、逻辑模型调用和物理尝试。
- W2：实现共用导航、总览、独立部门页、消息来源、检查区、草稿隔离和响应式骨架。
- W3：接入 Context 快照、精确请求跳转、Request/Response/事件详情和重试切换。
- W4：接入请求列表筛选、usage 覆盖率、部门/模型分组和缺失值显示。
- W5：接入真实流转、返工反馈、最近记录和全局任务输入。
- W6：在 W0 规则确定后实现部门定向指导的持久接收和真实内核处理。
- W7：使用本目录截图矩阵进行浅色/深色、桌面/移动端、真实 Web 流程和历史重放验收。
- W-P：等待 Provider 配置原型；当前只读 Provider 检查页保持位置和数据边界，不补配置表单。

六项前置工作完成前，不启动长期记忆、跨任务项目演化或独立学习管线。
