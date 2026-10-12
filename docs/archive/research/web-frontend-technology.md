# 游戏化 Web 界面的技术调研

日期：2026-09-25。服务的需求：[D30 游戏化的 Web 界面与界面实现](../requirements/web-game-frontend.md)。原型：[界面原型 v7](../prototypes/v7/design.md)。

## 1. 调研问题

1. 已有的把 AI agent 做成游戏角色的项目用了什么技术，怎样把 agent 的活动映射成角色的行为。
2. 游戏中让角色状态容易管理的做法，重点是《缺氧》。
3. Web 2D 渲染库、行为状态机、补间动画、像素字体的现状与许可。
4. 成熟项目怎样让界面与后端解耦：接口定义、客户端类型、事件流与客户端状态同步。
5. Yudao 现有后端与界面在解耦方面的差距。

## 2. 参考项目

### 2.1 Pixel Agents

VS Code 扩展与独立 Web 应用，把每个 Claude Code 终端显示成像素办公室里的一个小人（[仓库](https://github.com/pablodelucca/pixel-agents)，MIT 许可）。

- 技术：界面为 React 19 与 Vite，办公室用 Canvas 2D 绘制；服务端为 Fastify；单元测试用 Vitest 与 Node 自带的测试，端到端测试用 Playwright。
- 数据来源：以 Claude Code 的 hook 事件（`SessionStart`、`PreToolUse`、`PermissionRequest`、`Stop`）为主，扫描 JSONL 会话记录为后备；两条路径都转换成统一的 `AgentEvent`，由 `AgentRuntime` 处理。
- 活动到动画：写入对应打字，读取对应阅读，执行命令有自己的动画，等待输入与请求权限用气泡表示；小人在空闲、走动、坐下、打字、阅读、等待之间由状态机切换；走动用广度优先搜索寻路。
- 结构：`core/`（事件模型、适配器、传输、模式定义，没有运行时副作用）、`server/`、`adapters/vscode/`、`webview-ui/`；素材放在 `webview-ui/public/assets/`，家具用清单文件描述精灵、朝向、状态与动画帧。

### 2.2 AI Town

a16z 的开源虚拟小镇，AI 角色在其中生活与交谈（[架构说明](https://github.com/a16z-infra/ai-town/blob/main/ARCHITECTURE.md)，MIT 许可）。

- 技术：界面用 PixiJS 与 pixi-react 渲染；后端为 Convex。
- 模拟与渲染分开：服务端的游戏逻辑与引擎推进状态，客户端只读取状态并渲染。
- 平滑移动：引擎每秒写一次状态，但记录这一秒内数值的变化历史（historical object），客户端按历史回放位置，得到连续的动作。
- 用户输入写入输入表，带递增编号与时间，由引擎按顺序处理。

## 3. 《缺氧》的做法

### 3.1 覆盖层

同一张地图上有 16 种覆盖层（[官方 wiki](https://oxygennotincluded.wiki.gg/wiki/Overlays)）：氧气、电力、温度、材料、光照、液体管道、气体管道、装饰、细菌、农业、房间、防护服、自动化、运输轨道、辐射、优先级。每种都有快捷键与工具栏按钮；部分覆盖层要完成对应的研究才出现。

### 3.2 小人的状态与管理

- 小人头顶显示状态图标，例如开心、愤怒、困倦、饥饿、要上厕所、冷、热、无法呼吸、压力大（[官方 wiki](https://oxygennotincluded.wiki.gg/wiki/Duplicant)）。
- 需求有明确的阈值：体力为 0 时倒下，睡到 100% 才起来；热量在 3000 千卡时饥饿、1000 千卡时报警。
- 差事分 15 类（建造、挖掘、农业、研究等），用「小人 × 差事类型」的优先级矩阵管理；另有日程表管理工作与休息时间。

### 3.3 用到 Yudao 上

| 缺氧的做法 | Yudao 中的对应 | 事实来源 |
| --- | --- | --- |
| 覆盖层 | 楼层画面上的交接流向、用量与上下文占用、等待关系、待核实与风险、语义记录等视角，每种对应一个查询 | 各查询的结果 |
| 研究后才出现的覆盖层 | 后端提供某项能力之后，界面才出现对应的视角与区块 | 后端的能力清单 |
| 头顶状态图标 | 角色头顶显示最要紧的状态项：等待模型响应、重试中、上下文将满、等待其他部门回答、待核实、待恢复 | 调用尝试、协作请求、恢复观察状态 |
| 有阈值的需求 | 上下文占用率、时间上限的已用比例、重试的第几次 | 调用目标的容量、run 的时间上限、尝试事件 |
| 优先级矩阵 | 部门或角色 × 任务类型：谁能做什么、正在做什么 | 工具授权、角色任务（Stage 4） |
| 空闲时自由活动 | 部门未工作时小人喝茶、走动 | 部门状态为空闲 |

缺氧的需求值由游戏模拟产生；Yudao 的每个状态项都必须对应可测量的事实，只借用呈现方式。

## 4. 渲染与配套库

| 用途 | 库 | 现状 |
| --- | --- | --- |
| 2D 渲染 | PixiJS | v8 为当前主版本，最新版 8.21.0，2026 年保持每月发布；支持 WebGL 与 WebGPU，8.16.0 起有实验性的 Canvas 渲染器（[发布记录](https://github.com/pixijs/pixijs/releases)、[8.16.0 说明](https://pixijs.com/blog/8.16.0)） |
| React 集成 | @pixi/react v8 | 由 PixiJS 团队维护，只支持 React 19，围绕 `extend()` 重写（[发布说明](https://pixijs.com/blog/pixi-react-v8-live)） |
| 完整游戏框架 | Phaser | 4.0 于 2026 年 4 月 10 日发布，稳定版 4.1.0（[下载页](https://phaser.io/download/release/v4.1.0)）；自带场景、物理、输入与游戏循环，适合整页就是一个游戏的应用 |
| 行为状态机 | XState | v5，最新版 5.33.2，MIT 许可，无依赖；以状态机、层级状态图与 actor 模型组织逻辑（[仓库](https://github.com/statelyai/xstate)） |
| 补间动画 | GSAP | 2025 年 4 月起全部免费，含原来收费的插件；许可为 Standard「No Charge」License，禁止用于与 Webflow 竞争的无代码动画制作工具，其他网站与 Web 应用都可以使用（[许可](https://gsap.com/community/standard-license/)） |
| 中文像素字体 | Fusion Pixel Font（缝合像素字体） | 字体为 SIL OFL 1.1，构建脚本为 MIT；8、10、12 像素三种尺寸，覆盖《通用规范汉字表》（[仓库](https://github.com/TakWolf/fusion-pixel-font)） |
| 网格寻路 | — | 常用的 `pathfinding` 最后一次发布在十年前（0.4.18），其余 TypeScript 库处于早期阶段；Pixel Agents 自己实现广度优先搜索 |
| 镜头 | pixi-viewport | PixiJS 社区维护，已迁移到 PixiJS v8，提供拖动、缩放、跟随与边界（[仓库](https://github.com/pixijs-userland/pixi-viewport)） |
| 声音 | @pixi/sound | PixiJS 官方，6.0.1 支持 v8，基于 WebAudio；最近一次发布在两年前（[仓库](https://github.com/pixijs/sound)） |
| 无障碍基础组件 | Base UI | MUI 团队维护，2025 年 12 月发布 1.0 稳定版，35 个无障碍组件；部分 Radix 原作者在该团队；shadcn/ui 自 2026 年 7 月起新项目默认使用它（[发布记录](https://github.com/mui/base-ui/releases)、[shadcn/ui 说明](https://ui.shadcn.com/docs/changelog/2026-07-base-ui-default)） |

## 5. 界面与后端解耦：OpenCode 的做法

参考提交 `0027387`（`C:\project\codes\opencode`）。

- **接口定义**：服务端用带类型的接口定义生成 OpenAPI，`packages/opencode/src/server/server.ts:67` 的 `openapi()` 返回 `OpenApi.fromApi(PublicApi)`；`packages/opencode/test/server/httpapi-public-openapi.test.ts` 检查公开的 OpenAPI。
- **客户端 SDK**：`packages/sdk/js/src/v2/gen/` 下的 `sdk.gen.ts` 与 `types.gen.ts` 由 OpenAPI 生成（hey-api），事件类型是一个带类型的联合（`Event`，含 `EventSessionUpdated`、`EventMessagePartUpdated` 等），Web、桌面与 TUI 共用同一份 SDK。
- **事件流补齐**：`sdk.gen.ts:5749–5775` 的会话事件流 `GET /api/session/{sessionID}/event?after=`，先补发某个序号之后的持久事件，再继续推送新事件。
- **客户端状态同步**：`packages/app/src/context/global-sync/queue.ts` 的刷新队列先重新载入全局状态，再逐个刷新各实例；断线重连后按这个顺序恢复。

## 6. Yudao 现状

- 后端接口层 `harness/api/` 使用 FastAPI，路由、OpenAPI 与能力清单都由应用层 `harness/app/` 的注册表生成，返回 JSON，另有统一事件流 `GET /api/events`（按 `Last-Event-ID` 续传）。
- 接口层只导入应用层；应用层只导入控制核心的公开接口、知识层查询与 Provider 模块的管理接口。查询只读读取模型，命令经写入口修改。旧 Web 控制台（`harness/web/` 与它的一批旧路由）已经删除（[应用层与接口层设计说明](../design/app-and-interface.md)第 7.1、7.3 节）。
- 界面由桌面客户端提供，后端不返回界面文件；客户端使用 React 19、TypeScript、Vite、PixiJS 8、XState 5 与 GSAP（[ADR-0015](../adr/0015-desktop-client-and-http-contracts.md)）。
- 依赖：接口层使用 FastAPI 与 uvicorn，合同使用 pydantic 2；客户端接口类型由 OpenAPI 快照生成（`@hey-api/openapi-ts`）。

## 7. 对 Yudao 的建议

| 事项 | 建议 | 理由与限制 |
| --- | --- | --- |
| 界面框架 | React 19、TypeScript、Vite | 使用最广，AI 执行者生成与修改最可靠；Pixel Agents 用同样的组合；@pixi/react v8 要求 React 19 |
| 画面渲染 | PixiJS v8 | 只负责渲染，可以在一个应用里嵌入多个画面；WebGL 与 WebGPU 性能足够支撑大量小人与粒子；AI Town 用它渲染同类画面。Phaser 自带游戏循环与场景管理，更适合整页就是游戏的应用 |
| 画面与 React 的连接 | 画面对象用命令式 PixiJS 编写，React 只负责挂载与传入模型 | 画面逻辑不依赖 React 的渲染周期，便于单独测试，也能在动作图鉴与回放中复用；@pixi/react 只在需要把 React 组件放进画面时使用 |
| 角色行为 | XState v5 状态机 | 每个角色的行为是一张状态图，可以用 Stately 可视化，人能审阅；状态迁移由事实触发 |
| 补间动画 | GSAP | 免费且可商用，时间线功能适合编排一次动作的多个步骤；许可只禁止制作与 Webflow 竞争的无代码动画工具 |
| 寻路 | 自己实现网格上的广度优先搜索 | 没有仍在维护的成熟库；房间是小网格，Pixel Agents 用同样的做法 |
| 画面中的中文 | Fusion Pixel Font，用 PixiJS 的位图字体按需生成字形 | OFL 许可允许随应用分发；像素风格与画面一致 |
| 接口合同 | 后端用 pydantic 定义查询、命令与事件的模型，导出 OpenAPI；前端由 OpenAPI 生成类型 | 与 OpenCode 由类型定义生成接口说明、再生成客户端的做法一致；pydantic 已在环境中 |
| 事件流 | 保留 SSE，事件带序号，客户端断线后按序号补齐，发现缺口时重新载入 | 现有实现已按 `Last-Event-ID` 续传，与 OpenCode 的 `after` 参数同一思路 |
| 平滑动作 | 画面按事件与状态插值播放，事件间隔大时也连续 | AI Town 用历史数值回放得到连续动作 |

## 8. 来源

- Pixel Agents：https://github.com/pablodelucca/pixel-agents
- AI Town 架构说明：https://github.com/a16z-infra/ai-town/blob/main/ARCHITECTURE.md
- 缺氧覆盖层：https://oxygennotincluded.wiki.gg/wiki/Overlays
- 缺氧小人：https://oxygennotincluded.wiki.gg/wiki/Duplicant
- PixiJS 发布记录：https://github.com/pixijs/pixijs/releases ；8.16.0：https://pixijs.com/blog/8.16.0
- @pixi/react v8：https://pixijs.com/blog/pixi-react-v8-live
- Phaser 4.1.0：https://phaser.io/download/release/v4.1.0
- XState：https://github.com/statelyai/xstate
- GSAP 许可：https://gsap.com/community/standard-license/ ；免费公告：https://webflow.com/blog/gsap-becomes-free
- Fusion Pixel Font：https://github.com/TakWolf/fusion-pixel-font
- pathfinding（npm）：https://www.npmjs.com/package/pathfinding
- OpenCode 本地仓库提交 `0027387`：`packages/opencode/src/server/server.ts`、`packages/sdk/js/src/v2/gen/sdk.gen.ts`、`packages/app/src/context/global-sync/queue.ts`、`packages/opencode/test/server/httpapi-public-openapi.test.ts`
