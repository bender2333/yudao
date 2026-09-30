# M1 试用时桌面客户端的打包与安装：事实调研

- 调研日期：2026-10-01。
- 来源写法：网页写链接与读取日期；源代码写仓库、提交号或标签、文件与行号。
- OpenCode 本地仓库 `C:\project\codes\opencode` 是浅克隆，只有一个提交 `0027387`（完整提交号 `0027387dc5c59793c12dfc531abc78f825ed6868`，提交时间 2026-09-24）。第 1 节中没有写仓库名的路径都是这个仓库在这个提交下的文件；历史版本通过 GitHub API 按标签查询。
- 本文只记录事实，不包含建议。

## 1. OpenCode 桌面版

### 1.1 打包工具

- 当前的桌面版用 Electron 构建：`packages/desktop/README.md:3` 写着「The OpenCode Desktop app, built with Electron.」；依赖为 `electron` 42.3.3、`electron-builder` 26.15.2、`electron-updater` 6.8.9、`electron-store` 11.0.2，构建工具为 `electron-vite`（`packages/desktop/package.json:15-22、29-33、51-53`）。桌面版自身的版本号为 1.18.32（`packages/desktop/package.json:4`）。
- 历史情况（GitHub API `repos/anomalyco/opencode/contents/packages?ref=<标签>` 与 `releases/tags/<标签>`，读取于 2026-10-01）：
  - v1.1.1（2026-01-04 发布）：`packages/desktop` 中有 `src-tauri` 目录，是 Tauri 程序。
  - v1.3.0（2026-03-22）到 v1.14.29（2026-04-28）：仓库中同时有 `packages/desktop`（仍含 `src-tauri`）与 `packages/desktop-electron` 两个包。
  - v1.15.0（2026-05-15）起：只剩 `packages/desktop`，其中是 `electron-builder.config.ts` 与 `electron.vite.config.ts`，没有 `src-tauri`。
  - 最新发布为 v1.18.33（2026-09-28）。
- 发布流程仍然生成 Tauri updater 格式的 `latest.json`：脚本读取 electron-builder 生成的 `latest*.yml`，下载各平台安装包，用 `bunx @tauri-apps/cli signer sign` 生成签名，写成 Tauri 的 `platforms` 结构后上传到 release（`packages/desktop/scripts/finalize-latest-json.ts:113-133、148-217`）；发布任务传入 `TAURI_SIGNING_PRIVATE_KEY` 与 `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`（`.github/workflows/publish.yml:507-517`）。v1.18.33 的 release 中有这个 `latest.json`（9646 字节，下载自 https://github.com/anomalyco/opencode/releases/download/v1.18.33/latest.json ，读取于 2026-10-01）。

### 1.2 本机服务（sidecar）的启动与停止

默认方式（代码中称为 v1）：

- 服务代码随桌面程序一起打包：构建前在 `packages/opencode` 执行 `bun script/build-node.ts` 生成 Node 版服务（`packages/desktop/scripts/prebuild.ts:10`）；electron-vite 把 `virtual:opencode-server` 解析为 `../opencode/dist/node/node.js`，与主进程一起构建出 `sidecar.js`，并复制服务需要的 `.wasm` 文件（`packages/desktop/electron.vite.config.ts:6、41、64-80`）。
- 启动：主进程用 Electron 的 `utilityProcess.fork` 启动 `sidecar.js`，服务名为 `opencode server`（`packages/desktop/src/main/server.ts:19、57-69`）；子进程收到 `start` 消息后调用 `Server.listen`，跨域只允许 `oc://renderer`（`packages/desktop/src/main/sidecar.ts:51-71`）。
- 地址与口令：监听 `127.0.0.1`；端口取环境变量 `OPENCODE_PORT`，没有设置时先在 `127.0.0.1` 上绑定 0 号端口取得一个空闲端口；每次启动用 `randomUUID()` 生成口令，用户名固定为 `opencode`（`packages/desktop/src/main/index.ts:350-391`；`packages/desktop/src/main/sidecar.ts:83-89`）。
- 就绪判断：子进程发回 `ready` 消息视为启动成功，60 秒内没有消息视为失败（`packages/desktop/src/main/server.ts:20、90-142`）；之后每 100 毫秒请求一次 `/api/health` 或 `/global/health`（带 Basic 认证），主进程最多等 30 秒（`packages/desktop/src/main/server.ts:144-163、186-211`；`packages/desktop/src/main/index.ts:397-404`）。
- 停止：主进程在 `before-quit`、`will-quit` 事件以及收到 SIGINT、SIGTERM 时调用 `stopSidecars`，向子进程发送 `stop` 消息，6 秒内没有退出就调用 `child.kill()`（`packages/desktop/src/main/index.ts:167-170、224-232、246-251`；`packages/desktop/src/main/server.ts:21、165-181`；`packages/desktop/src/main/sidecar.ts:73-81`）。Windows 与 Linux 上关闭全部窗口时程序退出（`packages/desktop/src/main/index.ts:411-414`）。因此退出桌面程序时，本机服务一起停止。
- 同一时间只允许一个桌面程序实例（`app.requestSingleInstanceLock()`，`packages/desktop/src/main/index.ts:198-201`）。
- 用户数据目录设为 `%APPDATA%\<appId>`，正式版 appId 为 `ai.opencode.desktop`（`packages/desktop/src/main/index.ts:143-146`；`packages/desktop/electron-builder.config.ts:38-42`）。

第二种方式（代码中称为 v2，需要设置环境变量 `OPENCODE_SIDECAR_V2=1`，`packages/desktop/src/main/index.ts:64、333-348`）：

- 桌面程序运行随程序附带的 `opencode-cli(.exe)`：先把它复制到 `userData/cli/<版本>/`，再依次执行 `service status`、`service start`、`service get password`，取得服务地址与口令（`packages/desktop/src/main/background-cli.ts:19-78`）。
- `service start` 以 detached 方式启动 `serve --register` 后台进程；后台进程把 `{id, version, url, pid}` 写入状态目录下的 `server.json`，口令保存在同一目录的 `password` 文件中，重启以后口令不变；已有后台服务的版本与命令行程序的版本相同时直接复用，不同时先停止旧进程（先 SIGTERM，仍在运行再 SIGKILL）再启动新进程；`service status` 只在版本相同时返回地址（`packages/cli/src/services/daemon.ts:39-56、74-78、91-135、146-153、164-186`）。
- `serve` 默认监听 `127.0.0.1`，没有指定端口时从 4096 开始向上寻找空闲端口（`packages/cli/src/commands/commands.ts:43-49`；`packages/cli/src/commands/handlers/serve.ts:30-37`）。
- 这条路径没有给 `server` 变量赋值，`killSidecar` 与 `stopSidecars` 不会停止这个后台服务（`packages/desktop/src/main/index.ts:88-93、167-170、333-348`）；后台服务在桌面程序退出以后继续运行，由 `service stop` 停止（`packages/cli/src/services/daemon.ts:155-162`）。
- `opencode-cli` 只在 dev 渠道的构建中放进安装包：`files` 排除 `resources/opencode-cli*`，`extraResources` 只在 `channel === "dev"` 时加入它（`packages/desktop/electron-builder.config.ts:58-68`；`packages/desktop/scripts/prebuild.ts:11`）。

WSL 中的服务（只在 Windows 上）：

- 桌面程序通过 `wsl ... bash -se` 在指定的发行版中执行 `opencode serve --hostname 0.0.0.0 --port <随机端口>`，口令随机生成，然后连接 `http://127.0.0.1:<端口>`（`packages/desktop/src/main/wsl/sidecar.ts:17-44、60`）；退出桌面程序时 `wslServers.stopAll()` 结束这些进程（`packages/desktop/src/main/index.ts:167-170`；`packages/desktop/src/main/wsl/servers.ts:411-415`）。
- 桌面程序检查发行版中 opencode 的版本是否与桌面版版本相同（`matchesDesktop: version === expectedVersion`），并提供安装与桌面版相同版本的操作：`curl -fsSL https://opencode.ai/install | bash -s -- --version <桌面版版本>`（`packages/desktop/src/main/wsl/servers.ts:134-140、363-372、467-499`；`packages/desktop/src/main/wsl/runtime.ts:267-277`）。
- 安装 WSL 本身时，桌面程序用 `Start-Process -FilePath 'wsl.exe' -Verb RunAs` 请求管理员权限（`packages/desktop/src/main/wsl/runtime.ts:249-256`）。

### 1.3 连接远端服务

- 官方文档：桌面程序可以启动自己的本机服务（默认），也可以连接用户配置的服务地址；默认服务地址可以在界面的服务选择器中清除（`packages/web/src/content/docs/troubleshooting.mdx:116-124`）。
- 服务列表：界面保存一个服务列表（持久化键 `server.v3`），每一项是 HTTP 地址加可选的用户名与口令；输入的地址没有协议时补上 `http://`（`packages/app/src/context/server.tsx:23-28、184-195、263-304`）。连接类型有 `http`、`sidecar`（本机或 WSL）与 `ssh`，`ssh` 类型的注释为「Remote server desktop can SSH into」（`packages/app/src/context/server.tsx:181-222`）；在 `packages/desktop/src` 中按关键词 `ssh` 搜索没有结果。
- 默认服务地址由主进程保存在 electron-store 的 `opencode.settings` 文件中，键为 `defaultServerUrl`（`packages/desktop/src/main/server.ts:30-42`；`packages/desktop/src/main/store-keys.ts:1-2`；`packages/desktop/src/main/store.ts:15-26`）。
- 连接检查：客户端请求服务的 health 接口，有口令时带 Basic 认证，结果为 `{ healthy, version }`，每 10 秒检查一次（`packages/app/src/utils/server-health.ts:8、72-115`；`packages/app/src/context/server.tsx:15`）。服务设置界面显示服务报告的版本号（`packages/app/src/components/settings-v2/servers.tsx:113`）；在 `packages/app/src` 中搜索 health 与 version，没有找到把 `http` 类型服务的版本与桌面版版本作比较的代码。
- 远端服务的启动方式，文档以 WSL 为例：`opencode serve --hostname 0.0.0.0 --port 4096`，桌面程序连接 `http://localhost:4096`，不通时改用 WSL 的 IP 地址；文档要求监听 `0.0.0.0` 时设置 `OPENCODE_SERVER_PASSWORD`（`packages/web/src/content/docs/windows-wsl.mdx:45-67`）。`opencode serve` 默认监听 `127.0.0.1`、端口 0（由系统分配），没有设置口令时打印「server is unsecured」警告（`packages/opencode/src/cli/network.ts:6-33`；`packages/opencode/src/cli/cmd/serve.ts:13-22`）。

### 1.4 更新

- 更新程序为 electron-updater，更新源为 GitHub release：正式版 `anomalyco/opencode`，测试版 `anomalyco/opencode-beta`，`channel: "latest"`（`packages/desktop/electron-builder.config.ts:141、152`）。
- 这个更新源是公开仓库：v1.18.33 的 `latest.yml` 与 `latest.json` 用不带登录信息的 `curl -sL` 可以直接下载（2026-10-01）。Yudao 的仓库是私有仓库，未登录访问返回 404（见 7.2）。
- 设置：`channel = "latest"`、`allowPrerelease = false`、`allowDowngrade = true`、`autoDownload = false`、`autoInstallOnAppQuit = false`（`packages/desktop/src/main/updater.ts:13-27`）；只在已打包且渠道不为 dev 时启用（`packages/desktop/src/main/constants.ts:7`）。
- 流程：启动时检查一次，之后每 10 分钟检查一次（`packages/desktop/src/main/index.ts:315-318`）；检查到的版本号与当前版本不同时下载，下载完成后弹窗让用户选择「重启」或「稍后」；选择重启时先停止本机服务，再调用 `quitAndInstall`（`packages/desktop/src/main/updater-controller.ts:38-64、79-93`；`packages/desktop/src/main/updater.ts:35-47、63-94`）。检查到的版本号等于当前版本时视为已是最新（`packages/desktop/src/main/updater-controller.ts:47`）。
- 更新清单：Windows 的 x64 与 arm64 分别构建出 `latest.yml`，发布前合并成一个文件上传（`packages/desktop/scripts/finalize-latest-yml.ts:81-91、113-122`）。v1.18.33 的 `latest.yml` 共 384 字节，字段为 `version`、`files`（每项有 `url`、`sha512`、`size`）与 `releaseDate`（下载自 https://github.com/anomalyco/opencode/releases/download/v1.18.33/latest.yml ，读取于 2026-10-01）：

  ```yaml
  version: 1.18.33
  files:
    - url: opencode-desktop-win-arm64.exe
      sha512: op9fVk+WBGP/41a0nMEktvS2RUIht3PrnGfXEQ8rP0QHsObr3zMFmKQjxoDnxqwE7rmUggrxnBrsczpm0wBeFA==
      size: 118763080
    - url: opencode-desktop-win-x64.exe
      sha512: hM7Yyt2XswOUJTNAuL6wq86cGuaXNIXTJUQ4uCAaF/aPKNEDkQ2X/nPZDZlDoooHu+jj08KTtnPpJoPFLOImnw==
      size: 126242120
  releaseDate: '2026-09-28T04:13:18.511Z'
  ```

- 签名：
  - Windows：只在 GitHub Actions 中签名（`script/sign-windows.ps1:12-15`；`packages/desktop/electron-builder.config.ts:21-30`），用 Azure Artifact Signing（脚本输出文字为「Azure Artifact Signing is not configured」，环境变量沿用 `AZURE_TRUSTED_SIGNING_*` 名称），PowerShell 模块 `TrustedSigning` 0.5.8，文件摘要与时间戳摘要为 SHA256，时间戳服务器 `http://timestamp.acs.microsoft.com`（`script/sign-windows.ps1:17-70`）。electron-builder 通过 `win.signtoolOptions.sign` 调用这个脚本（`packages/desktop/electron-builder.config.ts:92-96`）。命令行程序用 `azure/artifact-signing-action` v1.2.0 签名（`.github/workflows/publish.yml:148-173`）。打包以后用 `Get-AuthenticodeSignature` 检查每个 `.exe`，状态必须为 `Valid`（`.github/workflows/publish.yml:377-391`）。
  - Windows 上更新时不校验新安装包的签名：`verifyUpdateCodeSignature: false`（`packages/desktop/electron-builder.config.ts:98`）。
  - macOS：hardened runtime、公证（notarize），dmg 也签名（`packages/desktop/electron-builder.config.ts:75-87`）；签名证书与 Apple API 密钥在 CI 中导入（`.github/workflows/publish.yml:261-270、343-346`）。

### 1.5 各平台的安装包形式与构建

- Windows：NSIS 安装包，`oneClick: true`、`perMachine: false`（按用户安装），x64 与 arm64 各一个，文件名格式 `opencode-desktop-${os}-${arch}.${ext}`（`packages/desktop/electron-builder.config.ts:45、92-105`）。
- macOS：dmg 与 zip（`packages/desktop/electron-builder.config.ts:83`）；发布流程另外打包 `.app.tar.gz`，供 Tauri 格式的 `latest.json` 使用（`.github/workflows/publish.yml:356-375`；`packages/desktop/scripts/finalize-latest-json.ts:163-164`）。
- Linux：AppImage、deb、rpm（`packages/desktop/electron-builder.config.ts:117`）。
- v1.18.33 release 中桌面版文件的大小（GitHub API `repos/anomalyco/opencode/releases/tags/v1.18.33`，读取于 2026-10-01）：

  | 文件 | 字节数 | 约合 |
  |---|---:|---:|
  | opencode-desktop-win-x64.exe | 126,242,120 | 120.4 MiB |
  | opencode-desktop-win-x64.exe.blockmap | 133,106 | 130 KiB |
  | opencode-desktop-win-arm64.exe | 118,763,080 | 113.3 MiB |
  | opencode-desktop-mac-arm64.dmg | 151,078,766 | 144.1 MiB |
  | opencode-desktop-mac-x64.dmg | 155,950,365 | 148.7 MiB |
  | opencode-desktop-mac-arm64.zip | 149,679,345 | 142.7 MiB |
  | opencode-desktop-linux-x86_64.AppImage | 159,115,682 | 151.7 MiB |
  | opencode-desktop-linux-amd64.deb | 123,113,816 | 117.4 MiB |
  | opencode-desktop-linux-x86_64.rpm | 106,478,045 | 101.5 MiB |

- 构建：GitHub Actions 的矩阵中，Windows x64 在 `blacksmith-4vcpu-windows-2025` 上构建，Windows arm64 在 GitHub 托管的 `windows-2025` 上构建（注释说明 blacksmith 缺少 ARM64 MSVC 交叉编译工具），Node.js 24，命令为 `npx electron-builder --win --publish never --config electron-builder.config.ts`；构建结果最后用 `gh release upload` 上传到 release（`.github/workflows/publish.yml:232-257、284-286、335-351、494-505`）。

## 2. Electron 打包（2026 年的现状）

来源简写（第 2、3 节通用；electron-builder 仓库的路径省略 `packages/` 前缀）：

- EB：electron-userland/electron-builder@5cdf017875。标签 electron-builder@26.17.0 与 electron-updater@6.8.10 都指向这个提交（2026-09-26）。
- EB-27a9：electron-userland/electron-builder@4719d58ab6，标签 electron-builder@27.0.0-alpha.9。
- EB-master：electron-userland/electron-builder@ccfe0937，master 分支（2026-09-30），v27 还在开发中。
- EL：electron/electron@bc8e748ec8，main 分支（2026-09-30）。
- FG：electron/forge@48f38bb11d，main 分支（2026-09-29，v8.0.1）。
- SQ：Squirrel/Squirrel.Windows@51f5e2cb01，develop 分支。
- EWI：electron/windows-installer@2d65bcd746。
- UEA：electron/update-electron-app@940508fcec。
- npm：registry.npmjs.org 上对应包的元数据，读取于 2026-10-01。
- GH：GitHub REST API，读取于 2026-10-01。

### 2.1 当前版本与维护情况

- **electron-builder**（npm）：
  - npm `latest` 标签是 26.15.3（2026-06-09）。
  - 更新的 26.x 版本放在 `v26` 标签下，最新是 26.17.0（2026-09-26）。
  - `next` 标签是 27.0.0-alpha.9（2026-09-26）。
- **electron-updater**（npm）：`latest` 是 6.8.9（2026-06-05），`v26` 是 6.8.10（2026-09-26），`next` 是 7.0.0-alpha.8。
- **@electron-forge/cli**：`latest` 是 8.0.1（2026-09-29），8.0.0 在同一天发布。7.x 的最后一个版本是 7.11.2（2026-05-20）。（npm；GH repos/electron/forge/releases）
- **electron**：`latest` 是 44.5.1（2026-09-30），`alpha` 是 45.0.0-alpha.13。（npm）
- **engines 字段**（npm）：
  - electron-builder 26.x 写的是 `node >=14.0.0`。
  - electron-builder 27.0.0-alpha.9 与 electron-updater 7.0.0-alpha.8 写的是 `node >=22.12.0`。
  - @electron-forge/cli 8.0.1 写的是 `node >= 22.13.0`，7.11.2 写的是 `>= 16.4.0`。
  - electron 44.5.1 写的是 `node >= 22.12.0`。
  - 这台电脑上的 Node.js v24.14.0 高于以上所有下限。
- **electron-builder 仓库的活动情况**：
  - 最近一次推送是 2026-09-30，有 `release/v26`、`release/v27` 两条发布分支。
  - 26.x 在 2026-05-30 到 2026-09-26 之间发布了 15 个版本。（GH；npm）
  - 26.16.0–26.17.0 与 electron-updater 6.8.10 的 CHANGELOG 中，多数条目的署名是 GitHub 应用 `@claude`。（EB app-builder-lib/CHANGELOG.md、electron-updater/CHANGELOG.md）
- **Electron Forge 仓库的活动情况**：最近一次推送是 2026-09-29。v8.0.1 的发布说明列出的变更（GH releases/tags/v8.0.1）：
  - 改用 Node 22 与 ESM（#4059）；
  - `publish` 命令改名为 `release`（#4305）；
  - 文档从 electron-forge-docs 迁入主仓库（#4345）；
  - AppX maker 改成 MSIX maker 的一层包装（#4392）。
- **Squirrel.Windows 上游**：最近一次提交是 2024-01-11，最近一次发布是 2.0.1（2020-09-27）。（GH）
- **electron-winstaller**（Forge 的 Squirrel maker 用它）：最新版本 5.4.4（2026-07-01），仓库的 vendor 目录自带 Squirrel.exe、Setup.exe 等文件。（npm；GH git tree）

### 2.2 Electron 官方文档的推荐

- 「Application Packaging」一文写明推荐使用 Electron Forge。（EL docs/tutorial/application-distribution.md:11-16）
- 「Distributing Apps With Electron Forge」一文对 electron-builder 的说法（EL docs/tutorial/forge-overview.md:7-23）：
  - 它是第三方工具，由社区成员维护，没有 Electron 项目的官方支持；
  - 它用自己的实现替换了 Electron 维护者使用的模块，例如 auto-updater。
- 官方教程第 5 部分用 Forge 打包，并说明 Forge 组合了 @electron/packager、@electron/osx-sign、electron-winstaller 等工具。（EL docs/tutorial/tutorial-5-packaging.md:29-40）
- electron-builder 自己提供 4 个 Forge maker，其中有 electron-forge-maker-nsis。文档写明，通过这些 maker 不能使用 electron-builder 的发布、自动更新和代码签名。（EB website/docs/features/electron-forge.md:7-8,119-127）

### 2.3 electron-builder 的 NSIS 按用户安装

- NSIS 是 electron-builder 在 Windows 上的默认目标。（EB website/docs/nsis.md:5）
- **安装方式的选项**（EB app-builder-lib/src/targets/nsis/nsisOptions.ts:86-121）：
  - `oneClick` 默认 true，`perMachine` 默认 false。
  - `oneClick` 为 true 时，由 `perMachine` 决定是否为所有用户安装。
  - `oneClick` 和 `perMachine` 都为 false 时，安装程序会显示「当前用户或所有用户」的选择页。
  - `allowElevation`（默认 true）和 `allowToChangeInstallationDirectory`（默认 false）只对 assisted 安装程序有效。
  - 要让用户在同一个安装程序里选择按用户或按机器安装，需要设置 `oneClick: false`。（EB website/docs/nsis.md:148-165）
- **管理员权限**：
  - 只有设置了 `perMachine: true`，生成的脚本才会定义 `INSTALL_MODE_PER_ALL_USERS`。（EB app-builder-lib/src/targets/nsis/NsisTarget.ts:538-548）
  - 没有定义这个宏时，安装脚本写的是 `RequestExecutionLevel user`；定义了它时，安装程序写的是 `RequestExecutionLevel admin`。（EB templates/nsis/installer.nsi:20-28；核对过该提交的这几行原文）
- **按用户安装时的安装目录**，按下面的顺序确定（EB templates/nsis/multiUser.nsh:21-56；核对过该提交的这几行原文）：
  1. 读取 HKCU 注册表里上次安装的 `InstallLocation`；
  2. 没有记录时，取 known folder `FOLDERID_UserProgramFiles`；
  3. 取不到时，用 `$LocalAppData\Programs`；
  4. 在上面的目录后拼上程序目录名；
  5. 命令行参数 `/D=` 可以覆盖以上结果。
  - `FOLDERID_UserProgramFiles` 是按用户的 known folder，默认路径是 `%LOCALAPPDATA%\Programs`。（MicrosoftDocs/win32@e103fa4e88 desktop-src/shell/knownfolderid.md:4548-4567）
- **程序目录名**（EB NsisTarget.ts:228；targetUtil.ts:39-41）：
  - 一键安装且按用户安装时，使用 sanitizedName，它由 package.json 的 `name` 得出。
  - assisted 安装或 perMachine 时，如果 productFilename 只含字母、数字和 `-_+ .`，就使用 productFilename。
- **为所有用户安装**：默认目录是 `$PROGRAMFILES` 或 `$PROGRAMFILES64` 下的程序目录，注册信息写在 HKLM。（EB multiUser.nsh:62-99）
- **安装程序的副本**：安装时，NSIS 安装程序会把自己复制到 `%LOCALAPPDATA%\<小写 sanitizedName>-updater\installer.exe`，按机器安装时也写到当前用户的这个目录。这个副本供以后的差分更新使用。（EB templates/nsis/include/installer.nsh:88-93；NsisTarget.ts:612-616；appInfo.ts:159-161）
- **更新时提权**：只有 perMachine 时，更新信息才会标记 `isAdminRightsRequired`，更新程序会通过 elevate.exe 运行安装程序。（EB NsisTarget.ts:388-390；electron-updater/src/NsisUpdater.ts:153-161）
- **多架构**：
  - 同时构建多个架构时，默认只得到一个包含全部架构的安装程序。
  - `nsis-web` 目标生成一个小的下载器，安装时按系统架构下载对应的包。（EB website/docs/nsis.md:13-27）

### 2.4 Electron Forge 的 Windows 安装包（对照）

- **Squirrel.Windows maker 的产物**：生成 `{appName} Setup.exe`、`{appName}-full.nupkg`、`RELEASES` 三个文件。文档称这种安装方式不提示、不需要管理员权限。（FG docs/config/makers/squirrel.windows.md:7-15）
- **Squirrel.Windows 的安装位置**（SQ docs/using/install-process.md:16-37,54-60）：
  - 装在 `%LocalAppData%\<应用名>`，每个版本放在一个 `app-<版本>` 子目录里；
  - 下载的 nupkg 放在 `packages` 子目录；
  - 快捷方式指向 `Update.exe --processStart <exe>`。
- **Squirrel.Windows 的运行要求**：
  - Setup.exe 会确认系统已安装 .NET Framework 4.5，没有时先下载安装。（SQ install-process.md:14,45）
  - Squirrel 在安装、更新、卸载时会带着特殊参数再启动一次应用，应用需要尽早处理这些参数，并在大约 15 秒内退出。（EWI README.md:95-108；FG squirrel.windows.md:88-99）
- **electron-builder 自己的 Squirrel.Windows 目标**：文档写明「仍在维护但已不推荐，请使用 nsis」。（EB website/docs/squirrel-windows.md:7）
- **Forge 的其他 Windows maker**：
  - WiX MSI maker 需要安装 WiX Toolset v3。Forge 文档写明一般推荐 Squirrel.Windows 目标，MSI 用于满足企业内部的分发规定。（FG docs/config/makers/wix-msi.md:9-19）
  - MSIX maker 从 v7.10 开始提供，标注为实验功能，需要 Windows 10/11 和 Windows SDK。（FG docs/config/makers/msix.md:9-19）
- **electron-winstaller 的构建要求**（EWI README.md:16-31）：
  - 可以在 x64 和 arm64 的 Windows 上构建；在 macOS/Linux 上构建需要 Wine 和 Mono。
  - 它是 ESM 包，需要 Node.js 22.12 以上。
  - Electron 44 起不再提供 32 位 Windows 版本。

### 2.5 安装包大小

下表中的程序在 GitHub 的发布里都有 latest.yml 和 Windows 安装程序，这是 electron-builder 的产物格式。数据来自 GH releases，读取于 2026-10-01。

| 程序 | 版本（发布日期） | 文件 | 字节数 | MiB | 说明 |
|---|---|---|---:|---:|---|
| Rocket.Chat Desktop | 4.17.3（2026-09-26） | rocketchat-4.17.3-win-x64.exe | 116,367,800 | 111.0 | x64 |
| Rocket.Chat Desktop | 同上 | rocketchat-4.17.3-win.exe | 332,098,568 | 316.7 | 文件名不带架构；同一次发布另有 x64、arm64、ia32 的单架构安装程序 |
| Heroic Games Launcher | 2.22.3（2026-09-16） | Heroic-2.22.3-Setup-x64.exe | 154,948,712 | 147.8 | x64 |
| Tabby | 1.0.237（2026-09-25） | tabby-1.0.237-setup-x64.exe | 169,734,624 | 161.9 | x64 |
| Mattermost Desktop | 6.0.4（2026-01-20） | mattermost-desktop-setup-6.0.4-win.exe | 203,092,808 | 193.7 | 文件名不带架构 |
| Beekeeper Studio | 6.1.4（2026-09-29） | Beekeeper-Studio-Setup-6.1.4.exe | 254,999,288 | 243.2 | 文件名不带架构 |
| Cherry Studio | 2.1.3（2026-09-24） | Cherry-Studio-2.1.3-win-x64-setup.exe | 318,827,702 | 304.1 | x64；发布里没有 .exe.blockmap |
| Joplin | 3.7.21（2026-09-25） | Joplin-Setup-3.7.21.exe | 361,008,040 | 344.3 | 文件名不带架构 |
| Bitwarden | desktop-v2026.9.0（2026-09-17） | Bitwarden-Installer-2026.9.0.exe | 734,240 | 0.7 | nsis-web 下载器；latest.yml 中的 x64 包 bitwarden-2026.9.0-x64.nsis.7z 为 128,651,178 字节（122.7 MiB） |
| GitHub Desktop（Squirrel.Windows，对照） | 3.6.6（2026-09-21） | GitHubDesktopSetup-x64.exe | 307,506,464 | 293.3 | 同一版本的 delta nupkg 为 1,525,093 字节（1.5 MiB） |

- Electron 44.5.1 的运行时压缩包 electron-v44.5.1-win32-x64.zip 是 157,998,329 字节（150.7 MiB）。（GH releases/tags/v44.5.1）
- electron-builder 文档说，把多个架构合进一个安装程序时，由于用了 LZMA 压缩，体积差别可以接受；文档没有给出具体数字。（EB website/docs/nsis.md:20）
- 第 1 节列出的 OpenCode 桌面版 Windows x64 安装包为 126,242,120 字节（120.4 MiB），同样使用 electron-builder 的 NSIS 目标。

### 2.6 在 Windows 上本机构建的要求

- **NSIS 编译器**：构建需要的 makensis 由 electron-builder 自己下载。默认从 electron-builder-binaries 的 nsis-3.0.4.1 发布取得，并校验 sha256。（EB app-builder-lib/src/toolsets/windows.ts:161-164,182-196）
- **修改 exe 资源**：从 26.11.0（2026-05-19）起，electron-builder 用 npm 包 `resedit` 修改 exe 的图标和版本信息，不再使用 app-builder-bin 调用的 rcedit.exe。（EB app-builder-lib/CHANGELOG.md 26.11.0 节，PR #9717；src/util/resEdit.ts；src/winPackager.ts:27）
- **winCodeSign 工具包**：在 26.17.0 的源码中，旧的 winCodeSign-2.6.0 工具包只在两种情况下下载：配置了证书并真正执行签名时，以及构建 AppX 目标时。（EB src/codeSign/windowsSignToolManager.ts:196-224,437-446；src/targets/AppxTarget.ts:78；src/toolsets/windows.ts:12-18,93-105）
- **issue #8149（符号链接错误）**：
  - 问题：普通用户在 Windows 上构建时，解压 winCodeSign-2.6.0.7z 里给 macOS 用的符号链接会失败，报错「A required privilege is not held by the client」。
  - 评论中给出的临时解决办法：以管理员身份运行；打开 Windows 开发者模式；或者预先把工具包解压到 `%LOCALAPPDATA%\electron-builder\Cache\winCodeSign\winCodeSign-2.6.0`。
  - 这个 issue 于 2026-02-09 关闭；之后到 2026-06 仍有评论报告同样的错误，其中 2026-02-26 的一条使用的是 26.8.1。（GH issue #8149 及评论）
- **原生依赖**：应用有原生依赖时，只能在目标平台上编译，除非这个依赖提供 prebuild。（EB website/docs/features/multi-platform-build.md:3-8）
- **Forge 各 maker 在 Windows 上的要求**（FG squirrel.windows.md:17-19；wix-msi.md:13-19；msix.md:17-19）：
  - Squirrel.Windows 可以直接在 Windows 上构建，在 Linux 上构建需要 mono 和 wine；
  - WiX MSI 需要 WiX Toolset v3；
  - MSIX 需要 Windows SDK。

### 2.7 第 2 节未能核实的事项

- 26.17.0 在 Windows 11 普通用户、没开开发者模式的情况下，构建不签名的 NSIS 安装包是否还会遇到符号链接错误：只看了源代码和 issue #8149，按规则没有在本机运行构建。
- 程序安装后实际占用的磁盘空间：GitHub 只提供安装包大小，没有实际安装去测。
- Electron 官方文档里关于安装包体积的数字：查了 EL 的 docs/faq.md 和 docs/tutorial 下打包、分发相关的文档，没有找到。

## 3. 自动更新

### 3.1 generic 提供方与服务器上的文件

- **支持的更新源**：electron-updater 支持 GitHub Releases、S3、DigitalOcean Spaces、Keygen，以及普通的 HTTP(S) 服务器（generic）。在 Windows 上只有 NSIS 目标支持自动更新，Squirrel.Windows 不支持。（EB website/docs/features/auto-update.md:19-42）
- **上传**：使用 generic 时，electron-builder 不上传文件，需要自己把产物和元数据放到服务器上。（EB website/docs/publish.md:5；src/publish/PublishManager.ts:158-161）
- **app-update.yml**：
  - 构建时，electron-builder 把 publish 配置写进 resources 目录下的 app-update.yml，其中含 updaterCacheDirName，在 Windows 上可能还含 publisherName。（EB PublishManager.ts:118-134,259-283）
  - 运行时，electron-updater 从 `process.resourcesPath\app-update.yml` 读取。（EB electron-updater/src/ElectronAppAdapter.ts:23-24）
- **请求的地址**：
  - generic 提供方请求 `<url>/<channel>.yml`。Windows 上默认的文件名是 `latest.yml`，不带平台后缀。
  - 请求没有 Authorization 头时，会在 channel 文件地址后加一个 `noCache` 查询参数。
  - （EB providers/GenericProvider.ts:18-28，核对过该提交的这几行原文；providers/Provider.ts:44-61；util.ts:13-29；AppUpdater.ts:667-682）
- **安装程序和 blockmap 的地址**（EB Provider.ts:28-38,152-173；AppUpdater.ts:119-129；nsisOptions.ts:200-203）：
  - `files[].url` 相对于 url 解析。
  - 新 blockmap 的地址是 `<安装程序地址>.blockmap`。
  - 旧 blockmap 的地址把新地址里的版本号换成当前版本号得到，也可以用 `previousBlockmapBaseUrlOverride` 指定。
  - 默认的安装程序文件名是 `${productName} Setup ${version}.exe`。
- **构建产物**：构建 NSIS 时会生成 `<安装程序>.blockmap`（gzip 压缩）和 latest.yml。`differentialPackage` 默认为 true。（EB src/targets/differentialUpdateInfoBuilder.ts:70-83；NsisTarget.ts:98,384-386）
- **运行时更换地址**：
  - `setFeedURL(options)` 在运行时替换 app-update.yml 中的配置；参数是字符串时，当作 generic 提供方的 url。（EB AppUpdater.ts:306-323）
  - 文档另外写了一句「Do not call setFeedURL」，意思是默认使用构建时生成的 app-update.yml。（EB website/docs/features/auto-update.md:76-78）
- **请求头**：可以通过 `requestHeaders` 或 `addAuthHeader()` 给更新请求加请求头。文档的示例直接构造 `new NsisUpdater({ provider: 'generic', url })`。（EB AppUpdater.ts:166-178；auto-update.md:100-123）
- **只在打包后检查**：只有打包后的程序（`app.isPackaged`）才检查更新。开发时要设置 `forceDevUpdateConfig`，并准备 dev-app-update.yml。（EB AppUpdater.ts:110-117,358-365；auto-update.md:135-139）
- **私有 GitHub 仓库作为更新源**（EB auto-update.md:187-199）：
  - 需要在用户机器上设置 GH_TOKEN；
  - 文档说明这种方式只用于非常特殊的情况；
  - GitHub API 每个用户每小时限 5000 次请求，一次更新检查最多用 3 次。

### 3.2 latest.yml 的字段与示例

- **UpdateInfo 的字段**（EB builder-util-runtime/src/updateInfo.ts:13-92）：
  - `version`；
  - `files`：每项有 `url`、`sha512`，可选 `size`、`blockMapSize`、`isAdminRightsRequired`；
  - 已废弃的顶层 `path` 和 `sha512`；
  - `releaseName`、`releaseNotes`、`releaseDate`、`stagingPercentage`、`minimumSystemVersion`；
  - Windows 上另有 `packages`（nsis-web 按架构列出的包）和旧的 `sha2`。
- **构建时写入的内容**（EB src/publish/updateInfoBuilder.ts:169-191,193-241）：
  - `files[0].url` 是安装程序的文件名；
  - `sha512` 是文件 SHA-512 的 base64 值；
  - `releaseDate` 是写文件时的 ISO 时间；
  - 同一个 channel 文件会合并同一次构建的多个安装程序。
- **实例**：Heroic Games Launcher 2.22.3 发布中的 latest.yml（读取于 2026-10-01）：

  ```yaml
  version: 2.22.3
  files:
    - url: Heroic-2.22.3-Setup-x64.exe
      sha512: tRCsv9Ich7/ozCEHddT4TWdhpClPQasfz6GSuhTzUwC42DJezR9HfRwBXMjlp8xbRKnGkSZTgeQbMr0x8gtebg==
      size: 154948712
    - url: Heroic-2.22.3-Setup-arm64.exe
      sha512: ZhiFWYokKKxmrmweoFYEGmK0wccKLR0sScQMY0bUaDSBtHctr1Pm32jHkC5I2+9QsGxPfGX9BJqmerCLl+j0UA==
      size: 153885880
  path: Heroic-2.22.3-Setup-x64.exe
  sha512: tRCsv9Ich7/ozCEHddT4TWdhpClPQasfz6GSuhTzUwC42DJezR9HfRwBXMjlp8xbRKnGkSZTgeQbMr0x8gtebg==
  releaseDate: '2026-09-16T15:14:28.818Z'
  ```

- **分批推送**：可以手工在 latest.yml 里写 `stagingPercentage`。分批推送的版本出了问题时，文档要求发布一个版本号更高的版本来替换。（EB auto-update.md:165-181）
- **缺少校验值**：文件项既没有 sha512 也没有 sha2 时，更新程序报 ERR_UPDATER_NO_CHECKSUM。（EB Provider.ts:152-162）

### 3.3 下载后的校验

- **完整下载**：下载时用 DigestTransform 计算 SHA-512，与 `files[].sha512` 比较，不一致时报 ERR_CHECKSUM_MISMATCH。文件先写成临时文件，校验通过后才改名。（EB builder-util-runtime/src/httpExecutor.ts:485-536,575-580；AppUpdater.ts:709-716,786-814）
- **已缓存的更新文件**：使用前重新计算 SHA-512，再与 latest.yml 比较。（EB DownloadedUpdateHelper.ts:132-148）
- **缓存目录**：`%LOCALAPPDATA%\<小写名称>-updater`，下载中的文件放在其中的 `pending` 子目录。（EB AppAdapter.ts:34-46；DownloadedUpdateHelper.ts:34-36；appInfo.ts:159-161）
- **签名校验**：Windows 上下载完成后还有一步 Authenticode 签名校验，见 3.5。（EB NsisUpdater.ts:73-81）

### 3.4 blockmap 与差分下载

- **blockmap 的格式**（版本 "2"）（EB src/targets/blockmap/blockmap.ts:28-33,64-81,153,169）：
  - 用 Rabin 算法按内容切块，最小 8 KiB、平均 16 KiB、最大 32 KiB；
  - 每一块记录 BLAKE2b 校验值（18 字节，base64）和长度；
  - 整个 blockmap 用 gzip 压缩，同时计算整个文件的 SHA-512。
- **客户端的差分下载过程**：
  1. 下载新旧两个 blockmap，旧的优先使用本地缓存的 current.blockmap；
  2. 生成 COPY/DOWNLOAD 操作计划：没变的块从本地旧安装程序复制，变化的块用 HTTP Range 请求下载；
  3. 本地的旧安装程序就是安装时复制到缓存目录的 installer.exe。
  - （EB AppUpdater.ts:819-900；NsisUpdater.ts:65-71；differentialDownloader/downloadPlanBuilder.ts:4-7,56-74；differentialDownloader/DifferentialDownloader.ts:223-224；builder-util-runtime/src/index.ts:50；templates/nsis/include/installer.nsh:88-93）
- **结果校验与失败时的处理**：差分下载的结果同样用 SHA-512 校验；过程中出现任何错误，都会退回完整下载。（EB DifferentialDownloader.ts:154-157；AppUpdater.ts:901-915）
- **对服务器 Range 支持的要求**（EB multipleRangeDownloader.ts:144-156；providerFactory.ts:23-25,70-76；builder-util-runtime/src/publishOptions.ts:232-235）：
  - 响应既不是 206、又没有 Accept-Ranges 头（或值为 none）时报错，然后退回完整下载；
  - 默认一次请求多个区间（multipart/byteranges）；
  - url 含 s3.amazonaws.com，或设置了 `useMultipleRangeRequest: false` 时，改为逐个区间请求。
- **6.8.10 的修复**：修复了多区间差分下载在实际服务器上的三个问题，这三个问题以前会导致退回完整下载（EB electron-updater/CHANGELOG.md 6.8.10 节，PR #10219）：
  - 只识别 CRLF 换行；
  - 头部结束符跨数据块时找不到；
  - 看门狗计时器没有解除。
- **26.17.0 新增 `nsis.differentialPackage: "store-asar"`**（EB nsisOptions.ts:211-227；CHANGELOG 26.17.0 节）：
  - 把 app.asar 不压缩地放进包里；
  - 文档给出的测量：约 32 MB 的 asar，改一行代码时差分下载量是 0.2%；
  - 代价是安装程序变大。
- **Yudao 当前锁定的服务器依赖**：Starlette 1.7.0。它的 FileResponse 默认返回 `accept-ranges: bytes`，支持单个区间和多个区间（multipart/byteranges）。（C:\project\yudao\uv.lock:836-837；encode/starlette@2269e9a08c（标签 1.7.0）starlette/responses.py:321,407-439）
- **blockmap 的大小示例**（GH releases，读取于 2026-10-01）：
  - Heroic 2.22.3：x64 安装程序 154,948,712 字节，blockmap 163,143 字节；
  - Rocket.Chat 4.17.3：x64 安装程序 116,367,800 字节，blockmap 122,316 字节。

### 3.5 没有签名时的更新

- **publisherName 什么时候写入 app-update.yml**：只有能得到发布者名称时才写入（EB PublishManager.ts:275-281；winPackager.ts:48-49；windowsSignToolManager.ts:70-80；winOptions.ts:39-45,136-140）：
  - `win.verifyUpdateCodeSignature` 不为 false（默认 true）；
  - 并且配置了 publisherName，或者配置了签名证书（这时取证书的 CN）；
  - 既没有证书也没有 publisherName 时，app-update.yml 里就没有 publisherName。
- **没有 publisherName 时**：NsisUpdater 下载后读取 app-update.yml 的 publisherName；它为空或者找不到 app-update.yml 时，直接通过校验，然后安装。（EB NsisUpdater.ts:73-81,109-124，核对过该提交的这几行原文）
- **有 publisherName 时**，默认用 PowerShell 的 Get-AuthenticodeSignature 检查（EB windowsExecutableCodeSignatureVerifier.ts:25-100,119-143）：
  - 签名状态必须是 Valid（0）；
  - 证书主题要与 publisherName 匹配：给出完整 DN 时比较所有字段，只给 CN 时只比较 CN，并给出警告；
  - 不通过时报 ERR_UPDATER_INVALID_SIGNATURE，并删除临时文件；
  - PowerShell 过旧、无法执行时，跳过这项校验。
- **自定义校验函数**：可以用 `verifyUpdateCodeSignature` 替换默认实现，函数签名是 `(publisherName: string[], path: string) => Promise<string | null>`，返回 null 表示通过。（EB NsisUpdater.ts:26-41；website/docs/win.md:29-69）
- **v27 的变化**：迁移文档写明，app-update.yml 没有 publisherName 时签名校验会被静默跳过；v27 会给出警告，v28 将改为拒绝更新。（EB-master website/docs/migration/v27-breaking-changes.md:864-870）
- 第 1 节列出的 OpenCode 桌面版在配置中写了 `verifyUpdateCodeSignature: false`（`packages/desktop/electron-builder.config.ts:98`）。

### 3.6 指定版本、降级与 channel

- **版本比较逻辑**（6.8.10，用 semver 比较）（EB AppUpdater.ts:430-478，核对过该提交的这几行原文）：
  - latest.yml 的版本与当前版本相等时，不更新；
  - 更高时，更新；
  - 更低时，只有 `allowDowngrade` 为 true 才更新；
  - 另外还检查 `minimumSystemVersion` 和 `stagingPercentage`。
- **allowDowngrade**：默认 false。代码注释写着「只在 channel 不同时考虑」，但 isUpdateAvailable 的代码并没有检查 channel。（EB AppUpdater.ts:84-91,455-461）
- **channel**：设置 `autoUpdater.channel` 会同时把 `allowDowngrade` 设为 true。generic 提供方按 channel 决定请求的文件名 `<channel>.yml`。（EB AppUpdater.ts:147-164；GenericProvider.ts:18-24）
- **allowPrerelease**：只对 GitHub 提供方有效；当前版本号带预发布标记时，它默认为 true。（EB AppUpdater.ts:71-76,290）
- **只读一个版本**：generic 提供方的 `getLatestVersion()` 只请求 channel 文件，并解析其中的一个 UpdateInfo。（EB GenericProvider.ts:23-47）
- **能否跟随控制主机上的版本**：由上面的比较逻辑可以得出，`allowDowngrade` 为 true 时，只要服务器 latest.yml 的版本与当前版本不同，并且满足 minimumSystemVersion 和 stagingPercentage，客户端就会下载并安装 latest.yml 写的那个版本。（EB AppUpdater.ts:430-462）
- **channel 文件的生成**（EB website/docs/tutorials/release-using-channels.md；updateInfoBuilder.ts:36-63）：
  - 版本号带 `-beta` 或 `-alpha` 时，生成对应的 channel 文件；
  - `generateUpdatesFilesForAllChannels` 为 true 时，latest 版本会同时写 alpha 和 beta 文件，文档说明这时 allowDowngrade 自动为 true。
- **NSIS 模板中的版本检查**：在 26.17.0 的 templates/nsis 目录下搜索 VersionCompare、downgrade 等关键字，没有找到比较新旧版本号、阻止安装旧版本的代码。（EB app-builder-lib/templates/nsis/）

### 3.7 安装更新的过程

- **默认行为**（EB AppUpdater.ts:53-69；BaseUpdater.ts:79-105）：
  - `autoDownload` 默认 true，发现更新就下载；
  - `autoInstallOnAppQuit` 默认 true，程序以退出码 0 退出时静默安装。
- **quitAndInstall(isSilent, isForceRunAfter)**：启动安装程序，然后退出程序。安装程序的参数（EB BaseUpdater.ts:15-28；NsisUpdater.ts:126-179）：
  - 总是带 `--updated`；
  - 静默安装时加 `/S`；
  - 可以加 `--force-run`；
  - 设置了 installDirectory 时加 `/D=`。
- **启动安装程序失败时**：错误是 EACCES 或 UNKNOWN 时，改用 elevate.exe 启动；错误是 ENOENT 时，用 shell 打开安装程序。

### 3.8 v27（开发中）对更新的改动

- **Ed25519 签名的更新清单（27.0.0-alpha.9 起）**（EB-27a9 website/docs/features/signed-update-manifests.md:7-14；electron-updater 7.0.0-alpha.8 CHANGELOG，PR #9877）：
  - 构建时用私钥给 latest*.yml 签名；
  - 公钥作为 `updateManifestPublicKey` 写入 app-update.yml；
  - electron-updater 在下载之前验证签名；
  - alpha.9 的文档写明这是可选功能。
- **PR #10255（2026-09-29 合并）把签名改为默认要求**（GH PR #10255；EB-master v27-breaking-changes.md:930-961）：
  - 带发布策略（--publish）并且会写更新元数据（NSIS 等）的构建，如果找不到签名私钥，构建失败；
  - 没有发布策略的本地构建只给出警告；
  - `updateManifest: false` 是唯一的关闭方式；
  - 这一变化会写进 27.0.0 正式版的说明。
- **密钥与签名范围**（EB-master website/docs/features/signed-update-manifests.md:9-55,141-163）：
  - 密钥对由 `electron-builder create-update-key` 在本地生成；
  - 签名使用 Node 内置的 crypto，不需要其他依赖或外部工具；
  - 签名覆盖 version、stagingPercentage、minimumSystemVersion，以及 files 的 url、sha512、size 等字段；
  - releaseNotes 这类说明字段不在签名范围内。
- **验证失败的处理**：内嵌了公钥的安装，收到没有签名或签名不符的清单时，会在下载前拒绝更新，报 ERR_UPDATER_MANIFEST_NOT_SIGNED 或 ERR_UPDATER_MANIFEST_SIGNATURE_INVALID。（EB-master signed-update-manifests.md:149-163）
- **其他相关改动**（EB-master v27-breaking-changes.md:104-112,120-130,864-870,895-928,982-1067）：
  - 需要 Node.js 22.12.0 以上；
  - `disableWebInstaller` 默认为 true；
  - latest*.yml 不再写顶层的 path 和 sha512；
  - `quitAndInstall` 改为接收一个对象参数；
  - `autoInstallOnAppQuit` 换成 `autoInstallEvent`（取值 "manual" | "onQuit" | "onNextLaunch"）；
  - `verifyUpdateCodeSignature` 改名为 `verifyUpdateFileAuthenticodeSignature`；
  - 配置的 publisherName 与证书不符时，构建失败；
  - 新增 `verifyUpdateFile`，让程序自己定义下载文件的校验。
- **v27 正式版还没有发布**：截至 2026-10-01，npm 的 `latest` 仍是 26.15.3，`next` 是 27.0.0-alpha.9。（npm）

### 3.9 Squirrel.Windows 与 Electron Forge 的更新方式（对照）

- **内置 autoUpdater 在 Windows 上的两种机制**：MSIX 包用 MSIX 的更新方式；用 electron-winstaller 或 Forge 的 Squirrel maker 安装的程序用 Squirrel.Windows。（EL docs/api/auto-updater.md:51-63）
- **Squirrel.Windows 的注意事项**（EL auto-updater.md:65-84）：
  - 首次运行时带 `--squirrel-firstrun` 参数，并持有文件锁，最初几秒内检查更新会失败；
  - 快捷方式的 AUMID 格式是 `com.squirrel.PACKAGE_ID.EXE`，程序需要用 app.setAppUserModelId 设置相同的值。
- **服务器要求**：feed 地址下的 `/RELEASES` 返回最新版本的 RELEASES 内容（SHA1、nupkg、大小）。没有更新时也要返回，由客户端比较版本。（EL docs/tutorial/updates.md:282-297）
- **静态存储**：
  - Forge 的 Squirrel maker 可以用 `remoteReleases` 生成增量包。（EWI README.md:84-85）
  - update-electron-app 的 StaticStorage 模式要求目录结构 `{platform}/{arch}/`；Windows 目录里需要有 RELEASES、`*-full.nupkg` 和安装程序，`*-delta.nupkg` 可选。（UEA README.md:59-69,110-143；EL updates.md:13-119）
  - update-electron-app 默认每 10 分钟检查一次，最短 5 分钟。（UEA README.md:84-89）
- **update.electronjs.org**：
  - 使用条件：程序运行在 macOS 或 Windows、GitHub 仓库公开、构建发布在 GitHub Releases、macOS 的构建已签名。（EL updates.md:121-130；tutorial-6-publishing-updating.md:27-46）
  - Yudao 的仓库是私有仓库，所以这个服务不适用。
  - update-electron-app 的 README 写明，私有程序可以把构建产物上传到一个公开的 GitHub 仓库来使用这个服务。（UEA README.md:130-132）
- **私有程序的更新服务器**：
  - 官方文档列出了 Hazel、Nuts、electron-release-server、Nucleus 等自建更新服务器。（EL updates.md:156-176）
  - Forge 文档列出三种更新方式：update.electronjs.org、静态存储、自建服务器。（FG docs/advanced/auto-update.md:13-35）
- **降级**：
  - Squirrel.Windows 不降级：本地版本高于远端版本时，要应用的版本列表为空。（SQ src/Squirrel/UpdateManager.CheckForUpdates.cs:184-187；src/Squirrel/UpdateInfo.cs:66-68）
  - MSIX 可以降级：`setFeedURL` 的 `allowAnyVersion: true` 允许降级，这个选项只对 MSIX 有效。（EL auto-updater.md:86-92,171-172）
- **签名要求**：
  - 内置 autoUpdater 在 macOS 上要求程序已签名；API 文档的 Windows 部分没有签名要求。（EL auto-updater.md:29-31,51-92）
  - electron-winstaller 的 README 写明：开发和内部使用时，不签名也可以；正式发布时不签名会被 SmartScreen 拦截。（EWI README.md:89-91）

### 3.10 第 3 节未能核实的事项

- v27 正式版的发布日期：master 的文档和 PR #10255 只说这些改动会写进 27.0.0 正式版的说明，没有给日期。

## 4. Windows 代码签名（2026 年）

### 4.1 没有签名的安装包与 Microsoft Defender SmartScreen

- **首次下载时的表现**：Microsoft 用一张表格列出了首次下载时的情况。
  - 没有签名的文件会显示「Windows protected your PC」，用户必须选择「Run anyway」才能运行，企业策略可以完全禁止继续运行。
  - 自签名证书的表现与没有签名相同。
  - 用有效的 OV 或 EV 证书签名的文件，在信誉积累之前同样被标记为无法识别的应用，但提示中会显示经过验证的发布者名称。

  （来源：https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation ，页面日期 2026-05-04，读取于 2026-10-01）
- **判断信号**：SmartScreen 根据两类信号判断。一类是发布者信誉，即文件是否签名、签名证书是否来自已知的受信任发布者。另一类是文件哈希信誉，即这个文件是否已被用户下载过且没有恶意迹象。哈希或证书的信誉为负面或未知时，会出现提示。（来源：同上）
- **没有签名时的信誉**：没有签名的文件，每个新版本都从零开始积累信誉。只有前后两个版本使用同一个发布者身份签名，信誉才能延续。（来源：同上）
- **信誉积累的速度**：信誉随下载量自动积累，没有确定的门槛，可能需要几周时间，以及来自广泛用户的几百次正常安装。个人电脑没有手动提交审核的途径；企业 IT 管理员可以通过 Microsoft Security Intelligence 门户提交文件。（来源：同上）
- **Intranet 位置**：企业可以从受信任的 Intranet 位置分发文件，这些文件不经过 SmartScreen 检查。（来源：同上）
- **跨版本积累**：使用同一个受信任的证书连续签名，发布者信誉可以跨版本积累，后续版本可能不再出现提示。更换签名证书会影响发布者信号。（来源：同上；https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options ，页面日期 2026-08-29，读取于 2026-10-01）
- **EV 证书不再直接取得信誉**：2024 年以前，用 EV 证书签名的新文件不出现下载提示。2024 年 Microsoft 修改了 Trusted Root Program 的要求，删除了 EV 专用的 OID。此后信誉只按文件哈希随时间积累，OV 证书与 EV 证书相同。（来源：MicrosoftDocs/windows-dev-docs 提交 aabd22a，`hub/apps/package-and-deploy/distribution-feature-status.md` 第 68–76 行，对应页面 https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/distribution-feature-status ，页面日期 2026-04-17；smartscreen-reputation 页面的 Note 写法相同）
- **「Check apps and files」开关**：Windows Security 中的这个开关让 SmartScreen 评估「从网上下载的应用和文件」的信誉。这个页面适用于 Windows 11 与 Windows 10，没有区分版本。（来源：https://support.microsoft.com/en-us/windows/security/windows-security/app-browser-control-in-the-windows-security-app ，读取于 2026-10-01）
- **保护范围**：SmartScreen 防范来自 Internet 的恶意文件，不保护内部位置与网络共享（UNC 路径、SMB/CIFS 共享）中的文件。（来源：https://learn.microsoft.com/en-us/windows/security/operating-system-security/virus-and-threat-protection/microsoft-defender-smartscreen/ ，页面日期 2026-04-23，读取于 2026-10-01）
- **Microsoft Edge 中的 SmartScreen**：Edge 默认开启 SmartScreen。信誉未知的下载文件会显示警告，用户仍然可以通过「... | Keep | Show More | Keep anyway」保留并运行。（来源：https://learn.microsoft.com/en-us/deployedge/microsoft-edge-security-smartscreen ，页面日期 2026-07-08，读取于 2026-10-01）
- **UAC 提升提示**：只有程序请求管理员访问令牌时才出现提升提示。没有签名或签名不受信任的程序显示黄色背景；Windows 管理程序或经过验证的发布者签名的程序显示灰色背景。（来源：https://learn.microsoft.com/en-us/windows/security/application-security/application-control/user-account-control/how-it-works ，页面日期 2026-04-23，读取于 2026-10-01）

### 4.2 Smart App Control

- **工作方式**：Microsoft 的云端服务先预测应用是否安全。无法给出有把握的预测时，检查签名：签名有效的应用可以运行，没有签名或签名无效的应用被阻止。没有针对单个应用放行的方法。（来源：https://support.microsoft.com/en-us/topic/what-is-smart-app-control-285ea03d-fa88-4d56-882e-6698afdb7003 ，读取于 2026-10-01）
- **承认的证书**：只承认 Trusted Root Program 中的 CA 签发的证书。只支持 RSA 签名，目前不支持 ECC 签名。（来源：https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/overview ，页面日期 2025-11-18，读取于 2026-10-01；MicrosoftDocs/windows-dev-docs 提交 aabd22a，`hub/apps/develop/smart-app-control/code-signing-for-smart-app-control.md` 第 11–20 行）
- **与 SmartScreen 的关系**：在 Windows 11 上，Smart App Control 可能取代 SmartScreen 的应用信誉检查。它阻止没有正面信誉的未签名文件，签名检查适用于全部可执行文件，与文件是否从 Internet 下载无关。（来源：smartscreen-reputation 页面的 Tip，读取于 2026-10-01）
- **三种状态**：Evaluation（只观察，不阻止）、On（强制执行）、Off。多数情况下系统会自动开启它，检测到开发者等不适合的用户时自动关闭。企业管理、开发者模式、S mode、关闭可选诊断数据，都会使它处于关闭状态。（来源：SAC overview 页面；SAC FAQ 页面）
- **开关方式**：Microsoft 各份文档的说法不一致。
  - 开发者文档（页面日期 2025-11-18 与 2025-10-28）写明：它只能在全新安装的 Windows 上启用，重置电脑也算全新安装；在 Windows 设置中把它设为 On 或 Off 是单向操作，只有处于 Evaluation 时才能在设置中更改；测试时可以在恢复环境中修改注册表值 `VerifiedAndReputablePolicyState`（0 表示 Off，1 表示 On，2 表示 Evaluation）。（来源：overview 页面；https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/test-your-app-with-smart-app-control ，读取于 2026-10-01）
  - Windows Security 的支持页面仍然写着「只能用于全新安装的 Windows 11，通过更新获得这项功能的电脑需要重置或重装才能开启」。（来源：app-browser-control 支持页面，读取于 2026-10-01）
  - KB5079391（2026-03-26，OS Build 26200.8116 预览更新）写明：可以在 Windows Security > App & Browser Control > Smart App Control settings 中开启或关闭，不需要全新安装，这项功能开始逐步推送。Smart App Control FAQ 页面也写明，最近的 Windows 更新允许不重装就开启或重新开启。（来源：https://support.microsoft.com/en-us/servicing/os/windows-11/2026/03/march-26-2026-kb5079391-os-builds-26200-8116-and-26100-8116-preview ；SAC FAQ 页面，读取于 2026-10-01）
- **地区**：开发者文档写明 Smart App Control 只在部分地区启用，没有列出具体地区。（来源：overview 页面）
- **这台电脑的状态**：
  - 系统为 Windows 11 家庭中文版（EditionID `CoreCountrySpecific`），版本 25H2，OS Build 26200.9457。
  - `HKLM\SYSTEM\CurrentControlSet\Control\CI\Policy\VerifiedAndReputablePolicyState` 的值为 0，`HKLM\SYSTEM\CurrentControlSet\Control\CI\Protected\VerifiedAndReputablePolicyStateMinValueSeen` 的值为 0。
  - `Get-MpComputerStatus` 返回的 `SmartAppControlState` 为 Off。
  - 家庭中文版上存在这项功能，当前处于关闭状态。

  （读取方式：PowerShell 只读查询 `Get-ItemProperty`、`Get-CimInstance Win32_OperatingSystem`、`Get-MpComputerStatus`，2026-10-01）

### 4.3 Mark-of-the-Web 与局域网 HTTP 下载

- **格式与取值**：Mark-of-the-Web 保存在 NTFS 备用数据流 `文件名:Zone.Identifier` 中，内容为 `[ZoneTransfer]` 段与 `ZoneId=` 行。ZoneId 的取值：0 为 My Computer，1 为 Local intranet，2 为 Trusted sites，3 为 Internet，4 为 Restricted sites。只适用于 NTFS，保存在 FAT32 上的文件没有这个标记。（来源：[MS-FSCC] https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fscc/6e3f7352-d11c-4d76-8c39-2516a9df36e8 ；https://learn.microsoft.com/en-us/microsoft-365-apps/security/internet-macros-blocked ，页面日期 2026-07-17，读取于 2026-10-01）
- **默认写入范围**：默认只有来自 Internet 或 Restricted sites 区域的文件会被加上 Mark-of-the-Web。浏览器是否写入，由 Windows 的 Internet 安全区域设置决定，例如 Microsoft Edge 对来自 Internet 区域的文件写入这个标记。（来源：internet-macros-blocked 页面）
- **Chromium 的写入方式**：
  - 下载完成后，Chromium 调用 Windows Attachment Services（`IAttachmentExecute`）：用 `SetSource` 传入下载地址（地址无效、为空或过长时改为传入 `about:internet`），有 referrer 时调用 `SetReferrer`，最后调用 `Save()`。
  - 文件为空、客户端 GUID 为空、或者调用 Attachment Services 失败时，Chromium 自己写入 `[ZoneTransfer]`、`ZoneId=3`、`ReferrerUrl` 与 `HostUrl`。
  - 没有 quarantine 服务时，也直接写入 `ZoneId=3`。

  （来源：chromium/chromium 提交 3908d08，`components/services/quarantine/quarantine_win.cc` 第 99–180、184–230、262–279 行；`components/download/internal/common/base_file.cc` 第 688–718 行）
- **Attachment Services 怎样判定区域**：`SetSource` 给出的地址是判定区域的主要依据，不调用时默认按 Restricted 区域处理。`SetReferrer` 与 `SetSource` 都设置时，采用两者中信任程度较低的区域。`Save()` 可能把 evidence 写入 NTFS 备用数据流。（来源：https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-iattachmentexecute-setsource ；https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-iattachmentexecute-setreferrer ；https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-iattachmentexecute-save ，读取于 2026-10-01）
- **区域判定规则**：
  - 主机名或 IP 地址中包含句点时（例如 `http://157.54.100.101` 或 FQDN），被判定为 Internet 区域。Microsoft 把这标为设计行为，解决方法是把 IP 地址范围或域名加入 Local intranet 站点列表（注册表 `ZoneMap\Ranges` 或 `ZoneMap\Domains`）。（来源：https://learn.microsoft.com/en-us/troubleshoot/windows-client/networking/intranet-site-identified-as-an-internet-site ，原 KB 303650，页面日期 2026-02-12，读取于 2026-10-01）
  - 区域映射函数不考虑目标站点的实际 IP 地址。主机名中没有句点时（例如 `http://team/`），按 PlainHostName 规则归入 Local intranet。绕过固定代理的站点、WPAD 脚本返回 DIRECT 的站点，也归入 Local intranet。没有映射到其他区域的站点，默认属于 Internet 区域。（来源：https://learn.microsoft.com/en-us/archive/blogs/ieinternals/the-intranet-zone ，2012-06-05，读取于 2026-10-01）
  - 从 IE7 开始，Local intranet 区域可能处于关闭状态。电脑加入域时默认开启；Network Location Awareness 显示至少一个连接是受管理的网络时，也会开启。用户选择「Turn on Intranet settings」以后，「Automatically detect intranet network」被取消勾选，其他 Intranet 选项被勾选。（来源：同上）
- **这台电脑的区域映射**：
  - 查询结果：`http://192.168.1.10/x.exe` 判定为 Internet；`http://hostname/x.exe` 判定为 Intranet；`http://yudao-host.local/x.exe` 判定为 Internet；`http://localhost/x.exe` 判定为 Intranet。同一方法另外查询的 `http://10.0.0.5:8080/x.exe` 与 `http://127.0.0.1:8000/x.exe` 判定为 Internet（2026-10-01 复核）。
  - 这台电脑没有加入域。
  - `HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings\ZoneMap` 中：AutoDetect=0，IntranetName=1，ProxyBypass=1，UNCAsIntranet=1。
  - `HKLM` 下同一位置：AutoDetect=1，IntranetName=0，ProxyBypass=0，UNCAsIntranet=0。

  （读取方式：在 Windows PowerShell 5.1 中调用 `[System.Security.Policy.Zone]::CreateFromUrl`，这个方法按本机 Internet 选项的区域映射判定，说明见 https://learn.microsoft.com/en-us/dotnet/api/system.security.policy.zone.createfromurl ；注册表用 `Get-ItemProperty` 只读查询，2026-10-01）
- **这台电脑上的 Attachment Services 实测**：使用与 Chromium 相同的调用顺序（`SetClientGuid`、`SetLocalPath`、`SetSource`、`SetReferrer`、`Save`）处理临时目录中的测试文件。
  - 来源为 `http://192.168.1.10/…` 时，写入了 `ZoneId=3`、`ReferrerUrl` 与 `HostUrl`。
  - 来源为 `http://yudao-host.local/…` 时，写入了 `ZoneId=3`。
  - 来源为 `http://hostname/…`（本机判定为 Intranet）时，没有写入 Zone.Identifier。

  （读取方式：在 PowerShell 7.6.6 中用 `Add-Type` 定义 `IAttachmentExecute` 接口后调用，再用 `Get-Item -Stream *` 检查，2026-10-01；测试文件事后已删除）
- **命令行工具实测**：用 `curl.exe` 8.21.0（Windows 自带）、PowerShell 7.6.6 的 `Invoke-WebRequest`、Windows PowerShell 5.1 的 `Invoke-WebRequest` 下载的文件，都只有 `:$DATA` 流，没有 Zone.Identifier。（读取方式：下载到临时目录后用 `Get-Item -Stream *` 检查，2026-10-01）
- **electron-updater**：electron-updater 6.8.9（npm 当前的 latest 版本）的发布包中，没有读写 Zone.Identifier 或调用 Attachment Services 的代码。在 Windows 上，它用子进程直接启动下载好的安装包；需要管理员权限时，通过 `elevate.exe` 启动。（来源：npm 包 electron-updater 6.8.9 的 `out/NsisUpdater.js` 第 124–135 行；在整个包中搜索 `Zone.Identifier|Unblock-File|ZoneTransfer|IAttachmentExecute|ZoneId`，没有结果，2026-10-01）
- **Edge 的 SmartScreen 下载检查**：策略 `SmartScreenForTrustedDownloadsEnabled` 处于启用或未配置状态时，SmartScreen 检查所有下载的信誉，与来源无关。只有禁用这项策略后，来自本机、Intranet 或 Trusted sites 区域的下载才不检查。这项策略只在加入 Active Directory 域的 Windows，或者登记了设备管理的 Windows 10 Pro、Enterprise 上可用。这台电脑是家庭版且没有加入域，无法使用这项策略。（来源：https://learn.microsoft.com/en-us/deployedge/microsoft-edge-policies/smartscreenfortrusteddownloadsenabled ，页面日期 2026-05-20，读取于 2026-10-01）
- **Chromium 的不安全下载提示**（与 Mark-of-the-Web 相互独立）：
  - 发起下载的页面不是可信来源（例如 http 页面），或者下载本身没有经过安全连接时，这次下载被视为不安全。只有下载地址是 localhost 时例外，局域网 IP 地址没有例外。
  - 不安全的下载会显示可以绕过的警告。
  - 没有开启 HTTPS-First Mode 时，扩展名属于安全列表的文件不警告。安全列表包括 txt、css、json、csv、tsv、常见图片与音视频格式，不包括 `.exe`。
  - 站点的「Insecure content」设置为允许时，也不警告。

  （来源：chromium/chromium 提交 3908d08，`chrome/browser/download/insecure_download_blocking.cc` 第 86–89、275–280、378–406、429–443 行）

### 4.4 Azure Artifact Signing（原名 Trusted Signing）

- **名称**：Microsoft 文档现在称为 Artifact Signing（formerly Trusted Signing）或 Azure Artifact Signing。Azure 零售价格 API 中的服务名仍然是「Trusted Signing」。（来源：code-signing-options 页面；MicrosoftDocs/azure-docs 提交 0ce5b33，`articles/artifact-signing/overview.md`；对 https://prices.azure.com/api/retail/prices 的查询，2026-10-01）
- **地区与对象**：
  - Public Trust 证书面向以下地区的组织：美国、加拿大、欧盟、英国、澳大利亚、新西兰、日本、韩国、新加坡、瑞士、挪威、以色列。
  - 个人开发者必须位于美国或加拿大。
  - Private Trust 证书没有地区限制，但 Private 身份验证只面向组织。

  （来源：azure-docs 提交 0ce5b33，`articles/artifact-signing/quickstart.md` 第 26–34、341–343 行，页面日期 2026-05-21，对应页面 https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart ）

  code-signing-options 页面（2026-08-29）列出的组织地区只有美国、加拿大、欧盟、英国；个人同样限于美国与加拿大。
- **对 Yudao 的适用性**：用户以个人身份在中国，不在个人开发者允许的地区之内；组织地区列表中也没有中国。因此无法申请 Public Trust 证书。
- **个人身份验证的条件**：
  - 订阅所关联的 Azure 计费账户，类型必须是 Individual。
  - 计费账户上的法定姓名与地址，必须与政府签发的证件一致。
  - 验证通过 AU10TIX 与 Microsoft Authenticator 中的 Verified ID 完成，包括证件照片与人脸核对。
  - 只能在 Azure 门户中完成验证。

  （来源：quickstart.md 第 31–34、331–460 行）
- **订阅要求**：必须使用付费的 Azure 订阅，免费、试用、赞助订阅都不能使用。（来源：azure-docs 提交 0ce5b33，`articles/artifact-signing/faq.yml` 第 37–39 行，页面日期 2026-05-14）
- **价格**：
  - Basic：每个账户每月 9.99 美元，每月 5,000 次签名，每类证书配置 1 个。
  - Premium：每月 99.99 美元，每月 100,000 次签名，每类证书配置 10 个。
  - 超出配额后，每次签名 0.005 美元。
  - 费用不按天折算。

  （来源：`how-to-change-sku.md` 第 25–32 行；`faq.yml` 第 233–235 行；Azure 零售价格 API 返回 Basic Account 9.99 美元、Premium Account 99.99 美元、Signature Overage 0.005 美元，生效日期 2024-06-01，查询于 2026-10-01。Azure 定价页面 https://azure.microsoft.com/en-us/pricing/details/artifact-signing/ 的价格由脚本加载，读取时显示为「$-」）
- **证书有效期与密钥**：
  - 证书每天更新，每张证书只有 72 小时有效期，因此签名时必须加上 RFC 3161 时间戳。服务提供的时间戳地址是 `http://timestamp.acs.microsoft.com`。
  - 密钥保存在服务管理的硬件加密模块中，不能导入或导出。关于模块的认证级别，同一页面第 67 行写的是 FIPS 140-3 Level 3，第 73 行写的是 FIPS 140-2 Level 3。

  （来源：`concept-certificate-management.md` 第 28–30、61–81 行，页面日期 2026-09-24）
- **身份验证续期**：身份验证到期前 60 天起可以续期，续期需要 1–20 个工作日。到期前没有续期，证书就停止更新，签名随之停止。（来源：`how-to-renew-identity-validation.md` 第 17–21 行）
- **其他特点**：
  - 这项服务不签发 EV 证书。
  - Public Trust 证书由「Microsoft Identity Verification Root Certificate Authority 2020」签发，适用于 Smart App Control 与 SmartScreen。
  - 签名后的文件同样需要积累 SmartScreen 信誉。

  （来源：`faq.yml` 第 141–143、205–207 行；`concept-trust-models.md` 第 31–42 行）
- **与 electron-builder 配合（26.15.3）**：这是 npm 的 `latest` 版本，发布于 2026-06-09。
  - 配置项为 `win.azureSignOptions`，字段有 `publisherName`（必须与证书的 CN 完全一致）、`endpoint`、`certificateProfileName`、`codeSigningAccountName`。
  - 其他字段直接传给 PowerShell 模块 `Invoke-TrustedSigning`。
  - 认证使用环境变量 `AZURE_TENANT_ID`、`AZURE_CLIENT_ID`、`AZURE_CLIENT_SECRET` 等。

  （来源：electron-userland/electron-builder 标签 electron-builder@26.15.3，提交 512a57e，`website/docs/features/code-signing/code-signing-win.md` 第 22–61 行；npm registry 的 dist-tags，读取于 2026-10-01）
- **与 electron-builder 配合（27.0.0-alpha.9）**：这是 npm 的 `next` 版本，发布于 2026-09-26。
  - 配置改为 `win.sign: { type: "azure", ... }`，标注为 Beta。
  - 调用方式为 `signtool.exe sign /dlib Azure.CodeSigning.Dlib.dll /dmdf metadata.json`。
  - 自动下载 .NET 8 运行时；在 macOS 或 Linux 上通过 Wine 运行 signtool。
  - 构建时必须能连接 Azure。

  （来源：electron-builder master 分支提交 ccfe093，`website/docs/features/code-signing/code-signing-win.md` 第 230–318 行）

### 4.5 普通代码签名证书（OV、EV）

- **私钥必须保存在硬件中**：从 2023-06-01 起，代码签名证书的私钥必须在符合 FIPS 140-2 Level 2 或 Common Criteria EAL 4+ 的硬件加密模块中生成、保存和使用。可以选择的方式有三种：自有的硬件令牌或 HSM、符合要求的云端 HSM、签名服务。（来源：CA/Browser Forum Code Signing Baseline Requirements v3.11.0（2026-06-16），cabforum/code-signing 提交 cbf9773，`docs/CSBR.md` 第 78–79、1999–2006 行）
- **最长有效期**：2026-03-01 以前签发的证书最长 39 个月。2026-03-01 起签发的证书最长 460 天（Ballot CSC-31，对应规定的 3.10 版）。（来源：同上，第 64、85、2036 行）
- **个人能否购买**：
  - Baseline Requirements 定义了 Individual Applicant，即以本人法定姓名作为证书主体的自然人。签发前，CA 必须核验申请人的政府签发带照片证件等材料。
  - EV 代码签名证书只能签发给 Private Organization、Government Entity、Business Entity、Non-Commercial Entity 四类申请者。
  - Yudao 由个人使用与分发，按这条规定无法取得 EV 证书。

  （来源：同上，第 294–296、1022–1035、1131 行）
- **Microsoft 给出的大致价格**：OV 证书每年 150–300 美元，EV 证书每年 400 美元以上；OV 证书在全球都可以购买。（来源：code-signing-options 页面，页面日期 2026-08-29）
- **CA 官方页面上的个人证书与价格**（读取于 2026-10-01）：
  - **SSL.com 的「IV Code Signing」**：
    - 面向个人开发者，证书上显示本人姓名，需要提供政府签发的证件。
    - 1 年期 129.00 美元，多年期折合每年 96.75–116.10 美元。
    - 私钥必须放在 FIPS 硬件令牌或云签名服务中：YubiKey 令牌另外收费 379.00 美元；eSigner 云签名需要另外订阅，页面没有列出价格。

    （来源：https://www.ssl.com/products/software-integrity/code-signing/iv/ ）
  - **Certum 的「Standard Code Signing」**：
    - 证书内容可以是自然人信息、自然人及其组织的信息，或者只有组织信息。
    - 起价：云端版本（SimplySign）209 欧元；含加密卡的套装 169 欧元；自带加密卡的电子码 139 欧元。
    - 云端产品每月限 5,000 次签名。
    - 从 2026-02-27 起，单张证书最长 459 天，2 年或 3 年的产品需要在期间免费重新签发。

    （来源：https://shop.certum.eu/code-signing.html ；https://shop.certum.eu/standard-code-signing-in-the-cloud.html ）
  - **Certum 的「Open Source Code Signing」与 SignPath Foundation 的免费签名**：
    - Certum 的这款产品起价 25、49、69 欧元，证书中的姓名前加上「Open Source Developer」。
    - 这两者都面向开源或免费软件。
    - Yudao 的代码仓库是私有仓库，不在这两者的对象之内。

    （来源：https://shop.certum.eu/open-source-code-signing-on-simplysign.html ；code-signing-options 页面）

### 4.6 自签名证书

- **SmartScreen 表现**：在 SmartScreen 下，自签名证书的表现与没有签名相同，都会显示「Windows protected your PC」，需要选择「Run anyway」。Microsoft 文档写明，能跨版本积累信誉的是用受信任证书签名的文件。（来源：smartscreen-reputation 页面）
- **默认不受信任**：Windows 默认不信任自签名证书。用户没有手动把证书安装为受信任根证书时，会触发强烈的 SmartScreen 阻止。Microsoft 列出的适用场景有两种：本机开发测试（可以手动安装证书），以及企业通过 Intune 或组策略把证书部署为受信任根证书。Microsoft Store 的 MSI 或 EXE 提交不接受自签名证书。（来源：code-signing-options 页面）
- **Smart App Control**：Smart App Control 只承认 Trusted Root Program 中的 CA 签发的证书，自签名证书不在其中。（来源：SAC overview 页面；`code-signing-for-smart-app-control.md` 第 20 行）
- **UAC**：对于已签名但不受信任的程序，UAC 提升提示显示黄色背景，与没有签名的程序相同。（来源：UAC how-it-works 页面）

### 4.7 第 4 节未能核实的事项

- SmartScreen 提示的中文界面文字与「More info」这一步：Microsoft 官方文档只给出了英文的「Windows protected your PC」与「Run anyway」，「More info」只出现在 Microsoft Q&A 的社区回答中。已查阅 smartscreen-reputation 页面、SmartScreen overview 页面、Defender for Endpoint 演示页面（该页面只有截图）。
- Smart App Control 启用的地区是否包括中国：开发者文档只写「只在部分地区启用」。已查阅 SAC overview 页面、SAC FAQ 页面、Windows Security 支持页面。
- 这台电脑是否已经收到 KB5079391 中「不重装即可开关」的推送：本机版本 26200.9457 晚于 26200.8116，但这项功能是逐步推送的，没有打开设置界面核对。
- Windows SmartScreen 在运行文件时的确切触发条件（例如是否只看 ZoneId=3 或 4）：Microsoft 文档只写明检查「从网上下载的文件」「来自 Internet 的文件」，没有写出 ZoneId 的阈值。已查阅 SmartScreen overview 页面、smartscreen-reputation 页面、App & browser control 支持页面、Office 的 Mark-of-the-Web 页面。
- Edge 下载时写入 Zone.Identifier 的具体实现，以及 Edge 是否带有 Chromium 的不安全下载提示：Edge 的源代码不公开，只有 Microsoft Office 文档中「Edge 对来自 Internet 区域的文件写入标记」这一句描述。上文关于 Chromium 的内容来自 Chromium 源代码。
- Artifact Signing 身份验证的有效期长度：文档只写了到期前 60 天可以续期。
- SSL.com 的 eSigner 订阅价格，以及各家 CA 对中国大陆个人购买的限制：已查阅的页面都没有写明。

## 5. 桌面程序管理本机服务的做法

### 5.1 Ollama（Windows）

#### 版本与程序组成
- 本节调研 Ollama v0.35.0，发布日期 2026-09-28，标签指向提交 cc40693，本节源代码行号都以这个提交为准（来源：https://api.github.com/repos/ollama/ollama/releases/latest ，读取于 2026-10-01）。
- Windows 安装包 `OllamaSetup.exe` 用 Inno Setup 制作，安装托盘程序 `ollama app.exe` 和命令行程序 `ollama.exe`（来源：ollama cc40693 `app/ollama.iss`:1-18、38、91-96）。
- `ollama app.exe` 用 Go 编写，窗口用 webview 库，Windows 上的引擎是 WebView2（`win32_edge_engine`）（来源：ollama cc40693 `app/webview/webview.h`:3347、3882；`app/cmd/app/webview.go`:47-68）。

#### 服务由谁启动
- 官方文档：安装以后 Ollama 在后台运行，API 地址是 `http://localhost:11434`（来源：https://docs.ollama.com/windows ，读取于 2026-10-01；ollama cc40693 `docs/windows.mdx`:5-9）。
- `ollama app.exe` 以子进程方式运行 `ollama.exe serve`。子进程隐藏窗口，放在新的进程组里，输出写入 `%LOCALAPPDATA%\Ollama\server.log`（来源：ollama cc40693 `app/cmd/app/app.go`:240-255；`app/server/server.go`:230-243；`app/server/server_windows.go`:17-30）。
- 每次启动服务进程之前（包括第一次），托盘程序都先等待 1 秒。服务进程退出以后，托盘程序会重新启动它（来源：ollama cc40693 `app/server/server.go`:25、178-228）。
- 服务的进程号写入 `%LOCALAPPDATA%\Ollama\ollama.pid`。托盘程序下次启动时，先按这个文件结束上一次遗留的进程（来源：ollama cc40693 `app/server/server.go`:109-141、186-188、207；`app/server/server_windows.go`:17-20）。
- 服务进程以退出码 1 结束时，托盘程序会结束其他 `ollama serve` 进程再重试一次；代码注释认为退出码 1 可能是端口冲突（来源：ollama cc40693 `app/server/server.go`:212-223；`app/server/server_windows.go`:126-174）。
- 托盘程序还在 `127.0.0.1` 的随机端口上运行一个供界面使用的 HTTP 服务，界面请求要带启动时生成的 token（来源：ollama cc40693 `app/cmd/app/app.go`:186-202）。
- 运行 `ollama run` 等命令时如果服务没有响应，`ollama.exe` 会用 `--hide --fast-startup` 参数启动 `ollama app.exe`，然后最多等待 5 秒（来源：ollama cc40693 `cmd/cmd.go`:2165-2179；`cmd/start_windows.go`:24-65；`cmd/start.go`:13-27）。
- 安装包 `[Run]` 段只启动托盘程序（来源：ollama cc40693 `app/ollama.iss`:122-123）。
- 要把 Ollama 作为 Windows 服务运行，官方文档的做法是：使用单独的 `ollama-windows-amd64.zip`（只有命令行程序与 GPU 库），再用 NSSM 这类工具运行 `ollama serve`（来源：https://docs.ollama.com/windows ，读取于 2026-10-01；ollama cc40693 `docs/windows.mdx`:82-99）。

#### 退出程序与关闭窗口
- 托盘菜单有 `Open Ollama`、`Settings`、`View logs`、`Quit Ollama`（来源：ollama cc40693 `app/wintray/messages.go`:5-17；`app/wintray/menus.go`:30-48）。
- 选择 `Quit Ollama` 后的过程：托盘程序结束消息循环；关闭界面用的 HTTP 服务，并取消服务进程的 context；服务进程先收到 CTRL_BREAK 与 CTRL_C 事件，5 秒内没有退出就被强制结束（来源：ollama cc40693 `app/wintray/eventloop.go`:77-78、201-205、219-229；`app/cmd/app/app_windows.go`:126-129；`app/cmd/app/app.go`:356-365；`app/server/server.go`:146-176、276-281；`app/server/server_windows.go`:32-77）。
- 关闭主窗口只销毁 webview 窗口。窗口销毁时产生的 WM_QUIT 被托盘消息循环接住，改为只结束 webview，所以托盘程序和 `ollama serve` 继续运行（来源：ollama cc40693 `app/webview/webview.h`:1078-1084、3398-3405、3626；`app/wintray/eventloop.go`:35-48）。
- 界面代码调用的 `close` 绑定只隐藏窗口（来源：ollama cc40693 `app/cmd/app/webview.go`:228-230）。
- 安装新版本之前，安装包先用 `taskkill` 结束 `ollama app.exe`、`ollama.exe` 与 `llama-server.exe`。卸载时也结束这三个进程（来源：ollama cc40693 `app/ollama.iss`:93-94、125-133、326-334）。

#### 登录时启动
- 安装包在 `{app}\lib\Ollama.lnk` 放一个快捷方式（来源：ollama cc40693 `app/ollama.iss`:114-117）。
- 托盘程序第一次运行时，把这个快捷方式复制到当前用户的启动文件夹 `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Ollama.lnk`。以后不再创建，所以用户删除后就不会再出现（来源：ollama cc40693 `app/cmd/app/app_windows.go`:38-40、229-236、241-275；`app/cmd/app/app.go`:310-320）。
- 从启动文件夹的快捷方式启动时，程序从 STARTUPINFO 读取快捷方式路径，路径含 `Startup` 就不显示窗口（来源：ollama cc40693 `app/cmd/app/app_windows.go`:195-208）。
- 官方 FAQ：Ollama 注册为登录项，可以在任务管理器的「启动应用」里禁用，升级后保持这个设置。卸载时删除启动快捷方式（来源：https://docs.ollama.com/faq ，读取于 2026-10-01；ollama cc40693 `docs/faq.mdx`:405-411；`app/ollama.iss`:140）。

#### 权限与安装位置
- 安装包设置 `PrivilegesRequired=lowest`，默认按用户安装到 `{localappdata}\Programs\Ollama`（来源：ollama cc40693 `app/ollama.iss`:34、37）。
- 官方文档：安装不需要管理员权限，默认安装在用户目录。可以用 `OllamaSetup.exe /DIR="d:\some\location"` 修改安装位置（来源：https://docs.ollama.com/windows ，读取于 2026-10-01；ollama cc40693 `docs/windows.mdx`:27-37、84-87）。
- 安装包把安装目录加入当前用户的 PATH（`HKCU\Environment`），并在 HKCU 下注册 `ollama://` 协议（来源：ollama cc40693 `app/ollama.iss`:157-164）。
- 文件位置（来源：ollama cc40693 `docs/windows.mdx`:61-72）：
  - `%LOCALAPPDATA%\Ollama`：日志和已下载的更新；
  - `%LOCALAPPDATA%\Programs\Ollama`：程序；
  - `%HOMEPATH%\.ollama`：模型与配置。

#### 监听地址与局域网访问
- 服务默认监听 `127.0.0.1:11434`，用环境变量 `OLLAMA_HOST` 修改（来源：https://docs.ollama.com/faq ，读取于 2026-10-01；ollama cc40693 `docs/faq.mdx`:183-187；`envconfig/config.go`:20-60）。
- Windows 上服务继承用户与系统的环境变量。修改步骤：先从托盘退出 Ollama，在「编辑账户的环境变量」里设置 `OLLAMA_HOST` 等变量，再从开始菜单启动（来源：ollama cc40693 `docs/faq.mdx`:113-127）。
- 设置页有「Expose Ollama to the network」开关，默认关闭。打开后托盘程序给服务进程设置 `OLLAMA_HOST=0.0.0.0`，并重新启动服务进程（来源：ollama cc40693 `app/ui/app/src/components/Settings.tsx`:680-699；`app/store/database.go`:64-69；`app/server/server.go`:250-252；`app/ui/ui.go`:1596-1600）。

#### 更新
- 托盘程序启动 3 秒后检查一次更新，以后每小时检查一次。检查地址是 `https://ollama.com/api/update`，请求带操作系统、架构和当前版本（来源：ollama cc40693 `app/updater/updater.go`:32-36、53-135、359-422）。
- 设置项「Auto-download updates」默认打开。打开时在后台下载新的 `OllamaSetup.exe`，放在 `%LOCALAPPDATA%\Ollama\updates_v2\<etag 的 sha256>\`（来源：ollama cc40693 `app/store/database.go`:91；`app/ui/app/src/components/Settings.tsx`:655-678；`app/updater/updater.go`:137-250、394-412；`app/updater/updater_windows.go`:60-72）。
- 下载后用 WinVerifyTrust 检查 Authenticode 签名，并要求签名证书的 Organization 是 `Ollama Inc.`，检查不通过就删除下载的文件（来源：ollama cc40693 `app/updater/updater.go`:244-247；`app/updater/updater_windows.go`:217-335）。
- 下载完成后托盘图标改变并弹出通知，菜单出现「Restart to update」（来源：ollama cc40693 `app/wintray/menus.go`:50-89；`app/wintray/messages.go`:8-13）。
- 选择「Restart to update」后，托盘程序停止服务，以 `/CLOSEAPPLICATIONS /FORCECLOSEAPPLICATIONS /SP /NOCANCEL /SILENT` 参数运行安装包，然后退出（来源：ollama cc40693 `app/cmd/app/app_windows.go`:136-145；`app/updater/updater_windows.go`:121-192）。
- 托盘程序以隐藏方式启动（例如登录时）时，如果有已下载的更新并且自动更新是打开的，就在启动阶段加 `/VERYSILENT /SUPPRESSMSGBOXES` 直接安装（来源：ollama cc40693 `app/cmd/app/app.go`:395-427；`app/updater/updater_windows.go`:150-153、369-371）。
- 升级后第一次启动时，程序清理旧的安装包，并以隐藏方式启动（来源：ollama cc40693 `app/cmd/app/app.go`:155-168；`app/updater/updater_windows.go`:194-215）。
- 也可以从官网手动下载新版本安装（来源：ollama cc40693 `docs/faq.mdx`:5-7）。
- 设置了 `KEY_CONTAINER` 环境变量时，Inno Setup 用 SignTool 给安装包和卸载程序签名（来源：ollama cc40693 `app/ollama.iss`:78-81）。

### 5.2 LM Studio

#### 程序组成与服务由谁启动
- LM Studio 有三个程序：桌面程序 LM Studio、没有界面的后台程序 llmster、命令行 `lms`。`lms` 可以操作桌面程序和 llmster，桌面程序和 llmster 都自带 `lms`（来源：https://lmstudio.ai/docs/app/basics/lmstudio-vs-llmster-vs-lms ，源文件 lmstudio-ai/docs 9b8bc20 `0_app/1_basics/lmstudio-vs-llmster-vs-lms.md`:7-45，读取于 2026-10-01）。
- llmster 是把桌面程序的核心部分单独打包成的后台程序，不安装桌面程序也能运行（来源：同上 26-37 行；https://lmstudio.ai/docs/developer/core/headless ，lmstudio-ai/docs 9b8bc20 `1_developer/0_core/headless.md`:13-15，读取于 2026-10-01）。
- 启动 API 服务有两种方法：在桌面程序的 Developer 页打开「Start server」开关，或运行 `lms server start`（来源：https://lmstudio.ai/docs/developer/core/server ，lmstudio-ai/docs 9b8bc20 `1_developer/0_core/0_server/index.md`:15-25，读取于 2026-10-01）。
- 服务启动后监听 `http://localhost:1234`（来源：lmstudio-ai/docs 9b8bc20 `0_app/1_basics/lmstudio-vs-llmster-vs-lms.md`:68；lmstudio-ai/lms 1b7181b `src/createClient.ts`:14）。
- 运行 `lms` 命令时，如果 LM Studio 没有运行，会自动启动它（来源：lmstudio-ai/docs 9b8bc20 `0_app/1_basics/lmstudio-vs-llmster-vs-lms.md`:58）。
- 自动启动的实现（来源：lmstudio-ai/lmstudio-js 6d2b268 `packages/lms-common-server/src/findOrStartLlmster.ts`:52-147、243-306；`packages/lms-common-server/src/findLMStudioHome.ts`:7-34；lmstudio-ai/lms 1b7181b `src/createClient.ts`:148-157）：
  - `lms` 读取 LM Studio 主目录（默认 `~/.lmstudio`）下 `.internal/` 里的 `llmster-install-location.json` 与 `app-install-location.json`；
  - 两个文件都存在时，优先启动 llmster；
  - 启动桌面程序时加 `--run-as-service` 参数；
  - Windows 上用 PowerShell 的 `Start-Process -WindowStyle Hidden` 启动 llmster；
  - 启动后每秒检查一次，最多检查 60 次。
- 桌面程序已经在运行时，`lms daemon up` 提示 LM Studio 已在运行，不启动第二个后台程序（来源：lmstudio-ai/lms 1b7181b `src/subcommands/daemon/up.ts`:36-50）。
- 使用 `lms` 之前，需要先运行一次 LM Studio（来源：https://lmstudio.ai/docs/cli ，lmstudio-ai/docs 9b8bc20 `3_cli/index.mdx`:35-39，读取于 2026-10-01）。

#### 退出程序与关闭窗口
- 在设置里勾选「run the LLM server on login」后，退出程序时程序缩小到系统托盘，LLM 服务继续在后台运行（来源：https://lmstudio.ai/docs/developer/core/headless ，lmstudio-ai/docs 9b8bc20 `1_developer/0_core/headless.md`:43-53，读取于 2026-10-01）。
- 服务的上一次状态会被保存，程序或服务启动时恢复（来源：同上 55-57 行）。
- `lms daemon down` 只能停止 llmster。服务作为桌面程序的一部分运行时，它会提示需要退出 LM Studio 才能停止（来源：https://lmstudio.ai/docs/cli/daemon/daemon-down ，lmstudio-ai/docs 9b8bc20 `3_cli/2_daemon/daemon-down.mdx`:8-16，读取于 2026-10-01；lmstudio-ai/lms 1b7181b `src/subcommands/daemon/down.ts`:17-35）。
- `lms server stop` 停止服务，正在处理的请求会中断（来源：https://lmstudio.ai/docs/cli/serve/server-stop ，lmstudio-ai/docs 9b8bc20 `3_cli/1_serve/server-stop.md`:8-20，读取于 2026-10-01）。

#### 登录与开机启动
- 桌面程序：在设置（Ctrl + ,）中勾选「run the LLM server on login」（来源：lmstudio-ai/docs 9b8bc20 `1_developer/0_core/headless.md`:47-51）。
- llmster：官方文档只写了 Linux 上用 systemd 开机启动的做法，依次运行 `lms daemon up`、`lms load`、`lms server start`，停止时运行 `lms daemon down`（来源：https://lmstudio.ai/docs/developer/core/headless_llmster ，lmstudio-ai/docs 9b8bc20 `1_developer/0_core/headless_llmster.mdx`:8-11、66-96，读取于 2026-10-01）。

#### 权限与安装位置
- Microsoft 的 winget-pkgs 仓库中 LM Studio 0.4.25+1 的 Windows 安装包清单（来源：microsoft/winget-pkgs 4263806 `manifests/e/ElementLabs/LMStudio/0.4.25+1/ElementLabs.LMStudio.installer.yaml`:6-38）：
  - 安装包类型是 nullsoft（NSIS）；
  - 同一个安装包支持按用户安装（`/currentuser`）和按机器安装（`/allusers`）；
  - 升级开关是 `--updated`；
  - 下载地址在 `installers.lmstudio.ai`。
- llmster 在 Windows 上用 `irm https://lmstudio.ai/install.ps1 | iex` 安装。脚本中没有请求管理员权限的步骤（来源：https://lmstudio.ai/install.ps1 ，读取于 2026-10-01，第 39-45、85-114、221-256、317-373 行）。脚本的步骤：
  - 下载 zip 和 `.sha512`，核对 SHA-512；
  - 运行 `llmster.exe bootstrap`，安装到 `$HOME/.lmstudio/bin`（或 `$env:LOCALAPPDATA/lm-studio/bin`）；
  - 运行 `lms bootstrap -y`，把这个目录加入 PATH。

#### 监听地址与局域网访问
- 服务默认绑定 `127.0.0.1`。设置里的「Serve on Local Network」开关让服务绑定到非 localhost 地址，同一局域网的其他设备就能访问（来源：https://lmstudio.ai/docs/developer/core/server/serve-on-network ，lmstudio-ai/docs 9b8bc20 `1_developer/0_core/0_server/serve-on-network.mdx`:9-29，读取于 2026-10-01）。
- 命令行对应 `lms server start --bind 0.0.0.0`，也可以用环境变量 `LMS_SERVER_HOST`（来源：https://lmstudio.ai/docs/cli/serve/server-start ，lmstudio-ai/docs 9b8bc20 `3_cli/1_serve/server-start.mdx`:10-25，读取于 2026-10-01）。
- 端口在设置的「Server Port」里修改，或者用 `--port` 参数（来源：https://lmstudio.ai/docs/developer/core/server/settings ，lmstudio-ai/docs 9b8bc20 `1_developer/0_core/0_server/settings.md`:15-28，读取于 2026-10-01；`3_cli/1_serve/server-start.mdx`:13-16）。
- 0.4.0 起支持 API Token 认证，默认关闭，在 Developer 页的 Server Settings 打开「Require Authentication」（来源：https://lmstudio.ai/docs/developer/core/authentication ，lmstudio-ai/docs 9b8bc20 `1_developer/0_core/authentication.mdx`:8-14，读取于 2026-10-01）。
- 另有 LM Link：与 Tailscale 合作的端到端加密网络，用来在自己的多台设备之间使用模型，需要登录账号（来源：https://lmstudio.ai/docs/lmlink ，lmstudio-ai/docs 9b8bc20 `5_lmlink/index.md`:10，读取于 2026-10-01；`5_lmlink/1_basics/index.md`:12-14）。

#### 更新
- 桌面程序在 macOS 和 Windows 上自带更新程序。每次打开程序时联网检查，有新版本就通知用户，由用户选择立即更新或稍后更新（来源：https://lmstudio.ai/docs/app/offline ，lmstudio-ai/docs 9b8bc20 `0_app/0_root/offline.mdx`:45-48，读取于 2026-10-01）。
- llmster 用 `lms daemon update` 更新：先运行 `lms daemon down` 再更新；加 `--beta` 参数会更新到 beta 版本（来源：https://lmstudio.ai/docs/cli/daemon/daemon-update ，lmstudio-ai/docs 9b8bc20 `3_cli/2_daemon/daemon-update.md`:8-47，读取于 2026-10-01）。

### 5.3 Docker Desktop（Windows）

#### 版本与程序组成
- 当前版本是 4.93.0，发布于 2026-09-28（来源：https://docs.docker.com/desktop/release-notes/ ，docker/docs c7f01ac `content/manuals/desktop/release-notes.md`:27-29，读取于 2026-10-01）。
- Docker Engine 运行在 Docker Desktop 管理的 Linux 虚拟机里。Windows 上的网络与端口转发由 `com.docker.backend.exe` 进程处理（来源：https://docs.docker.com/desktop/features/networking/ ，docker/docs c7f01ac `content/manuals/desktop/features/networking/_index.md`:11-36，读取于 2026-10-01）。
- 使用 WSL 2 时，Docker Engine 运行在 `docker-desktop` 这个 WSL 发行版里（来源：https://docs.docker.com/desktop/use-desktop/resource-saver/ ，docker/docs c7f01ac `content/manuals/desktop/use-desktop/resource-saver.md`:62-70，读取于 2026-10-01）。

#### 服务由谁启动
- 按机器安装时，会安装一个特权辅助服务 `com.docker.service`；按用户安装时不安装。它的情况如下（来源：https://docs.docker.com/desktop/setup/install/windows-permission-requirements/ ，docker/docs c7f01ac `content/manuals/desktop/setup/install/windows-permission-requirements.md`:29、55-76，读取于 2026-10-01）：
  - 以 SYSTEM 权限运行的 Windows 服务；
  - 监听命名管道 `//./pipe/dockerBackendV2`；
  - 负责创建、启动、停止 Hyper-V 虚拟机 `DockerDesktopVM`，以及启动、停止 Windows Docker Engine 等。
- 使用 Windows 容器或 Hyper-V 时，`com.docker.service` 在系统启动时启动并一直运行，Docker Desktop 没有运行时它也在运行。使用 WSL 2 时不需要这个服务，它不随系统启动（来源：同上 78-80 行）。
- 安装完成后，Docker Desktop 不会自动启动（来源：https://docs.docker.com/desktop/setup/install/windows-install/ ，docker/docs c7f01ac `content/manuals/desktop/setup/install/windows-install.md`:217-229，读取于 2026-10-01）。
- 命令行 `docker desktop start|stop|restart|status` 用来启动、停止、重启 Docker Desktop 和查询状态，`stop` 有 `--force` 与 `--detach` 选项（来源：https://docs.docker.com/desktop/features/desktop-cli/ ，docker/docs c7f01ac `content/manuals/desktop/features/desktop-cli.md`:9-38、`data/cli/desktop/docker_desktop_stop.yaml`:1-30，读取于 2026-10-01）。

#### 退出程序与关闭窗口
- Docker 图标显示在系统托盘（来源：docker/docs c7f01ac `content/manuals/desktop/use-desktop/resource-saver.md`:39-42）。
- Resource Saver 默认开启：没有容器运行满 5 分钟后，停止 Linux 虚拟机。在 WSL 上它只暂停 `docker-desktop` 发行版里的 Docker Engine，WSL 虚拟机继续运行（来源：同上 11-14、24-27、62-75 行）。
- 4.73.0（2026-05-11）修复了 Windows 上 Ctrl+Q 不能完全退出 Docker Desktop 的问题（来源：docker/docs c7f01ac `content/manuals/desktop/release-notes.md`:935-950）。

#### 登录时启动
- 设置 General 页有「Start Docker Desktop when you sign in to your computer」，默认关闭（来源：https://docs.docker.com/desktop/settings-and-maintenance/settings/ ，docker/docs c7f01ac `content/manuals/desktop/settings-and-maintenance/settings.md`:33-35，读取于 2026-10-01）。
- 4.42.0（2025-06-04）的发布说明有一条修复：部分系统语言下读取「auto-start registry key」出错（来源：docker/docs c7f01ac `content/manuals/desktop/release-notes.md`:2131-2185）。
- 安装参数 `--always-run-service`：安装完成后启动 `com.docker.service`，并把它的启动类型设为 Automatic（来源：docker/docs c7f01ac `content/manuals/desktop/setup/install/windows-install.md`:291）。

#### 权限与安装位置
- Docker Desktop 有两种安装模式（来源：docker/docs c7f01ac `content/manuals/desktop/setup/install/windows-install.md`:33-47）：
  - 按用户安装：位置 `%LOCALAPPDATA%\Programs\DockerDesktop`，写 HKCU；安装和更新都不需要管理员权限；后端用 WSL 2 或 Docker VMM；不支持 Windows 容器。
  - 按机器安装：位置 `C:\Program Files\Docker\Docker`，写 HKLM；安装和更新都需要管理员权限；支持 WSL 2、Hyper-V、Docker VMM 与 Windows 容器。
- 安装包默认选择按用户安装，命令行写法是 `"Docker Desktop Installer.exe" install --user`（来源：docker/docs c7f01ac `content/manuals/desktop/setup/install/windows-install.md`:35、147、165-171、286）。
- 从 4.83.0（2026-07-20）起，Windows 安装包默认选择按用户安装（来源：docker/docs c7f01ac `content/manuals/desktop/release-notes.md`:472-516）。
- 第一次启用 WSL 2 需要管理员权限，每台机器一次。设置里标着「Requires password」的项目，修改时需要提升权限（来源：docker/docs c7f01ac `content/manuals/desktop/setup/install/windows-permission-requirements.md`:48-53）。
- 两种模式安装以后，运行 Docker Desktop 都不需要管理员权限（来源：同上 21-37 行）。

#### 监听地址与局域网访问
- Windows 上的客户端通过命名管道 `npipe:////./pipe/docker_engine` 或 TCP `tcp://localhost:2375` 连接 Docker Engine（来源：https://docs.docker.com/desktop/troubleshoot-and-support/faqs/general/ ，docker/docs c7f01ac `content/manuals/desktop/troubleshoot-and-support/faqs/general.md`:18-37，读取于 2026-10-01）。
- 使用 `tcp://localhost:2375` 要打开设置「Expose daemon on tcp://localhost:2375 without TLS」。这个设置默认关闭，只适用于 Hyper-V 后端；文档提示，不用 TLS 暴露有远程代码执行的风险（来源：docker/docs c7f01ac `content/manuals/desktop/settings-and-maintenance/settings.md`:44）。
- 按用户安装不支持 Hyper-V 后端（来源：docker/docs c7f01ac `content/manuals/desktop/setup/install/windows-install.md`:43）。
- 容器用 `-p` 发布的端口默认监听所有网卡（`0.0.0.0`），本机和局域网都能访问，也可以指定 `127.0.0.1`。监听由 `com.docker.backend` 进程完成，防火墙可以按这个进程过滤（来源：docker/docs c7f01ac `content/manuals/desktop/features/networking/_index.md`:51-64）。

#### 更新
- 设置 Software updates 页的两个选项（来源：docker/docs c7f01ac `content/manuals/desktop/settings-and-maintenance/settings.md`:298-306）：
  - 「Automatically check for updates」默认打开，有新版本时在 Docker 菜单和 Dashboard 底部提示；
  - 「Always download updates」默认关闭，打开后在后台下载新版本。
- 每周发布新版本。也可以在 Docker 菜单选择「Check for updates」（来源：https://docs.docker.com/desktop/troubleshoot-and-support/faqs/releases/ ，docker/docs c7f01ac `content/manuals/desktop/troubleshoot-and-support/faqs/releases.md`:9-17，读取于 2026-10-01）。
- 命令行 `docker desktop update`：`--check-only` 只检查，`--quiet` 静默检查并安装（来源：https://docs.docker.com/reference/cli/docker/desktop/update/ ，docker/docs c7f01ac `data/cli/desktop/docker_desktop_update.yaml`:1-28，读取于 2026-10-01）。
- 从 4.90.0（2026-09-07）起，按机器安装的 Docker Desktop 在程序内更新时，会提示改为按用户安装，之后的更新就不需要管理员权限（来源：docker/docs c7f01ac `content/manuals/desktop/release-notes.md`:189-228）。

### 5.4 第 5 节未能核实的事项
- LM Studio 桌面程序「run the LLM server on login」在 Windows 上用什么方式实现（注册表 Run 项、启动文件夹还是计划任务）：lmstudio.ai 文档（docs 仓库 9b8bc20，全文搜索 tray、login、startup）和 winget 清单中都没有写。
- LM Studio 桌面程序按用户安装时的默认安装目录：lmstudio.ai 文档、winget-pkgs 清单（只列出 `/currentuser`、`/allusers` 两个开关）、lmstudio-bug-tracker 第 591 号 issue 中都没有写。
- 没有勾选「run the LLM server on login」时，退出 LM Studio 或关闭窗口对服务的影响：官方文档（headless.md）只写了勾选以后的行为。
- llmster 在 Windows 上怎样开机或登录启动：官方文档只有 Linux systemd 的做法。
- Docker Desktop 关闭 Dashboard 窗口与退出程序的区别，以及退出以后 Docker Engine 是否停止：docs.docker.com 的安装、设置、Explore Docker Desktop、Resource Saver、FAQ 页面和发布说明（docker/docs c7f01ac）中都没有直接说明。
- Docker Desktop「Start Docker Desktop when you sign in to your computer」写入的注册表位置：文档没有写，发布说明 4.42.0 只提到「auto-start registry key」。

## 6. uv

### 6.1 版本与这台电脑

- 本节按 astral-sh/uv 标签 0.11.14 核对，与这台电脑上的 uv 是同一版本，发布于 2026-05-12。uv 最新发布版本为 0.12.21，发布于 2026-09-29（来源：这台电脑上运行 `uv --version`，输出 `uv 0.11.14 (3fdfdc7d4 2026-05-12 x86_64-pc-windows-msvc)`；https://api.github.com/repos/astral-sh/uv/releases/latest ，读取于 2026-10-01）。
- 在 0.12.0 到 0.12.21 的变更记录中，按 `uv tool`、`tool install`、`python download`、`mirror`、`uv auth`、`update-shell` 搜索，命中的条目如下（来源：astral-sh/uv 标签 0.12.21 `CHANGELOG.md` 第 1–851 行）：
  - `uv tool upgrade` 的提示与错误输出（第 212、234、359、441 行）；
  - 新增 `uv tool audit`（第 554 行）；
  - `update-shell` 写入启动文件的时机（第 606 行）；
  - `uv tool list --outdated` 使用配置的索引（第 609 行）。
  - 没有修改安装来源写法、存储目录或 Python 下载来源的条目。
- 这台电脑上的实际情况（来源：这台电脑上运行 `(Get-Command uv).Source`、`[Environment]::GetEnvironmentVariable('Path','User')` 与下列 uv 命令，2026-10-01）：
  - `uv.exe` 位于 `%USERPROFILE%\.local\bin\uv.exe`，用户级 PATH 包含 `%USERPROFILE%\.local\bin`；
  - `uv tool dir` 输出 `%APPDATA%\uv\tools`；
  - `uv tool dir --bin` 与 `uv python dir --bin` 都输出 `%USERPROFILE%\.local\bin`；
  - `uv python dir` 输出 `%APPDATA%\uv\python`。

### 6.2 安装来源的写法

- `uv tool install` 的包参数按 requirements.txt 中一行的规则解析：先按 PEP 508 解析，失败时再按直接 URL 或本地路径解析。相对路径以当前目录为基准（来源：astral-sh/uv 标签 0.11.14 `crates/uv-requirements/src/sources.rs` 第 295–301 行、`crates/uv-requirements-txt/src/requirement.rs` 第 129–160 行）。
- 直接 wheel 地址：uv 的测试 `tool_install_unnamed_package` 运行 `uv tool install https://files.pythonhosted.org/.../black-24.4.2-py3-none-any.whl`。安装后工具目录中生成安装回执（receipt）`uv-receipt.toml`，其中记录 `requirements = [{ name = "black", url = "…/black-24.4.2-py3-none-any.whl" }]`（来源：标签 0.11.14 `crates/uv/tests/it/tool_install.rs` 第 2801–2875 行）。
- 直接地址的类型由 URL 路径（不含查询字符串与 `#` 之后的片段）的扩展名决定：`.whl` 按 wheel 处理，`.tar.gz`、`.zip` 等按源代码包处理，其他扩展名报错，错误信息列出支持的扩展名（来源：标签 0.11.14 `crates/uv-pypi-types/src/parsed_url.rs` 第 332–347 行、`crates/uv-distribution-filename/src/extension.rs` 第 44–57、70–102、130–139 行；2026-10-01 读取源代码）。
- 没有写包名的 wheel 地址（`uv tool install <wheel 地址>`）：包名取自 URL 最后一段的 wheel 文件名，文件名按 wheel 命名格式解析；写了包名的地址（`包名 @ 地址`）要求文件名中的包名与所写包名一致，否则报包名不匹配的错误（来源：标签 0.11.14 `crates/uv-requirements/src/unnamed.rs` 第 87–102 行；`crates/uv-distribution-types/src/lib.rs` 第 372–389 行；2026-10-01 读取源代码）。
- git 地址：写法为 `uv tool install git+https://github.com/httpie/cli`。文档中 `uvx --from` 的例子在地址后加 `@master`、`@3.2.4`、`@2843b87`，分别指定分支、标签、提交；`uv tool install` 使用同样的包来源写法（来源：标签 0.11.14 `docs/guides/tools.md` 第 117–143、204–214 行）。
- 本地文件：再次安装同一个本地路径时，uv 把安装记录中的文件信息与当前文件比较，不一致时判定为过期并重新安装（来源：标签 0.11.14 `crates/uv-installer/src/satisfies.rs` 第 139–159、228–279 行）。
- 普通 `http://` 地址：
  - 文档写明 `allow-insecure-host` 只作用于 HTTPS 连接，原文为 "HTTP connections are inherently insecure"。控制主机使用普通 `http://` 地址时，与这个选项无关。
  - uv 的测试 `tool_install_credentials` 使用 `http://[LOCALHOST]/basic-auth/simple` 形式的包索引。
  - （来源：标签 0.11.14 `docs/concepts/authentication/certificates.md` 第 61–79 行、`crates/uv/tests/it/tool_install.rs` 第 5123–5136、5196 行）
- wheel 的依赖默认从 `https://pypi.org/simple` 解析。`--find-links` 增加查找位置；`--no-index` 不使用包索引，只使用直接 URL 依赖与 `--find-links` 提供的文件（来源：这台电脑上运行 `uv tool install --help`，2026-10-01）。
- Yudao 的 `pyproject.toml`：构建后端为 setuptools，`requires-python = ">=3.11"`，运行依赖 9 个（openai、httpx、anthropic、httpx2、pydantic、fastapi、uvicorn、filelock、truststore），都写成版本范围；没有 `[project.scripts]` 表；`harness` 包带有 `web/static/*` 与 `definitions/*.json` 两类数据文件（来源：`C:\project\yudao\pyproject.toml` 第 1–23 行，读取于 2026-10-01）。
- HTTP 凭据的来源按优先顺序为（来源：标签 0.11.14 `docs/concepts/authentication/http.md` 第 3–60 行）：
  1. URL 中的用户名与密码；
  2. netrc 文件（由 `NETRC` 环境变量指定，默认 `~/.netrc`）；
  3. uv 凭据存储（`uv auth login` 写入，默认是明文文件）；
  4. keyring provider（默认关闭）。
  - 适用范围是包索引、`find-links` 与 `package @ https://...` 这类直接地址。

### 6.3 从私有 git 仓库安装时的认证

- SSH：写法为 `git+ssh://git@github.com/<owner>/<repo>`，用户名必须是 `git`（来源：标签 0.11.14 `docs/concepts/authentication/git.md` 第 5–16 行）。
- HTTPS：令牌写在地址中，写法为 `git+https://<user>:<token>@github.com/...` 或 `git+https://<token>@github.com/...`。使用 GitHub personal access token 时，用户名可以任意填写（来源：同一文件第 18–30 行）。
- 地址中没有凭据而仓库需要认证时，uv 向 Git credential helper 查询。在 GitHub 上可以运行 `gh auth login` 配置 credential helper；使用 `gh auth login --with-token` 时，还需要运行 `gh auth setup-git`（来源：同一文件第 32–33、49–70 行）。
- `uv auth login` 保存的凭据只用于 HTTPS Basic 认证，文档写明目前不用于 Git 请求，因此对 git 地址的安装不起作用（来源：标签 0.11.14 `docs/concepts/authentication/cli.md` 第 29–31 行）。
- uv 文档中 netrc 属于 HTTP 凭据来源，git 认证一节没有提到 netrc（来源：`docs/concepts/authentication/http.md` 第 20–26 行、`git.md` 全文）。
- uv 调用系统中的 `git` 程序完成 Git 操作，找不到时报错 "Git executable not found. Ensure that Git is installed and available."（来源：标签 0.11.14 `crates/uv-git/src/git.rs` 第 26–27、44–46 行）。

### 6.4 `--reinstall`、`--force`、`--python`

- `--reinstall`（来源：这台电脑上运行 `uv help tool install`；标签 0.11.14 `crates/uv/src/commands/tool/install.rs` 第 469–473、809–822 行）：
  - 帮助文本为 "Reinstall all packages, regardless of whether they're already installed. Implies `--refresh`"。
  - 使用这个参数时，`uv tool install` 跳过「已经安装」的检查。
  - 回执中没有固定 Python、并且这次选到的解释器与原环境不同时，重新创建环境。
- `--force`：帮助文本为 "Will recreate any existing environment for the tool and replace any existing entry points with the same name in the executable directory"。源代码中 `--force` 同时隐含 `--reinstall-package <包名>`（来源：`uv help tool install`；`install.rs` 第 334–342、451–453 行）。
- 可执行文件目录中已有同名、并非由 uv 安装的文件时，没有 `--force` 的安装会失败，报错提示使用 `--force`（来源：标签 0.11.14 `docs/concepts/tools.md` 第 259–263 行、`crates/uv/src/commands/tool/common.rs` 第 265–291 行）。
- `--python`：帮助文本为 "The Python interpreter to use to build the tool environment"。工具环境不读取项目中的 `.python-version` 与 `requires-python`，只使用 `--python` 或全局的版本设置（来源：`uv help tool install`；`docs/concepts/tools.md` 第 231–239 行；`install.rs` 第 91–108 行）。
- 显式给出的 `--python`（来源：`install.rs` 第 755–767、798–807 行；`crates/uv/src/commands/tool/upgrade.rs` 第 451 行；`docs/concepts/tools.md` 第 241–242 行）：
  - 写入回执，`uv tool upgrade` 沿用回执中的值；
  - 与现有环境的解释器不同时，重新创建环境；
  - 工具使用的 Python 被卸载后，工具环境损坏。
- 本机没有满足 `--python 3.12` 的 Python 时，uv 默认自动下载。`--no-python-downloads` 或 `UV_PYTHON_DOWNLOADS=never` 关闭自动下载（来源：标签 0.11.14 `docs/concepts/python-versions.md` 第 20–30、50–52、367–379 行；`install.rs` 第 110–126 行；`uv tool install --help`）。

### 6.5 再次安装与升级

- 同时满足以下条件时，`uv tool install` 输出 "`…` is already installed" 后结束（来源：`install.rs` 第 469–549 行）：
  - 要求与回执相同；
  - 已安装的包满足要求；
  - 没有 `--reinstall` 或升级参数。
- 对 http 或 https 直接地址，uv 只比较地址是否相同，不检查服务器上的文件是否变化；只有 `file://` 地址会比较文件信息（来源：`satisfies.rs` 第 98–160、378–379 行）。
  - 按这两处代码，同一个地址上的文件被替换以后，没有 `--reinstall` 或 `--force` 的再次安装会按「已经安装」结束（由代码推出，没有实际运行验证）。
- 地址不同时（例如文件名中的版本号改变），要求与回执不同。uv 在原环境上按新要求更新，然后删除旧的入口程序（entry point），写入新的入口程序与回执（来源：`install.rs` 第 551–617、755–774 行）。
- `uv tool upgrade <名称>`（来源：`upgrade.rs` 第 319–340 行；`tool_install.rs` 第 2865–2875 行；`docs/concepts/tools.md` 第 117–146 行）：
  - 使用回执中保存的要求与约束重新解析，设置的优先顺序为命令行、回执、用户配置；
  - 回执中的要求是一个 URL 时，升级仍然使用这个 URL；
  - 文档写明，改变版本约束的方法是重新运行 `uv tool install`。
- 升级时的其他行为（来源：`docs/concepts/tools.md` 第 148–164 行；`upgrade.rs` 第 344–387 行）：
  - 总会重新安装工具的可执行文件；
  - `uv tool upgrade --reinstall` 重新安装环境中的全部包；
  - `uv tool upgrade --python <版本>` 在解释器不同时重新创建环境。

### 6.6 入口程序与目录（Windows）

- `pyproject.toml` 的 `[project.scripts]` 表定义命令行入口，使用入口表需要定义 build system（来源：标签 0.11.14 `docs/concepts/projects/config.md` 第 20–44 行）。
- 工具的可执行文件包括包提供的全部 console entry point、script entry point 与 binary script。Unix 上建立符号链接，Windows 上复制到可执行文件目录；依赖包提供的可执行文件不会安装（来源：`docs/concepts/tools.md` 第 244–252 行；`common.rs` 第 294–311 行）。
- 入口程序中包含工具环境里 Python 解释器的绝对路径（来源：`install.rs` 第 572–575 行的注释）。
- 工具目录默认是持久数据目录下的 `tools`，可以通过 `UV_TOOL_DIR` 修改，`uv tool dir` 显示。每个工具的环境在 `<工具目录>\<包名>`，回执文件是其中的 `uv-receipt.toml`（来源：标签 0.11.14 `docs/reference/storage.md` 第 148–158 行；`crates/uv-tool/src/lib.rs` 第 128–148、195 行）。
- 文档与实际目录有出入（来源：`docs/reference/storage.md` 第 44–57 行；`crates/uv-dirs/src/lib.rs` 第 66–84 行；这台电脑上运行 `uv tool dir`）：
  - storage.md 列出的 Windows 持久数据目录是 `%APPDATA%\uv\data`；
  - 源代码中 `user_state_dir` 使用 etcetera base strategy 的 data 目录再加 `uv`，含有 `data` 子目录的写法属于 `legacy_user_state_dir`；
  - 这台电脑上 `uv tool dir` 的输出为 `%APPDATA%\uv\tools`。
- Windows 上可执行文件目录依次使用 `%XDG_BIN_HOME%`、`%XDG_DATA_HOME%\..\bin`、`%USERPROFILE%\.local\bin`。`UV_TOOL_BIN_DIR` 优先于这三个位置，`uv tool dir --bin` 显示（来源：`docs/reference/storage.md` 第 87–102、160–168 行；`crates/uv-dirs/src/lib.rs` 第 11–38 行；`crates/uv-tool/src/lib.rs` 第 425–426 行）。
- 可执行文件目录不在 PATH 中时，安装后显示警告，并提示运行 `uv tool update-shell`。Windows 上这个命令（来源：`docs/concepts/tools.md` 第 254–257 行；`common.rs` 第 345–381 行；`crates/uv/src/commands/tool/update_shell.rs` 第 17–43 行；`crates/uv-shell/src/windows.rs` 第 20–53 行）：
  - 把目录写入注册表 `HKEY_CURRENT_USER\Environment` 的 `PATH` 值；
  - 广播 `WM_SETTINGCHANGE`；
  - 提示 "Restart your shell to apply changes"。

### 6.7 Windows 上下载 Python

- CPython 来自 Astral 的 python-build-standalone 项目（来源：标签 0.11.14 `docs/concepts/python-versions.md` 第 445–460 行）。
- 没有设置镜像时，uv 先从 `https://releases.astral.sh/github/python-build-standalone/releases/download/...` 下载，失败时再从 `https://github.com/astral-sh/python-build-standalone/releases/download/...` 下载（来源：`crates/uv-python/src/downloads.rs` 第 186–199、1157–1189、1520–1575 行；`crates/uv-static/src/lib.rs` 第 9–10 行）。默认先使用 Astral 镜像是从 0.10.8 开始的，该版本发布于 2026-03-03（来源：标签 0.11.14 `CHANGELOG.md` 第 544–560 行）。
- 可下载的 Python 版本列表编在每个 uv 版本里。0.11.14 内置列表中 Windows x86_64 最新的 3.12 为 3.12.13，文件为 `cpython-3.12.13+20260510-x86_64-pc-windows-msvc-install_only_stripped.tar.gz`，列表附带 SHA-256 值（来源：`docs/concepts/python-versions.md` 第 119–122 行；`crates/uv-python/download-metadata.json` 中的 `cpython-3.12.13-windows-x86_64-none`）。
- 下载后按列表中的 SHA-256 校验，不一致时报错（来源：`downloads.rs` 第 80–85、1466–1497 行）。
- 镜像与缓存相关的环境变量（来源：`crates/uv-static/src/env_vars.rs` 第 433–489 行；`downloads.rs` 第 1254–1291、1546–1573 行；`docs/reference/storage.md` 第 122–136 行）：
  - `UV_PYTHON_INSTALL_MIRROR`：替换 `https://github.com/astral-sh/python-build-standalone/releases/download` 前缀，可以使用 `file://` 本地目录；设置后只使用这个地址。
  - `UV_ASTRAL_MIRROR_URL`（0.11.14 新增）：替换 `https://releases.astral.sh`；设置后只使用这个地址。
  - `UV_PYTHON_DOWNLOADS_JSON_URL`：以本地路径或 URL 上的 JSON 列表替换内置列表。
  - `UV_PYTHON_CACHE_DIR`：保存下载的压缩包；离线并且缓存中没有对应文件时报错。
  - `UV_PYTHON_INSTALL_DIR`：修改安装目录。
- 安装位置是持久数据目录下的 `python`，这台电脑上为 `%APPDATA%\uv\python`。`uv python install` 默认还把名称中含有版本号的 Python 可执行文件放入可执行文件目录（来源：`docs/reference/storage.md` 第 122–146 行；`docs/concepts/python-versions.md` 第 127–146 行；这台电脑上运行 `uv python dir`）。
- 注册表（来源：`docs/concepts/python-versions.md` 第 485–498 行；`crates/uv-python/src/windows_registry.rs` 第 159–161 行；`env_vars.rs` 第 425–431 行）：
  - Windows 上安装托管 Python 时，按 PEP 514 写入 `HKEY_CURRENT_USER\Software\Python\Astral`；
  - 源代码注释写明 Windows 上只为当前用户安装；
  - `UV_PYTHON_NO_REGISTRY`（0.11.8 新增）关闭注册表的查找与写入。
- 上面各条中 uv 写入的位置都在当前用户的目录与 `HKEY_CURRENT_USER` 之下。标签 0.11.14 的上述文档中没有关于管理员权限的说明（来源：以上各条；在下载的文档中搜索 administrator、elevat 没有结果）。
- Python 查找顺序：`UV_PYTHON_INSTALL_DIR` 中的托管 Python，然后是 PATH 中的 `python.exe`，然后是 Windows 注册表与 Microsoft Store 中的 Python。默认 `python-preference` 为 `managed`：已安装的托管 Python 优先，其次系统 Python，两者都不满足时才下载（来源：`docs/concepts/python-versions.md` 第 289–314、401–422 行）。
- 托管 Python 有按次版本号命名的目录（例如 `cpython-3.12-...`），在 Windows 上是指向具体补丁版本的 junction。使用它建立的虚拟环境，在 `uv python upgrade` 后会自动使用新的补丁版本；`install-python.md` 把补丁版本升级标注为 preview（来源：`docs/concepts/python-versions.md` 第 157–210 行；`docs/guides/install-python.md` 第 130–150 行）。

### 6.8 许可证

- uv 采用 Apache License 2.0 与 MIT License 双许可证，由使用者任选其一（来源：标签 0.11.14 `docs/reference/policies/license.md` 第 1–15 行、`README.md` 第 311–319 行）。
- MIT 许可证允许使用、复制、修改、合并、发布、分发、再许可与出售。条件是在全部副本或实质部分中包含版权声明与许可声明；版权声明为 "Copyright (c) 2025 Astral Software Inc."（来源：`LICENSE-MIT` 第 1–13 行）。
- Apache 2.0 第 4 节的分发条件如下，第 6 节不授予商标使用权（来源：`LICENSE-APACHE` 第 89–128、138–141 行）：
  - 随附许可证副本；
  - 修改过的文件带有修改说明；
  - 保留原有的版权、专利、商标与署名声明；
  - 作品附有 NOTICE 文件时，随附其中的署名内容。
- uv 仓库根目录没有 NOTICE 文件（来源：https://api.github.com/repos/astral-sh/uv/git/trees/0.11.14?recursive=1 ，读取于 2026-10-01）。
- 发布压缩包（来源：标签 0.11.14 `dist-workspace.toml` 第 41–42、91–96 行；https://api.github.com/repos/astral-sh/uv/releases/tags/0.11.14 ，读取于 2026-10-01）：
  - 配置为 `auto-includes = false`，不自动放入 README、LICENSE 等文件；
  - Windows 压缩包包含 `uv`、`uvx`、`uvw` 三个程序；
  - 0.11.14 的 `uv-x86_64-pc-windows-msvc.zip` 为 23,339,260 字节。

## 7. GitHub

### 7.1 Actions 的免费额度与价格

- 本节的 GitHub 文档读取自 github/docs 仓库提交 d45a621（2026-09-30 的 main），对应的页面地址写在各条来源中。
- 私有仓库：每个账户按方案获得免费的分钟数、产物存储与缓存存储，用于 GitHub 托管的运行器，超出部分计费。分钟数在每个计费周期开始时恢复，费用记在仓库所有者名下（来源：github/docs 提交 d45a621 `content/billing/concepts/product-billing/github-actions.md` 第 22–32、119–121 行；页面 https://docs.github.com/en/billing/concepts/product-billing/github-actions ，读取于 2026-10-01）。
- 公开仓库使用标准托管运行器免费，self-hosted runner 的使用也免费（来源：同一文件第 24 行）。公开仓库这一条不适用于 Yudao，因为仓库是私有仓库（来源：这台电脑上运行 `gh api repos/bender2333/yudao`，返回 `"private": true`，2026-10-01）。
- 个人方案的额度（来源：github/docs 提交 d45a621 `data/reusables/billing/actions-included-quotas.md` 第 1–4 行，显示在上面的页面中）：

  | 方案 | 每月分钟数 | 产物存储 | 每个仓库的缓存 |
  | --- | --- | --- | --- |
  | GitHub Free | 2,000 | 500 MB | 10 GB |
  | GitHub Pro | 3,000 | 1 GB | 10 GB |

- Team 与 Enterprise 属于组织方案，单人使用的个人账户不涉及（来源：`content/get-started/learning-about-github/githubs-plans.md` 第 26–146 行；页面 https://docs.github.com/en/get-started/learning-about-github/githubs-plans ，读取于 2026-10-01）。
- 标准运行器每分钟价格如下，每个作业的用时按整分钟向上取整（来源：`data/reusables/billing/actions-standard-runner-prices.md` 第 1–8 行、`content/billing/reference/actions-runner-pricing.md` 第 14–16 行；页面 https://docs.github.com/en/billing/reference/actions-runner-pricing ，读取于 2026-10-01）：

  | 运行器 | 每分钟价格 |
  | --- | --- |
  | Linux 1 核 | $0.002 |
  | Linux 2 核 x64 | $0.006 |
  | Linux 2 核 arm64 | $0.005 |
  | Windows 2 核 x64 | $0.010 |
  | Windows 2 核 arm64 | $0.010 |
  | macOS 3 核或 4 核 | $0.062 |

- 官方计费页给出的算例：超出额度的 5,000 分钟中，3,000 分钟 Linux 按每分钟 $0.006 合 $18，2,000 分钟 Windows 按每分钟 $0.010 合 $20，共 $38（来源：github/docs 提交 d45a621 `content/billing/concepts/product-billing/github-actions.md` 第 173–179 行）。同一页写明 Windows 与 macOS 的作业比 Linux 的作业费用更高（同一文件第 157 行）。
- 由上表价格计算的比值（官方文档没有直接写出倍数，这里只做除法）：Windows 2 核 x64 每分钟价格是 Linux 2 核 x64 的 1.67 倍（0.010 ÷ 0.006），macOS 3 核或 4 核是 10.3 倍（0.062 ÷ 0.006）；2026-01-01 以前这两个比值是 2.0 倍（0.016 ÷ 0.008）与 10 倍（0.080 ÷ 0.008）。
- 2026-01-01 以前的标准运行器价格为 Linux 2 核 $0.008、Windows 2 核 $0.016、macOS $0.080，文档在 2026-01-05 的提交中改为现价（来源：github/docs 提交 260144b4be 对 `data/reusables/billing/actions-standard-runner-prices.md` 的修改）。
- 原名「Actions minute multipliers」的参考页在 2025-10-30 改名为「Actions runner pricing」，旧地址 `/billing/reference/actions-minute-multipliers` 转到新页面（来源：github/docs 提交 3d77b7e3ca；`actions-runner-pricing.md` 第 10–11 行）。
- 2025-12-16 的公告（来源：https://github.blog/changelog/2025-12-16-coming-soon-simpler-pricing-and-a-better-experience-for-github-actions/ 、https://github.blog/changelog/2026-01-01-reduced-pricing-for-github-hosted-runners-usage/ 、https://github.com/resources/insights/2026-pricing-changes-for-github-actions ，均读取于 2026-10-01）：
  - 2026-01-01 起托管运行器降价最多 39%，免费分钟数不变；2026-01-01 的更新日志写明降价已经生效。
  - 原定 2026-03-01 起对私有仓库的 self-hosted runner 每分钟收取 $0.002 平台费，公告页面顶部的更新写明这一项推迟。
- 同一公告的问答写明，Linux、Windows、macOS 标准运行器按列表价格消耗免费额度（来源：同上）。
- 账户没有有效的付款方式时，额度用完后停止使用。larger runner 总是计费，不能使用方案中的免费分钟数（来源：`github-actions.md` 第 131–139 行；`actions-runner-pricing.md` 第 68 行；`data/reusables/billing/default-over-quota-behavior.md` 第 1–3 行）。
- 私有仓库中 Copilot code review 也消耗 Actions 分钟数（来源：`github-actions.md` 第 34–41 行）。
- 存储规则（来源：`github-actions.md` 第 43–52、112–117、163–171 行）：
  - 产物与 GitHub Packages 共用同一份存储额度；
  - 缓存每个仓库另有 10 GB；
  - 存储按小时累计；
  - 超出部分的价格为共用存储每 GB 每月 $0.25、Actions 缓存每 GB 每月 $0.07；
  - 工作流日志与作业摘要不计入产物存储。
- Pro 方案的共用存储有两个数字：Actions 计费页的表格写 1 GB，GitHub Packages 计费页与方案介绍页写 2 GB（来源：`actions-included-quotas.md` 第 4 行；`content/billing/concepts/product-billing/github-packages.md` 第 45–61 行，页面 https://docs.github.com/en/billing/concepts/product-billing/github-packages ；`githubs-plans.md` 第 45–52 行；读取于 2026-10-01）。
- 产物与日志默认保留 90 天，私有仓库可以设为 1 到 400 天（来源：github/docs 提交 d45a621 `data/reusables/actions/about-artifact-log-retention.md` 第 1–21 行）。

### 7.2 Release 资源的下载

- 对仓库有读取权限的人可以查看 release。每个 release 最多 1000 个资源文件，每个文件小于 2 GiB，总大小与流量没有限制（来源：https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases ，读取于 2026-10-01）。
- REST 接口 `GET /repos/{owner}/{repo}/releases/assets/{asset_id}`（来源：https://docs.github.com/en/rest/releases/assets ，读取于 2026-10-01）：
  - 在浏览器中，使用响应里的 `browser_download_url`；
  - 在程序中，把请求头 `Accept` 设为 `application/octet-stream`，接口会重定向（302）或直接返回内容（200），客户端需要处理这两种情况。
- fine-grained personal access token：下列接口需要仓库权限 "Contents" 的 read，文档说明这些权限用于访问私有资源（来源：https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens ，读取于 2026-10-01）：
  - `GET .../releases`
  - `GET .../releases/latest`
  - `GET .../releases/tags/{tag}`
  - `GET .../releases/{release_id}`
  - `GET .../releases/{release_id}/assets`
  - `GET .../releases/assets/{asset_id}`
- classic token：`repo` scope 对公开与私有仓库给出完整的读写权限；`public_repo` 只限公开仓库；scope 列表中没有只读私有仓库代码的 scope（来源：https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps ，读取于 2026-10-01）。
- 这台电脑上的实际请求：未登录访问 `https://api.github.com/repos/bender2333/yudao/releases` 与 `https://github.com/bender2333/yudao/releases` 都返回 404。使用已登录的 `gh api` 请求同一接口返回成功，结果为 0 个 release（来源：这台电脑上运行 curl 与 `gh api`，2026-10-01）。
- `gh release download [<tag>]` 的用法（来源：https://cli.github.com/manual/gh_release_download ，读取于 2026-10-01；这台电脑上运行 `gh release download --help`，gh 2.101.0）：
  - 不写标签时下载最新 release，这时必须给出 `--pattern` 或 `--archive`；
  - `-p/--pattern`：按 glob 选择文件，可以给出多次；
  - `-D/--dir`：指定目录，默认当前目录；
  - `-O/--output`：把单个文件写到指定位置；
  - `--clobber`：覆盖同名文件；
  - `--skip-existing`：跳过已有的同名文件；
  - `-A/--archive`：下载 zip 或 tar.gz 格式的源代码；
  - `-R/--repo [HOST/]OWNER/REPO`：指定仓库。
- gh 的认证（来源：https://cli.github.com/manual/gh_auth_login ，读取于 2026-10-01；这台电脑上运行 `gh help environment`）：
  - `gh auth login` 默认使用浏览器流程，令牌保存在系统凭据存储中，无法使用时写入明文文件；
  - `--with-token` 从标准输入读取 classic token，最少需要 `repo`、`read:org`、`gist` 三个 scope；
  - 手册写明 fine-grained token 优先通过 `GH_TOKEN` 提供；
  - `GH_TOKEN`、`GITHUB_TOKEN`（按这个优先顺序）优先于已保存的凭据。
- 这台电脑上 gh 为 2.101.0（2026-09-15 发布），以 bender2333 登录，令牌保存在 keyring，Git 操作协议为 ssh（来源：这台电脑上运行 `gh --version`、`gh auth status`，2026-10-01）。

### 7.3 第 6、7 节未能核实的事项

- 2026 年起 Windows 运行器的分钟数怎样从免费额度中扣除：现行 Actions 计费文档只列每分钟价格，没有写出扣除规则；公告只写「按列表价格消耗」。`content/actions/how-tos/monitor-workflows/view-job-execution-time.md` 与 `data/reusables/actions/actions-usage-metrics-not-billing-metrics.md` 仍提到 "minute multipliers"，链接指向按分钟价格的一节。已查阅 github/docs 提交 d45a621 的计费页、价格参考页、方案页；在 github/docs 中搜索 "multiplier"、"included minutes"、"list price"；2025-12-16 与 2026-01-01 的更新日志；Executive Insights 页面。
- Pro 方案共用存储是 1 GB 还是 2 GB：两处官方文档数字不同，没有找到说明以哪一处为准的文字。
- 从普通 `http://` 直接地址安装 wheel：uv 文档没有直接说明这种写法，只有上面 `allow-insecure-host` 的说明与测试中的 http 包索引；按规则没有运行安装命令验证。
- 带令牌请求私有仓库的 `browser_download_url`（`https://github.com/<owner>/<repo>/releases/download/...`）的行为：Yudao 仓库目前没有 release，无法实际请求；REST 文档只写在浏览器中使用这个地址。
- uv.exe 中编入的第三方 Rust crate 的许可证清单是否随发布提供：发布配置关闭了自动附带文件，仓库根目录没有第三方许可证清单；没有下载发布压缩包查看内容。
