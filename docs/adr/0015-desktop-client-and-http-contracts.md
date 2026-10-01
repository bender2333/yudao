# 桌面客户端、FastAPI 接口层，服务之间使用 HTTP 加 JSON

Status: 「从本机以外访问需要认证」一项，2026-09-28 用户决定在只于局域网内使用期间暂缓：接口层保留认证这一步，局域网访问不校验，访问令牌与 TLS 标为 TODO，离开局域网访问之前加入（[应用层与接口层设计说明](../design/app-and-interface.md)第 6.2、6.3 节）。「外包 agent 的运行容器」由 [ADR-0022](0022-run-directly-without-containers.md) 改为外包 agent 的运行进程，Yudao 不使用容器。其余决定继续有效。

界面要改为桌面程序（[系统架构原理](../design/architecture/core-and-materials.md)第 9 节），原型 v7 规定界面只通过查询读取、只通过命令提交（[ADR-0007](0007-boundaries-for-distributed-deployment.md) 第 5 条），Stage 6 要把执行层与观察者部署到不同的机器。决定：

- 客户端是桌面程序，外壳使用 Electron；界面使用 React 19、TypeScript、Vite、PixiJS 8、XState 5 与 GSAP。后端不提供界面文件。客户端按地址连接本机或远端的部署。
- 接口层使用 FastAPI，OpenAPI 由 pydantic 类型生成：
  - 命令带身份与基准版本，返回接受或拒绝，最终状态以事件为准；
  - 查询返回快照与它对应的全局位置；
  - 一条可以按范围筛选的事件流（SSE），带全局位置，断线后按位置补齐，发现缺口时重新同步快照；
  - 能力清单列出当前部署提供的查询、命令与覆盖层；
  - 从本机以外访问需要认证。
- 服务之间（控制核心与 Provider、执行环境、外包 agent 的运行容器、观察者）使用 HTTP 加 JSON，流式结果使用 SSE 或分块传输；合同都是 pydantic 类型。

理由：

- 合同只有一种来源（pydantic），客户端与服务之间使用同一套工具（FastAPI、httpx、OpenAPI 生成的客户端），不需要第二种描述语言。
- 模型调用与命令输出的流式传输、取消（关闭连接或按身份取消）与期限，HTTP 都能表达。
- Electron 在各平台使用同一个 Chromium 内核，PixiJS 的表现一致；桌面程序提供独立窗口、托盘、系统通知与窗口布局记忆，循环画面可以放在第二块屏幕。

考虑过的做法：服务之间使用 gRPC，取消与期限可以跨服务传递，流式返回方便；但合同需要 protobuf 作为第二种来源，另需一套生成与测试工具。

后果：

- 命令行与客户端经过同一个应用层；接口层只调用应用层，查询不写入事件。
- 界面的端到端测试用 Playwright 启动 Electron 应用。
