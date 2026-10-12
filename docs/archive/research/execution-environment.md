# 执行环境服务调研

日期：2026-09-29。用途：给 [D29](../requirements/remote-execution.md)「设计中待确定的内容」与 [执行环境服务设计说明](../design/execution-environment.md)提供一手来源：本机容器使用的工具与镜像、执行代理的安装与服务管理、心跳的间隔与超时、工作区内容的传输方式。本次阅读官方文档与源码，没有安装或运行 Docker、Podman、执行代理或服务包装工具。

## 阅读范围

| 来源 | 版本或提交 | 读到的内容 |
| --- | --- | --- |
| Yudao | `82b0f34` | `harness/actions.py`、`harness/environment.py`、`harness/workspace.py`、`harness/public_tree.py`、`harness/tree_archive.py`，以及 `engine.py`、`orchestrator.py` 中调用执行环境的位置 |
| docker-py（PyPI `docker`） | 7.2.0（2026-07-09），main 提交 `56343ddf8f0c44281e151c2dad016c16cdb8393d` | [容器 API](https://docker-py.readthedocs.io/en/stable/containers.html)、[低层 API](https://docker-py.readthedocs.io/en/stable/api.html)、[客户端](https://docker-py.readthedocs.io/en/stable/client.html)；`pyproject.toml`、`docker/constants.py`、`docker/utils/utils.py` |
| Podman | 文档 latest（2026-09-29 读取） | [podman-system-service](https://docs.podman.io/en/latest/markdown/podman-system-service.1.html)、[Podman for Windows](https://github.com/containers/podman/blob/main/docs/tutorials/podman-for-windows.md)、[RHEL 容器工具 API](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/8/html/building_running_and_managing_containers/using-the-container-tools-api)、[podman-py](https://github.com/containers/podman-py)（5.8.0，main `5dd81b49f35733a27b8051c47e23d3b4c85ea716`） |
| Docker 安装与许可 | 2026-09-29 读取 | [Windows 安装](https://docs.docker.com/desktop/setup/install/windows-install/)、[WSL2 后端](https://docs.docker.com/desktop/features/wsl/)、[Docker Desktop 许可](https://docs.docker.com/subscription/desktop-license/)、[Raspberry Pi OS](https://docs.docker.com/engine/install/raspberry-pi-os/)、[Debian](https://docs.docker.com/engine/install/debian/)、[Ubuntu](https://docs.docker.com/engine/install/ubuntu/) |
| Docker 镜像与存储 | 2026-09-29 读取 | [多平台构建](https://docs.docker.com/build/building/multi-platform/)、[命名卷](https://docs.docker.com/engine/storage/volumes/)、[RUN --mount=type=cache](https://docs.docker.com/reference/dockerfile/#run---mounttypecache)、[构建缓存优化](https://docs.docker.com/build/cache/optimize/)、[python 官方镜像](https://hub.docker.com/_/python) |
| Anthropic 参考实现 | [claude-quickstarts](https://github.com/anthropics/claude-quickstarts/tree/dee71163217524eed07d79d00ffea5a7d02cedda/computer-use-demo) `dee7116` | `computer-use-demo/Dockerfile`、`image/start_all.sh`、`image/entrypoint.sh`、`README.md`；与 [computer use 实现调研](computer-use-implementations.md)读的是同一个提交 |
| OpenCode | `C:\project\codes\opencode` `0027387` | `packages/opencode/src/control-plane/types.ts`、`control-plane/workspace.ts`、`control-plane/adapters/index.ts`、`server/routes/instance/httpapi/handlers/event.ts`、`src/index.ts`、`packages/containers/README.md` |
| OMP | `C:\project\codes\oh-my-pi` `fdfeef1f78` | `packages/coding-agent/src/task/worktree.ts`、`task/isolation-ownership.ts`；在全部 TypeScript 与 Rust 源码中搜索 docker、podman、bwrap、sandbox-exec、landlock |
| Bazel Remote Execution API | [bazelbuild/remote-apis](https://github.com/bazelbuild/remote-apis) `adbf4a2` | `build/bazel/remote/execution/v2/remote_execution.proto` 的 `Execute`、`WaitExecution`、`FindMissingBlobs`、`BatchUpdateBlobs` |
| 心跳 | 2026-09-29 读取 | [Temporal：检测活动失败](https://docs.temporal.io/encyclopedia/detecting-activity-failures)、[Kubernetes 节点](https://kubernetes.io/docs/concepts/architecture/nodes/)、[kubelet 配置](https://kubernetes.io/docs/reference/config-api/kubelet-config.v1beta1/)、[kube-controller-manager](https://kubernetes.io/docs/reference/command-line-tools-reference/kube-controller-manager/)、kubernetes 提交 `f2cd2b7594444925ce243fb5bdb83cb24961584c` 的 `pkg/kubelet/kubelet.go` |
| 服务管理与分发 | 2026-09-29 读取 | [systemd.service](https://man7.org/linux/man-pages/man5/systemd.service.5.html)、[systemd.exec](https://man7.org/linux/man-pages/man5/systemd.exec.5.html)、[NSSM 下载页](https://nssm.cc/download)、[WinSW 发布](https://github.com/winsw/winsw/releases)、[pywin32](https://github.com/mhammond/pywin32)（提交 `9f88183224af4a9c127c0d6d1b3c7d4846124171`）、[shawl](https://github.com/mtkennerly/shawl)、[uv 工具](https://docs.astral.sh/uv/concepts/tools/)、[pipx](https://pipx.pypa.io/stable/) |

## 1. Yudao 现在的执行环境

提交 `82b0f34`：

- 合同类型在 `harness/actions.py`：`Action`（第 26–36 行：动作身份、类别 `read`/`write`/`check`/`command`、工具、部门、输入、前置条件中的树摘要）、`ActionReceipt`（第 39–52 行：`completed`、`failed`、`timeout`、`cancelled`）、`FactsQuery` 与 `WorkspaceFacts`（第 55–118 行：公开树清单与摘要、检查回执、路径的规范形式与种类）。全部是 pydantic 类型，不含进程对象。
- 本机实现 `LocalEnvironment` 在 `harness/environment.py` 第 74–140 行：`perform` 执行动作并交回回执，`cancel` 按动作身份取消（动作开始之前到达的取消使动作不执行），`query` 提供只读查询，`snapshot` 交回带文件内容的公开树。文件工具在第 46–55 行登记，进程工具 `run_check`、`run_command` 在第 56 行登记；定义中的环境工具没有实现时启动失败（第 58–62 行）。
- 进程在新的进程组（Windows）或新的会话（POSIX）中启动（第 466 行起的 `_run_process`），超时或取消时用 `taskkill /T /F` 或 `os.killpg` 结束整个进程树（第 491 行起的 `_kill_process_tree`）。检查与登记命令的回执中写着 `"executor": "host"`（第 394、456 行）。
- `Workspace`（`harness/workspace.py`）负责受限的文件读写；检查在工作区公开树的副本中运行（第 114 行 `check_copy`），检查回执写在工作区内的 `.checks/receipts.jsonl`（第 42、120 行）。
- 公开树的清单格式 `yudao-public-tree-v1`（`harness/public_tree.py` 第 15 行）：目录列表加文件列表，每个文件只有路径、大小与 `sha256:` 内容摘要（第 48–53 行），树摘要是清单的规范摘要（第 56 行）。清单中没有可执行权限。`materialize_tree`（第 159–177 行）只写入新目录并在写完后核对整棵树。
- 封存在控制主机的工件存储中进行：`harness/tree_archive.py` 的 `store_tree` 把每个文件存为一个工件并读回核对，再写清单。
- 调用位置：步骤驱动在工具许可之前查询（`engine.py` 第 474 行）、执行动作（第 492 行）；流程编排在创建 run 时直接写入初始树（`orchestrator.py` 第 279–283 行），每次激活新建一个 `LocalEnvironment`（第 895 行），提案判断前查询（第 959 行），提交时取得带内容的公开树（第 998 行）。前两处直接操作工作区的位置由 #110 改为经过执行环境。

## 2. 本机容器的工具

### 2.1 Docker Engine 与 docker-py

- docker-py 是 Docker 官方的 Python SDK，当前 7.2.0，同步阻塞接口，依赖 `requests` 与 `urllib3`，Windows 上依赖 `pywin32`（`pyproject.toml` 第 33–35 行）。官方没有异步接口，相关 issue [#327](https://github.com/docker/docker-py/issues/327)、[#1171](https://github.com/docker/docker-py/issues/1171) 仍然开放。第三方异步库 aiodocker（aio-libs）最新 v0.27.0（2026-05-27）。
- `containers.run` / `create` 提供本设计需要的全部参数：`mounts`（`docker.types.Mount`，文档称它比 `volumes` 功能更强）、`network_mode`、`mem_limit`、`nano_cpus`、`pids_limit`、`user`、`read_only`、`labels`、`detach`、`auto_remove`。
- `exec_run` 在 `stream=True` 时不返回退出码（`exit_code` 为 `None`），要另外调用 `exec_inspect` 取得；docker exec 的会话随客户端连接存在。
- `put_archive` / `get_archive` 以 tar 流写入与读取容器中的文件，目标路径必须已经存在。
- `docker.from_env()` 读取 `DOCKER_HOST`；没有设置时 Windows 默认连接 `npipe:////./pipe/docker_engine`，其他平台连接 `unix:///var/run/docker.sock`（`docker/constants.py` 第 14–15 行，`docker/utils/utils.py` 第 233–238 行）。默认 API 版本 1.45，最低 1.24（`constants.py` 第 5–6 行）。

### 2.2 Podman

- `podman system service` 提供兼容 Docker v1.40 API 的接口与 Podman 自己的 Libpod 接口；rootless 时 socket 为 `unix://$XDG_RUNTIME_DIR/podman/podman.sock`。文档给出的用法是设置 `DOCKER_HOST` 后运行 docker-compose，没有点名 docker-py。
- Windows 上每台 Podman machine 是一个 WSL2 发行版，需要 Windows 11；默认 rootless，只能使用 1023 以上的端口；Docker API 经命名管道转发，默认 `\\.\pipe\docker_engine`。
- podman-py 5.8.0 的 README 写明「currently under development」，TCP 连接尚未实现。

### 2.3 平台前置条件

| 平台 | 官方说明 |
| --- | --- |
| Windows | Docker Desktop 使用 WSL2 后端：Windows 10 22H2（19045）或 Windows 11 23H2（22631）以上、WSL 2.1.5 以上、CPU 支持 SLAT、8GB 内存、BIOS 开启虚拟化。同一页面一处列出 Enterprise、Pro、Education，另一处写「Windows Home or Education editions only allow you to run Linux containers」，两处说法不一致，原文如此。安装 Docker Desktop 之前要卸载直接装在 WSL 发行版中的 Docker Engine |
| Docker Desktop 许可 | 员工超过 250 人或年收入超过 1000 万美元的企业商业使用需要付费订阅；个人使用、教育、非商业开源与小企业免费；Docker Engine 的开源许可不变 |
| Debian / Ubuntu | Docker Engine 支持 Debian 13、12 与 Ubuntu 26.04、24.04、22.04，架构包括 amd64、arm64、armhf；推荐 apt 仓库安装；convenience script 只用于测试与开发，不用于升级 |
| 树莓派 | Docker Engine v28 是最后一个支持 32 位 Raspberry Pi OS（armhf）的大版本，v29 起不提供 32 位软件包；ARMv6（Pi 1、Zero、Zero W）不再支持；64 位 Raspberry Pi OS 按 Debian 的说明安装 |
| 多架构镜像 | `python:3.12-slim` 提供 amd64 与 arm64/v8 等架构；在各自的机器上本机构建不需要 buildx，发布多架构镜像时使用 `docker buildx build --platform linux/amd64,linux/arm64` |

### 2.4 缓存

- 命名卷的内容独立于容器的生命周期，一直保留到显式删除。Docker 文档没有专门讨论用命名卷保存依赖缓存。
- BuildKit 的 `RUN --mount=type=cache` 在多次构建之间保留缓存，文档要求构建在缓存目录为任意内容时都能工作；pip 示例的目标是 `/root/.cache/pip`，npm 是 `/root/.npm`，apt 使用 `sharing=locked`。

## 3. 参考实现

### 3.1 Anthropic computer-use-demo（`dee7116`）

- `Dockerfile` 第 1 行基础镜像 `ubuntu:22.04`；第 8–17 行安装 Xvfb、xdotool、scrot、imagemagick、mutter、x11vnc；第 55–57 行安装 noVNC 与 websockify；第 60–64 行创建用户 `computeruse` 并给予免密码 sudo；第 97–104 行设置 `WIDTH=1024`、`HEIGHT=768` 与入口脚本。
- `README.md` 第 49–58 行的运行命令：`docker run -e ANTHROPIC_API_KEY -v $HOME/.anthropic:/home/computeruse/.anthropic -p 5900:5900 -p 8501:8501 -p 6080:6080 -p 8080:8080 -it ghcr.io/anthropics/anthropic-quickstarts:computer-use-demo-latest`。宿主只挂载一个设置目录，其他内容都在容器中。
- `README.md` 第 6–16 行的安全说明：使用专用虚拟机或容器并给最小权限，不让模型接触敏感数据，用域名白名单限制上网，有实际后果的决定交给人。第 34 行写明组件之间隔离较弱：代理循环运行在被控制的容器内，同一时间只供一个会话使用。

### 3.2 OpenCode（`0027387`）

- OpenCode 没有容器或沙箱执行。它把工作区抽象为适配器（`control-plane/types.ts` 第 46–58 行）：`create`、`remove`、`target`；`target` 是本机目录，或者一个远程地址加请求头（第 30–39 行）。远程目标上运行的是完整的 OpenCode 服务，请求整体转发过去（`control-plane/workspace.ts` 第 253–262 行的 `runInWorkspace`），内置的适配器只有 git worktree（`adapters/index.ts` 第 5–7 行）。
- 事件流每 10 秒发送一次 `server.heartbeat`（`server/routes/instance/httpapi/handlers/event.ts` 第 63–66 行），接收方丢弃心跳消息（`control-plane/workspace.ts` 第 399 行）。
- `src/index.ts` 第 137–139 行的注释：有些以 Docker 容器运行的 MCP 服务不响应 SIGTERM，除非用 `docker run --init` 运行。
- `packages/containers/README.md`：CI 用的预构建镜像以 Ubuntu 24.04 为基础，逐层加入 Bun、Node、Rust；用 Buildx 发布 amd64 与 arm64 两种架构。

### 3.3 OMP（`fdfeef1f78`）

- OMP 没有容器、bubblewrap、sandbox-exec 或 landlock 一类的进程隔离；搜索到的 docker 相关代码是命令输出的精简规则与 Dockerfile 语法高亮。
- 子任务的隔离在文件系统层：`task/worktree.ts` 第 422–444 行按平台选择写时复制的后端（APFS、btrfs、zfs、reflink、overlayfs、Windows ProjFS 与块克隆、普通复制），第 495 行起的 `ensureIsolation` 为任务建立合并视图。
- 隔离目录中写一份所有者标记，记录进程号与进程启动时间（`task/isolation-ownership.ts` 第 12–26 行）；清理时进程号仍然存在但启动时间不同，说明进程号已被复用，按已经结束处理（第 76–106 行）。

### 3.4 Bazel Remote Execution API（`adbf4a2`）

- 内容按摘要寻址存储：`FindMissingBlobs`（`remote_execution.proto` 第 360 行）让客户端先问服务端缺哪些内容块，只上传缺少的；`BatchUpdateBlobs`（第 388 行）批量上传。
- `Execute`（第 118 行）返回长时间运行的操作流；注释写明服务端不保证一次调用只执行一次，可能重复执行，冗余的执行可能在操作完成后仍然在运行（第 114–117 行）。`WaitExecution`（第 136 行）在连接中断后重新接上同一个操作：服务端立即返回当前状态，在完成时返回结果；操作已经不存在时返回 `NOT_FOUND`，客户端重新调用 `Execute`。

## 4. 心跳

- Temporal：心跳是执行活动的 Worker 发给服务端的消息，表示活动在推进、Worker 没有崩溃，可以携带进度；超过 Heartbeat Timeout 没有心跳时该次活动判定为失败，按重试策略处理；取消请求只在活动发送心跳时送达。心跳发送按 `heartbeatTimeout * 0.8` 节流。文档建议长时间运行的活动使用较短的心跳超时并频繁发送，没有给出具体比例。
- Kubernetes：kubelet 每 10 秒续约一次节点 Lease，Lease 时长默认 40 秒（`nodeLeaseDurationSeconds`）；续约间隔是 Lease 时长的 0.25（`pkg/kubelet/kubelet.go` 第 238、1171 行）。控制器的 `--node-monitor-grace-period` 默认 40 秒，说明写明它必须是 kubelet 状态更新频率的 N 倍。
- OpenCode：事件流每 10 秒一次心跳（第 3.2 节）。

## 5. 服务管理与分发

- systemd：`Restart=on-failure` 在非零退出、被信号结束、超时与 watchdog 超时时重启；`User=`、`WorkingDirectory=` 设置运行用户与工作目录。
- Windows 服务包装：NSSM 稳定版 2.24 发布于 2014-08-31，最新预发布版 2017-04-26；WinSW 稳定版 v2.12.0 发布于 2023-01-28，v3 仍然是 alpha，仓库最近提交在 2026-05-30；pywin32 312（2026-06-04）的 `win32serviceutil.ServiceFramework` 可以直接写服务；shawl v1.9.0 发布于 2026-05-03。
- Python 应用分发：`uv tool install`（uv 0.12.19）与 `pipx install`（1.17.7）都为每个应用建立独立环境并把命令放到 PATH；`uv tool upgrade` 按原来的版本约束升级。

## 6. 对设计的影响

- 容器的生命周期（建立、启动、停止、删除、查看状态）调用次数少，适合用官方的 docker-py 在线程中调用；动作本身不经过 docker exec：流式执行时退出码要另外查询，执行会话随控制主机的连接存在，控制主机重启以后没有按动作身份重新接上的办法。容器中运行执行代理，本机容器与远程机器使用同一份 HTTP 合同、同一套心跳与动作记录。
- Podman 的 Docker 兼容接口没有官方文档说明 docker-py 可以使用，podman-py 仍然在开发中；Yudao 声明支持的容器引擎是 Docker Engine 与 Docker Desktop，Podman 在真实验证之前不标为支持。
- 树莓派上的容器要求 64 位系统；执行代理本身是 Python 程序，32 位系统可以运行。
- 工作区内容的传输采用 Bazel 的做法：清单加按摘要寻址的内容块，先问缺少哪些再上传；Yudao 的公开树清单已经是这种形式（路径、大小、`sha256:` 摘要）。动作的跟随采用 `WaitExecution` 的做法：连接中断后按动作身份重新接上，服务端立即给出当前状态。
- 心跳间隔 10 秒、超时 40 秒，与 Kubernetes 节点 Lease 的默认值与 OpenCode 的事件流心跳一致；超时后的处理由 Yudao 的动作核实决定，Temporal 的自动重试不适用于有副作用的动作。
- 执行代理重新启动后判断遗留进程是否仍然在运行，记录进程号与进程启动时间，参照 OMP 的所有者标记。
- Linux 上执行代理以 systemd 服务运行。Windows 上使用 WinSW：单个可执行文件加一份 XML 配置，支持失败后重启；NSSM 多年没有发布；pywin32 的服务框架要求以 `pythonservice.exe` 加载，和 `uv tool install` 建立的独立环境配合不便。
