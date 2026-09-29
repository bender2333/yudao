# 浏览器与 computer use 设计说明

更新：2026-09-29。状态：设计草稿，第 16 节的事项等待用户确认；未实施。路线位置：[Stage 3 计划](../stage-3-plan.md) 3.2D，父工单 [#123](https://github.com/bender2333/yudao/issues/123)。

依据：需求 [D34](../requirements/browser-and-computer-use.md)；[执行环境服务设计说明](execution-environment.md)（3.2C：执行环境服务、本机容器、执行代理、执行位置、动作回执）；[模型管理设计说明](model-management.md)第 4.3、5.6、6 节（输入方式、部门的建议能力、请求时按输入方式提供工具）；[总体架构](architecture/overall-architecture.md)第 6.3、7.3、7.4 节；[恢复契约与故障矩阵](recovery-contract-and-fault-matrix.md)第 4 节；[应用层与接口层设计说明](app-and-interface.md)第 3.2、3.3、4.3 节；[本地通用工具设计说明](local-tools.md)第 2 节；[语义系统设计说明](semantic-system.md)第 5.5、13 节；[评测场景](evaluation-scenarios.md)场景 1；[原型 v8 设计说明](../prototypes/v8/design.md)第 7.1、7.3、8.3、9.4 节。调研：[浏览器与 computer use 调研](../research/browser-and-computer-use.md)、[computer use 实现调研](../research/computer-use-implementations.md)。工单：[#122](https://github.com/bender2333/yudao/issues/122)（3.2B）、[#69](https://github.com/bender2333/yudao/issues/69)（MCP 工具）、[#146](https://github.com/bender2333/yudao/issues/146)（输入方式与建议能力）、[#142](https://github.com/bender2333/yudao/issues/142)（3.2C 的 F）。用词以 `CONTEXT.md` 为准。

参照实现的提交号：Playwright MCP `microsoft/playwright-mcp` v0.0.83（2026-09-28，`main` 提交 `f183dad`，依赖 Playwright `1.64.0-alpha-1790635538000`）；Anthropic `claude-quickstarts` 提交 `dee7116`；OMP `C:\project\codes\oh-my-pi` 提交 `fdfeef1f78`；OpenCode `C:\project\codes\opencode` 提交 `0027387`。

## 1. 范围

3.2D 交付：

- **试用会话**：在 run 的本机容器中，从一份公开树清单建立试用副本，用项目登记的启动命令启动交付的软件，再打开浏览器或虚拟屏幕供部门操作。
- **浏览器工具**：内置的 Playwright MCP 服务，经 3.2B 的 MCP 客户端调用，每个动作一个工具；每一步把页面的可访问性结构交给模型，模型能看图时同时附上截图；每一步的截图都保存为证据。
- **computer use**：容器中的虚拟屏幕，8 个屏幕工具（截图、点击、拖动、移动、滚动、输入文字、按键、等待），坐标是截图像素。
- **按模型输入方式提供工具**：调用目标不含图像时不提供屏幕工具与浏览器截图工具，浏览器只给可访问性结构，截图只保存为证据（模型管理设计说明第 5.6 节）。
- **截图作为证据**：存进工件存储，绑定动作回执、试用会话与交付快照；在质检试用台、试用记录与资料页显示。
- **试用记录与放行**：质检按 ProductSpec 的验收条件建立试用用例，逐条给出结论；每条验收条件都有通过的证据才能放行；没能核验的条目如实报告，事项不能放行。
- **工程的研发自测**：工程可以在自己的运行工作区的副本上使用浏览器，模型能看图时也可以使用屏幕工具；这些结果只是动作回执，不能作为质检的证据。

不在范围内：运维部门是否使用这两个工具（Stage 4 设计运维部门时决定）；在远程机器或真实显示器上操作桌面程序；实时画面（VNC）。

## 2. 概念与分层

### 2.1 概念层级

```mermaid
flowchart TB
  C["run 的本机容器：镜像带试用层"]
  S["试用会话：一个部门、一个启动的交付软件、一个浏览器或一块虚拟屏幕"]
  T["试用副本：按一份公开树清单建立，质检用交付快照，工程用当时的运行工作区"]
  K["试用用例（质检）：引用验收条件、计划的操作与预期结果"]
  A["步骤：浏览器或屏幕工具的一次动作 > 动作尝试 > 回执"]
  E["证据：截图、可访问性结构文本"]
  C --> S --> T
  S --> K --> A --> E
```

- **试用会话**属于一个部门，同一时刻每个部门最多一个；开始新的会话时，本部门原来的会话先结束。会话有种类：网页（浏览器）或桌面（虚拟屏幕），由启动的登记命令的种类决定。
- **试用副本**是会话专用的一次性目录，会话结束时删除。它的树摘要写进每一步的回执，质检的试用副本的树摘要等于交付快照的摘要。
- **试用用例**只属于质检。用例打开到结束之间，本部门在同一会话中的浏览器与屏幕动作都是这个用例的步骤。
- **试用记录**是一个 run 中质检全部试用用例及其步骤、证据与结论的总称，由事件派生，不另外保存。

### 2.2 分层与职责

| 层 | 模块 | 3.2D 增加的职责 | 边界 |
| --- | --- | --- | --- |
| 定义 | `harness/definitions/` | 试用工具、浏览器工具与屏幕工具的定义，每个工具的动作类别、恢复契约与是否需要图像输入；各部门可用的工具；限额（屏幕尺寸、截图前的等待、就绪时限）；质检的内置 Prompt 中生成测试的规则 | 随系统发布，运行中不可修改（ADR-0014） |
| 控制核心 · 步骤驱动 | `engine.py` | 按调用目标的输入方式选出这次请求提供的工具（#146 的机制）；把回执中的截图交给 P | 不读取截图内容 |
| 控制核心 · P | `assembly.py` | 调用目标包含图像时，把最近 3 张截图放进请求，更早的换成带证据编号的占位文字 | 只读取事件与工件 |
| 控制核心 · U | `adjudication.py`、`validation.py` | 工具许可：模型不含图像时拒绝桌面种类的试用会话；试用用例的开始与结束；QAReview 的逐条结论与放行规则 | 不调用模型 |
| 控制核心 · 流程编排 | `orchestrator.py` | 质检无法核验时发出决定请求；回答「重新核验」后重新激活质检 | 经决定请求机制（总体架构第 7.4 节） |
| 执行层 · 执行代码 | `harness/execution/` | 试用会话管理（建立试用副本、启动与就绪、结束进程树）、Playwright MCP 会话、虚拟屏幕与屏幕动作、截图写进内容块存储 | 不导入 Yudao 的其他模块 |
| 执行层 · 执行代理 | `harness/agent/` | 新的动作类别 `trial`、`browser`、`screen` 经已有的 `/actions` 路径执行；会话记录与动作记录一起保存在本机 | 合同与 3.2C 相同 |
| 执行层 · 执行环境池 | `harness/environments/` | 构建带试用层的镜像；按回执中的内容摘要取回截图，核对摘要后存进工件存储 | 不写事件 |
| 应用层 | `harness/app/` | 查询：试用记录、截图原文、资料中的逐条结论、工具清单中的内置工具；命令：登记启动命令 | 查询不写入 |
| 客户端 | 桌面程序 | 质检试用台、工程显示器、试用记录页签、资料页中的截图 | 只经接口层 |

### 2.3 模块交互

```mermaid
flowchart LR
  subgraph Host["控制主机"]
    App["应用层：run.trials、evidence.screenshot、work_item.materials、tools.registry、command_registration.save"]
    subgraph Core["控制核心"]
      Step["步骤驱动：按输入方式选工具"]
      P["上下文装配 P：最近 3 张截图"]
      U["裁决规则 U：工具许可、试用用例、放行"]
      Orch["流程编排：无法核验的决定请求"]
      Write["写入口与事件日志"]
    end
    Pool["执行环境池：镜像、取回截图"]
    Art[("工件存储：交付快照、截图、可访问性结构")]
  end
  subgraph Box["run 的本机容器（带试用层）"]
    Agent["执行代理"]
    Sess["试用会话管理"]
    Copy[("试用副本")]
    AppUT["交付的软件（登记的启动命令）"]
    MCP["Playwright MCP（stdio）+ Chromium（headless）"]
    Screen["Xvfb + mutter + tint2，xdotool、scrot"]
    Blobs[("内容块存储：截图")]
  end
  App --> Orch
  App -->|"读取"| Write
  App -->|"截图原文"| Art
  Step --> U
  Step --> P
  Step -->|"动作"| Pool
  Pool -->|"HTTP 加 JSON，127.0.0.1"| Agent
  Pool -->|"内容块"| Art
  Agent --> Sess
  Sess --> Copy
  Sess --> AppUT
  Sess -->|"MCP 客户端会话"| MCP
  Sess --> Screen
  MCP -->|"http://127.0.0.1:端口"| AppUT
  Screen --> AppUT
  Sess --> Blobs
  Step -->|"回执、截图引用"| Write
  U --> Write
  Orch --> Write
```

## 3. 试用会话与试用镜像

### 3.1 试用的位置

试用总是在 run 的本机容器中进行（总体架构第 7.3 节 3.2D 行）。run 的执行位置已经用到本机容器时使用同一个容器；没有用到时，执行环境池在第一次开始试用会话时按 3.2C 第 5.2.6 节建立这个容器，基础镜像取 run 冻结的执行位置中的容器基础镜像（没有设置时为 Yudao 默认基础镜像）。质检的检查位置是本机进程或一台登记的机器时，检查照常在那里运行，试用在容器中运行，两者按同一份交付快照的清单建立。

控制主机的容器引擎不可用时，试用工具的动作不发出，run 按 3.2C 第 6.5 节进入待恢复，原因为 `container_engine_unavailable`，问题解决以后自动继续。

### 3.2 试用镜像

3.2C 第 5.2.3 节的执行环境镜像在执行代理层之后再加一层试用层，本机容器全部使用带试用层的镜像。镜像标签由基础镜像摘要、执行代码摘要与试用层 Dockerfile 的摘要共同确定，三者都没有变化时复用。

试用层的内容：

| 部分 | 内容 | 版本 |
| --- | --- | --- |
| Node.js | 官方二进制包放在 `/opt/yudao/node`，只给 Playwright MCP 使用，不依赖基础镜像自己的 Node | Node.js 24 LTS 的一个固定小版本，写在 Dockerfile 中 |
| Playwright MCP | `@playwright/mcp` 安装在 `/opt/yudao/trial`，按代码仓库中的 `package-lock.json` 用 `npm ci` 安装 | 0.0.83 |
| 浏览器 | Chromium，由 Playwright MCP 依赖的 Playwright 自带的安装命令安装（`install --with-deps chromium`），放在 `/opt/yudao/ms-playwright`；系统依赖由同一命令用 apt 安装 | 由 Playwright `1.64.0-alpha-1790635538000` 确定，与 Playwright MCP 一起固定 |
| 虚拟屏幕 | `xvfb`、`mutter`、`tint2`、`xdotool`、`scrot`（与 Anthropic 参考实现 `computer-use-demo/Dockerfile` 第 10–17 行相同，去掉 `x11vnc` 与 noVNC） | Debian 软件源中的版本 |
| 字体与图形库 | `fonts-noto-cjk`（中文界面）、Tk 8.6、GTK 3，以及 Qt 6 与 Electron 程序需要的 xcb、EGL 与 OpenGL 运行库 | Debian 软件源中的版本 |

试用层使用 apt 安装，项目登记的基础镜像因此要求是 Debian 或 Ubuntu 系列（3.2C 的示例 `rust:1-bookworm` 满足）；Yudao 默认基础镜像 `python:3.12-slim-bookworm` 满足。Chromium 与 Playwright 都有 arm64 版本，控制主机是 arm64 时同样可以构建。

### 3.3 登记的启动命令

交付的软件用项目登记的命令启动（D34）。`command_registration.save` 的登记命令增加种类：

| 字段 | 取值 |
| --- | --- |
| 种类 | 命令（3.2A 已有，经 `run_command` 使用）；网页启动；桌面启动 |
| 固定参数、允许的额外参数、输出上限 | 与已有登记命令相同 |
| 就绪条件 | 网页启动：一个地址，例如 `http://127.0.0.1:3000/`，对它的请求得到任何 HTTP 响应即就绪，会话随后在浏览器中打开这个地址；桌面启动：虚拟屏幕上出现第一个可见的顶层窗口（`xdotool search --sync --onlyvisible`） |
| 就绪时限 | 默认 300 秒，用户可以修改 |

启动命令在试用副本中运行，工作目录是副本的根目录，环境与已有登记命令相同（最小环境、依赖缓存的环境变量，3.2C 第 5.2.5 节），桌面启动另外设置 `DISPLAY=:1`。依赖目录与构建产物不在公开树中，启动命令负责准备它们（例如 `sh -c "npm ci && npm run build && npm start"`），下载的内容来自项目的缓存卷，就绪时限因此包含安装与构建的时间。启动的进程一直运行到会话结束，没有单独的运行时限。

启动命令随其他登记命令在事项创建时冻结。工程在自己的工具说明中看到冻结的启动命令，交付的软件要能用它启动；新项目没有既定的启动方式时，用户按项目的技术约定登记（评测场景 1 的接口约定写明了启动方式与端口）。`run_command` 不接受启动种类的登记名。

### 3.4 试用工具

| 工具 | 部门 | 输入 | 作用 | 回执 |
| --- | --- | --- | --- | --- |
| `trial_start` | 质检、工程 | 启动命令的登记名、允许的额外参数 | 结束本部门原来的会话；建立试用副本；启动交付的软件并等待就绪；网页种类启动 Playwright MCP 并打开就绪地址，桌面种类启动虚拟屏幕 | 会话身份、种类、试用副本的树摘要、启动输出的开头部分；网页种类带页面的可访问性结构与截图，桌面种类带屏幕截图 |
| `trial_output` | 质检、工程 | 可选的字节数 | 取回交付软件到目前为止的标准输出与标准错误的末尾部分 | 输出、截断标记 |
| `trial_stop` | 质检、工程 | 无 | 结束会话：关闭 MCP 服务与浏览器、虚拟屏幕，结束交付软件的进程树，删除试用副本 | 结束方式、输出的末尾部分 |

试用副本的来源：

- **质检**：本次检查的交付快照的清单。流程编排在质检激活时已经封存了交付（3.2C 第 4.3 节），执行环境池按这份清单在容器中建立试用副本，只上传容器中缺少的内容块。
- **工程**：`trial_start` 时对运行工作区执行一次封存（3.2C 第 4.3 节「在其他位置检查」的同一个操作），按得到的清单建立试用副本。之后工程修改的文件要在新的会话中才能看到。

会话记录（身份、部门、种类、试用副本、各进程的进程号与启动时间）与动作记录一起保存在执行代理的 SQLite 中。执行代理启动时，把进行中的会话改为中断，并按 3.2C 第 5.3.1 节结束仍然存在的遗留进程树。run 进入终态时，执行环境池删除容器之前先结束全部会话。

## 4. 浏览器工具（Playwright MCP）

### 4.1 运行方式

Playwright MCP 是 Yudao 内置的 MCP 服务，由试用会话在容器中以 stdio 方式启动，每个网页种类的会话一个进程。MCP 客户端使用 3.2B（#69）的实现，客户端会话放在执行代码中，由执行代理进程持有，控制主机经执行代理的动作合同调用它，与其他动作一样有心跳、动作记录与按尝试身份去重（3.2C 第 4.4、6 节）。内置服务的工具许可按角色的定义，不经过 #69 的项目登记与一次性批准（总体架构第 7.3 节：按普通浏览器 MCP 的默认做法运行，不另加限制）。

启动参数：

| 参数 | 取值 | 原因 |
| --- | --- | --- |
| `--browser` | `chromium` | 默认的 `chrome` 渠道在 Linux arm64 上没有；与镜像中安装的浏览器一致 |
| `--headless` | 开启 | 网页试用不需要虚拟屏幕；截图由 Playwright 从页面取得 |
| `--no-sandbox` | 开启 | 与官方 Docker 用法相同（README 的 Docker 一节）；容器以 UID 1000 运行、去掉全部 capabilities，Chromium 自己的沙箱无法建立 |
| `--isolated` | 开启 | 浏览器配置保存在内存中，每个会话从空白状态开始，同一份交付的两次试用结果可以比较 |
| `--viewport-size` | `1280x800` | 与虚拟屏幕相同；Anthropic 文档对网页任务建议的尺寸之一 |
| `--caps` | `testing` | 启用 `browser_verify_*` 断言工具 |
| `--image-responses` | `allow` | 截图以 MCP 图像内容返回，由 Yudao 决定是否放进请求（第 6 节） |
| `--snapshot-mode` | `full` | 每个动作的结果带页面的可访问性结构 |
| `--output-dir` | 会话目录中的 `mcp-output` | 工具以文件名保存的内容留在会话目录，会话结束时删除 |
| 其余参数 | 默认值 | 动作时限 5 秒、导航时限 60 秒；不设置允许或禁止的来源 |

工具定义由代码仓库中的提取脚本从这个固定版本的 `tools/list` 生成，写进定义；升级 Playwright MCP 时同时更新版本、`package-lock.json` 与生成的定义。Yudao 直接使用 Playwright MCP 给出的工具定义与只读标注，不在调用时另外核实。

### 4.2 提供的工具

| 工具 | Playwright 只读标注 | 需要图像输入 |
| --- | --- | --- |
| `browser_navigate`、`browser_navigate_back` | 否 | 否 |
| `browser_click`、`browser_hover`、`browser_drag`、`browser_type`、`browser_fill_form`、`browser_select_option`、`browser_press_key`、`browser_file_upload`、`browser_handle_dialog` | 否 | 否 |
| `browser_wait_for`、`browser_tabs`、`browser_resize`、`browser_emulate_media`、`browser_close` | 否 | 否 |
| `browser_snapshot`、`browser_find`、`browser_console_messages`、`browser_network_requests`、`browser_network_request` | 是 | 否 |
| `browser_verify_element_visible`、`browser_verify_text_visible`、`browser_verify_list_visible`、`browser_verify_value` | 否 | 否 |
| `browser_generate_locator` | 是 | 否 |
| `browser_take_screenshot` | 是 | 是 |

不提供的工具：`browser_evaluate` 与 `browser_run_code_unsafe`，原因是试用记录要反映用户在界面上能做的操作，脚本可以绕过界面直接修改页面状态，这样得到的结论不能说明用户能完成这项操作（第 16 节第 5 项）。`vision`、`pdf`、`storage`、`devtools` 能力不启用：坐标操作由屏幕工具承担，其余三项与核验交付无关。

`browser_file_upload` 的路径是试用副本中的相对路径，执行代码把它转成容器中的路径；副本之外的路径拒绝。

### 4.3 每一步交给模型的内容

- 每个浏览器工具的结果是 Playwright MCP 返回的文本，包括动作的说明与页面的可访问性结构（带元素引用）。
- 只读标注为否的工具执行以后，执行代码在同一个动作中接着调用一次 `browser_take_screenshot`（视口，PNG），截图写进内容块存储，回执带它的摘要；`trial_start` 打开就绪地址以后同样截一张。这样每一个改变页面的步骤都有截图作为证据，与模型能否看图无关。
- 调用目标包含图像时，这张截图随工具结果放进请求；不包含时只保存为证据（第 6 节）。
- 模型自己调用 `browser_take_screenshot` 时（只提供给能看图的模型），返回的图像同样保存为证据。

这与 OMP 浏览器工具的提示一致：默认使用可访问性结构操作，只在需要看外观时截图（`packages/coding-agent/src/prompts/tools/browser.md` 第 30 行）。

## 5. computer use

### 5.1 虚拟屏幕

桌面种类的会话启动时，执行代码按 Anthropic 参考实现的顺序启动（`image/xvfb_startup.sh` 第 4–5、37 行，`image/start_all.sh`）：

1. `Xvfb :1 -ac -screen 0 1280x800x24 -retro -dpi 96 -nolisten tcp -nolisten unix`；
2. `mutter --replace --sm-disable`（窗口管理器：焦点、对话框与窗口装饰）；
3. `tint2`（任务栏：找回被最小化或被遮住的窗口）；
4. 交付软件的桌面启动命令，`DISPLAY=:1`，等待第一个可见窗口。

参考实现中的 `x11vnc` 与 noVNC 不使用：界面显示的是作为证据的截图，不需要实时画面，也就不需要额外的端口。

### 5.2 坐标空间与截图

- 屏幕 1280×800，24 位色，DPI 96。1280×800 是参考实现缩放表中的 WXGA，截图按原尺寸交给模型，不缩放；截图像素就是屏幕像素，模型给出的坐标直接交给 `xdotool`，不需要换算。
- 这个尺寸在各家的限制以内：长边 1280 小于旧版 Claude 模型的 1568 像素上限；按 Anthropic 的算法约 1334 个视觉 token（`⌈1280/28⌉ × ⌈800/28⌉`），小于 4784；OpenAI 的集成配方使用同一尺寸。
- 坐标原点在左上角，x 取值 0 至 1279，y 取值 0 至 799；超出范围时工具返回错误，不执行。
- 截图用 `scrot -p` 取得 PNG（参考实现 `computer.py` 第 258–264 行的第二种方式），写进内容块存储。

### 5.3 动作集合

每个动作一个工具，与浏览器工具的形式相同。工具以 Yudao 自己的函数工具提供给任何支持工具调用、能看图的模型，不使用各家的原生 computer 工具：Anthropic 的 `computer_toolset_20260801` 只由支持它的 Claude 模型发出，OpenAI 与 Gemini 的动作名称与坐标空间各不相同（computer use 实现调研第 6 节），Yudao 的模型由用户提供，协议不限于一家。

| 工具 | 输入 | 对应的 Anthropic 成员 | 返回 |
| --- | --- | --- | --- |
| `screen_screenshot` | 无 | `screenshot` | 截图 |
| `screen_click` | `x`、`y`；`button`（left、right、middle，默认 left）；`count`（1 至 3，默认 1）；`modifiers`（可选，例如 `ctrl+shift`） | `left_click`、`right_click`、`middle_click`、`double_click`、`triple_click` | 截图 |
| `screen_drag` | `from_x`、`from_y`、`to_x`、`to_y`；`modifiers`（可选） | `left_click_drag` | 截图 |
| `screen_move` | `x`、`y` | `mouse_move` | 截图 |
| `screen_scroll` | `direction`（up、down、left、right）、`amount`（滚轮格数）；`x`、`y`（可选，先移动到这里） | `scroll` | 截图 |
| `screen_type` | `text` | `type` | 截图 |
| `screen_key` | `keys`（xdotool 的键名，`+` 连接组合键）；`repeat`（1 至 100，默认 1） | `key` | 截图 |
| `screen_wait` | `seconds`（不超过 100） | `wait` | 截图 |

取舍：

- 五种点击合成一个 `screen_click`，按键与次数作为参数；OpenAI 与 Gemini 的点击同样带按键参数。
- 不提供 `zoom`：它用来找回缩小截图时丢失的细节，Yudao 的截图按原尺寸交给模型。
- 不提供 `left_mouse_down`、`left_mouse_up`、`hold_key`：拖动由 `screen_drag` 完成；按住鼠标或按键的精细操作用于游戏与绘图，不属于核验交付的常见操作。
- 不提供 `cursor_position`：光标只由模型自己的动作移动，模型知道它在哪里。
- 每个动作都返回截图：参考实现同样在每个会改变画面的动作之后截图（`computer.py` 第 267–275 行）；试用记录的每一步因此都有截图。

### 5.4 执行

- 输入经 `xdotool` 发出，前缀 `DISPLAY=:1`。`screen_type` 按 50 个字符一组、每组间隔 12 毫秒输入（参考实现 `computer.py` 第 18–19 行）。
- 会改变画面的动作执行以后等待 2 秒再截图，与参考实现的默认值相同（`computer.py` 第 99 行）；`screen_screenshot` 立即截图；`screen_wait` 等待指定时间后截图。这两个时间写在定义的限额中。
- 每个屏幕工具的执行时限 30 秒，`screen_wait` 为等待时间加 30 秒；到时限时结束 `xdotool` 进程，回执记为超时。

## 6. 按模型输入方式提供工具

### 6.1 工具定义的声明

定义中的每个工具增加 `requires_image_input`（#146 的「工具定义可以声明需要图像输入」）。声明为需要的工具：`screen_*` 全部 8 个、`browser_take_screenshot`。步骤驱动按调用目标的输入方式确定这次请求的工具：不包含图像时，这些工具不出现在请求的工具定义中（模型管理设计说明第 6 节）。

调用目标不包含图像时，`trial_start` 使用桌面种类的启动命令被工具许可拒绝，原因写明「当前模型不支持图像输入，不能操作虚拟屏幕」；质检据此把依赖桌面程序的验收条件报告为无法核验（第 8.4 节）。

### 6.2 请求中的图像

- 调用目标包含图像：工具结果中的截图作为图像放进请求。P 在请求中只保留最近 3 张截图，更早的换成一行占位文字「截图 <证据编号> 已保存为证据」；换出按 3 张一组进行，减少请求前段的变化，保持缓存有效。做法与数值参照 Anthropic 参考实现（`computer_use_demo/loop.py` 第 244 行起的 `_maybe_filter_to_n_most_recent_images`，`streamlit.py` 第 209 行默认 3 张）。
- 调用目标不包含图像：截图不放进请求，工具结果中也不出现占位文字；截图只作为证据保存。这与 OpenCode 的做法相同，OpenCode 对不支持图像的模型把图像换成文字说明（`packages/opencode/src/provider/transform.ts` 第 409 行起）。
- 同一个角色任务中调用目标可能改变（模型管理设计说明第 5.4 节）。换成不含图像的模型以后，下一次请求中已有的截图全部换成占位文字，工具定义按新的输入方式选出。

### 6.3 各部门可用的工具

| 工具 | 质检（含图像） | 质检（只有文本） | 工程（含图像） | 工程（只有文本） | 产品 |
| --- | --- | --- | --- | --- | --- |
| `trial_start`、`trial_output`、`trial_stop` | 有 | 有（只能启动网页种类） | 有 | 有（只能启动网页种类） | 无 |
| 浏览器工具（除 `browser_take_screenshot`） | 有 | 有 | 有 | 有 | 无 |
| `browser_take_screenshot` | 有 | 无 | 有 | 无 | 无 |
| `screen_*` | 有 | 无 | 有 | 无 | 无 |
| `trial_case_begin`、`trial_case_end`（第 8.2 节） | 有 | 有 | 无 | 无 | 无 |

质检的建议能力是图像输入（模型管理设计说明第 5.6 节），不具备时的提醒由 #146 与界面工单 #94、#95 完成。

## 7. 截图作为证据

### 7.1 保存与绑定

1. 执行代码把截图写进执行代理的内容块存储（3.2C 第 4.3 节），回执带截图的 `sha256:` 摘要、媒体类型、宽高与字节数。
2. 执行环境池收到回执以后按摘要取回内容块（`GET /blobs/{digest}`），重新计算摘要核对，存进工件存储（`ArtifactStore.put`，种类 `screenshot`，媒体类型 `image/png`）。浏览器工具返回的可访问性结构文本作为工具结果按已有方式保存。
3. 步骤驱动把工件引用写进 `tool_called` 事件的回执。回执同时带动作身份与尝试身份、会话身份、试用副本的树摘要与执行位置说明。
4. 质检的试用副本从交付快照建立，树摘要等于交付的 `code_snapshot_hash`；截图经「回执 → 会话 → 试用副本的树摘要」绑定到交付快照。U 在放行时核对这一点（第 8.3 节）。

截图属于 run 的工件，保留规则与其他工件相同（[总体路线图](../program-roadmap.md)第 5.1 节）。每张 1280×800 的 PNG 通常在几百 KB 以内。

### 7.2 查询

| 查询 | 内容 |
| --- | --- |
| `run.trials`（新增） | 按部门列出试用会话：种类、启动命令、试用副本的树摘要（质检的会话标明是否等于交付快照）、开始与结束、结束方式。质检的试用用例：引用的验收条件与原文、计划的操作与预期结果、步骤（工具、输入、结果状态、截图的工件引用、可访问性结构的摘录、收到这个结果的请求是否包含图像）、结论与观察到的结果、作为证据的步骤 |
| `evidence.screenshot`（新增） | 按工件引用返回截图，按摘要核对以后返回内容；所属事件的位置放在响应头，与 `delivery.file` 相同 |
| `work_item.materials` | 质检一项增加：每份 QAReview 的逐条结论（验收条件、结果、证据：检查名称与试用用例）、试用用例的截图引用、无法核验的条目与原因 |
| `run.actions` | 浏览器与屏幕动作的回执带截图引用与会话身份 |
| `department.workspace` | 本部门进行中的试用会话与最近一张截图的引用（部门房间的试用台与显示器使用） |
| `tools.registry` | 增加内置工具一节：Playwright MCP 的版本、提供的工具与恢复契约；屏幕工具、屏幕尺寸；每个工具是否需要图像输入 |

### 7.3 界面

按原型 v8：

- **部门房间**（第 8.3 节）：质检的试用台显示器与工程的显示器嵌入最近一张截图的缩略图，来自最新的浏览器或屏幕动作的 `tool_called` 事件。浏览器的每一步都有截图，模型不能看图时显示器同样显示截图，角落标明「模型只读取文字」。
- **部门工作间的试用记录页签**（第 7.1 节）：按用例列出引用的验收条件、计划的操作、每一步的操作、截图与结论；每张截图标明模型是否看到它；点击截图查看原尺寸，旁边列出同一步的可访问性结构摘录。
- **资料页的质检一项**（第 7.3 节）：每份 QAReview 的逐条结论表，每条验收条件一行，列出结果、证据与截图缩略图；表头写明交付快照的摘要。
- **工具与扩展页**（第 9.4 节）：内置的浏览器工具与屏幕工具。
- 原型 v8 第 15 节「试用台截图的尺寸与缩放」确定为 1280×800（16:10），界面等比缩放。

## 8. 质检从 PRD 生成测试与试用记录

### 8.1 验收条件的引用

试用用例与 QAReview 引用验收条件的形式是 `AC<序号>`，序号是验收条件在 ProductSpec 中的位置（从 1 开始）；引用所在的记录都绑定 ProductSpec 的内容摘要（现有的 `product_spec_hash`），同一份摘要下序号确定唯一的条目。试用记录属于 run 流，跟随应用版本（ADR-0019）。语义系统的项目内稳定编号（语义系统设计说明第 5.5 节，#27）实施时，引用改用稳定编号（第 16 节第 1 项）。

### 8.2 试用用例

质检的内置 Prompt 写明生成测试的规则：

1. 读取 ProductSpec 的每条验收条件，决定核验方式：能用命令核对的（数据、计算、接口）用 `run_check`；需要在界面上操作才能观察的用试用用例；一条验收条件可以同时使用两种。
2. 每个试用用例从一条或几条验收条件导出：前置状态、操作步骤、预期结果。
3. 用 `trial_case_begin` 打开用例，按计划操作，观察结果；用 `trial_case_end` 给出结论。
4. 页面上有可以断言的内容时优先使用 `browser_verify_*`，断言的结果本身就是证据。

两个主机工具：

| 工具 | 输入 | 主机的核对 | 事件 |
| --- | --- | --- | --- |
| `trial_case_begin` | `criteria`（`AC<序号>` 列表，至少一条）、`title`、`steps`（计划的操作）、`expected`（预期结果） | 本部门有进行中的试用会话；没有另一个打开的用例；引用的验收条件存在于当前 ProductSpec | `trial_case_opened`（用例身份、会话身份、ProductSpec 摘要、以上输入） |
| `trial_case_end` | `result`（`passed`、`failed`、`unverified`）、`observed`（观察到的结果）、`evidence_steps`（作为证据的步骤的动作身份；`passed` 与 `failed` 至少一个）、`reason`（`unverified` 时必填） | 证据步骤属于这个用例；`passed` 时用例中没有结果未知的步骤 | `trial_case_concluded` |

用例打开到结束之间，本部门在同一会话中的浏览器与屏幕动作都记为它的步骤，由主机按动作身份关联。会话结束或中断时，打开的用例自动结束为中断（`trial_case_concluded`，结果 `interrupted`），中断的用例不能作为证据。

### 8.3 QAReview 的逐条结论与放行

`qa_review` 提案增加必填字段 `criteria`：当前 ProductSpec 的每条验收条件一项，`{criterion, result, checks, trial_cases, note}`，`result` 为 `passed`、`failed`、`unverified`。

U 的核对（在现有核对之上，`validation.py` 第 428 行起）：

- `criteria` 覆盖当前 ProductSpec 的全部验收条件，每条一项。
- `checks` 中的检查名称按现有规则取得本次激活、绑定当前快照与合同的质检回执；`trial_cases` 中的用例属于本次激活，所在会话的试用副本的树摘要等于当前交付的 `code_snapshot_hash`，用例的结论与该项的 `result` 一致。
- `passed` 至少有一个证据（检查回执退出状态为 0，或结论为通过的用例）。
- **放行**（`release`）：每条验收条件都是 `passed`；缺陷为空；现有的检查与指导规则照旧。这是语义系统设计说明第 13 节「每条有效验收条件都必须有通过的检查结果与证据引用」在 3.2D 的实施。
- **返工**（`rework_engineering`、`rework_product`）：至少一条缺陷（现有规则）；缺陷可以写明违反的验收条件。
- **无法核验**（`cannot_verify`，新增）：没有 `failed` 的条目，至少一条 `unverified`，每条写明原因。

QAReview 工件的 `evidence_refs` 写入逐条结论引用的检查回执与试用用例身份。

### 8.4 无法核验

质检没能核验的条目如实报告，事项不能放行（D34）。原因分三类，处理不同：

| 原因 | 质检的做法 |
| --- | --- |
| 交付的软件无法启动、找不到对应的界面、结果不符 | 条目是 `failed`，返工给工程，缺陷写明现象与截图 |
| 验收条件含义不清、无法操作或前后矛盾 | 向产品发协作请求，或返工给产品 |
| 质检自己的条件不够：模型不支持图像输入而条目依赖桌面程序或外观、容器中缺少运行交付软件需要的环境 | 条目是 `unverified`，提交 `cannot_verify` |

`cannot_verify` 被接纳以后，流程编排发出决定请求「质检无法核验」，阻塞范围是这个 run，说明中列出每条无法核验的验收条件与原因。选项：

- **重新核验**：用户修改设置（例如给质检换成能看图的模型）以后回答，质检以新的激活重新检查同一份交付；
- **停止事项**：事项结束，交付不被采纳。

交接状态：`QUALITY` 保持不变，等待回答期间 run 显示待恢复，原因写明质检无法核验。

### 8.5 工程的研发自测

- 工程可以在运行工作区的副本上开始试用会话（第 3.4 节），用浏览器检查自己做的界面；模型能看图时也可以使用屏幕工具。
- 工程的试用动作是普通的动作回执，截图同样保存为证据，显示在工程房间的显示器与 `run.actions` 中。工程没有试用用例工具；交付说明的 `check_names` 只接受 `run_check` 回执（现有规则），试用动作不能列入；QAReview 不接受工程的会话与动作作为证据。

## 9. 恢复契约

每类动作按恢复契约第 4 节的问题回答。试用动作的影响限于这个 run 的容器中的试用会话：试用副本从确定的清单建立，会话结束时删除，不改变运行工作区、交付快照与项目流。交付的软件自己对外产生的影响属于被测软件的行为，Yudao 不另外处理。

| 动作 | 谁有权做 | 结果未知时向哪里查 | 可以重做 | 取消能否确认停止 |
| --- | --- | --- | --- | --- |
| `trial_start` | 质检、工程（角色的工具许可） | 按尝试身份查询动作记录与会话记录 | 可以：会话记录不存在或已中断时以新的尝试重新开始，得到新的会话；会话已经就绪时使用它 | 能：结束已启动的进程树，回执为已取消 |
| `trial_stop` | 同上 | 会话记录 | 可以：按会话身份重复执行，结果相同 | 能 |
| `trial_output` | 同上 | 无需查询 | 可以 | 能 |
| 只读标注为是的浏览器工具、`screen_screenshot`、`screen_wait` | 同上 | 无需查询 | 可以：以新的尝试重新执行 | 能：MCP 的取消通知或结束 `xdotool` 进程 |
| 只读标注为否的浏览器工具、其余屏幕工具 | 同上 | 动作记录；会话仍然存在时取得当前页面的可访问性结构与截图，或当前屏幕截图 | 不可以：页面或程序的状态可能已经改变 | 能：MCP 的取消通知或结束 `xdotool` 进程；已经送达页面的输入不能撤回 |
| `trial_case_begin`、`trial_case_end` | 质检 | 事件日志（主机工具，写入口在同一事务中完成） | 已接纳则跳过 | 不适用 |

改变页面或程序的动作结果未知时（3.2C 第 6.3 节），核实按以下规则作出，不发出「核实结果未知的动作」决定请求：

- 会话仍然存在：核实记录写明「按当前实际状态继续」，依据是新取得的页面结构与截图（屏幕工具为截图）；模型看到的工具结果是这份当前状态加上「上一个动作的结果未知」的说明。
- 会话已经不存在（容器或执行代理重新启动）：会话记为中断，模型看到的工具结果写明会话已中断，需要重新开始会话。
- 两种情况下，所在的试用用例记下这个结果未知的步骤，这个用例不能以 `passed` 结束；质检在新的用例中重新执行它（可以在新的会话中）。

这样处理的依据：试用会话的状态属于一次性的试用副本，不涉及外部责任，按当前实际状态继续与重新执行用例都不会让未知的影响进入交付或项目；结论的可信度由「含结果未知步骤的用例不能作为通过的证据」保证。

## 10. 安全

按用户决定（D34），与普通浏览器 MCP 的默认做法相同，不另加限制：不设置允许或禁止访问的来源；浏览器可以访问外网（容器使用 3.2C 的默认 bridge 网络）；Chromium 按官方 Docker 用法关闭自身沙箱。Playwright MCP 的 README 写明它不是安全边界；试用在 3.2C 的容器中运行（UID 1000、`no-new-privileges`、去掉全部 capabilities、不挂载控制主机的目录），容器中的代码看不到控制主机的文件与模型凭据，这是 3.2C 已有的设置。

## 11. 时序

### 11.1 质检在浏览器中核验一条验收条件

```mermaid
sequenceDiagram
  participant S as 步骤驱动
  participant U as 裁决规则 U
  participant P as 上下文装配 P
  participant Pool as 执行环境池
  participant A as 执行代理（run 的本机容器）
  participant M as Playwright MCP
  participant W as 写入口
  participant Art as 工件存储
  S->>U: trial_start(web)
  U-->>S: 允许
  S->>Pool: 动作：交付快照的清单
  Pool->>A: 建立试用副本（只上传缺少的内容块）
  A->>A: 启动命令，等待就绪地址
  A->>M: 启动（stdio），browser_navigate(就绪地址)
  A->>M: browser_take_screenshot
  A-->>Pool: 回执：会话、树摘要、页面结构、截图摘要
  Pool->>A: GET /blobs/{digest}
  Pool->>Art: 核对摘要后存入
  S->>W: tool_called（截图引用）、trial_session_started
  S->>U: trial_case_begin(AC3, 步骤, 预期)
  U->>W: trial_case_opened
  loop 每一步
    S->>Pool: browser_click / browser_type ...
    Pool->>A: 动作
    A->>M: 工具调用，再截图
    A-->>Pool: 回执（页面结构、截图摘要）
    Pool->>Art: 截图
    S->>W: tool_called
    S->>P: 下一次请求
    P-->>S: 含图像时附最近 3 张截图，否则只有文字
  end
  S->>U: trial_case_end(passed, 证据步骤)
  U->>W: trial_case_concluded
  S->>U: submit_review(criteria 逐条, release)
  U->>U: 每条 passed 且有绑定交付快照的证据
  U->>W: 接纳或拒绝
```

### 11.2 在虚拟屏幕中操作桌面程序

```mermaid
sequenceDiagram
  participant S as 步骤驱动
  participant A as 执行代理
  participant X as Xvfb、mutter、tint2
  participant G as 交付的桌面程序
  S->>A: trial_start(desktop)
  A->>X: Xvfb :1 1280x800x24，mutter，tint2
  A->>G: 启动命令（DISPLAY=:1）
  A->>X: 等待第一个可见窗口
  A-->>S: 回执：会话、屏幕截图
  loop 每一步
    S->>A: screen_click(x, y) 等
    A->>X: xdotool
    A->>A: 等待 2 秒，scrot 截图
    A-->>S: 回执：截图摘要
  end
  S->>A: trial_stop
  A->>G: 结束进程树
  A->>X: 结束虚拟屏幕，删除试用副本
```

### 11.3 动作结果未知

```mermaid
sequenceDiagram
  participant S as 步骤驱动
  participant O as 流程编排
  participant Pool as 执行环境池
  participant A as 执行代理
  participant W as 写入口
  S->>Pool: browser_click（尝试 a1）
  Note over Pool,A: 40 秒没有心跳
  Pool-->>S: 结果未知
  S->>W: 动作结果未知
  S->>O: 交给动作核实
  O->>Pool: 按尝试身份查询动作记录与会话记录
  alt 会话仍然存在
    O->>Pool: browser_snapshot 与截图（新尝试）
    O->>W: 核实记录：按当前实际状态继续（依据：页面结构、截图）
    O->>S: 继续，模型看到当前状态与「结果未知」说明
  else 会话已中断
    O->>W: 核实记录：会话中断；trial_session_ended、用例中断
    O->>S: 继续，模型看到会话已中断
  end
```

## 12. 事件、命令与查询

| 种类 | 名称 | 内容 |
| --- | --- | --- |
| 命令 | `command_registration.save` | 增加种类（命令、网页启动、桌面启动）、就绪条件与就绪时限 |
| 事件 | `command_configured` | 同上字段 |
| 事件 | `trial_session_started`、`trial_session_ended` | 会话身份、部门、种类、启动命令（登记名与冻结版本）、试用副本的树摘要与清单来源（交付快照或运行工作区的封存）、结束方式（停止、被新会话替换、中断、run 结束） |
| 事件 | `trial_case_opened`、`trial_case_concluded` | 第 8.2 节 |
| 事件 | `tool_called` | 回执增加截图的工件引用、会话身份、试用副本的树摘要 |
| 事件 | QAReview 接纳事件 | 工件增加逐条结论；结论种类增加 `cannot_verify` |
| 决定请求 | 质检无法核验 | 选项：重新核验、停止事项；阻塞范围为 run |
| 查询 | `run.trials`、`evidence.screenshot`（新增）；`work_item.materials`、`run.actions`、`department.workspace`、`tools.registry`（增加内容） | 第 7.2 节 |

以上事件都属于 run 流；`command_configured` 属于项目流，只增加字段（ADR-0019）。

## 13. 故障与处理

| 情况 | 处理 |
| --- | --- |
| 启动命令在就绪时限内没有就绪，或进程提前退出 | `trial_start` 回执为失败，带启动输出；会话不建立。质检把相关条目记为 `failed`，缺陷写明启动输出 |
| 交付软件在会话中途退出 | 下一个浏览器动作得到连接错误，屏幕动作的截图中没有窗口；质检用 `trial_output` 查看输出，按 `failed` 处理 |
| Playwright MCP 进程退出 | 动作回执为失败，写明原因；会话记为中断，模型需要重新开始会话 |
| 容器或执行代理重新启动 | 会话中断，遗留进程由执行代理结束（第 3.4 节）；进行中的动作按第 9 节核实 |
| 容器引擎不可用 | run 进入待恢复，问题解决以后自动继续（第 3.1 节） |
| 模型不支持图像，交付是桌面程序 | 桌面种类的 `trial_start` 被工具许可拒绝；质检提交 `cannot_verify`，用户收到决定请求 |
| 截图取回时摘要不符 | 动作回执为失败，原因写明摘要不符；控制主机不采用没有核对的内容（3.2C 第 4.3 节） |
| 放行时有条目缺少证据或证据不绑定当前交付快照 | U 拒绝提案，字段级错误写明缺少的验收条件 |

## 14. 验收场景

全部在真实的控制主机、真实的 Docker、真实的 Playwright MCP 与 Chromium、真实的 Xvfb 上进行，不使用模拟。确定行为的测试由 FakeAdapter 给出模型回答；场景 1、2、3、7 另用真实的、能看图的模型运行一次（D32：评测模型由用户提供）。与 Stage 3 计划 3.2D 行及 #123 的验收标准一致。

1. **质检在浏览器中核验网页应用**：一个项目登记网页启动命令，事项要求一个待办清单网页（评测场景 1 的需求）。工程交付以后，质检从 ProductSpec 的每条验收条件建立试用用例，在浏览器中逐项操作；`run.trials` 列出每个用例的验收条件、步骤与截图，每张截图的会话树摘要等于交付快照的摘要；QAReview 逐条列出结论，全部通过时放行；资料页与试用记录页签显示这些截图。
2. **质检在虚拟屏幕中核验桌面程序**：一个项目登记桌面启动命令，事项要求一个 Tk 的待办清单程序。质检在虚拟屏幕中用屏幕工具逐项操作并核验，截图同样绑定交付快照，全部通过时放行。
3. **质检的模型不支持图像**：给质检设置只有文本输入的模型。保存时出现提醒；部门工作间一直显示提醒。网页项目中，请求的工具定义里没有 `screen_*` 与 `browser_take_screenshot`，工具结果只有可访问性结构，截图仍然保存为证据、界面标明模型没有看到；桌面项目中，桌面种类的 `trial_start` 被拒绝，质检提交 `cannot_verify`，出现「质检无法核验」决定请求；换成能看图的模型并回答「重新核验」以后，质检完成核验并放行。
4. **缺少证据不能放行**：质检的 `criteria` 中有一条验收条件没有证据，或引用了另一份快照上的用例，放行提案被拒绝，错误写明缺少的验收条件。
5. **结果未知**：在一个 `browser_click` 进行期间暂停执行代理进程超过 40 秒再恢复。出现「动作结果未知」事件与核实记录「按当前实际状态继续」，所在用例不能以通过结束；质检在新的用例中重新执行并通过。另一次在动作进行期间停止并重新启动容器，会话记为中断，打开的用例记为中断，质检开始新的会话。
6. **工程的研发自测**：工程在运行工作区的副本上开始网页会话并操作页面，回执与截图出现在 `run.actions` 与工程的显示器上；把这些动作列入交付说明或 QAReview 的证据时被拒绝。
7. **评测场景 1**：评测工作线（#118）的 Yudao 运行器完成以后，运行评测场景 1，并运行场景 2、3 的版本回归（Stage 3 计划第 7 节）。

## 15. 需要同步修改的文档

本设计确认以后，架构师修改：

- `CONTEXT.md`：新增试用会话、试用副本、试用用例、试用记录、登记的启动命令、无法核验。
- [执行环境服务设计说明](execution-environment.md)第 5.2.3 节：本机容器的镜像都带试用层；项目基础镜像要求 Debian 或 Ubuntu 系列。
- [应用层与接口层设计说明](app-and-interface.md)：`command_registration.save` 的字段；第 3.3 节的决定种类「质检无法核验」；第 4.3 节的 `run.trials`、`evidence.screenshot` 与四个查询的增加内容。
- [总体架构](architecture/overall-architecture.md)第 7.3 节 3.2D 行（执行环境写明 run 的本机容器）、第 7.4 节的决定表。
- [恢复契约与故障矩阵](recovery-contract-and-fault-matrix.md)第 4 节：增加试用、浏览器与屏幕动作一行。
- [语义系统设计说明](semantic-system.md)第 13 节：放行规则在 3.2D 实施，引用形式见本文第 8.1 节。
- [原型 v8 设计说明](../prototypes/v8/design.md)第 7.1、8.3、15 节：浏览器的截图总是存在，模型不能看图时标明；截图尺寸 1280×800。
- [Stage 3 计划](../stage-3-plan.md) 3.2D 行与 [D34](../requirements/browser-and-computer-use.md) 的状态：写上工单编号。

## 16. 待用户确认

1. **验收条件的引用与放行规则。** 语义系统的项目内稳定编号在 Stage 5（#27），3.2D 在 Stage 3。推荐：试用记录与 QAReview 用「ProductSpec 摘要 + 验收条件序号」引用（第 8.1 节），同时在 3.2D 实施语义系统第 13 节已经确认的放行规则「每条验收条件都有通过的证据」。理由：试用记录只针对一份交付与一份 ProductSpec，序号在绑定的摘要下已经唯一；这条放行规则就是 D34「没有核验的条目不能放行」的具体做法，不另外发明规则。
2. **新增质检结论「无法核验」与决定请求。** 现有结论只有放行与两种返工，质检因为自己条件不够（例如模型不能看图）而没能核验时，返工会把责任错放到工程或产品，循环不会结束。推荐按第 8.4 节新增 `cannot_verify` 与决定请求「质检无法核验」（重新核验、停止事项）。
3. **本机容器的镜像都带试用层。** 推荐每个本机容器都使用带试用层的镜像，项目基础镜像因此要求 Debian 或 Ubuntu 系列（第 3.2 节）。理由：一个 run 只有一个容器，质检与工程都可能试用，只有一种镜像最简单；镜像按摘要复用，只构建一次。代价是镜像增加 Chromium 与图形库，约 1 GB。
4. **启动命令由用户登记。** 推荐按 D34 使用项目登记的启动命令（第 3.3 节），工程按它交付。影响：从想法开始的新项目，用户需要在工程开始之前登记启动方式（例如 `npm start` 与端口）；没有登记时质检无法启动交付的软件，相关条目只能记为无法核验。
5. **不提供 `browser_evaluate` 与 `browser_run_code_unsafe`。** 推荐不提供这两个工具（第 4.2 节）。理由是核验的有效性：脚本可以绕过界面直接修改页面状态。这项取舍与安全无关，安全仍按默认做法。
6. **屏幕工具使用 Yudao 自己的函数工具。** 推荐第 5.3 节的 8 个工具提供给所有能看图的模型，不使用各家的原生 computer 工具。代价：原生工具经过厂商的专门训练，同一个模型使用原生工具可能更准确；好处是一套工具、一种坐标空间、一套恢复契约适用于用户提供的任何模型。

## 17. 建议的工单拆分

全部属于父工单 #123。后端工单被 #142（3.2C 的 F）与 #146 阻塞，MCP 相关的被 #69 阻塞；界面工单被 #80 与 #125 阻塞。#69 的 MCP 客户端会话需要放在执行代码中、由执行代理进程持有（第 4.1 节），这一点写进 #69 的评论。

| 工单 | 交付 | 验证方法 | 被阻塞于 |
| --- | --- | --- | --- |
| A. 试用工具的定义与请求中的图像 | 定义中的试用、浏览器（由提取脚本从 Playwright MCP 0.0.83 生成）与屏幕工具，`requires_image_input`，各部门可用的工具，恢复契约与限额；步骤驱动按输入方式选出工具；P 保留最近 3 张截图、3 张一组换出；U 拒绝不含图像的模型启动桌面会话；质检内置 Prompt 中生成测试的规则 | 调用目标含图像与不含图像时，请求的工具定义与图像内容符合第 6 节；中途更换模型以后截图换成占位文字 | #146 |
| B. 试用镜像、登记的启动命令与试用会话 | 试用层 Dockerfile 与镜像派生；`command_registration.save` 的启动种类与就绪条件；`trial_start`、`trial_output`、`trial_stop`；试用副本（质检用交付快照，工程用运行工作区的封存）；会话记录、执行代理启动时处理中断的会话与遗留进程；`trial_session_*` 事件；run 结束时结束会话 | 在真实 Docker 中启动一个网页与一个 Tk 程序并等到就绪；就绪超时与进程提前退出有真实的回执；重新启动执行代理以后会话记为中断、没有遗留进程；质检的试用副本树摘要等于交付摘要 | #142、#143、A |
| C. 浏览器工具（Playwright MCP） | 在执行代码中经 #69 的 MCP 客户端以 stdio 启动 Playwright MCP，第 4.1 节的参数；第 4.2 节的工具；改变页面的动作之后自动截图；截图经内容块取回、核对并存进工件存储；回执带截图引用；第 9 节的核实规则 | 真实页面上完成导航、点击、输入、断言；每个改变页面的步骤都有截图工件，摘要一致；暂停执行代理超过 40 秒得到结果未知与「按当前实际状态继续」的核实记录 | B、#69 |
| D. computer use（虚拟屏幕） | Xvfb、mutter、tint2 的启动与结束；8 个屏幕工具，坐标核对，`xdotool` 输入，等待 2 秒后 `scrot` 截图；截图存为证据 | 在虚拟屏幕中对真实的 Tk 程序点击、输入、按键、拖动、滚动，截图反映操作结果；越界坐标被拒绝；超时结束 `xdotool` 进程 | B |
| E. 试用用例、逐条结论与放行 | `trial_case_begin`、`trial_case_end` 与事件；步骤按动作身份关联到用例；会话结束时用例中断；QAReview 的 `criteria` 与 `cannot_verify`；U 的放行规则（第 8.3 节）；决定请求「质检无法核验」与重新核验；拒绝工程的试用动作作为证据 | 第 14 节场景 4；缺少证据、证据绑定另一份快照、用例含结果未知步骤时放行被拒绝；`cannot_verify` 出现决定请求，回答「重新核验」后质检重新激活 | C |
| F. 查询 | `run.trials`、`evidence.screenshot`；`work_item.materials`、`run.actions`、`department.workspace`、`tools.registry` 的增加内容 | 应用层的查询测试：调用前后事件日志末尾不变；截图按摘要核对后返回 | E、#73 |
| G. 界面：部门房间与试用记录 | 质检试用台与工程显示器的截图缩略图；部门工作间的试用记录页签（用例、步骤、截图、模型是否看到） | Playwright 启动 Electron 应用，对真实后端的一次试用检查画面与页签内容 | F、#80、#125 |
| H. 界面：资料页与工具页 | 资料页质检一项的逐条结论表与截图；工具与扩展页的内置工具一节 | 同上 | F、#80、#125；工具与扩展页由 3.2B 的界面工单建立 |
| I. 3.2D 的真实验收 | 第 14 节全部场景，场景 1、2、3 使用真实的能看图的模型；报告写在 `docs/stage-3/` | 报告附事件、回执与截图；失败与缺失如实列出 | D、E、G、H；场景 7 需要 #118 的 Yudao 运行器 |

阻塞关系：A → B → C、D；C → E → F → G、H；D、E、G、H → I。
