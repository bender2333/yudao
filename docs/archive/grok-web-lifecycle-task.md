# Web 最后生命周期验收

继续同一会话。只修改 Web 实现和 Web 测试，保留 CLI 的 smoke 与并行后端改动。

第二轮 HTTP 测试已通过，但以下真实 UI 行为仍有确定性缺口，请修复并完成行为验证，不要只检查源码字符串。

1. 已用 Node VM 独立复现：`scheduleRefresh('A', 1)` 正在等待时切换 `state.gen=2; state.runId='B'`，随后 `scheduleRefresh('B', 2)` 被全局 refreshInFlight 拦截；A 完成后 while 因 gen 不符退出，B 的刷新没有执行。实际调用列表只有 A。让刷新合并状态属于对应任务/代次，旧任务完成不能清掉新任务的刷新请求，或用更简单的调度办法。保持旧响应不会覆盖新 DOM 的 seq 约束。
2. worker 生命周期与 SSE 不相同。取消/最终事件先产生，worker 过一会才退出，退出本身不产生事件。UI 在最后一次事件处理时若拿到 busy=true，之后就会永远禁用开始。worker 异常发生在最后一次事件后时，UI 也无法看到执行错误。需要在服务 busy/等待 worker 退出期间以低频、无重叠请求检查 health（或同样简单的服务状态推送），退出后及时恢复按钮并显示执行错误；没有任务时不要无限频繁刷新整页。若页面展示历史任务而另一任务正在运行，同样要能观察当前 worker 退出。测试延迟退出与无新 SSE 的场景。
3. worker_error 当前是服务最后一次历史错误，applyHealth 无条件写全局 exec-alert，会让新成功任务继续显示旧错误。执行错误应与所选任务明确关联；切换到无错误任务应清掉，异常任务仍能查看。
4. 图标与许可证已有 static 根目录版本，index.html 也已有官方 icon inline path。清理重复、未使用的资源，保留最小一套官方来源与许可证。不要改 pyproject，也不要留下未打包的 icons/重复文件。

可用 Node 自带 vm + 受控 document/fetch/EventSource 来做少量 JS 行为测试，不需要浏览器或前端框架。已有 Node 可执行文件。应测试：旧任务慢请求期间新任务 SSE 仍能刷新；取消后 worker 延迟退出且无 SSE 时开始按钮恢复；异常后无新事件仍可见；旧 worker 错误不污染另一任务。Python Web 测试继续跑，新增 JS 测试可由一个 Web 专项 pytest 调 node，或直接 node:test 并报告命令。

完成后报告实际测试输出，不调用真实 provider，不修改其他目录，不启动另一个 Grok。
