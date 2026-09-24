# Grok Build：真实 Provider 三部门验收

## 分工与范围

用户指定 Grok Build 为实现主力，Codex 负责架构与验收。本任务直接实现和验证，不停留在计划。保留当前未提交改动，不提交 git，不修改 oh-my-pi 源码。

阅读 docs/loop-system-mvp-design.md 和 jour.md。首要结果是在用户 provider 上跑通真实 product -> engineering -> quality 循环，模型提出 spec，控制层判定交接和完成。不要加入长期记忆、知识图谱或新的部门。

## 已有证据

- provider.md 中两个 provider 已通过 models、Responses 非流式、流式、function tools 验证。不要重复探测，不要通过工具读取或输出该文件。主 provider blackrouter，模型 gpt-5.6-terra；备用 penguin，模型 gpt-5.6-luna，仅人工显式选择。
- 启动本任务的进程已注入 BLACKROUTER_API_KEY、PENGUIN_API_KEY、PI_CODING_AGENT_DIR、YUDAO_OMP_COMMAND、YUDAO_OMP_ARGS、YUDAO_OMP_PROVIDER、YUDAO_OMP_MODEL。直接继承环境变量，禁止打印环境变量值或凭据。
- 源码版 OMP 缺少 native addon，但已发布包正常。当前 Bun 为 C:/Users/dengx/AppData/Local/npm-cache/_npx/5c4f1b4a21be27f7/node_modules/bun/bin/bun.exe；发布包入口为 C:/Users/dengx/AppData/Local/npm-cache/_npx/7feb23472ba5a719/node_modules/@oh-my-pi/pi-coding-agent/dist/cli.js。不要再扫描整个用户目录或构建 native addon。
- 临时 OMP profile 是 .tmp-omp-profile/agent/models.yml，只引用环境变量，已忽略。真实结果放在 .yudao/provider-validation 下。
- 原工具映射 ls 在 OMP 中不存在；已改为 glob。带 read,write,bash 的发布包已发出 ready。不要把此启动成功等同于三部门验收成功。

## 必须修复的链路

1. 当前 adapter 使用阻塞 readline，timeout/abort 无法在静默 stdout 上生效，stderr 可能堵塞。采用成熟 OMP Python RPC client（先调查本地 python/omp-rpc 的 API/可安装性）或最小可靠读队列，确保 deadline、进程退出、清理与错误诊断实际生效。避免吞掉早退为 completed。诊断必须过滤凭据。
2. Yudao 工具名称与模型实际可调用工具一致。优先复用 OMP RPC set_host_tools / host_tool_call / host_tool_result，把工具执行交给 Yudao ToolRuntime。禁用无约束的内建工具，防止 Product/Quality 通过 bash 绕过写权限。协议、字段以本地 OMP 文档源码为准。
3. run_check/collect_evidence 必须真正执行检查并由主机产生 exit code、摘要、当前快照回执；不能接受模型自报 exit_code 当证据。fake 脚本的模拟行为应明确隔离。检查在工作区内运行，权限和快照边界明确，不向检查子进程透传 provider 凭据。不降低 validation 验收条件来获得 DONE。处理 .checks 私有路径，不能让 agent 伪造回执。
4. 上下文提供各部门可提交的 proposal 合同/字段，关联 id/hash/版本和校验反馈，让真实模型能正确提交。不能靠测试任务包含整套内部 JSON 实现协议来掩盖缺失。保留当前 spec、必要事实与薄因果链，隔离跨部门 transcript。禁用无关 OMP 自动发现和持久历史的注入。
5. 使用真实主 provider 跑最小文件/CLI 任务，经历产品 spec、工程实际写文件并检查、质检独立检查、DONE。另验证一次 ask -> react 的往返，允许用明确的需求歧义或指示触发，但 spec 和决定仍来自真实模型。遇 provider 错误真实记录，禁止替换 fake 冒充成功。
6. 保存可重复运行的 smoke 入口（读取环境变量而非 provider.md），产出简明结果报告：run id、路由、provider/model、真实工具/检查回执、结束原因、replay 一致性、上下文隔离。更新 README 与中文 jour.md。运行适当测试和 python -m pytest harness/tests -q，修复有证据的问题。

## 完成回报

报告修改文件、测试结果、真实 run id 和证据路径、已验证的能力和实际局限。不要为赶验收去掉质量检查、绕过预算或人为插入成功事件。本机已有用户 Grok 交互进程，不要终止它。
