# Yudao 桌面客户端

Electron 外壳、生成的接口类型、连接设置与事件流同步（[ADR-0015](../docs/adr/0015-desktop-client-and-http-contracts.md)、
[应用层与接口层设计说明](../docs/design/app-and-interface.md)第 5.7、6 节）。界面代码在这个独立目录中，后端不提供它。

使用的技术：Electron 44、React 19、TypeScript、Vite（electron-vite）、
[`@hey-api/openapi-ts`](https://www.npmjs.com/package/@hey-api/openapi-ts) 生成接口类型、
npm [`eventsource`](https://www.npmjs.com/package/eventsource)（传入自定义 fetch）、Playwright 启动 Electron。

## 目录

```
src/main/        主进程：yudao:// 协议、窗口、常驻托盘、连接设置、本机服务管理与更新
src/preload/     预加载脚本：对渲染进程暴露受限的接口（连接设置、通知、托盘数量、更新）
src/renderer/    渲染进程：外壳、连接设置、更新页、视图同步（React）
  src/api/       由 /openapi.json 生成的接口类型与记录生成所用接口版本的文件
  src/contract/  连接、能力清单核对、事件流、视图同步、查询与命令的调用
  src/shell/     左侧栏、顶栏、项目标签与路径
  src/views/     连接设置与更新页（首页、项目页面与像素画面由各自的工单实现）
scripts/         generate-api.mjs（生成接口类型）、make-tray-icons.mjs（生成托盘与应用图标）、
                 build-installer.mjs（构建 NSIS 安装程序、blockmap 与 latest.yml）
tests/unit/      不需要 Electron 与网络的单元测试（node --test）
tests/e2e/       Playwright 启动 Electron，连接真实后端（FakeAdapter 驱动的服务）
```

## 常用命令

```bash
npm ci                     # 按锁文件安装依赖
npm run generate:api       # 由 harness/tests/openapi/openapi.json 生成接口类型并记录接口版本
npm run build              # electron-vite 构建到 out/
npm run build:installer    # 构建 NSIS 安装程序、blockmap 与 latest.yml（可用环境变量改写 appId、产品名与版本）
npm run typecheck          # tsc 类型检查
npm test                   # 单元测试（node --test）
npm run test:e2e           # 端到端测试（Playwright 启动 Electron；需要仓库项目的 Python 环境）
```

端到端测试用 `uv run python client/tests/e2e/backend.py` 启动真实后端；先在仓库根目录运行一次
`uv sync --frozen`。本机服务的启动与停止、托盘菜单与登录时启动见 #207；安装包与更新页见 #208。

## 安装包与更新

`scripts/build-installer.mjs` 用 electron-builder 26 系列构建 NSIS 按用户安装包（不需要管理员权限），
生成 `Yudao-Setup-<版本>.exe`、`.blockmap` 与更新清单 `latest.yml`。appId、产品名、安装目录名与
发布版本号可以用环境变量改写（`YUDAO_APP_ID`、`YUDAO_PRODUCT_NAME`、`YUDAO_SETUP_BASENAME`、
`YUDAO_VERSION`、`YUDAO_API_VERSION`），测试构建因此不影响用户已经安装的那一份。

客户端连接时读取能力清单；接口版本与它构建时记录的版本不同则显示更新页，按钮「更新客户端」经主进程的
`electron-updater`（generic 提供方）从已连接的地址加 `/client-update/` 下载同版本的安装程序并更新
（[设计说明](../docs/design/client-packaging-and-release.md)第 5 节）。不签名，安装程序不带
「来自网络」标记，不出现 SmartScreen 警告（第 7 节）。

## 接口版本

`GET /api/capabilities` 的 `deployment.api_version` 是接口版本；客户端构建时把它记录在
`src/renderer/src/api/interface-version.ts`。连接时两者不同则只显示更新页，不打开页面、不执行命令。
