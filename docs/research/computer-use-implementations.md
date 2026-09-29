# computer use 实现调研

日期：2026-09-28。用途：给 [D34](../requirements/browser-and-computer-use.md) 设计时确定的三项提供一手来源：虚拟屏幕、截图尺寸、动作集合。方案名称比较见 [浏览器与 computer use 调研](browser-and-computer-use.md)。本次阅读官方文档与参考实现源码，没有运行这些容器、虚拟机或示例应用。

D34 已确认：网页用 Playwright MCP；桌面程序在容器的虚拟屏幕中运行，部门通过截图、点击与输入操作它；动作集合参照 Anthropic 的 Docker 容器加虚拟显示。下文按这个边界记录各家实现实际怎么做。

## 阅读范围

| 来源 | 读到的内容 | 没有读的内容 |
| --- | --- | --- |
| Anthropic 工具文档 | [Computer use tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool)，2026-09-28 读取：环境组成、批次、17 个成员、坐标、截图尺寸、从 `computer_20251124` 迁移的条目 | 每种语言的完整示例、价格表的全部数字 |
| Anthropic 参考实现 | [claude-quickstarts](https://github.com/anthropics/claude-quickstarts) `main` 提交 `dee71163217524eed07d79d00ffea5a7d02cedda`（2026-09-24）：`computer-use-demo` 的 Dockerfile、启动脚本、`computer.py`、`groups.py`、`loop.py` 的采样循环 | `streamlit.py` |
| OpenAI | [Computer use](https://developers.openai.com/api/docs/guides/tools-computer-use)、[集成配方](https://developers.openai.com/api/docs/guides/tools-computer-use-integration)，2026-09-28 读取；[openai-cua-sample-app](https://github.com/openai/openai-cua-sample-app) README（页面未给出本次核对过的提交号） | 示例应用的 `worker.py` 源码 |
| Gemini | [Computer use](https://ai.google.dev/gemini-api/docs/computer-use)，2026-09-28 读取；[google-gemini/computer-use-preview](https://github.com/google-gemini/computer-use-preview) README 与文件树（提交接口返回 403，未取得提交号） | `computers/playwright/playwright.py` |
| OMP | `C:\project\codes\oh-my-pi` 提交 `fdfeef1f78`：`computer.ts`、`computer/protocol.ts`、`prompts/tools/computer.md`、`settings-schema.ts`、`worker.ts` 的截图与可访问性调用 | 原生扩展内部实现 |
| OSWorld | [xlang-ai/OSWorld](https://github.com/xlang-ai/OSWorld) README 的安装与提供方，2026-09-28 读取 | 动作执行源码 |

## 1. Anthropic

### 1.1 工具合同

当前合同是客户端工具集 `computer_toolset_20260801`。请求的 `tools` 里放一条 `{"type": "computer_toolset_20260801"}`，不需要 beta 头。模型返回的是成员 `tool_use`：`name` 为成员名，块上带 `toolset_name: "computer"`，`input` 里没有 `action` 字段。应用在自己控制的环境里执行，把结果作为 `tool_result` 交回，结果也要带同一个 `toolset_name`。网页任务文档指向单独的 browser use 工具，那个工具读页面本身，不需要完整桌面（文档第 34–36、279、316–333 行，按本次保存的 Markdown）。

Claude API 与 Google Cloud 上，Claude 5.5 及以后的模型只接受这个工具集，更早的 `computer_20251124` 会报错。Opus 4.7、Opus 4.6、Sonnet 4.6、Opus 4.5 仍使用 `computer_20251124` 加 beta 头。Bedrock 等平台文档写明目前只有更早的 beta 版本（文档开头的 feature 说明）。

一次回应可以包含多个成员调用，文档称为 batch。应用按 `content` 里的顺序执行，不能并发。某一块失败后，后面的块不再执行，但每一块都要有 `tool_result`：失败块 `is_error: true` 并写明原因，未执行的块 `is_error: true`，文字固定为 `Not executed: an earlier computer action in this turn failed.`。漏掉任何一块，下一次请求会被拒绝。文档写明 Claude 通常用 `screenshot` 结束一批；一批不以截图结束时，应用可以把截图附在该批最后一个结果上（文档第 347、380、417–435 行）。

只有 `screenshot` 与 `zoom` 的结果必须是图像。其余成员用短文本即可，例如 `OK`；`cursor_position` 用文本返回坐标（文档第 332、380 行）。

工具集定义不接受 `name`、`display_width_px`、`display_height_px`、`display_number`、`enable_zoom`。坐标空间就是交回的全屏截图像素，原点在左上角。`zoom` 的图像不构成新的坐标空间，之后的坐标仍相对全屏截图。应用若把截图缩小再交回，必须把模型给出的坐标按同一比例放大后再作用到真实显示（文档第 764、879–880、2121、2127–2128 行）。工具集不会替应用缩小超限图像，超限直接拒绝。

声明全部默认成员大约增加 4500 个输入 token（文档第 2208 行，按模型略有差别）。

### 1.2 十七个成员

文档第 744–760 行的成员与参数：

| 成员 | 输入 |
| --- | --- |
| `screenshot` | 无 |
| `zoom` | `region`: `[x0, y0, x1, y1]` |
| `left_click` | `coordinate` 可选 `[x, y]`；`text` 可选，按住的修饰键 |
| `right_click`、`middle_click`、`double_click`、`triple_click` | 与 `left_click` 相同 |
| `left_click_drag` | `start_coordinate`、`coordinate`；`text` 可选 |
| `mouse_move` | `coordinate` |
| `left_mouse_down`、`left_mouse_up` | 无，作用于当前光标 |
| `cursor_position` | 无，文本返回截图像素坐标 |
| `scroll` | `scroll_direction`（`up`/`down`/`left`/`right`）、`scroll_amount`（滚轮格数）；`coordinate`、`text` 可选 |
| `type` | `text`，打到当前键盘焦点 |
| `key` | `text` 为键或 `+` 连接的组合；`repeat` 可选，1 到 100，默认 1 |
| `hold_key` | `text`、`duration`（秒，上限 300） |
| `wait` | `duration`（秒，上限 300） |

省略 `coordinate` 的点击与滚动作用在当前光标位置。`zoom` 默认启用；环境做不到时用 `configs` 关掉该成员，不要留着再返回错误（文档第 765 行）。

更早的单一 `computer` 工具用 `action` 字段区分动作，并在工具定义里声明 `display_width_px` 与 `display_height_px`。参考实现的版本表在 `computer_use_demo/tools/groups.py` 第 36–67 行：`computer_use_20241022`、`computer_use_20250124`、`computer_use_20250429`、`computer_use_20251124` 带各自的 beta 头；`computer_toolset_20260801` 的 `beta_flag` 为空。

### 1.3 参考实现的虚拟屏幕

仓库 README 与文档第 437–458 行描述同一套环境，并说明参考实现把这些部分放在一个 Docker 容器里。模型不直接连接这台机器；应用收到工具调用，翻译成环境操作，再把截图交回。

`computer-use-demo/Dockerfile`（提交 `dee7116`）：

- 基础镜像 `ubuntu:22.04`（第 1 行）。
- 安装 `xvfb`、`xterm`、`xdotool`、`scrot`、`imagemagick`、`mutter`、`x11vnc`（第 10–17 行），以及 Firefox ESR、LibreOffice、gedit、pcmanfm、tint2 等（第 42–50 行）。
- noVNC `v1.5.0` 与 websockify `v0.12.0`（第 55–57 行）。
- 用户 `computeruse`，`NOPASSWD: ALL`（第 60–63 行）。
- 构建参数默认 `DISPLAY_NUM=1`、`HEIGHT=768`、`WIDTH=1024`（第 97–102 行）。

`image/start_all.sh` 设置 `DISPLAY=:${DISPLAY_NUM}`，然后依次运行 `xvfb_startup.sh`、`tint2_startup.sh`、`mutter_startup.sh`、`x11vnc_startup.sh`。`xvfb_startup.sh` 第 4–5 行把分辨率组成 `${WIDTH}x${HEIGHT}x24`，DPI 为 96；第 37 行启动 `Xvfb $DISPLAY -ac -screen 0 $RES_AND_DEPTH -retro -dpi $DPI -nolisten tcp -nolisten unix`。`image/entrypoint.sh` 在此之后启动 noVNC 与 Streamlit。README 给出的端口：VNC 5900、noVNC 6080、Streamlit 8501、合并界面 8080。运行时可用环境变量 `WIDTH`、`HEIGHT` 覆盖屏幕尺寸。

README 写明组件分隔很弱：代理循环跑在被控制的容器里面，一次只能一个会话，会话之间需要重启或重置。

### 1.4 截图、缩放与动作执行

`computer.py` 从环境变量读取 `WIDTH`、`HEIGHT`，用 `xdotool` 发键鼠，显示前缀为 `DISPLAY=:${DISPLAY_NUM}`（第 113–126 行）。截图优先 `gnome-screenshot -p`，否则 `scrot -p`（第 258–264 行），文件写到容器内 `/tmp/outputs`（第 16、228–236 行），再 base64 放进工具结果。

缩放默认开启（第 99–100 行）。目标分辨率按宽高比就近选择，容差 0.02，且只在目标宽度小于物理宽度时缩小（第 58–61、279 行起）：

| 名称 | 宽 | 高 |
| --- | --- | --- |
| XGA | 1024 | 768 |
| WXGA | 1280 | 800 |
| FWXGA | 1366 | 768 |

默认 1024×768 与 XGA 相同，不会再缩小。模型坐标是截图像素。`ScalingSource.API` 把截图像素换算成物理像素再交给 `xdotool`；`ScalingSource.COMPUTER` 反向换算（第 294–302 行，物理到截图为 `round(x * target_width / physical_width)`）。README 建议自己实现时直接用 XGA；高于此时先缩小到 XGA 再按比例映射坐标，并写明依赖 API 侧缩小图像会降低准确度。文档第 1817–1821 行的建议是：一般桌面用 1024×768 或 1280×720，网页用 1280×800 或 1366×768，避免超过 1920×1080。支持 `computer_toolset_20260801` 的模型，截图与 zoom 图像的长边上限是 2576 像素，视觉 token 合计上限 4784（`⌈宽 / 28⌉ × ⌈高 / 28⌉`）；更早模型的长边上限是 1568 像素。超限图像会被拒绝，API 不代为缩小（文档第 1607–1610 行）。

`zoom` 把区域从截图像素映射到物理分辨率裁剪，再按比例缩进截图框内，不改变后续坐标空间（第 475 行起的文档字符串，与文档第 749、764 行一致）。

会改变界面的动作走 `shell()`：默认先等待 2.0 秒，再截一张图（第 99、267–275 行）。`type` 按 50 字分组、每组延迟 12 毫秒，全部打完再截一张（第 18–19 行与 `type` 分支）。这比文档要求的「只有截图与 zoom 必须回图像」多回了图。`hold_key` 与 `wait` 在参考实现里拒绝超过 100 秒（第 376 行）；文档上限是 300 秒（第 759–760 行）。

`loop.py` 第 200–241 行按块顺序执行工具集成员，第一块失败后其余块回 `ToolFailure`，不再执行，与文档的批次规则一致。

## 2. OpenAI

文档给出两条路径（[Computer use](https://developers.openai.com/api/docs/guides/tools-computer-use)）：

- 代码执行：模型写脚本，应用在隔离的浏览器或桌面里运行，回文本或图像。文档对 GPT-6 Astra 推荐这条。Python 示例的工具名是 `exec_py`，持久命名空间里有 PyAutoGUI、`log`、`display(PIL_image)`，并要求保持 PyAutoGUI 的 fail-safe。JavaScript 示例的工具名是 `exec_js`，视口写明 1440×900。会话在两次调用之间保持；`previous_response_id` 只延续对话，不恢复浏览器、登录或运行时变量。
- 内置 `computer` 工具：模型返回 `computer_call`，其中 `actions` 按顺序排列。应用执行整批后回一张截图，类型为 `computer_call_output` / `computer_screenshot`，`detail` 使用 `original`。文档列出的动作：`click`、`double_click`、`drag`、`move`、`scroll`、`keypress`、`type`、`wait`、`screenshot`。只有 `screenshot` 时不改变界面，只回当前画面。`status: "completed"` 表示模型已经生成完这次调用，应用仍要执行它。

截图规则（集成配方 “Capture screenshots”）：优先 `detail: "original"`。`original` 仍可能因模型尺寸上限被缩小。基于图块的图像输入在缩小后仍超过 30000 图块时，API 拒绝，不会再缩小到该上限以内。应用若先缩小再发送，必须把模型坐标从缩小后的坐标空间映射回原图。文档要求避免 `high` 与 `low`。

桌面环境配方是 Ubuntu 22.04 容器：安装 `xfce4`、`x11vnc`、`xvfb`、`xdotool`、`imagemagick`、Firefox ESR；`Xvfb :99 -screen 0 1280x800x24`；`x11vnc` 监听 `0.0.0.0:5900` 并使用密码；动作经 `docker exec` 从容器外执行；截图命令是 `import -window root png:-`。浏览器配方的 Playwright 视口示例是 1280×720。文档写明网页用浏览器，原生桌面程序用虚拟机或容器，同一次任务保持同一个会话。

[openai-cua-sample-app](https://github.com/openai/openai-cua-sample-app) README（MIT）：JavaScript 侧用 Playwright；Python 侧用 PyAutoGUI 控制宿主桌面上可见的浏览器，鼠标键盘是宿主的真实设备，截图可能含其他窗口。README 写明示例没有操作系统沙箱。每次运行把实验页面复制到新目录，截图与回放留在应用的 `data/`。

## 3. Gemini

[Computer use](https://ai.google.dev/gemini-api/docs/computer-use) 把 `computer_use` 放进 Interactions API 的 `tools`，用 `environment` 区分 `browser`、`mobile`、`desktop`。应用执行 `function_call`，再把新截图放进 `function_result`。Gemini 3.x 的动作带 `intent`。响应里可以有 `safety_decision`：放行、要求确认、或阻止。

桌面环境的动作（文档 “Desktop environment” 表）：`click`、`double_click`、`triple_click`、`middle_click`、`right_click`、`mouse_down`、`mouse_up`、`move`、`type`、`drag_and_drop`、`wait`、`press_key`、`key_down`、`key_up`、`hotkey`、`take_screenshot`、`scroll`。没有浏览器的 `navigate`、`go_back`、`go_forward`。坐标字段的取值写的是 0–999。执行示例把坐标从 1000×1000 的归一化网格换算到实际像素：`int(x / 1000 * screen_width)`。同一页前文写「模型预测的是按屏幕宽高缩放后的像素坐标，请求时不必声明显示尺寸」。动作表与换算函数使用 0–999；前文那句与这张表并用时，以动作表和换算函数为准才能点到表中声明的坐标。浏览器示例视口是 1440×900。`scroll` 的 `magnitude_in_pixels` 也标成 0–999，默认 300。

文档要求生产环境使用沙箱虚拟机或容器，并链接 [computer-use-preview](https://github.com/google/computer-use-preview) 为带 Docker 沙箱的参考实现。本次打开该链接得到的仓库是 `google-gemini/computer-use-preview`，README 与文件树只有 `playwright` 与 `browserbase` 两种浏览器环境，没有 Dockerfile，也没有桌面虚拟屏幕。文档中的 Docker 沙箱在本次读到的仓库里没有对应目录。

## 4. OMP

提交 `fdfeef1f78`。`computer` 默认关闭（`settings-schema.ts` 第 4326–4328 行）。打开后，模型提交一段 JavaScript，在持久会话里执行（`computer.ts` 第 42–46、83–89 行）。暴露的 API 在 `prompts/tools/computer.md`：窗口枚举、截图、点击、拖拽、滚动、打字、按键、操作系统可访问性树。提示要求优先用可访问性树的元素操作，元素操作不需要截图。指针坐标是同一目标最近一张截图上的像素；没有该目标的截图时，坐标输入会抛出。可访问性树的边界是桌面全局坐标，两套坐标不能混用。

默认输入方式是 `delivery: "background"`，不改变用户焦点。`read_only: true` 只允许查看。工具描述写明 `code` 拥有宿主权限，没有沙箱（`computer.md` 末尾）。截图上限默认宽 3840、高 2400（`settings-schema.ts` 第 4348–4367 行）。模型属于 Anthropic，或图像传输不能保留 `original` 细节时，捕获上限再收到 1280×896（`computer.ts` 第 28–29、138–149 行）。交回模型的图像带 `detail: "original"`（第 175–177 行）。全分辨率文件写到临时目录（`worker.ts` 第 188–209 行）。

OMP 操作的是运行智能体的那台机器的桌面。

## 5. Codex 与 OSWorld 的环境

Codex 提交 `69f7140` 与插件形态已记在 [浏览器与 computer use 调研](browser-and-computer-use.md)：桌面操作实现不在开源仓库，开源部分是权限、确认与界面。官方文档要求 macOS 的屏幕录制与辅助功能权限，Windows 只能操作前台，并建议放进虚拟机。仓库里没有 Xvfb 容器实现。

[OSWorld](https://github.com/xlang-ai/OSWorld) README 提供的是完整客户机：VMware、VirtualBox、带 KVM 的 Docker、Modal、Daytona、AWS。Docker 提供方运行 Ubuntu 或 Windows 客户机，README 要求宿主支持 KVM，并说明 macOS 宿主一般没有 KVM。本次没有读它的动作执行代码。许可为 Apache-2.0。

## 6. 与已确认边界相关的事实

虚拟屏幕。D34 点名的 Anthropic 参考实现是 Ubuntu 22.04 容器内的 Xvfb、Mutter、tint2、x11vnc、noVNC，默认 1024×768×24，键鼠经 `xdotool`，截图经 `gnome-screenshot` 或 `scrot` 再经 ImageMagick 缩放。OpenAI 集成配方是同一类容器：Xvfb、xfce4、x11vnc、`xdotool`，屏幕 1280×800×24，截图用 `import -window root`，动作从容器外 `docker exec`。OMP、Codex 插件与 OpenAI 的 PyAutoGUI 示例操作的是宿主桌面。OSWorld 运行完整客户机。Yudao 已确认 computer use 在 3.2C 的容器中运行虚拟屏幕（总体架构动作表，3.2D 行）。

截图尺寸与坐标。Anthropic 文档建议桌面 1024×768 或 1280×720，参考实现默认 1024×768；坐标是交回模型的全屏截图像素；缩小截图时要按同一比例把坐标映射回物理显示；`zoom` 不改变坐标空间。支持当前工具集的模型拒绝长边超过 2576 像素的截图。OpenAI 要求 `detail: "original"`，应用自行缩小时同样要映射坐标；配方里的容器屏幕是 1280×800。Gemini 桌面动作表的坐标是 0–999，由应用乘上实际宽高再除以 1000。三家的坐标空间不同，不能把一家的数字直接送进另一家的执行器。

动作集合。Anthropic 当前工具集是上面的 17 个成员，一次回应可以有多块，按顺序执行，失败即停，未执行的块仍要回答。OpenAI 内置工具是 9 种动作组成一批，整批执行完回一张截图。Gemini 桌面是 17 个 `function_call` 名称，坐标归一化，并带 `intent`。这三套名称是各自模型的工具合同。Yudao 的模型由用户提供，协议不限于 Anthropic Messages（[模型管理](../design/model-management.md)、[D34](../requirements/browser-and-computer-use.md)）。Anthropic 参考实现的价值在环境与「截图像素坐标、点击、输入、截图」的执行方式；`computer_toolset_20260801` 这个类型本身只被支持它的 Claude 模型发出。

证据。Anthropic 参考实现把截图写在容器内 `/tmp/outputs`，再放进当次工具结果；`zoom` 的临时文件在返回后删除。OpenAI 示例把截图与回放留在应用的 `data/`。OMP 把全分辨率文件写到临时目录，同时把图像放进工具结果。D34 仍要在设计里确定截图作为证据的保存位置与界面显示。Yudao 已确认环境工具的回执回到控制核心（总体架构第 7.3 节）；容器内的 `/tmp/outputs` 不会自己成为控制主机上的证据。

循环所在的位置。Anthropic 参考实现把采样循环放在被控制的容器里，一次一个会话。OpenAI 文档把对话状态与环境状态分开：应用持有环境，`previous_response_id` 只延续对话。Yudao 已确认每一步由控制核心驱动，环境工具在执行环境中执行（总体架构第 5、7.3 节）。
