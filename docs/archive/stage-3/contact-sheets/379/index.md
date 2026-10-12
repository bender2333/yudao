# 截图联系表 · 工单 #379

原型 v9 与真实系统的同一个页面并排。每张联系表六行：1440×900 与 1920×1080 两种窗口乘设备像素比 1、1.25、1.5；
每行左侧是原型 v9，右侧是真实系统，行尾附两侧按原始像素显示的局部。

真实系统一侧用端到端后端（`client/tests/e2e/backend.py` 的 default 预置：真实接口层、应用层与事件日志，
模型回答由 FakeAdapter 给出）；页面清单里的预置项目名在运行时换成服务端生成的项目标识。
机器、运行、工具与恢复四个页面在真实系统里当前是占位内容（由工单 #378、#380 填入），联系表照拍占位画面。

## 浅色

### 项目概览与楼层（overview）

![项目概览与楼层 · light](overview-light.png)

- 原型 v9 路由：`#/p/p-metro/overview?w=w-metro-transfer`（档位 `ui`，用原型自带的示例数据）
- 真实系统路由：`#/p/proj_281f3eb05eb540ec/overview` · 预置项目「交付历史」
- 行数：6 · 图片体积：1.29 MB

## 深色

### 项目概览与楼层（overview）

![项目概览与楼层 · dark](overview-dark.png)

- 原型 v9 路由：`#/p/p-metro/overview?w=w-metro-transfer`（档位 `ui`，用原型自带的示例数据）
- 真实系统路由：`#/p/proj_281f3eb05eb540ec/overview` · 预置项目「交付历史」
- 行数：6 · 图片体积：1.29 MB

## 回放中的一帧

原型 v9 没有回放位置参数，回放中的一帧不与原型并排，单独拍真实系统：
概览页拖到时间轴上最早的一格，回放状态由路径上的 `?at=` 给出（工单 #296 的设计说明第 3.3 节）。

### 概览回放（overview-replay）

![概览回放 · light](overview-replay-light.png)

![概览回放 · dark](overview-replay-dark.png)

- 真实系统路由：`#/p/<预置项目「交付历史」>/overview?at=<最早一个刻度>`
- 窗口 1440×900 · 设备像素比 1 · 整页截图

## 重新生成

```
cd client && npm run build:pages
node scripts/build-page-contact-sheet.mjs --issue 379
node scripts/build-page-contact-sheet.mjs --issue 379 --pages home,models --themes light,dark
node scripts/shot-replay-frame.mjs --issue 379
```

页面清单与截图矩阵：`client/scripts/page-contact-sheet-pages.ts`（单元测试 `client/tests/unit/page-contact-sheet.test.ts`）。
原始整页截图写在 `.tmp/contact-sheet-raw/379/`，被 git 忽略。
