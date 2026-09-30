# computer use 调研：屏幕来源、不打扰用户、家庭版、开发板与 UI Automation

日期：2026-09-30。用途：专题 2「computer use」的讨论材料，只整理事实与来源，不给建议。

背景：用户 2026-09-30 决定 Yudao 不使用容器，也不使用 WSL，代码直接在执行位置上运行。执行位置有控制主机（Windows 11 家庭中文版，用户同时在使用它的桌面）与登记的机器（Orange Pi AIpro 开发板，Ubuntu 22.04.5，aarch64）。原设计在容器的虚拟屏幕中运行被测的桌面程序，见 `docs/design/browser-and-computer-use.md` 第 5 节。`docs/research/computer-use-implementations.md` 与 `docs/research/browser-and-computer-use.md` 已经记录的内容（Anthropic 参考实现的 Dockerfile、启动脚本与 `computer.py`，三家模型的动作合同与坐标，OpenAI 的容器配方，Codex 的插件形态，OMP `computer` 工具的 JavaScript 接口）本文不再重复。

调研方式：读网页、文档与源码。控制主机上没有运行任何被调研的软件，只从注册表读取了系统版本。开发板上只做只读检查：`dpkg -l`、`apt-cache policy`、`apt-cache show`、`apt-get -s`（模拟安装，不写入系统）、`ps`、`free`、`loginctl`、`/proc` 与 `/sys` 中的信息。

源码与文档的版本（均在 2026-09-30 读取）：

| 来源 | 提交或版本 | 提交日期 |
| --- | --- | --- |
| anthropics/claude-quickstarts | `792cdebb32` | 2026-09-29 |
| openai/openai-cua-sample-app | `f2a3dc523a` | 2026-09-04 |
| microsoft/UFO；论文 arXiv 2504.14603v2 | `a795552d97` | 2026-09-29 |
| microsoft/WindowsAgentArena；论文 arXiv 2409.08264v2 | `6d39ed88c5` | 2024-11-20 |
| trycua/cua | `0f29c142d7` | 最近推送 2026-09-29 |
| bytebot-ai/bytebot（已归档） | `3d37894ce0` | 2025-09-11 |
| simular-ai/Agent-S | `3aa272d23d` | 2026-09-05 |
| openinterpreter/openinterpreter | main `12ad79b828`；分支 `main-backup` `e00f08e2ed` | 2026-09-30；2026-05-17 |
| endolith/open-interpreter | `3b9a12e2c1` | 2026-09-27 |
| CursorTouch/Windows-MCP | `6885dc1fc4` | 2026-09-30 |
| mediar-ai/terminator | `73a381c0c1` | 2026-06-02 |
| pywinauto/pywinauto（行号取自 0.6.8 标签） | `18d2a95ceb` | 2026-05-23 |
| FlaUI/FlaUI | `fd7cc64ab0` | 2026-08-13 |
| microsoft/WinAppDriver | `09e3f7111e` | 2025-04-14 |
| appium/appium-windows-driver | `24d07f1f8b` | 2026-09-14 |
| AutomateThePlanet/appium-novawindows-driver | `3679250e6f` | 2026-08-27 |
| microsoft/mxc | `f82237f4e8` | 2026-09-30 |
| nashaofu/xcap | 标签 `v0.9.6`（`d4ff80928a`） | 2026-05-24 |
| dockur/windows | `1e99833c8f` | — |
| OMP（本地 `C:\project\codes\oh-my-pi`） | `fdfeef1f78` | 2026-09-04 |
| OpenCode（本地 `C:\project\codes\opencode`） | `0027387` | — |
| Codex（本地 `C:\project\codes\codex`） | `69f7140` | 2026-09-28 |
| 微软文档源文件 | MicrosoftDocs/win32 `e103fa4e88`，sdk-api `9e0d205d74`，dotnet/docs `91cc9093b4` | — |

## 1. 屏幕从哪里来

### 1.1 各项目一览

| 项目 | 屏幕来源 | 平台 | 是否打扰用户的桌面 | 无障碍结构 | 维护状态 |
| --- | --- | --- | --- | --- | --- |
| Anthropic computer-use-demo | Docker 容器中的 Xvfb | 镜像有 linux/amd64 与 linux/arm64 | 不打扰 | 不使用 | 目录最近改动 2026-08-21 |
| Anthropic computer-use-best-practices | 宿主 macOS 的真实屏幕，不用容器 | 只有 macOS | 打扰，移动真实的鼠标与键盘 | 不使用 | 2026-05-13 加入，最近改动 2026-08-21 |
| OpenAI CUA 示例程序 | JavaScript：Playwright 的 Chromium（默认 headless）；Python：运行者的真实桌面 | Python 部分：macOS、Linux X11、Windows | Python 部分打扰 | 不使用 | 最近提交 2026-09-04；2026-03 删除了 Docker 环境 |
| Microsoft UFO² | 当前用户桌面；画中画桌面（RDP loopback）的代码没有发布 | Windows 10 及以上 | 打扰 | 使用 UIA，可以合并 OmniParser 视觉检测 | 最近提交 2026-09-29，v3.0.10 |
| Windows Agent Arena | Docker 中 QEMU/KVM 运行的 Windows 11 虚拟机 | 宿主 Linux，或 Windows 的 WSL 2 | 不打扰 | 可选，UIA 或 win32 | main 最近提交 2024-11-20 |
| trycua/cua | Lume 虚拟机、Docker 桌面、Windows 沙盒、云端虚拟机、宿主桌面 | macOS、Linux、Windows | 宿主模式打扰；Cua Driver 尽量在后台 | computer-server：macOS AX、Windows Win32 子窗口、Linux 空树；Cua Driver：UIA、AX、AT-SPI | 最近推送 2026-09-29 |
| Bytebot | Docker 中的 Xvfb 与 XFCE | 能运行 Docker 的系统 | 不打扰 | 不使用 | 已归档，最近提交 2025-09-11 |
| Agent S | 运行它的电脑的桌面；评测时用虚拟机 | Linux、macOS、Windows | 打扰 | S1 使用；S2 以后只用截图 | 最近提交 2026-09-05，v0.3.2 |
| Open Interpreter OS 模式 | 运行它的电脑的桌面 | 文档没有列出 | 打扰 | 不使用，文字定位用 OCR | main 已改为 Rust 版本，OS 模式只在旧分支与社区分支 |
| Windows-MCP | 用户正在使用的桌面 | Windows | 打扰 | 使用 UIA | 最近提交 2026-09-30，v0.8.7 |
| Codex（ChatGPT 桌面应用） | 运行应用的电脑的桌面 | macOS、Windows | Windows 上占用前台；macOS 可以在后台 | 没有找到来源 | rust-v0.159.2（2026-09-29） |
| Claude Code（命令行） | 用户 Mac 的真实桌面 | 只有 macOS | 打扰，隐藏其他应用 | 没有找到来源 | v2.1.285（2026-09-29） |
| Claude 桌面应用 | 用户电脑的真实桌面 | macOS、Windows | macOS 15 及以后可以在后台窗口中工作 | 没有找到来源 | 2026-03-23 发布 |
| OMP | 运行 OMP 的电脑已有的桌面 | Windows、macOS、Linux X11、Wayland | 默认后台投递，部分界面库需要前台 | 使用 UIA、AX、AT-SPI | 本地提交 2026-09-04 |
| OpenCode | 没有 computer use | — | — | — | 本地提交 `0027387` |

各项目的细节与来源见第 6 节。

### 1.2 不用容器、不用虚拟机时的屏幕来源

- **运行者自己的桌面**：Anthropic computer-use-best-practices、OpenAI 示例的 Python 部分、UFO²（当前实现）、cua 的宿主模式与 Cua Driver、Agent S、Open Interpreter、Windows-MCP、Codex、Claude Code、Claude 桌面应用、OMP。
- **同一台电脑上的另一个 Windows 会话**：UFO² 的画中画桌面（论文中有描述，代码没有发布），Windows 的 agent workspace（Copilot Actions 预览），MXC 的 isolation session（目前不支持界面程序）。见第 2.1 节与第 3.6 节。
- **Linux 上另建一个 X display**：
  - Xvfb 的手册页：Xvfb 可以在没有显示硬件、没有输入设备的机器上运行（第 4.4 节）。
  - Anthropic 工具文档（[computer-use-tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool)，Markdown 版第 917 行）：「Create a virtual display or connect to an existing display that Claude will interact with. This typically involves setting up Xvfb (X Virtual Framebuffer) or similar technology.」
  - cua 的 computer-server 在 Linux 处理代码中写「Run with virtual display: xvfb-run python -m computer_server」，截图注释写 ImageGrab「works with X11/Xvfb」（`libs/python/computer-server/computer_server/handlers/linux.py` 第 1–8 行）。
  - Cua Driver 安装文档：没有桌面会话的服务器「has no windows to drive until you start a desktop session (for example `xfce4` under `Xvfb`)」（`docs/content/docs/how-to-guides/driver/install.mdx` 第 54 行）。
  - cua 博客：「Headless is still early. The broader private-display story has not shipped. A pure-headless `Xvfb` recipe like `xvfb-run -a cua-driver serve` can be handy for CI experiments, but it is not the same thing as a fully supported background desktop product, and the community fork that explored private Xvfb and Hyprland background capture was closed rather than merged.」（`blog/inside-linux-computer-use.md` 第 91 行）。Cua Driver 路线图把「Real-Xorg MPX and uinput behavior」列为「Evidence gap」，写明要证明「routes that Xvfb cannot represent」（`docs/content/docs/reference/cua-driver/platform-roadmap.mdx` 第 66 行）。
- **把单个窗口送到宿主桌面**：CuaBot「runs a Docker container with a full X11 Linux desktop」，「Xpra acts as the X11 display server inside the container and streams individual application windows over WebSocket to your host, where they appear as native windows」（`blog/clawcon-multiplayer.md` 第 25、27 行）。这个做法仍然使用容器。

## 2. 在用户正在使用的电脑上不打扰用户

### 2.1 另建一个 Windows 会话

- **UFO² 画中画桌面（PiP）**：
  - 论文第 4.1 节（第 11 页）：「implemented via Windows' native Remote Desktop Protocol (RDP) loopback [44], creating a distinct virtual session hosted on the same machine. Applications launched within the PiP session inherit the user's identity, credentials, settings, and network context」；第 4.2 节：「leverages the RDP subsystem to maintain distinct input queues and device contexts across sessions」；第 4.3 节：主机与 PiP 之间用 Windows Named Pipes 通信，按会话凭据认证并加密；第 5 节（第 12 页）：PiP 桌面这类 Windows 专用操作由 C# 部分实现。
  - 文档 `documents/docs/ufo2/overview.md` 第 145–159 行：「Nested virtual desktop via Windows Remote Desktop loopback」，「User and agent don't compete for mouse/keyboard」。
  - 论文与仓库文档都没有写 PiP 对 Windows 版本、远程桌面服务或用户账户的要求。
  - 代码没有发布：提交 `a795552d97` 与另外 7 个分支中搜索 pip、picture、rdp、remote desktop、mstsc、loopback、CreateDesktop，没有 PiP 实现；整个仓库没有 `.cs`、`.csproj`、`.sln` 文件。`ufo/README.md` 第 46、80 行写「coming soon」，第 479 行写「In development」；`documents/docs/faq.md` 第 305–309 行写「Picture-in-Picture mode is planned for future releases」；询问发布时间的 issue [#222](https://github.com/microsoft/UFO/issues/222)（2025-05-12）没有回复。
- **Windows agent workspace** 与 **MXC isolation session**：见第 3.6 节。

### 2.2 在同一个桌面上把输入投递给目标窗口（后台方式）

- **OMP**：默认 `delivery: "background"`。Windows 用 `PostMessageW` 投递鼠标与键盘消息，X11 用 `XSendEvent` 或 XI2 MPX，macOS 用 SkyLight 的 `SLEventPostToPid`；已知会忽略投递消息的界面库直接报错，要求改用前台方式或无障碍操作。细节见第 6.13 节。
- **Cua Driver**（trycua/cua 的一部分，最新版本 `cua-driver-rs-v0.30.4`，2026-09-28）：
  - 「The default paths do not move the real pointer, do not raise the target window, and do not switch the user's frontmost app.」「This is a best effort rather than an absolute promise.」（`docs/content/docs/concepts/the-no-foreground-contract.mdx` 第 6、8 行）
  - Windows：「UI Automation can inspect and operate controls by window handle and automation element while another app is active. For input-like behavior, Cua Driver can post messages to a target window or use foreground escalation when the app only listens to active device input.」（同一文件第 28 行）
  - 按元素点击「performs the UIA Invoke pattern on the cached element via PostMessage. No cursor move, no focus steal.」；`type_text` 用「character-by-character PostMessage(WM_CHAR)」；后台方式遇到 Chromium/Electron 内容、GTK 按钮、VCL/LibreOffice 快捷键时返回 `background_unavailable`；前台方式是「a brief SetForegroundWindow swap + SendInput, restoring the prior foreground afterward」（`docs/content/docs/reference/cua-driver/mcp-tools-windows.mdx` 第 282、296、396 行）。
  - `launch_app` 的 `start_minimized` 用 `SW_SHOWMINNOACTIVE` 启动：「UIA / background dispatch still work on a minimized window; only `screenshot` and `delivery_mode:"foreground"` need it restored.」（同一文件第 222 行）
  - Windows 截图先用 `PrintWindow` 与 GDI，得到 UWP、WinUI、DirectComposition 界面的黑色画面时改用 Windows.Graphics.Capture：「WGC reads the window's own composited frame from DWM, even when another window sits above it.」「Minimized windows have no pixels for WGC to capture」（`blog/inside-windows-computer-use.md` 第 58、122 行）。代理的光标画在一个透明、点击穿透、不激活的分层窗口中（同一文件第 78 行）。
  - Linux：AT-SPI 的 `Action.DoAction`「do not need pointer injection or foreground focus」（`the-no-foreground-contract.mdx` 第 34 行）；X11 上经 XTEST 或 XInput2 主指针注入；用会话的 MPX 指针发送真实按键事件时，被其他窗口遮住的位置会拒绝（`reference/cua-driver/mcp-tools-linux.mdx` 第 249、267 行）。Wayland：「Arbitrary raw background PX is not available to an ordinary client on a standard Wayland compositor.」（`reference/cua-driver/platform-support.mdx` 第 176 行）
  - 与用户共用的部分：「they still share the same screen, keyboard, pointer, accessibility tree, and OS focus. Session or runtime identity does not create an independent desktop.」（`reference/cua-driver/process-model.mdx` 第 86–89 行）
- **Terminator**：README 第 75 行写「Doesn't take over your cursor or keyboard」；源码中 `click()` 用 `SendInput` 以绝对坐标移动并点击，调用时不恢复光标位置（`element.rs` 第 666–722 行）；`invoke` 用 InvokePattern，`set_value` 用 ValuePattern（第 838–858、1380–1406 行）。
- **Claude 桌面应用**：帮助中心 [14128542](https://support.claude.com/en/articles/14128542)：「On macOS (version 15 or later), Claude works in background windows, so you can keep using your computer while it runs. Claude doesn't take over your pointer or keyboard, and it generally waits if you're in the middle of typing.」文档只写了 macOS 的后台方式。
- **Codex**：macOS 上支持的任务可以在后台运行（`computer-use.md` 第 72–73 行）；Windows 见第 2.3 节。

### 2.3 占用用户的前台

- **Codex（Windows）**：「On Windows, Computer Use runs on the active desktop. It can't operate in the background while you keep using the same Windows session, so expect ChatGPT to move the pointer, type, and take over the foreground while the task runs.」文档给出的办法之一是在 Windows 虚拟机中运行 ChatGPT 桌面应用，「so Computer Use takes over the VM instead of your main desktop」（[computer-use](https://learn.chatgpt.com/docs/computer-use) 第 81–89 行）。
- **Claude Code 命令行（macOS）**：开始操作时隐藏其他可见的应用，结束后恢复；第一次操作时出现通知「Claude is using your computer · press Esc to stop」（`computer-use.md` 第 105–109、119 行）。
- **Claude 桌面应用**：不在后台运行时，Claude 工作期间隐藏其他窗口，结束后恢复（`desktop.md` 第 319 行）；Windows 上是否占用鼠标与键盘，没有找到明确原文。
- **Windows-MCP**：点击、移动、滚动、拖动用 `SetCursorPos` 加 `mouse_event`；切换窗口时调用 `ShowWindow` 与 `SetForegroundWindow`（`desktop/service.py` 第 589–640、696–880 行）；`SECURITY.md` 第 50–61 行建议部署在虚拟机、Windows 沙盒或专用的测试机上。
- **UFO²**：FAQ：「UFO² can run automation tasks on your current desktop. For non-disruptive operation, you can run it on a separate machine or virtual desktop environment.」（`faq.md` 第 305–309 行）默认点击与输入是 pywinauto 的 `click_input` 与 `type_keys`（模拟输入）。
- **用 pyautogui 的项目**：Agent S、Open Interpreter OS 模式、OpenAI 示例的 Python 部分、Anthropic computer-use-best-practices 都控制真实的鼠标与键盘。OpenAI 示例 README 第 89 行：「Python controls your real mouse and keyboard, and screenshots may include other windows. Use a dedicated desktop session and keep the lab window in front on your primary monitor.」

### 2.4 会话、锁屏与断开

- **Session 0**：
  - 微软文档：「Services cannot directly interact with a user as of Windows Vista.」（第 3.5 节）
  - Cua Driver：经 SSH 启动的进程通常在 Session 0，「Session 0 is not the logged-in user's GUI desktop, so it cannot see or operate those windows.」守护进程要放在交互用户的会话中，可以用计划任务保持（`process-model.mdx` 第 80–82 行）。
  - pywinauto 远程执行指南：以服务方式或经 SSH 运行时，GUI 测试不能工作（`docs/remote_execution.txt` 第 114–119 行）。
- **锁屏**：
  - Codex：「Windows Computer Use requires an active, unlocked desktop.」（`chatgpt-work-local-security.md` 第 59 行）
  - cua computer-server 在桌面锁定时拒绝执行，返回「Windows desktop is locked. Automation input is blocked by OS security.」（`handlers/windows.py` 第 31–35 行）
  - Cua Driver 的测试要求：「They reject Session 0, locked desktops, and disconnected RDP sessions.」（`libs/cua-driver/docs/test-harnesses-guide.md` 第 466–467 行）
  - pywinauto：锁定的机器上 `click_input` 等以 `_input` 结尾的方法、`set_focus`（它使用 `SetCursorPos` 与 `SetForegroundWindow`）、`type_keys`、`mouse` 与 `keyboard` 模块都不能使用；uia 与 win32 的 `set_edit_text`、win32 的 `send_chars` 与 `send_keystrokes` 能否使用取决于具体程序（`remote_execution.txt` 第 70–100 行）。
- **远程桌面最小化或断开**：
  - pywinauto：「If RDP window is minimized, there is no active desktop on remote PC by default.」「If RDP is disconnected, the desktop is locked out.」两种情况下 GUI 自动化都会失败（`remote_execution.txt` 第 18–24 行）。
  - WinAppDriver：关闭远程桌面会锁定电脑，交互会话暂停，GUI 测试失败；文档用 `tscon` 把会话交还控制台（`Docs/RunningOnRemoteMachine.md` 第 46–47 行）。
  - Cua Driver：「A disconnected session remains in `Disc` state and is still a live interactive session.」（`how-to-guides/driver/keep-running.mdx` 第 107 行）
- **截图**：UFO² 的代码注释写 `PrintWindow`「works on disconnected RDP sessions」，`BitBlt` 在断开的 RDP 会话上返回全黑图像（`ufo/automator/ui_control/screenshot.py`）；Windows-MCP 的代码注释写 dxcam 在虚拟机或 RDP 桌面上可能返回空帧，锁屏与屏保桌面上得到全黑截图属于正常结果（`desktop/screenshot.py` 第 280–285、302–309 行）；Desktop Duplication 在会话断开时返回 `DXGI_ERROR_SESSION_DISCONNECTED`（第 5.1 节）。

## 3. Windows 11 家庭版

### 3.1 控制主机的版本

注册表 `HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion`（2026-09-30 读取）：`EditionID` 为 `CoreCountrySpecific`（家庭中文版），`DisplayVersion` 为 `25H2`，`CurrentBuild` 为 26200，`UBR` 为 9457，`InstallationType` 为 `Client`。

### 3.2 微软文档对家庭版的说明

| 功能 | 家庭版 | 原文与来源 |
| --- | --- | --- |
| Hyper-V | 不能安装 | 「The Hyper-V role **can't** be installed on Windows 10 Home or Windows 11 Home.」要求列出 Windows 11 Pro 或 Enterprise。[Install Hyper-V](https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/get-started/install-hyper-v?pivots=windows)（ms.date 2025-05-23，文档提交 `a67a8c2`）；[System requirements for Hyper-V](https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/host-hardware-requirements)（ms.date 2025-06-26）同样只列 Windows 11 Professional 或 Enterprise |
| Windows 沙盒（Windows Sandbox） | 不支持 | 版本表只有 Pro、Enterprise、Pro Education/SE、Education；「Windows Sandbox is currently not supported on Windows Home edition.」沙盒是基于 hypervisor 的一次性虚拟机，同一时刻只能运行一个实例。[Windows Sandbox](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/)（ms.date 2026-03-29，文档提交 `ebc645a`） |
| 远程桌面的被连接端 | 不能作为被连接端 | 「Windows Home editions can't serve as Remote Desktop hosts, though they can be used as clients」。[Enable Remote Desktop on your PC](https://learn.microsoft.com/en-us/windows-server/remote/remote-desktop-services/remotepc/remote-desktop-allow-access)（ms.date 2025-06-18，文档提交 `a67a8c2`）。微软支持页面 [How to use Remote Desktop](https://support.microsoft.com/windows/how-to-use-remote-desktop-5fe128d5-8fb1-7a23-3b8a-41e636865e8c) 同样写明被连接的电脑要运行 Windows Pro 版本 |

### 3.3 家庭版上不能使用的做法

- 依赖 Hyper-V 的虚拟机：家庭版不能安装 Hyper-V。cua Sandbox SDK 的 Hyper-V 运行方式写明「Requires Windows Pro/Enterprise/Education with Hyper-V enabled.」（`cua_sandbox/runtime/hyperv.py` 第 11 行）。
- 依赖 Windows 沙盒的做法：家庭版不支持 Windows 沙盒。cua 的 Windows Sandbox 提供方（文档写「Windows Sandbox needs Pro/Enterprise」，`blog/ubuntu-docker-support.md` 第 11 行）与 MXC 的 `windows_sandbox` 后端都属于这一类。
- UFO² 的画中画桌面：论文写它基于远程桌面 loopback，家庭版不能作为远程桌面的被连接端；并且它的代码没有发布。
- Windows Agent Arena：宿主要用 WSL 2 上的 Docker 与嵌套虚拟化（dockur/windows README 写 Docker Desktop 需要「Windows 11 with nested virtualization enabled」）；用户已经决定不使用容器与 WSL。Bytebot、Anthropic 与 OpenAI 的容器配方、cua 的 Docker 提供方同样依赖容器。

### 3.4 文档中没有家庭版限制的做法

- 在用户的桌面上直接操作：Windows-MCP（README 列出 Windows 7 至 11）、Codex（Windows 桌面应用）、Claude 桌面应用（Windows）、用 pyautogui 的项目。这些都占用前台（第 2.3 节）。
- 后台投递与 UIA：OMP 的 Windows 后端；Cua Driver（要求「Windows 10/11 or Windows Server with an interactive desktop session and PowerShell」，`install.mdx` 第 36 行）；Terminator；pywinauto；FlaUI；NovaWindows Driver（Windows 10 及以上）。UIA 是 Windows 自带的接口（第 5 节）。
- 这些做法都在已经登录、没有锁定的交互桌面上工作（第 2.4 节）。

### 3.5 服务进程与用户桌面

[Interactive Services](https://learn.microsoft.com/en-us/windows/win32/services/interactive-services)（ms.date 2018-05-31，更新于 2025-04-15，文档提交 `70d815f`）：「Services cannot directly interact with a user as of Windows Vista.」所有服务运行在 session 0，默认使用不能交互的 window station；服务要显示界面，文档给出的做法是用 `CreateProcessAsUser` 在交互用户的会话中启动一个界面程序，两者经进程间通信交换信息。文档同时写明快速用户切换是用 Terminal Services 实现的。

### 3.6 微软正在提供的「另一个会话」

- **agent workspace**（微软支持文章 [Experimental Agentic Features](https://support.microsoft.com/en-us/windows/experimental-agentic-features-a25ede8a-e4c2-4841-85a8-44839191dfb3)，2025-10-16 发布，2025-11-17 与 2025-12-05 更新，2026-09-30 读取全文）：
  - 「agent workspace runs in a separate Windows session, allowing agents to interact with apps in parallel to your own session」；为代理提供「its own desktop」，同时限制代理看到用户桌面上的活动；文章称这种做法在常见操作上比 Windows 沙盒这样的完整虚拟机更省资源。
  - 每个代理使用单独的代理账户；设置「Experimental agentic features」默认关闭，只能由管理员打开，打开后对本机所有用户生效。
  - 使用它的是 Copilot Actions（Windows 预览体验计划中 Copilot Labs 的预览功能）；按代理管理文件访问的功能在预览版本 26100.7344 及以后提供；Windows On-Device Registry 中的 agent connectors（MCP 服务）默认在 agent workspace 中运行。
  - 文章没有写明家庭版是否可用，也没有写第三方的桌面代理怎样使用它。[Windows 11 security book - Agentic security](https://learn.microsoft.com/en-us/windows/security/book/operating-system-agentic-security)（ms.date 2025-11-13）写「the Windows platform and its security controls will be available for other developers in preview soon」。
- **Windows Developer Blog「Windows platform security for AI agents」**（2026-06-02）：session isolation 把代理的执行与用户的交互桌面、剪贴板、界面、输入设备分开；「Our initial release will support non-interactive sessions with additional capabilities targeted for future releases.」开发者接口是 Microsoft Execution Containers（MXC）SDK。
- **MXC**（[microsoft/mxc](https://github.com/microsoft/mxc)，`main` 提交 `f82237f4e8`，MIT，未归档，没有发布版本）：
  - README 第 6 行写明是早期预览，「no MXC profiles should be treated as security boundaries currently」。
  - README 第 29 行的 Windows 后端：`processcontainer`（默认，最低 26100）、`windows_sandbox`、`wslc`、`microvm`、`hyperlight`、`isolation_session`；`isolation_session` 最低版本 26340.9212（预览体验版本）。控制主机当前是 26200.9457。
  - `docs/isolation-session/oneshot.md`：每次执行建立一个新的代理用户与一个由系统管理的会话（第 20–26 行）；「GUI applications | No display server inside the session; only stdout/stderr captured」列在不支持的项目中（第 422 行）；会话中 `SendInput` 返回 `ERROR_ACCESS_DENIED`（第 257–265 行）。

## 4. 开发板（登记的机器）

### 4.1 硬件与当前状态（2026-09-30 21:30 只读检查）

| 项目 | 结果 |
| --- | --- |
| 系统 | Ubuntu 22.04.5 LTS（jammy），内核 `5.10.0+`，aarch64 |
| CPU | `/proc/cpuinfo` 有 4 个核心；普通进程的 CPU 亲和性是 0–2（`taskset -cp` 输出），`nproc` 返回 3 |
| 内存 | 共 7545 MB，已用 590 MB，可用 6740 MB；交换区 4095 MB，未使用 |
| 磁盘 | 根分区 59 GB，已用 20 GB，剩余 37 GB |
| 负载 | 负载平均值约 17；有 17 个 D 状态的进程（例如内核线程 `dev0_sq_task`），CPU 占用最高的进程是 `sshd`（4%） |
| 显示设备 | `/sys/class/drm/` 只有 `card0` 与 `renderD128`，驱动是 `panfrost`（Mali GPU，`OF_COMPATIBLE` 为 `arm,mali-bifrost`）；没有显示接口条目（没有 `card0-HDMI-A-1` 之类）；没有 `/dev/fb*` |
| 图形会话 | 默认目标是 `graphical.target`，但 `display-manager`、`lightdm`、`gdm3`、`sddm`、`xrdp` 都不在运行；`ps` 中没有 Xorg、Xvfb、Xwayland、任何窗口管理器或桌面进程；`HwHiAiUser` 的 8 个进程的环境中都没有 `DISPLAY` 或 `WAYLAND_DISPLAY`；`loginctl` 只有两个 SSH 会话 |
| 已安装的相关包 | `x11-common`、`x11-utils`、`x11-xserver-utils`、`xauth`、`libxtst6`、`libgtk-3-0`、`at-spi2-core` 2.44.0、`libatspi2.0-0`；共 791 个已安装的包 |
| 没有安装的包 | `xvfb`、`xserver-xorg-core`、`mutter`、`tint2`、`xdotool`、`scrot`、`python3-tk`、`imagemagick`、`x11vnc`、`gnome-screenshot`、`fonts-noto-cjk`、`python3-pyatspi`，也没有任何桌面环境 |
| Python | 3.10.12；`python3-tk` 未安装 |
| 软件源 | `repo.huaweicloud.com/ubuntu-ports`，jammy、jammy-security、jammy-updates、jammy-proposed 四组，main、restricted、universe、multiverse；本地包列表的日期是 2026-01 至 2026-03 |
| apt 设置 | `APT::Install-Recommends "1"`（默认安装推荐的包） |

### 4.2 软件源中的包

Launchpad 的发布记录（`api.launchpad.net`，`getPublishedBinaries`，jammy arm64，2026-09-30 查询）与开发板 `apt-cache policy` 的候选版本一致：

| 包 | 版本 | 仓库组件 | 发布日期 |
| --- | --- | --- | --- |
| `xvfb` | 2:21.1.4-2ubuntu1.7~22.04.16（updates、security） | universe | 2025-10-29 |
| `mutter` | 42.9-0ubuntu9（updates） | universe | 2024-09-29 |
| `tint2` | 17.0.1-1（release） | universe | 2021-10-21 |
| `xdotool` | 1:3.20160805.1-4（release） | universe | 2021-10-15 |
| `scrot` | 1.7-1（release） | universe | 2021-11-11 |
| `python3-tk` | 3.10.8-1~22.04（updates、security） | main | 2023-07-31 |
| `openbox` | 3.6.1-10（release） | universe | 2022-02-02 |
| `xfwm4` | 4.16.1-1（release） | universe | 2021-10-15 |

`xvfb` 包含 `/usr/bin/Xvfb` 与 `/usr/bin/xvfb-run`（packages.ubuntu.com，jammy-updates arm64 文件列表）。`python3-pyatspi` 的候选版本是 2.38.2-1。

### 4.3 安装占用（`apt-get -s` 模拟，按候选版本的 `Installed-Size` 与 `Size` 相加）

| 组合 | 新增包数 | 安装后占用 | 下载量 |
| --- | --- | --- | --- |
| `xvfb mutter tint2 xdotool scrot`（安装推荐的包，开发板默认） | 105 | 约 193 MB | 约 60 MB |
| 同上，`--no-install-recommends` | 87 | 约 161 MB | 约 48 MB |
| `xvfb` | 5（`libunwind8`、`libxfont2`、`x11-xkb-utils`、`xserver-common`、`xvfb`） | 约 3 MB | 约 1 MB |
| `mutter` | 76 | 约 155 MB | 约 46 MB |
| `tint2` | 6 | 约 2 MB | 约 1 MB |
| `xdotool` | 2（`libxdo3`、`xdotool`） | 小于 1 MB | 小于 1 MB |
| `scrot` | 4（`libgif7`、`libid3tag0`、`libimlib2`、`scrot`） | 约 1 MB | 小于 1 MB |
| `python3-tk` | 4（`libtk8.6`、`tk8.6-blt2.5`、`blt`、`python3-tk`） | 约 5 MB | 约 1 MB |
| `openbox` | 9 | 约 2 MB | 约 1 MB |
| `xfwm4` | 13 | 约 7 MB | 约 1 MB |
| `fonts-noto-cjk` | 1 | 约 89 MB | 约 58 MB |

单独模拟的各行都带 `--no-install-recommends`。`mutter` 的依赖中占用最大的是 `libwebkit2gtk-4.0-37`（86664 KB）与 `libjavascriptcoregtk-4.0-18`（30797 KB）；`mutter` 42.9 的 `Depends` 包括 `zenity`、`gnome-settings-daemon-common`、`gsettings-desktop-schemas`、`adwaita-icon-theme`、`libmutter-10-0`。`python3-tk` 带来的 `libtk8.6` 版本是 8.6.12。

### 4.4 运行占用

- Xvfb 的手册页（[x.org Xvfb.1](https://www.x.org/archive/current/doc/man/man1/Xvfb.1.xhtml)）：Xvfb 是可以在没有显示硬件、没有输入设备的机器上运行的 X 服务，用虚拟内存模拟帧缓冲；没有指定 `-shmem` 或 `-fbdir` 时，帧缓冲用 `malloc()` 分配；指定 `-fbdir` 时每个屏幕的帧缓冲是一个 xwd 格式的内存映射文件，复制这个文件就得到一张包含光标的全屏截图。
- 1280×800 的帧缓冲按每像素 3 至 4 字节计算约 3 至 4 MB。窗口管理器与被测程序的内存占用没有找到可引用的数字。
- 开发板当前可用内存 6740 MB。

### 4.5 各项目在这类 Linux 机器上的要求

- OMP 的 Linux 后端连接已有的显示服务：先看 `WAYLAND_DISPLAY`，再看 `DISPLAY`，两者都没有时报错（第 6.13 节）。
- Cua Driver：安装文档要求「an x86_64 Linux desktop session with X11/XWayland or the opt-in native Wayland backend described below, plus AT-SPI 2 for accessibility-tree tools」（`install.mdx` 第 54 行）；安装脚本把 `Linux-aarch64|Linux-arm64` 对应到 `linux-arm64`（`libs/cua-driver/scripts/_install-rust.sh` 第 586 行），发布版本 `cua-driver-rs-v0.30.4` 带有 `linux-arm64` 文件；博客写「Tested on Debian 12, Ubuntu 22.04, Ubuntu 24.04, Rocky 9, and Fedora 41」（`blog/inside-linux-computer-use.md` 第 12 行）。
- cua 的 computer-server：Linux 上用 pynput 输入、ImageGrab 截图，无障碍树返回模拟的空树（`handlers/linux.py` 第 1–8、41–51、80 行）。
- Anthropic 参考实现的镜像基于 `ubuntu:22.04`，与开发板的系统版本相同，镜像有 linux/arm64 版本（第 6.1 节）。
- Tk 8.6 没有 ATK 支持（第 5.5 节）；开发板已经安装 `at-spi2-core`。

## 5. Windows 的无障碍结构（UI Automation）

### 5.1 微软文档

1. [UI Automation Overview](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-uiautomationoverview)：UIA 提供对桌面上大多数界面元素的程序访问，可以「manipulate the UI by means other than standard input」，也用于自动化测试；元素树以桌面为根；control pattern 提供操作元素的方法（第 24、93、97 行）。「UI Automation does not enable communication between processes that are started by different users through the Run as command.」（第 40 行）
2. [UI Automation Security Overview](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-securityoverview)：辅助技术程序运行在 medium 完整性级别，UAC 对话框与登录界面在更高的级别；要访问更高级别的进程，manifest 中要设 `uiAccess=true` 并由管理员账户启动，程序需要 Authenticode 签名，安装在需要 UAC 才能写入的位置（例如 Program Files）；系统级别的界面只有在 UAC 桌面上以 SYSTEM 身份启动的进程才能访问（第 28–46、57–61 行）。
3. IsOffscreen（[Automation Element Property Identifiers](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-automation-element-propids) 第 233 行）：元素完全滚出视区，或被折叠（包括最小化窗口中的元素）时为 TRUE；「The value of the property is not affected by occlusion by other windows」，也与元素在哪个显示器上可见无关；IsOffscreen 为 TRUE 的元素仍然在 UI 模型中。
4. Invoke：`IUIAutomationInvokePattern::Invoke`「Invokes the action of a control, such as a button click」，应当立即返回；`IInvokeProvider::Invoke` 是异步调用。两页都没有写需要窗口在前台或获得焦点。
5. SetValue：要求 `CurrentIsEnabled` 为 TRUE、`IsReadOnly` 为 FALSE，没有写需要前台或焦点；多行编辑框不实现 `IValueProvider`，改用 `ITextProvider`。
6. [Desktops](https://learn.microsoft.com/en-us/windows/win32/winstation/desktops)：窗口消息只能在同一桌面上的进程之间发送；WinSta0 中同一时间只有一个桌面处于活动状态，即 input desktop，它对用户可见并接收用户输入；默认有 Default、ScreenSaver、Winlogon 三个桌面，安全屏保启动时切换到 ScreenSaver 桌面，按 Ctrl+Alt+Del 或出现 UAC 对话框时切换到 Winlogon 桌面（第 15–29 行）。
7. [Window Stations](https://learn.microsoft.com/en-us/windows/win32/winstation/window-stations)：每个远程桌面会话有自己的 WinSta0；只有交互式 window station 能显示界面、接收输入（第 15–17 行）。
8. `CreateDesktop` 把新桌面关联到调用进程的 window station，并分配给调用线程；`SwitchDesktop` 使指定桌面可见并激活，从 WinLogon、ScreenSaver 这类安全桌面调用时会失败（`CreateDesktopW` 第 61 行；`SwitchDesktop` 第 58、87–88 行）。
9. `SendInput` 受 UIPI 限制，只能向完整性级别相同或更低的程序注入输入；被阻止时返回值与 `GetLastError` 都不说明原因；事件串行插入输入流（第 89–95 行）。该页没有写「只注入当前输入桌面」，没有找到这方面的官方来源。
10. `SetCursorPos`：「The input desktop must be the current desktop when you call SetCursorPos.」（第 95 行）
11. `SetForegroundWindow` 有一组限制条件：「An application cannot force a window to the foreground while the user is working with another window.」（第 88–104 行）
12. `LockWorkStation`「has the same result as pressing Ctrl+Alt+Del and clicking Lock」，只能由交互式桌面上的进程调用。
13. Desktop Duplication：没有权限访问当前桌面图像时返回 `E_ACCESSDENIED`，「only an application that runs at LOCAL_SYSTEM can access the secure desktop」；会话断开时返回 `DXGI_ERROR_SESSION_DISCONNECTED`；桌面切换时 `AcquireNextFrame` 返回 `DXGI_ERROR_ACCESS_LOST`（`DuplicateOutput` 第 76、79 行；`AcquireNextFrame` 第 77–81 行）。
14. `PrintWindow` 由拥有窗口的程序处理（`WM_PRINT` 或 `WM_PRINTCLIENT`），页面只列出 `PW_CLIENTONLY` 一个标志（第 56、83、99 行）。
15. Windows.Graphics.Capture（[screen-capture](https://learn.microsoft.com/en-us/windows/apps/develop/media-authoring-processing/screen-capture)，ms.date 2026-08-23）：页面描述由用户经系统选择器选择显示器或窗口，系统在被捕获的项目周围画黄色边框；只支持 Windows 桌面设备与 Mixed Reality 头显；`IGraphicsCaptureItemInterop::CreateForWindow` 最低要求 Windows 10 1903。
16. 没有找到微软官方文档说明：UIA 能否跨桌面、跨会话工作；RDP 窗口最小化时的影响；锁屏、最小化、RDP 断开时 `PrintWindow`、`BitBlt`、Windows.Graphics.Capture 的行为。项目文档的说法见第 2.4 节。

### 5.2 以 UIA 为主的项目

| 项目 | 形式 | 读取与操作 | 平台 | 维护状态 |
| --- | --- | --- | --- | --- |
| [Terminator](https://github.com/mediar-ai/terminator) | Rust 库，仓库简介「playwright for windows computer use」 | Rust `uiautomation` 0.22.0；选择器按 name、role、window 查找（README 第 118、142–152 行）；`invoke` 用 InvokePattern，`set_value` 用 ValuePattern，`type_text` 先 SetFocus 再输入，`click()` 用 SendInput；截图用 xcap | 只支持 Windows（README 第 113 行） | 最近提交 2026-06-02，v0.24.32（2026-04-05），MIT |
| [pywinauto](https://github.com/pywinauto/pywinauto) | Python 库 | backend 有 win32（默认）与 uia；uia 下 `click()` 调用 InvokePattern，`set_edit_text` 调用 ValuePattern.SetValue，`set_focus()` 先还原最小化的窗口再调用 UIA SetFocus；`click_input`、`type_keys` 是模拟输入；`capture_as_image` 用 PIL ImageGrab（`uia_controls.py` 第 118–126、424–462 行，`uiawrapper.py` 第 402–418、508–518 行） | Windows | 最近提交 2026-05-23，0.6.9（2025-01-06；上一版 0.6.8 在 2019-10-27），BSD-3-Clause |
| [FlaUI](https://github.com/FlaUI/FlaUI) | .NET 库 | 封装 UIA2（托管接口）与 UIA3（COM），示例用 `button1?.Invoke()`（README 第 14–34、64–65 行） | Windows | 最近提交 2026-08-13，v5.0.0（2025-02-25），MIT |
| [WinAppDriver](https://github.com/microsoft/WinAppDriver) | Selenium 风格的服务 | 支持 UWP、WinForms、WPF、Win32 程序；需要开发者模式；需要交互式桌面会话（`Docs/RunningOnRemoteMachine.md` 第 33 行） | 文档写 Windows 10 | 最近提交 2025-04-14，最新版本 v1.2.1（2020-11-05）；appium-windows-driver README 写「WinAppDriver server has not been maintained by Microsoft for years」 |
| [appium-windows-driver](https://github.com/appium/appium-windows-driver) | Appium 驱动，代理 WinAppDriver | `windows: click`、`windows: scroll` 基于 SendInput；README 推荐改用 NovaWindows（第 17–19、416–418 行） | 宿主只支持 Windows 10；5.0.0 起只兼容 Appium 3 | 最近提交 2026-09-14，v6.3.0，Apache-2.0 |
| [NovaWindows Driver](https://github.com/AutomateThePlanet/appium-novawindows-driver) | Appium 2/3 驱动，后端是一个 PowerShell 会话，不需要开发者模式 | pattern 命令：invoke、expand、collapse、scrollIntoView、select、toggle、setValue，WindowPattern 的 maximize、minimize、restore、close，以及 setFocus；`windows: click`、`windows: scroll` 是鼠标手势（README 第 223–244、331–520 行） | Windows 10 及以上 | 最近提交 2026-08-27，v1.4.5，Apache-2.0 |

### 5.3 computer use 项目怎样使用 UIA

- **UFO²**：把控件列表交给模型，UIA 控件与 OmniParser 检测结果合并；默认点击与输入仍是模拟输入，可以改为 InvokePattern 与 ValuePattern（第 6.4 节）。
- **Windows Agent Arena**：可以用 UIA 或 win32 的树生成 Set-of-Marks；论文附录（第 15 页）：「We do not feed the UIA tree directly to the Navi agent. Instead, some agent configurations parse the tree to extract … names … types … positions」（第 6.5 节）。
- **Windows-MCP**：用 UIA 读取可交互元素与坐标，动作按坐标用模拟鼠标键盘执行，动作部分没有调用 UIA pattern（第 6.10 节）。
- **OMP**：用 Rust `uiautomation` 读取控件树，并用 Invoke、Toggle、LegacyIAccessible、ExpandCollapse、SelectionItem、ScrollItem、Value 这些 pattern 执行操作（第 6.13 节）。
- **Cua Driver**：`get_window_state` 同时返回无障碍树与截图；元素动作在 Windows 上经 UIA Invoke，macOS 上经 `AXPerformAction`，Linux 上经 AT-SPI `doAction`（`docs/content/docs/concepts/capture-and-delivery-modalities.mdx` 第 12、28 行）。
- **cua computer-server**：Windows 的无障碍树取前台窗口后用 `EnumChildWindows` 枚举 Win32 子窗口，没有使用 UIA（`handlers/windows.py` 第 76–137 行）。
- **Agent S**：只有 S1 在 Windows 上用 pywinauto 与 win32gui；S2 以后只用截图（第 6.8 节）。

### 5.4 是否要求程序显示在可见的桌面上

- 微软文档：IsOffscreen 不受其他窗口遮挡的影响；最小化窗口中的元素 IsOffscreen 为 TRUE，但仍在 UI 模型中（第 5.1 节第 3 项）。Invoke 与 SetValue 的文档没有写需要前台或焦点（第 4、5 项）。`SetCursorPos` 要求 input desktop 是当前桌面（第 10 项）。
- Cua Driver：「UIA / background dispatch still work on a minimized window; only `screenshot` and `delivery_mode:"foreground"` need it restored.」WGC 截取不到最小化的窗口；被遮住的窗口可以经 WGC 截取（第 2.2 节）。
- UFO²：只取 `IsOffscreen=FALSE` 的控件（`inspector.py` 第 243–266 行）。
- Windows-MCP：只列出当前 Windows 虚拟桌面上可见的顶层窗口（`tree/service.py` 第 933–950 行）。
- OMP：窗口列表跳过最小化的窗口（`win32/capture.rs` 第 177 行）。
- Codex：「On Windows, keep the target app visible on the active desktop while the task runs.」（`computer-use.md` 第 44 行）
- 所有项目的文档都要求一个已经登录、没有锁定的交互桌面（第 2.4 节）；pywinauto 写明锁定的机器上 `set_edit_text` 这类方法能否使用取决于具体程序。
- 没有找到微软官方文档说明 UIA 能否跨桌面或跨会话工作（第 5.1 节第 16 项）。

### 5.5 被测程序使用的界面库与无障碍接口

3.2D 真实验收工单 [#155](https://github.com/bender2333/yudao/issues/155) 的场景 2 是「质检在虚拟屏幕中核验 Tk 待办清单程序并放行」。

- **Tk**：[TIP 733「Add accessibility/screen reader support to Tk」](https://core.tcl-lang.org/tips/doc/trunk/tip/733.md)（状态 Final，目标 Tk 9.1，2025-09-24 建立）的理由一节写明「Tk is conspicuous among these toolkits in not supporting accessibility」。它加入 `tk accessible` 命令：Windows 上用 MSAA，X11 上用 ATK（经 at-spi2 桥接），macOS 上用 NSAccessibility；「A thin bridge layer to UI Automation driven by MSAA has been included in tka11y, but it is not robust.」Tcl/Tk 9.1.0 于 2026-09-29 发布（[tcl-lang.org 9.1 页面](https://www.tcl-lang.org/software/tcltk/9.1.html)，列出「Accessibility screen reader support」）。Python 3.14.7 文档写明官方二进制版本带的是 Tcl/Tk 8.6（[tkinter 文档](https://docs.python.org/3/library/tkinter.html)）；开发板上 `python3-tk` 依赖的是 `libtk8.6` 8.6.12。OMP 的后台投递表把 Tk 列为忽略投递键盘消息的界面库（`win32/delivery.rs` 第 78–80 行）。
- **Electron 与 Chromium**：[Electron 文档 Accessibility](https://www.electronjs.org/docs/latest/tutorial/accessibility)：检测到辅助技术时自动打开无障碍功能；也可以用 `app.setAccessibilitySupportEnabled(enabled)` 手动暴露 Chrome 的无障碍树。OMP 与 Cua Driver 都把 Chromium/Electron 内容列为忽略投递消息的目标（第 2.2 节）。
- **其他**：OMP 的表还列出 WinUI 3 忽略投递的鼠标消息，WPF 忽略投递的点击、移动、按键与文字，GTK 忽略投递的鼠标点击，VCL 忽略投递的按键（`win32/delivery.rs` 第 62–88 行）。

## 6. 逐项记录

### 6.1 Anthropic computer-use-demo（补充）

仓库 [anthropics/claude-quickstarts](https://github.com/anthropics/claude-quickstarts)，`main` 提交 `792cdebb32`（2026-09-29），MIT，未归档，没有发布版本。最近一次改动 `computer-use-demo/` 的提交是 `5264b729de`（2026-08-21，支持 `computer_toolset_20260801`）。

- 屏幕来源：容器中的 Xvfb 桌面，README 第 26 行写「a Linux desktop in Docker with X11 + VNC」。
- 支持的平台：镜像同时构建 linux/amd64 与 linux/arm64（`.github/workflows/build.yaml` 第 16–37、66–72 行；2026-09-30 查询 ghcr.io 的 `computer-use-demo-latest` 清单，列出这两个平台）。所有启动方式都是 `docker run`。
- 是否打扰用户的桌面：不打扰，操作的是容器中的桌面。
- 动作接口与截图方式：已记在 `computer-use-implementations.md` 第 1 节。
- 是否使用无障碍结构：没有，`computer.py` 中没有无障碍相关的调用。
- README 第 6–16 行的安全提示：使用专用虚拟机或容器并给最小权限；不给模型账号登录信息；网络限制在域名白名单内；有实际后果的决定由人确认；网页或图片中的指令可能覆盖用户的指令。

### 6.2 Anthropic computer-use-best-practices（同一仓库，不用容器）

同一提交 `792cdebb32` 的 `computer-use-best-practices/`，2026-05-13 加入（`b03d42cc10`），最近一次改动 `5264b729de`（2026-08-21）。

- 屏幕来源：宿主 macOS 的真实屏幕，README 第 34–35 行写「running **locally** (no Docker)」；截图用 `pyautogui.screenshot()`（`computer_use/tools/computer.py` 第 277–278 行）。
- 支持的平台：只支持 macOS，README 第 27–29 行：「It targets macOS only. Key handling, the `pyautogui` backend, and `sandbox-exec` are all Mac-specific; a containerized or Linux variant is out of scope here.」
- 是否打扰用户的桌面：打扰。README 第 66 行「This task will move your real mouse and keyboard」；第 6–10 行「Running this agent outside of a virtual machine is **strongly discouraged**. The agent has full control of your mouse, keyboard, and screen.」；第 12–15 行建议放在一次性的 macOS 虚拟机中（UTM、Parallels）。关闭 computer 工具以后只剩 headless Playwright Chromium，第 139–146 行说这种方式「handy when you do not want the agent touching your desktop」。
- 动作接口与截图方式：pyautogui 负责鼠标、按键与截图；文字输入用 Quartz 的 `CGEventKeyboardSetUnicodeString` 加 `CGEventPost`（`computer.py` 第 133–150 行）；终端需要 Screen Recording 与 Accessibility 权限（README 第 103–112 行）；bash 与 python 工具在 `sandbox-exec` 中运行（`sandbox/default.sb` 第 10、13 行）。
- 是否使用无障碍结构：没有；Accessibility 权限只用于控制鼠标与键盘（README 第 103–104 行）。
- Anthropic 工具文档（2026-09-30 读取 Markdown 版，共 2247 行）第 440、906 行要求沙箱化、虚拟化或容器化的环境；第 917 行见第 1.2 节。文档中没有单独讲直接在用户电脑上运行的一节。

### 6.3 OpenAI CUA 示例程序

仓库 [openai/openai-cua-sample-app](https://github.com/openai/openai-cua-sample-app)，提交 `f2a3dc523a`（2026-09-04），MIT，未归档，没有发布版本。2026-03-05 的提交 `6a14341497` 删除了 Dockerfile 与 `computers/`（docker、local_playwright、browserbase、scrapybara 四种环境），当前提交没有 Docker 环境。

- 屏幕来源：JavaScript 部分是 Playwright 启动的 Chromium 页面，默认 headless，可以改成可见（`javascript-app/src/browser/session.ts` 第 87 行，`browser/javascript-process.ts` 第 65–67 行，`javascript-app/README.md` 第 9 行）；Python 部分是运行者电脑的真实桌面，`pyautogui.screenshot()` 截全屏（`python-app/app/desktop/worker.py` 第 46–63 行）。
- 支持的平台：Python 部分在 macOS 需要 Accessibility 与 Screen Recording，Linux 需要 X11 桌面，Windows 需要图形桌面会话（`python-app/README.md` 第 9–11 行）；释放残留按键时 macOS 用 Quartz、Windows 用 `SendInput`、Linux 用 XTest（`desktop/release_inputs.py` 第 136–143 行）。
- 是否打扰用户的桌面：Python 部分打扰（README 第 89 行，见第 2.3 节）；JavaScript 部分默认 headless。
- 动作接口与截图方式：模型写代码，经函数工具 `exec_js`（持久的 Playwright REPL）或 `exec_py`（持久的 Python 进程，可以使用 `pyautogui`）执行，图像放在 `function_call_output` 的 `input_image` 中返回。
- 是否使用无障碍结构：没有。
- 另外两个官方示例：`openai/openai-testing-agent-demo`（`d116b832ce`，2025-06-17）用 `chromium.launch({ headless: false })` 做前端测试，只覆盖网页；`openai/openai-agents-python` 的 `examples/tools/computer_use.py`（`main` 提交 `c513dd1814`，2026-09-30）用 `LocalPlaywrightComputer`，默认 headless，截图用 `page.screenshot`，只覆盖浏览器。

### 6.4 Microsoft UFO²

仓库 [microsoft/UFO](https://github.com/microsoft/UFO)，提交 `a795552d97`（2026-09-29）；文档 [microsoft.github.io/UFO](https://microsoft.github.io/UFO/)（gh-pages `259b896d9c`）；论文 [arXiv 2504.14603v2](https://arxiv.org/abs/2504.14603)。

- 屏幕来源：当前用户桌面。整个桌面的截图依次尝试 PIL `ImageGrab.grab`、win32 `BitBlt`、对桌面窗口或前台窗口调用 `PrintWindow`；单个窗口依次尝试 pywinauto `capture_as_image`、`PrintWindow(PW_RENDERFULLCONTENT)`、整个桌面（`ufo/automator/ui_control/screenshot.py` 第 82–133、136–206、209–289、302–338 行）。画中画桌面见第 2.1 节。
- 支持的平台：Windows 10 及以上，Python 3.10 及以上（`ufo/README.md` 第 106 行）；FAQ 推荐 Windows 11（`faq.md` 第 289–293 行）。
- 是否打扰用户的桌面：打扰（第 2.3 节）；`ControlReceiver` 创建时对控件或应用调用 `set_focus()`（`controller.py` 第 64–68 行）。
- 动作接口与截图方式：默认 `CLICK_API: "click_input"`、`INPUT_TEXT_API: "type_keys"`（`config/ufo/system.yaml` 第 50、52 行），都是 pywinauto 的模拟输入；可以改成 `click`（pywinauto 0.6.8 中 Button 的 `click()` 调用 InvokePattern）或 `set_text`（`set_edit_text` 调用 ValuePattern.SetValue）；按坐标的点击、拖动、滚动与打字用 pyautogui（`controller.py` 第 113–170、329–369 行）；Excel、Word、Outlook 等程序优先走 COM 或 API，失败后回到模拟输入（论文第 3.5 节）。
- 是否使用无障碍结构：使用。`CONTROL_BACKEND` 默认 `["uia"]`，可以设为 `["omniparser"]` 或两者都用（`system.yaml` 第 11–12 行）。先用 pywinauto 的 win32 backend 列出顶层窗口，再包装成 UIA 元素，用 IUIAutomation `FindAllBuildCache` 取控件，条件是 IsEnabled、IsOffscreen=FALSE、IsControlElement、控件类型在 CONTROL_LIST 中，最多 500 个（`inspector.py` 第 179–203、243–266、334–369 行）。合并时保留全部 UIA 控件，OmniParser-v2 的检测框与任一 UIA 框的 IoU 大于 0.1 时丢弃，其余包装成 UIAWrapper（`screenshot.py` 第 1317–1345 行；论文第 3.4 节）。依赖 pywinauto==0.6.8、uiautomation==2.0.18、pyautogui==0.9.54、comtypes==1.2.0（`requirements.txt`）。
- 维护状态：最新版本 v3.0.10（2026-09-22），未归档，MIT；README 第 153、566–575 行把 UFO² 标为 LTS。

### 6.5 Windows Agent Arena

仓库 [microsoft/WindowsAgentArena](https://github.com/microsoft/WindowsAgentArena)，main 提交 `6d39ed88c5`（2024-11-20）；论文 [arXiv 2409.08264v2](https://arxiv.org/abs/2409.08264)。

- 屏幕来源：Docker 容器中用 QEMU 运行 Windows 11 Enterprise Evaluation 虚拟机，有 `/dev/kvm` 时用 KVM 加速；镜像按 dockur/windows 改写（`Dockerfile-WinArena` 第 48–56 行设定分辨率 1440×900、内存 8G、8 核）。虚拟机内的 Flask 服务取截图：`/obs_winagent` 用 `ImageGrab.grab`，`/screenshot` 用 `pyautogui.screenshot()`（`vm/setup/server/main.py` 第 308–340、379–424 行）。人经浏览器 `localhost:8006` 查看虚拟机。
- 支持的平台：宿主是 Linux 或 Windows 的 WSL（README 第 58 行），Windows 上推荐 Docker Desktop 的 WSL 2 后端（第 45 行）；检测不到 `/dev/kvm` 时关闭 KVM，README 不建议这样运行（第 357–365 行）；dockur/windows README（第 405–434 行）写 Docker Desktop 需要「Windows 11 with nested virtualization enabled」。
- 是否打扰用户的桌面：不打扰，动作在容器内的虚拟机中执行。
- 动作接口与截图方式：Navi 输出 Python 代码，经 POST `/execute_windows` 在虚拟机中用 `exec` 执行，`computer.mouse` 与 `computer.keyboard` 内部调用 pyautogui（`main.py` 第 167–196 行）。
- 是否使用无障碍结构：可选，参数 `--som-origin a11y|mixed-oss|mixed-omni` 与 `--a11y-backend uia|win32`，README 推荐 `mixed-omni` 加 `uia`（第 173、184–196 行）；`/accessibility` 用 pywinauto 遍历窗口并输出 XML（`main.py` 第 847–872 行）；论文附录的说法见第 5.3 节。
- 维护状态：最新版本 v0.0.4（2024-09-28）；仓库 `pushed_at` 为 2026-04-13（来自 dependabot 分支）；未归档，MIT。

### 6.6 trycua/cua

仓库 [trycua/cua](https://github.com/trycua/cua)，提交 `0f29c142d7`。

- 屏幕来源：Computer SDK 的提供方有 `lume`、`lumier`、`cloud`、`cloudv2`、`winsandbox`、`docker`（`libs/python/computer/computer/providers/base.py` 第 13–18 行）：
  - Lume：Apple Silicon 上用 Apple Virtualization.Framework 的 macOS/Linux 虚拟机（README 第 129 行）；Lumier：Docker 中的 macOS/Linux 虚拟机。
  - Docker：默认镜像 `trycua/cua-ubuntu:latest`，「KasmVNC + Ubuntu 22.04 (Xfce) in Docker」（`blog/ubuntu-docker-support.md` 第 35 行）。
  - Windows Sandbox：经 pywinsandbox 建立，沙盒中以隐藏窗口启动 `cua-computer-server`（`providers/winsandbox/`，`setup_script.ps1` 第 119、127 行）；「supports **one virtual machine at a time**」（`blog/windows-sandbox.md` 第 57 行）。
  - 云端虚拟机。
  - 宿主桌面：`Computer(use_host_computer_server=True)`，「If True, target localhost instead of starting a VM」（`libs/python/computer/computer/computer.py` 第 101、138 行）；CLI 的 `host` 目标；Sandbox SDK 的 `Localhost`，「Direct host control — **not sandboxed**」（`libs/python/cua-sandbox/README.md` 第 129–139 行）。
  - Sandbox SDK 的本地运行方式还有裸机 QEMU、Docker、Windows 上可用时的 Hyper-V、Lume、Android 模拟器（`runtime-support.mdx` 第 20–26 行）。
  - Cua Driver：「observes and controls the desktop where it is installed and targeted. That can be your existing computer or a guest」（`docs/content/docs/concepts/how-sandboxes-work.mdx` 第 22–24 行）。
- 支持的平台：Windows Sandbox 提供方的文档有「Windows 10/11: Any edition that supports Windows Sandbox」（`blog/windows-sandbox.md` 第 222 行）与「Windows Sandbox needs Pro/Enterprise」（`blog/ubuntu-docker-support.md` 第 11 行），代码只检查 `winsandbox` 模块能否导入；Docker 桌面在 macOS、Windows、Linux；Cua Driver 的 Windows 与 Linux 要求见第 3.4、4.5 节。
- 是否打扰用户的桌面：宿主模式打扰：「the agent takes over your screen and you lose your machine until it's done.」（`blog/clawcon-multiplayer.md` 第 17 行）；CLI 选择 `host` 之前要求用户同意「This grants full keyboard, mouse, and screen access to your local desktop.」（`cli-reference.mdx` 第 429–430 行）。Cua Driver 见第 2.2 节。
- 动作接口与截图方式：computer-server 按系统选择后端 native、`vnc`、`cua-driver`（`handlers/factory.py`）；Windows 用 pynput 输入、`PIL.ImageGrab.grab()` 截全屏，桌面锁定时拒绝执行（`handlers/windows.py` 第 4–5、20–50 行）；Linux 用 pynput 与 ImageGrab；`cua-driver` 后端把截图与输入交给 Cua Driver，「never falls back to OS-native input injection」（`libs/python/computer-server/README.md` 第 64–69、104–116 行）；`Localhost` 与 `cua-auto` 用 pynput 输入，截图先用 `PIL.ImageGrab`，失败后用 mss。
- 是否使用无障碍结构：computer-server 提供 `computer_get_accessibility_tree` 与 `computer_find_element`：macOS 用 AX API；Windows 用 Win32 `EnumChildWindows`；Linux 返回模拟的空树，「simulated, no accessibility API available on Linux」。Cua Driver 使用 UIA、AX、AT-SPI（第 5.3 节）。
- 维护状态：未归档，最近推送 2026-09-29；`releases/latest` 为 `sandbox-v0.8.0`（2026-09-15）；Cua Driver 最新 `cua-driver-rs-v0.30.4`（2026-09-28）；MIT。

### 6.7 Bytebot

仓库 [bytebot-ai/bytebot](https://github.com/bytebot-ai/bytebot)，提交 `3d37894ce0`。

- 屏幕来源：Docker 容器中的虚拟桌面：`FROM ubuntu:22.04`，`ENV DISPLAY=:0`，安装 `xvfb`、`x11vnc`、`xfce4`（`packages/bytebotd/Dockerfile` 第 6、14、21、24、36 行）；supervisord 启动 `Xvfb :0 -screen 0 1280x960x24`、`x11vnc`、`websockify` 与 `bytebotd`（`supervisord.conf` 第 28、58、71、83 行）。
- 支持的平台：部署方式有 Docker Compose、Helm、Railway；「Same environment on Mac, Windows, or Linux」（`docs/core-concepts/desktop-environment.mdx` 第 25 行）；Dockerfile 区分 amd64 与 arm64。
- 是否打扰用户的桌面：「No Risk to Host: All actions happen inside the container」（同一文件第 19 行）。
- 动作接口与截图方式：`@nut-tree-fork/nut-js` 的 `mouse`、`keyboard` 与 `screen.capture`（`packages/bytebotd/src/nut/nut.service.ts`）；粘贴文字先用 `xclip` 写剪贴板，再发送 Ctrl+V。
- 是否使用无障碍结构：没有找到。
- 只能在容器中运行：文档写「a complete Linux desktop that runs in a Docker container」，没有找到在容器之外运行 `bytebotd` 的说明。
- 维护状态：已归档，最近提交 2025-09-11，没有发布版本，Apache-2.0。

### 6.8 Agent S

仓库 [simular-ai/Agent-S](https://github.com/simular-ai/Agent-S)，提交 `3aa272d23d`。

- 屏幕来源：运行它的电脑的桌面，S3 的 CLI 每一步执行 `pyautogui.screenshot()`（`gui_agents/s3/cli_app.py` 第 164–175 行）；评测时用 OSWorld 的 VMware 或 AWS 虚拟机，以及 WindowsAgentArena 的虚拟机。
- 支持的平台：「Supported Platforms: Linux, Mac, and Windows」「Single Monitor」（README 第 119–121 行）。
- 是否打扰用户的桌面：「Security: The agent runs Python code to control your computer - use with care」（README 第 120 行）；没有找到与用户共用桌面的说明。
- 动作接口与截图方式：模型输出 pyautogui 代码字符串，CLI 用 `exec()` 执行（`cli_app.py` 第 215 行；`agents/grounding.py` 第 363–370 行）。
- 是否使用无障碍结构：S1 使用，Linux 用 `pyatspi`，macOS 用 `AXUIElement*`，Windows 用 `pywinauto` 与 `win32gui`（`gui_agents/s1/aci/`）；S2 的 worker 只读取截图，坐标由 grounding 模型给出，文字位置用 pytesseract；S2.5 与 S3 中没有 accessibility、pyatspi、pywinauto、AXUIElement；README 把 grounding 模型列为必需，推荐 UI-TARS-1.5-7B（第 155–156 行）。
- 维护状态：未归档；最新版本 v0.3.2（2025-12-16）；Apache-2.0。

### 6.9 Open Interpreter OS 模式

- 维护状态：仓库现名 [openinterpreter/openinterpreter](https://github.com/openinterpreter/openinterpreter)，main 提交 `12ad79b828`（2026-09-30），当前 main 是 Rust 版本，README 第 47 行「Open Interpreter is a fork of OpenAI's Codex」，第 147–148 行指向社区维护的 Python 分支 `endolith/open-interpreter`；main 没有 `interpreter/` Python 包，OS 模式不在 main 中。带 `--os` 的 Python 版本在分支 `main-backup`（`e00f08e2ed`，版本 0.4.3）与 `endolith/open-interpreter`（`3b9a12e2c1`）。PyPI 上 `open-interpreter` 最新是 0.4.3（2024-10-26）。main 现在的 computer use 是内置的 QA skill，用 `cua-driver` 命令行操作桌面程序（`codex-rs/skills/src/assets/samples/qa-testing/SKILL.md` 第 3、61–78 行）。
- 以下行号指 `main-backup` 的 `e00f08e2ed`。
- 屏幕来源：运行它的电脑的桌面，截图用 `pyautogui.screenshot()`（`interpreter/computer_use/tools/computer.py` 第 222–228 行）；`interpreter --os` 进入 `interpreter/computer_use/loop.py`，使用 Anthropic beta `computer-use-2024-10-22`。
- 支持的平台：OS 模式文档没有列出平台；「OS mode does not currently support multiple displays.」（`docs/guides/os-mode.mdx` 第 15–17 行）。
- 是否打扰用户的桌面：启动时显示「This AI has full system access … Move your mouse to any corner of the screen to exit.」（`loop.py` 第 456–458 行）。
- 动作接口与截图方式：pyautogui 的 `moveTo`、`dragTo`、`hotkey`、`press`、`write`、`click`；`computer.display.view()` 用 `pyautogui.screenshot()`。
- 是否使用无障碍结构：没有找到。文字定位用 OCR：先请求 `api.openinterpreter.com` 的 `/point/text/`，失败或离线时用本地 pytesseract（`display.py` 第 277–307 行）；用 pywinctl 读取活动窗口的应用名与标题。

### 6.10 Windows-MCP

仓库 [CursorTouch/Windows-MCP](https://github.com/CursorTouch/Windows-MCP)，提交 `6885dc1fc4`。

- 屏幕来源：用户正在使用的真实桌面；截图后端的 auto 模式依次尝试 dxcam（DXGI Desktop Duplication）、mss、pillow ImageGrab（README 第 632 行；`desktop/screenshot.py` 第 51–62、105–270、327–375 行）。
- 支持的平台：README 列出 Windows 7、8、8.1、10、11，要求 Python 3.13 及以上（第 35–40、77 行）；`pyproject.toml` 写 `requires-python >=3.14`，classifiers 只列 Windows 10 与 11。
- 是否打扰用户的桌面：打扰，`SECURITY.md` 第 13–16 行「interacts directly with your actual Windows operating system」。
- 动作接口与截图方式：点击、移动、滚动、拖动用 `SetCursorPos` 加 `mouse_event`；输入先点击坐标，再用 `SendKeys`（`keybd_event` 或 `SendInput`），20 个字符以上的纯文本用剪贴板加 Ctrl+V（`service.py` 第 718–780 行）；动作部分没有调用 Invoke、SetValue 等 UIA pattern。
- 是否使用无障碍结构：使用。仓库内置的 `windows_mcp.uia` 来自 yinkaisheng 的 Python-UIAutomation-for-Windows（`uiautomation`），基于 comtypes（`uia/core.py` 第 1–11 行）；遍历时读取缓存的 IsOffscreen、IsKeyboardFocusable、LegacyIAccessible 属性（`tree/service.py` 第 319–640 行）。Snapshot 工具返回光标位置、显示器、虚拟桌面、焦点窗口、已打开的窗口与 UI 树（可交互元素及坐标、可滚动区域），可以附带标出元素框的截图（`tools/snapshot.py` 第 25–120 行）。
- 维护状态：最新版本 v0.8.7（2026-09-30），未归档，MIT。

### 6.11 Codex（ChatGPT 桌面应用中的 Computer Use）

文档 [learn.chatgpt.com/docs/computer-use](https://learn.chatgpt.com/docs/computer-use)（2026-09-30 读取）及相关页面；本地仓库 `C:\project\codes\codex` 提交 `69f7140`；`openai/codex` 最新发布 `rust-v0.159.2`（2026-09-29）。

- 屏幕来源：运行 ChatGPT 桌面应用的那台电脑的桌面；也可以在 Windows 虚拟机中运行应用（第 88–89 行）。
- 支持的平台：macOS 与 Windows（第 5–6 行）；Linux 预览版没有，「Computer Use is available on macOS and Windows but not yet in the Linux preview」（`linux-app.md` 第 123–125 行）。What's new 记录 2026-05-25 至 05-29 加入 Windows。
- 是否打扰用户的桌面：Windows 上占用前台（第 2.3 节）；第 169 行「Locked use is for macOS. On Windows, Computer Use works in the foreground.」；macOS 上支持的任务可以在后台运行。
- 动作接口与截图方式：查看屏幕、截图、操作窗口、菜单、键盘输入与剪贴板（第 207–208 行）；按应用授权，Windows 程序用可执行文件名或 AppUserModelID 标识（第 145–155 行；本地仓库 `codex-rs/config/src/computer_use.rs` 第 9–35 行的配置只有 `macos.bundle_ids` 与 `windows.aumids`、`windows.exes`）；不能操作终端应用与 ChatGPT 本身（第 234–237 行）。
- 是否使用无障碍结构：文档写 macOS 的 Accessibility 权限用于「click, type, and navigate」（第 51 行）；是否读取 macOS 辅助功能树或 Windows UIA，没有找到来源。

### 6.12 Claude Code 与 Claude 桌面应用

文档 [code.claude.com/docs/en/computer-use](https://code.claude.com/docs/en/computer-use)、[desktop](https://code.claude.com/docs/en/desktop)，帮助中心文章 [14128542](https://support.claude.com/en/articles/14128542)（均 2026-09-30 读取）。

- Claude Code（命令行）：
  - 屏幕来源：用户 Mac 的真实桌面，「computer use runs on your actual desktop with access to the apps you approve」（`computer-use.md` 第 126 行）。
  - 支持的平台：只有 macOS，「Computer use in the CLI is not available on Linux or Windows」（第 202 行）；research preview，需要 Pro 或 Max，`-p` 非交互模式不能使用（第 10 行）。
  - 是否打扰用户的桌面：打扰（第 2.3 节）；同一时刻只有一个会话能使用电脑（第 103 行）。
  - 动作接口与截图方式：内置 MCP 服务 `computer-use`，默认关闭，在 `/mcp` 中启用（第 39–53 行）；截图发送前自动缩小，目标尺寸不能调整（第 111–115 行）；命令行与桌面应用使用同一个 computer use 引擎（第 178 行）。
  - 是否使用无障碍结构：没有找到来源；文档只写 Accessibility 权限用于点击、输入、滚动（第 56–62 行）。
  - 维护状态：2026 年第 14 周加入；最新版本 v2.1.285（2026-09-29）。
- Claude 桌面应用：
  - 屏幕来源：用户电脑的真实桌面（`desktop.md` 第 262 行）；帮助中心：「Computer use has no sandbox between Claude and your applications.」
  - 支持的平台：macOS 与 Windows，research preview，需要 Pro 或 Max（`desktop.md` 第 254 行）；Linux 版没有（第 930 行）。
  - 是否打扰用户的桌面：macOS 15 及以后可以在后台窗口中工作（第 2.2 节）；其他情况隐藏其他窗口（第 2.3 节）。
  - 动作接口与截图方式：帮助中心写「Claude takes screenshots of your computer to understand how to navigate the screen」；按应用授权分三级：View only、Click only、Full control（`desktop.md` 第 302–314 行）；实现方式没有公开来源。
  - 是否使用无障碍结构：没有找到来源。
  - 维护状态：2026-03-23 发布，后台方式在 2026 年第 36 周加入（beta）。

### 6.13 OMP（oh-my-pi）

本地仓库 `C:\project\codes\oh-my-pi`，提交 `fdfeef1f78`（2026-09-04）。`computer` 工具的 JavaScript 接口与截图上限已记在 `computer-use-implementations.md` 第 4 节；下面是原生部分，源码在 `crates/pi-natives/src/desktop/`（共 11140 行），上次调研没有读。

- 屏幕来源：运行 OMP 的那台机器上已有的桌面，不建立虚拟屏幕。设置说明是「Enable the scriptable host-desktop control tool (screenshots, input, accessibility)」，默认关闭（`packages/coding-agent/src/config/settings-schema.ts` 第 4326–4335 行）。Linux 上先看 `WAYLAND_DISPLAY`，再看 `DISPLAY`，两者都没有时报错「no display server」（`linux/mod.rs` 第 11–20 行）。
- 支持的平台：Windows（`win32/`）、macOS（`macos/`）、Linux X11（`linux/x11/`）、Linux Wayland（`linux/wayland/`，经 xdg-desktop-portal 的 RemoteDesktop 与 libei，只有后台方式，`background_window_input: false`，`wayland/mod.rs` 第 68、121–122 行）。
- 是否打扰用户的桌面：输入默认 `delivery: "background"`，提示词写明「target window input without changing user focus, pointer, or window order」；`foreground` 方式短暂激活目标窗口，操作后恢复焦点（`packages/coding-agent/src/prompts/tools/computer.md` 第 18 行）。
  - Windows 的后台方式用 `PostMessageW` 把 `WM_LBUTTONDOWN`、`WM_MOUSEMOVE`、`WM_MOUSEWHEEL`、`WM_KEYDOWN`、`WM_CHAR` 等消息投递给目标窗口（`win32/input.rs` 第 242–251、293–342、524–561 行）。投递之前按窗口类名检查，已知会忽略投递消息的界面库直接报错，提示改用前台方式或无障碍操作（第 230–240 行）。`win32/delivery.rs` 第 62–88 行的表：Chromium（`Chrome_WidgetWin_*`）全部事件都忽略；WinUI 3 忽略鼠标；WPF 忽略点击、移动、按键与文字；Tk 忽略按键与文字；GTK 忽略鼠标点击；VCL（`SAL*`）忽略按键。
  - Windows 的前台方式先 `SetForegroundWindow` 到目标窗口，再用 `SendInput`，结束后把前台窗口切回原来的窗口（`win32/input.rs` 第 589–627 行）；目标是整个桌面时用 `enigo` 发出全局输入（第 808–848 行）。
  - X11 的后台方式用 `XSendEvent`；GTK、Qt、Chromium、Firefox 会过滤这类事件，这时鼠标事件改用 XI2 MPX（另建一个指针），键盘事件报错；前台方式用 XTEST（`linux/x11/input.rs` 第 25、53–57、84–163 行）。
  - macOS 的后台方式用私有框架 SkyLight 的 `SLEventPostToPid`（`macos/skylight.rs` 第 25–35、107–125、154 行）。
- 动作接口与截图方式：
  - Windows 截图用 `xcap` 0.9.6，关闭默认功能（`crates/pi-natives/Cargo.toml` 第 90 行），走 GDI 路径：整屏用 `BitBlt`，单个窗口用 `PrintWindow`（先用标志 2，即 `PW_RENDERFULLCONTENT`，再试 0 与 4，最后用 `BitBlt`）（xcap `src/windows/capture.rs` 第 48–79、107–112 行，`src/windows/gdi.rs` 第 83–108、124–179 行）。窗口列表跳过最小化的窗口（`win32/capture.rs` 第 177 行）。
  - X11 截图用 `x11rb` 对根窗口 `GetImage`，要求 TrueColor（`linux/x11/capture.rs` 第 80–103、367–382 行）。
- 是否使用无障碍结构：使用。Windows 用 Rust 库 `uiautomation` 0.25.0 读取控件树，并用 Invoke、Toggle、LegacyIAccessible、ExpandCollapse、SelectionItem、ScrollItem、Value 这些 pattern 执行操作与设置值（`win32/ax.rs` 第 1–5、95–130、209–253 行）；Linux 用 `atspi` 0.30.0 连接 AT-SPI（`linux/ax.rs` 第 1、13–23 行）；macOS 用 `AXUIElement`（`macos/ax.rs` 第 11 行）。
- 维护状态：本地提交 `fdfeef1f78` 的日期是 2026-09-04。

### 6.14 OpenCode

本地仓库 `C:\project\codes\opencode`，提交 `0027387`，与上次调研相同，没有 computer use 的执行代码。代码中出现的 `computer_call` 只是解析 OpenAI Responses 接口返回的项目：`packages/llm/src/protocols/openai-responses.ts` 第 543–551 行把 `computer_use_call` 列为服务端执行的工具；`packages/core/src/github-copilot/responses/openai-responses-language-model.ts` 第 652–670 行把它记为 `providerExecuted: true` 的工具调用。
