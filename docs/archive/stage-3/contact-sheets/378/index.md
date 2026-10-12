# 截图联系表 · 工单 #378

原型 v9 与真实系统的同一个页面并排。每张联系表六行：1440×900 与 1920×1080 两种窗口乘设备像素比 1、1.25、1.5；
每行左侧是原型 v9，右侧是真实系统，行尾附两侧按原始像素显示的局部。

真实系统一侧用端到端后端（`client/tests/e2e/backend.py` 的 default 预置：真实接口层、应用层与事件日志，
模型回答由 FakeAdapter 给出）；页面清单里的预置项目名在运行时换成服务端生成的项目标识。
机器、运行、工具与恢复四个页面在真实系统里当前是占位内容（由工单 #378、#380 填入），联系表照拍占位画面。

## 浅色

### 首页（含决定卡片）（home）

![首页（含决定卡片） · light](home-light.png)

- 原型 v9 路由：`#/home`（档位 `ui`，用原型自带的示例数据）
- 真实系统路由：`#/home`（系统页，不选项目）
- 行数：6 · 图片体积：1.08 MB

### 机器（machines）

![机器 · light](machines-light.png)

- 原型 v9 路由：`#/sys/machines`（档位 `3.2C`，用原型自带的示例数据）
- 真实系统路由：`#/sys/machines`（系统页，不选项目）
- 行数：6 · 图片体积：0.58 MB

### 运行（runtime）

![运行 · light](runtime-light.png)

- 原型 v9 路由：`#/sys/runtime`（档位 `3.4A`，用原型自带的示例数据）
- 真实系统路由：`#/sys/runtime`（系统页，不选项目）
- 行数：6 · 图片体积：0.54 MB

### 工具（tools）

![工具 · light](tools-light.png)

- 原型 v9 路由：`#/sys/tools`（档位 `3.2B`，用原型自带的示例数据）
- 真实系统路由：`#/sys/tools`（系统页，不选项目）
- 行数：6 · 图片体积：0.78 MB

## 深色

### 首页（含决定卡片）（home）

![首页（含决定卡片） · dark](home-dark.png)

- 原型 v9 路由：`#/home`（档位 `ui`，用原型自带的示例数据）
- 真实系统路由：`#/home`（系统页，不选项目）
- 行数：6 · 图片体积：1.08 MB

### 机器（machines）

![机器 · dark](machines-dark.png)

- 原型 v9 路由：`#/sys/machines`（档位 `3.2C`，用原型自带的示例数据）
- 真实系统路由：`#/sys/machines`（系统页，不选项目）
- 行数：6 · 图片体积：0.57 MB

### 运行（runtime）

![运行 · dark](runtime-dark.png)

- 原型 v9 路由：`#/sys/runtime`（档位 `3.4A`，用原型自带的示例数据）
- 真实系统路由：`#/sys/runtime`（系统页，不选项目）
- 行数：6 · 图片体积：0.54 MB

### 工具（tools）

![工具 · dark](tools-dark.png)

- 原型 v9 路由：`#/sys/tools`（档位 `3.2B`，用原型自带的示例数据）
- 真实系统路由：`#/sys/tools`（系统页，不选项目）
- 行数：6 · 图片体积：0.78 MB

## 重新生成

```
cd client && npm run build:pages
node scripts/build-page-contact-sheet.mjs --issue 378
node scripts/build-page-contact-sheet.mjs --issue 378 --pages home,models --themes light,dark
```

页面清单与截图矩阵：`client/scripts/page-contact-sheet-pages.ts`（单元测试 `client/tests/unit/page-contact-sheet.test.ts`）。
原始整页截图写在 `.tmp/contact-sheet-raw/378/`，被 git 忽略。
