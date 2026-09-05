# Grok Build Web 入口任务

你是本任务的实现主力，直接完成代码与测试。架构师已授权此范围的执行工作，遵守 AGENTS.md 的工程约束，但不要把其中架构师不写代码的角色说明误认为禁止你实现。

## 文件所有权

只允许修改 `harness/web/**`、`harness/__main__.py`、`harness/tests/test_web.py`、新增 Web 专项测试和本任务文档。不要修改 runtime、adapter、context、tools、workspace、orchestrator、README、jour 或其他文档。另一 Grok 正同时修改那些模块。不要撤销他人改动、不要重写旧架构、不要提交 git commit。仓库若有 .codegraph，先用 CodeGraph 定位需要的代码。

## 已确认目标

首版入口是本地 Web 控制台：浏览器启动任务，观察 Product -> Engineering -> Quality 的真实循环与 spec/ask/react。界面发出命令，由现有 LoopSystem 负责创建、运行、取消，禁止 UI 直接改投影、状态或工件。

## 必做

1. `POST /api/runs` 接受任务文本与已有合理预算参数，通过 LoopSystem.create_run 和 run_until_stop 运行。服务内仅一个活动后台 worker；第二个启动请求返回 409，无复杂队列。输入错误 400，未知资源 404，provider 未配置时提供清楚错误，不能悄悄换 fake。
2. `POST /api/runs/{id}/cancel` 调用现有 LoopSystem.cancel。避免取消后旧 worker 尚未退出时接受新任务，活动占用必须以 worker 生命周期为准。不要在本任务修改引擎。
3. `python -m harness serve --adapter omp|fake`，默认 omp；demo 保持明确使用 fake。调整 serve 接收 LoopSystem 的已有调用与测试，不加旧 API 兼容层。普通 serve 默认 OMP 无配置时明确报错；合理选择启动时拒绝还是请求时拒绝，并测试。
4. UI 提供简洁中文任务输入表单、开始/取消命令、活动状态、错误与冲突状态。已有四个观察视图使用中文名称，保持信息紧凑。新建后自动选中并订阅任务。任务列表随状态更新。不得展示介绍应用实现或教用户运行 CLI 的文案。不要添加前端框架；沿用本地风格并去掉卡片嵌套。工具按钮优先熟悉图标，带 aria-label/title。
5. SSE 支持 `Last-Event-ID` 与 `after_seq` 的正确续传。切换任务不能把前一个任务的异步响应渲染到当前任务；连接与请求错误应有可见状态。清理旧 EventSource。
6. 用户输入与模型生成的 spec/ask/react/error 等均按文本显示，不可直接插入未经转义的 innerHTML；可以统一转义工具或 DOM textContent，保持实现简单。
7. 测试覆盖浏览器后端创建、409、取消、错误输入、未配置 provider、SSE 续传、只通过引擎改变状态、replay 不变性。可使用 FakeAdapter 或受控 mock，不调用真实 provider；主代理统一做真实 provider 验收。

## 已知代码形状

`harness/web/server.py` 当前仅接收 EventStore，POST 除 replay 外均 405。`harness/__main__.py` 当前 serve 固定 fake。`app.js` 使用 innerHTML 渲染不可信文本。SSE 每次 idle 约 30 秒断开而不读取 Last-Event-ID。请读现有运行门面与测试，使用它们已有功能，不扩展未确认功能。

## 验证与交付

运行 Web 专项测试，必要时全套 `python -m pytest harness/tests -q`。共享文件有并行改动，若全套失败明确区分本任务问题与另一 Grok 正在修改的依赖，不能编辑越界文件。不要停在计划或说明，完成实现后报告：修改文件、测试命令与结果、已知问题。不要读取或打印 provider.md 中的密钥，不运行另一个 Grok，不终止已有用户交互 Grok。
