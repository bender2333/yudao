# 手机新任务入口

上一稳定 Web 块已经由主代理提交推送（d3ba319）。继续同一会话，只实现本次独立小功能，改动范围仅 `harness/web/**` 和 Web 专项测试。不要改后端/CLI，不执行 git commit 或 push，主代理验收后立即提交。

## 目标

当前手机先显示运行看板，长历史任务的上下文/事件很多，现有创建表单排在页面底部。390宽用户不应手动滚完整页才开始新任务。

在手机顶部增加一个熟悉的加号图标入口，accessible name 和 tooltip 为“新任务”。使用同一官方 Lucide 图标来源，保留许可证，不加前端依赖。点击后直接定位/展开现有创建表单，聚焦任务输入框。成功提交后返回该任务运行看板。不要复制出第二套表单，不要丢弃用户已有输入，不要改变桌面现有布局，不重做页面。

保留已实现的提交中禁用、busy冲突、取消中状态、事件订阅和刷新代次处理。输入错误/409/503时应留在可修正输入的位置，只有成功创建并选中后才回看板。可以修极少量直接相关的问题，避免扩大范围。

## 验证

新增或调整少量真正的行为测试：手机新任务入口聚焦已有输入且保留内容；提交成功回看板，失败仍留表单；现有开始/取消行为不退化。运行 `python -m pytest harness/tests/test_web.py -q` 与 `node --test harness/tests/test_web_ui.js`。Python调Node必须显式UTF-8，不能依赖临时环境变量。

主代理的临时 fake demo 地址为 `http://127.0.0.1:8771`，可用于浏览器只读/假任务交互验收，不终止它。真实Chrome在 `C:/Program Files/Google/Chrome/Application/chrome.exe`；Playwright模块在 `C:/Users/dengx/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright`。390宽长历史任务下确认入口首屏可见，不需要手动翻到底部；桌面保持现状。

完成后报告实际改动与测试结果，不停在方案，代码需实际落盘。
