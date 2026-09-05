# Web 浏览器验收补全

继续同一 Web 会话，不改后端，不运行 git commit/push（主代理会按用户要求统一及时提交推送）。保留已完成的命令/生命周期逻辑及 CLI smoke。

## 已发现的真实布局问题

主代理已用真实 Chrome 在 `http://127.0.0.1:8771` 的 fake demo 页面截图。桌面 1440 宽没有溢出、没有 pageerror；手机 390 宽 scrollWidth=400，运行看板 12 个指标挤成窄列、逐字折行。截图位于 `.tmp/web-desktop.png` 与 `.tmp/web-mobile.png`。

修复指标区为明确、稳定的响应式网格，手机两列左右、桌面适度密度；整个页面在 390 宽不得横向溢出，正常词和数字不能逐字堆叠。不要只隐藏横向溢出来掩盖布局问题。

## 已确认三部门可视化

当前页面仅展示大段 transitions 文本，不能一眼看出产品、工程、质检三个部门。请在运行看板增加简洁三节点循环带：产品 -> 工程 -> 质检，当前部门从 `board.active_department` 高亮，节点/连线和相应文字显示当前阶段；Ask/React、返工和停止/完成状态来自现有 board 与 timeline 事实。三节点是数据流概览，保留四个既有详情视图，不重做页面，不引入前端框架，不用装饰性卡片。手机与桌面都要清楚，产品/工程/质检名称必须首屏可辨识。

## 测试和范围

只修改 `harness/web/**` 与 Web 专项测试。架构师已在第三轮完成后独立复跑：`test_web.py` 的 Node subprocess.run 仍无 encoding，17项中此项在系统默认 GBK 环境失败，其余16项通过。必须在实际代码显式指定 UTF-8，不能仅通过 PYTHONUTF8 环境变量让你自己的测试通过，也不能报告未落盘的修复。无新 SSE 的 delayed worker 场景应使用受控 worker 验证，不要强行假定并行后端取消后一定不会追加事件；不得为过测试修改后端。

完成后运行 `python -m pytest harness/tests/test_web.py -q` 与 `node --test harness/tests/test_web_ui.js`。浏览器若由你验证，可使用本机 `C:/Program Files/Google/Chrome/Application/chrome.exe`，不需要另装浏览器；已有 8771 服务由主代理管理，不终止它。主代理也会做截图复验。报告实际测试结果和改动，以便主代理提交。
