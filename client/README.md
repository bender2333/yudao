# Yudao 桌面客户端

Electron 外壳、生成的接口类型、连接设置与事件流同步（[ADR-0015](../docs/adr/0015-desktop-client-and-http-contracts.md)、
[应用层与接口层设计说明](../docs/design/app-and-interface.md)第 5.7、6 节）。界面代码在这个独立目录中，后端不提供它。

使用的技术：Electron 44、React 19、TypeScript、Vite（electron-vite）、
[`@hey-api/openapi-ts`](https://www.npmjs.com/package/@hey-api/openapi-ts) 生成接口类型、
npm [`eventsource`](https://www.npmjs.com/package/eventsource)（传入自定义 fetch）、Playwright 启动 Electron。

## 目录

```
src/main/        主进程：yudao:// 协议、窗口、常驻托盘、连接设置
src/preload/     预加载脚本：对渲染进程暴露受限的接口（连接设置、通知、托盘数量）
src/renderer/    渲染进程：外壳、连接设置、更新页、视图同步（React）
  src/api/       由 /openapi.json 生成的接口类型与记录生成所用接口版本的文件
  src/contract/  连接、能力清单核对、事件流、视图同步、查询与命令的调用
  src/shell/     左侧栏、顶栏、项目标签与路径
  src/views/     连接设置与更新页（首页、项目页面与像素画面由各自的工单实现）
scripts/         generate-api.mjs（生成接口类型）、make-tray-icons.mjs（生成托盘图标）
tests/unit/      不需要 Electron 与网络的单元测试（node --test）
tests/e2e/       Playwright 启动 Electron，连接真实后端（FakeAdapter 驱动的服务）
```

## 常用命令

```bash
npm ci                     # 按锁文件安装依赖
npm run generate:api       # 由 harness/tests/openapi/openapi.json 生成接口类型并记录接口版本
npm run build              # electron-vite 构建到 out/
npm run typecheck          # tsc 类型检查
npm test                   # 单元测试（node --test）
npm run test:e2e           # 端到端测试（Playwright 启动 Electron；需要仓库项目的 Python 环境）
```

端到端测试用 `uv run python client/tests/e2e/backend.py` 启动真实后端；先在仓库根目录运行一次
`uv sync --frozen`。客户端安装包与更新由 #208 实现，本机服务的启动与停止、托盘菜单由 #207 实现。

## 接口版本

`GET /api/capabilities` 的 `deployment.api_version` 是接口版本；客户端构建时把它记录在
`src/renderer/src/api/interface-version.ts`。连接时两者不同则只显示更新页，不打开页面、不执行命令。
