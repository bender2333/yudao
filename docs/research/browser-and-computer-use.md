# 浏览器与 computer use 调研

日期：2026-09-28。用途：[D34 浏览器与 computer use](../requirements/browser-and-computer-use.md)的依据。用户要求参考 Codex 的做法。
实现细节（虚拟屏幕、截图尺寸、动作集合、坐标空间）见 [computer use 实现调研](computer-use-implementations.md)。

## 1. Codex

仓库 `openai/codex`，本地 `C:\project\codes\codex`，提交 `69f7140`（2026-09-28）。开源仓库中只有这些工具的配置、权限审查与界面展示，浏览器与桌面操作的实现在随桌面应用分发的内置插件中，源码不在仓库。

- 内置插件与 MCP 服务器（`codex-rs/plugin/src/bundled_hooks.rs:26-111`）：`browser`、`chrome`、`computer-use` 等插件都经名为 `node_repl` 的 MCP 服务器工作，`unified-computer-use` 经 `cua_repl`。判定逻辑在 `codex-rs/protocol/src/mcp.rs:39-62`。
- 形态：一个常驻的 Node REPL，只有一个 MCP 工具 `js`，参数 `{code}`，模型写 JavaScript 驱动浏览器或桌面；截图经 `nodeRepl.emitImage(...)` 作为 MCP 图像内容返回（测试 `codex-rs/core/tests/suite/code_mode.rs:6850-6920`）。
- 仓库中没有 Responses API 原生 `computer` 工具的处理代码。
- 权限：浏览器按站点来源设置访问、下载、上传、完整 CDP 访问，批准有效期为本轮或整个会话（`codex-rs/config/src/browser_use.rs:7-22`）；computer use 按应用允许或拒绝（`codex-rs/config/src/computer_use.rs:7-35`）。确认策略把动作分为必须交还用户、执行时确认、可以预先批准、无需确认四级（`codex-rs/models-manager/models.json:126-127`），敏感动作交给用户或审查模型同步审查（`codex-rs/core/src/session/mcp.rs:770-826`）。
- 模型能力：内置模型全部支持图像；模型不支持图像时，历史与工具输出中的图像换成文字占位（`codex-rs/core/src/context_manager/normalize.rs:328-376`），模型看不到截图。
- 官方文档（已读）：https://learn.chatgpt.com/docs/browser?surface=app —— 浏览器只在桌面应用中提供，使用独立的浏览器配置，可以打开 localhost 与本地文件页面；首次访问网站前询问，提交、购买、改权限、删数据前确认。https://learn.chatgpt.com/docs/computer-use —— 需要安装插件（含 MCP 服务器与技能），macOS 需要屏幕录制与辅助功能权限，Windows 只能在前台操作，文档建议放进虚拟机；本地开发的网页应用先用内置浏览器。

## 2. OMP 与 OpenCode

- OMP（`C:\project\codes\oh-my-pi`，提交 `fdfeef1f78`）：自带 `browser` 与 `computer` 两个工具，都是模型写 JavaScript 的形式。`browser` 用 Puppeteer，`tab.observe()` 返回带编号的可访问性快照，`ariaSnapshot()` 返回 Playwright 的 ARIA 快照，另有截图与正文提取（`packages/coding-agent/src/tools/browser/tab-worker.ts:242-243, 1554-1627`）；提示写明默认使用 `observe()`，只在需要看外观时截图（`packages/coding-agent/src/prompts/tools/browser.md:13`）。`computer` 默认关闭，经原生扩展提供截图、键盘鼠标输入与操作系统可访问性树（`packages/coding-agent/src/tools/computer.ts:44-80`）。
- OpenCode（`C:\project\codes\opencode`，提交 `0027387`）：没有内置浏览器或 computer use 工具，官方技能文档用 Playwright MCP 作为 MCP 接入示例（`packages/core/src/plugin/skill/customize-opencode.md:111-116`）；MCP 返回的图像转成附件交给模型（`packages/opencode/src/session/tools.ts:426-435`）。

## 3. 可选方案

| 方案 | 形态 | 给模型的输入 | 是否需要看图模型 | 维护方 |
| --- | --- | --- | --- | --- |
| Playwright MCP | MCP 服务器，每个动作一个工具，另有断言工具（`browser_verify_*`） | 可访问性快照文本与元素引用；截图可选 | 不需要，README 写明不需要视觉模型 | Microsoft，v0.0.82（2026-09-18） |
| Chrome DevTools MCP | MCP 服务器，底层 Puppeteer | `take_snapshot` 的可访问性文本；另有网络、控制台、性能 | 快照不需要 | Google Chrome DevTools 团队，v1.10.1（2026-09-23） |
| OpenAI computer use | 模型写代码由应用执行，或 Responses 原生 `computer` 工具 | 截图 | 需要 | OpenAI |
| Anthropic computer use | Messages API 的客户端工具集，参考实现是 Docker 容器加虚拟显示 | 截图，坐标为截图像素 | 需要 | Anthropic |
| browser-use | Python 库，自带智能体循环 | DOM 文本，截图可选 | 可以不需要 | browser-use，MIT，0.13.10 |

## 4. 对 Yudao 的相关事实

- 网页操作有不需要看图的做法（可访问性结构），桌面程序的操作在所有调研对象中都依赖截图加坐标，需要看图的模型。
- Codex 的浏览器与桌面操作实现不开源，可以借鉴的是权限与确认的分级。
- Playwright MCP 经 MCP 接入即可使用，是 OpenCode 官方示例采用的方案。
