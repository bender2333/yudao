# Yudao 网页界面

React + TypeScript + Vite 构建的页面文件，由 Yudao 服务提供（[ADR-0032](../docs/adr/0032-interface-served-as-web-pages.md)、[应用层与接口层设计说明](../docs/design/app-and-interface.md)）。
界面代码在这个独立目录中，构建产物经发布脚本复制进 `harness/release_assets/`，随 wheel 一起发布。

使用的技术：React 19、TypeScript、Vite、
[`@hey-api/openapi-ts`](https://www.npmjs.com/package/@hey-api/openapi-ts) 生成接口类型、
npm [`eventsource`](https://www.npmjs.com/package/eventsource)（传入自定义 fetch）、Playwright 跑浏览器端到端测试。

## 目录

```
src/renderer/    页面：外壳、连接设置、视图同步（React）
  src/api/       由 /openapi.json 生成的接口类型与记录生成所用接口版本的文件
  src/contract/  连接、能力清单核对、事件流、视图同步、查询与命令的调用
  src/shell/     左侧栏、顶栏、项目标签与路径
  src/views/     连接设置页（首页、项目页面与像素画面由各自的工单实现）
scripts/         generate-api.mjs（生成接口类型）
tests/unit/      不需要网络的单元测试（node --test）
tests/e2e/       Playwright 启动 Chromium，连接真实后端（FakeAdapter 驱动的服务）
```

## 常用命令

```bash
npm ci                     # 按锁文件安装依赖
npm run generate:api       # 由 harness/tests/openapi/openapi.json 生成接口类型并记录接口版本
npm run build:pages        # Vite 构建页面文件到 out/renderer（发布脚本调用）
npm run typecheck          # tsc 类型检查
npm test                   # 单元测试（node --test）
npm run test:e2e           # 端到端测试（Playwright 启动 Chromium；需要仓库项目的 Python 环境）
```

端到端测试用 `uv run python client/tests/e2e/backend.py` 启动真实后端；先在仓库根目录运行一次
`uv sync --frozen`。

## 开发方式

```bash
cd client && npm ci
npm run generate:api       # 接口类型与后端快照保持一致
npm run build:pages        # 构建出 out/renderer，用后端提供它联调
```

或者直接用 Vite 开发服务器打开页面联调后端（端口按后端实际地址）：

```bash
cd client && npx vite --config vite.pages.config.ts
```

## 接口版本

`GET /api/capabilities` 的 `deployment.api_version` 是接口版本；页面构建时把它记录在
`src/renderer/src/api/interface-version.ts`。
