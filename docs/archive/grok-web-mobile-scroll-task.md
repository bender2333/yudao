# 手机提交成功后显式回到看板

只修上一轮手机入口的一个已真实复现问题，不改其他功能、不操作 git。

Chrome 390x844、8771长历史任务页面：点击“新任务”后正确把表单提到前面，scrollY=117。拦截 POST /api/runs 返回201与已有run_id（避免调用provider），点击开始，创建与选中成功后仅移除 body.compose。由于浏览器滚动锚定，最终 scrollY=4882，boardTop=-4782，用户被留在页面底部，看板完全不可见。去掉 compose 不等于返回看板。

成功选中新任务后请显式让运行看板进入视口，并处理输入焦点/滚动锚定，确保390手机能看到三部门。只在手机执行这个移动端返回动作，桌面行为不改。请求失败/校验失败继续保留表单与输入。

请在实际Chrome复验，库与路径沿用上一轮任务：C:/Users/dengx/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright，executablePath C:/Program Files/Google/Chrome/Application/chrome.exe，URL http://127.0.0.1:8771。可用Playwright route拦截POST返回已有run_id，从而只测UI，不写真实任务。不要仅断言compose类被移除就算成功；看板或三部门节点的getBoundingClientRect必须实际在视口中。

补小型相关JS行为断言，运行Node与Web测试，报告实际截图/坐标，不调用真实provider。
