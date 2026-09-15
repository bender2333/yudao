# Stage 1 F 网络诊断（2.1.1）

日期：2026-09-15  
范围：计划项 2.1.1。只采集、不改 harness、不关 TLS 校验、不改系统代理/DNS。凭据只进进程内存，不写入本文或证据 JSON。

## 1. 方法

对 `provider.md` 中 **primary** 与 **back** 两套地址各做分层探测，重复若干次估计频率。

| 层 | 做法 | 超时 |
| --- | --- | --- |
| DNS | `getaddrinfo`，记录是否落入 Clash fake-IP `198.18.0.0/15` | — |
| TCP | 连 `:443` | 10s |
| TLS | 默认 `ssl.create_default_context()`，SNI 为证书主机名，`verify=True` | 含 TCP 共 10s |
| 无认证 HTTP | `GET {base}/v1/models`，`httpx` `trust_env=true` 与 `false` 各一遍 | 15s |
| 认证 Responses | 最小非流式 `POST /v1/responses`（`store=false`，`max_output_tokens=16`） | 45s |
| 认证流式 | 同上但 `stream=true`，只计 SSE 行数与是否见到 `response.completed`，不保存事件正文 | 45s |

约束：

- 未设置 `verify=False`，未改 `HTTP(S)_PROXY` / DNS / 证书库。
- 本机无 `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY` 环境变量；`trust_env` 只影响 httpx 是否读取这些变量，**不能绕过 TUN/fake-IP**。
- 错误只记类型链与 HTTP 状态，不记 Authorization、密钥、响应正文。
- 非流式 5 轮；流式 3 轮（harness 实际走流式，且历史 TLS EOF 出现在流式上）。

机器证据（无密钥）：

- `.yudao/stage1-final-validation/network/probe-results.json`（2026-09-15T03:53:13Z）
- `.yudao/stage1-final-validation/network/probe-stream-results.json`（2026-09-15T03:55:14Z）

探测目标（来自当前 `provider.md`，不是历史 `.org` 记录）：

| 标签 | 主机 | 请求模型 | 目录 |
| --- | --- | --- | --- |
| primary | `penguinapi.vip` | `gpt-5.6-luna` | 主段 |
| back | `api.agnes-ai.cn` | `agnes-3.0-flash` | `back` 段；与 `.yudao/providers.stage2-a1-back.json` 一致 |

## 2. 本机路径

| 观察 | 值 |
| --- | --- |
| 代理环境变量 | 均未设置 |
| 本机进程 | `clash-verge.exe`、`clash-verge-service.exe`、`verge-mihomo.exe`、`Nextin.MihomoHost.exe` |
| primary DNS | `198.18.0.91`（fake-IP） |
| back DNS | `198.18.0.81`（fake-IP） |
| TLS 证书 | primary：`CN=penguinapi.vip`，签发 `YR1`；back：`CN=*.agnes-ai.cn`，签发 `Sectigo Public Server Authentication CA DV R36`。均为 TLS 1.3 / `TLS_AES_256_GCM_SHA384` |

结论（本机）：默认路由仍走 **Clash Verge / Mihomo TUN + fake-IP**。TCP 对端是本机隧道，不是远端公网地址。证书主体是真实站点名而非 Clash 伪造 CA，更像 **TLS 被隧道转发、未被本机 MITM**。未关闭 Clash，因此不能给出“直连公网”对照。

## 3. 探测结果

错误类口径：`SSLEOFError`（含 `ConnectError -> ConnectError -> SSLEOFError`）、`429`、`timeout`、`connect`、`protocol`、`http_<status>`、其它。无认证 401 视为 **传输成功、应用层未授权**，不是失败。

### 3.1 primary `penguinapi.vip` / `gpt-5.6-luna`

| 探测 | 次数 | 成功 | 失败 | 耗时 | 备注 |
| --- | --- | --- | --- | --- | --- |
| DNS / TCP | 5 | 5 | 0 | DNS 2–8 ms；TCP 0.8–26 ms | 对端 `198.18.0.91:443` |
| TLS | 5 | 5 | 0 | 829–1113 ms | TLS 1.3 |
| GET `/v1/models` `trust_env=true` | 5 | 5（HTTP 401） | 0 | 1550–1962 ms | `error.type=new_api_error` |
| GET `/v1/models` `trust_env=false` | 5 | 5（HTTP 401） | 0 | 1660–1744 ms | 与 true 同类，无差异 |
| 非流式 Responses `trust_env=false` | 5 | 5（HTTP 200） | 0 | 3067–3660 ms | 返回模型 `gpt-5.6-luna` |
| 非流式 Responses `trust_env=true` | 2 | 2（HTTP 200） | 0 | 3295–4141 ms | 与 false 同类 |
| 流式 Responses `trust_env=false` | 3 | 2 | **1 × SSLEOFError** | 失败 5354 ms；成功 3418 / 3719 ms | 失败时无 HTTP 状态；成功见到 `response.completed` |

本窗口 **未出现 429、timeout**。`trust_env` true/false 在非流式上无差别。

### 3.2 back `api.agnes-ai.cn` / `agnes-3.0-flash`

| 探测 | 次数 | 成功 | 失败 | 耗时 | 备注 |
| --- | --- | --- | --- | --- | --- |
| DNS / TCP | 5 | 5 | 0 | DNS 0.6–2.0 ms；TCP 0.7–17 ms | 对端 `198.18.0.81:443` |
| TLS | 5 | 5 | 0 | 149–224 ms | TLS 1.3，明显快于 primary |
| GET `/v1/models` `trust_env=true` | 5 | 5（HTTP 401） | 0 | 670–819 ms | `error.type=AgnesAI_error` |
| GET `/v1/models` `trust_env=false` | 5 | 5（HTTP 401） | 0 | 596–766 ms | 与 true 同类，无差异 |
| 非流式 Responses `trust_env=false` | 5 | 5（HTTP 200） | 0 | 962–1655 ms | 返回模型 `agnes-3.0-flash` |
| 非流式 Responses `trust_env=true` | 2 | 2（HTTP 200） | 0 | 1067–1258 ms | 与 false 同类 |
| 流式 Responses `trust_env=false` | 3 | 3 | 0 | 1328–1498 ms | 均见到 `response.completed` |

本窗口 **无 SSLEOFError、无 429、无 timeout**。

## 4. 频率

| 错误类 | primary 非流式 | primary 流式 | back 非流式 | back 流式 |
| --- | --- | --- | --- | --- |
| 成功 200 | 7/7 | 2/3 | 7/7 | 3/3 |
| SSLEOFError | 0/7 | **1/3** | 0/7 | 0/3 |
| 429 | 0 | 0 | 0 | 0 |
| timeout | 0 | 0 | 0 | 0 |
| 其它 HTTP 4xx/5xx（认证请求） | 0 | 0 | 0 | 0 |

1/3 只是本窗口点估计，样本小，不能外推为稳定故障率。它足以证明：**当前 primary 流式路径仍能打出与 F 验收相同的 `SSLEOFError` 类**，且 back 在同一本机路径上未打出该类。

## 5. 分类：本机路径 vs 网关 vs 模型

**本机路径（Clash TUN / fake-IP）**

- 两主机都经 `198.18.0.0/15`，同一组 Clash 进程。TCP 成功只说明隧道接受了连接。
- 若故障 **仅** 在本机 TUN，两主机流式应同向失败。观测是 primary 流式 1/3 EOF、back 流式 3/3 成功，故 **本机路径是公共前置条件，但不是 primary 独有 EOF 的充分原因**。
- 未做直连/换 DNS 对照（禁止改系统网络），因此 **不能排除** Clash 到 penguinapi 上游的那一跳（节点、UDP、复用）仍参与 EOF。

**网关**

- 无认证 401 证明 TLS 之后 HTTP 已到达各自 API 网关。
- primary 流式失败发生在 **尚无 HTTP 状态** 时（约 5.35 s），类型链 `ConnectError -> ConnectError -> SSLEOFError`，与历史 `APIConnectionError -> ConnectError -> EndOfStream -> SSLEOFError` 同类。这是传输层中断，不是 `429` 或应用 JSON 错误。
- 无法在“penguinapi 网关掐流”与“Clash→该上游的隧道中断”之间单点定性。确定性仅到：**故障面在 primary 的传输路径，不在请求 JSON 格式。**

**模型**

- 非流式 200 的实际返回模型分别为 `gpt-5.6-luna`、`agnes-3.0-flash`，与请求一致。
- 无 `invalid_request_error` / 模型名 400。EOF 不能归因于模型标识或最小 prompt 写错。
- 不能用本次 16 token 探针证明长压缩流在 back 上永远稳定。

**不确定项（保持显式）**

- 未切换直连、未换 DNS、未关闭 Clash。
- 未用 600 s 长流或小窗压缩载荷复现 EOF。
- back 本窗口 0 次 EOF ≠ back 永不 EOF。
- 历史部分失败发生在 `penguinapi.org`；当前主段是 `penguinapi.vip`。同类网关家族，**主机名不完全相同**，旧 `.org` 时序不能逐条套到 `.vip`。

## 6. 历史 luna `provider_error` 仍是真实失败

下列记录不得因本次短探针部分成功而改写：

- Stage 1 F：`run_c9f1b6ca018f41ef`、`run_8af405b0b3da4b79` 等连接失败，未到独立 QA。
- 复验诊断：`APIConnectionError -> ConnectError -> EndOfStream -> SSLEOFError`；无认证请求也可在 TLS 层 EOF；`trust_env` true/false 都出现过（见 `docs/mvp-acceptance.md`）。
- Stage 2 进度：luna 目录对照 `run_d004266f212a4c2c` 的 `provider_error` 保留。
- 本窗口：`penguinapi.vip` + `gpt-5.6-luna` **流式 1/3 再次打出 `SSLEOFError`**（约 5.35 s，无 HTTP 状态），与历史短流失败时序同量级。

短非流式 200 只证明存在成功路径，**不抹去** 上述失败，也 **不** 把 luna 重新标成 2.1.3 可用通道。

## 7. 对 2.1.2 / 2.1.3 的结论

2.1.2 已选定：**改用 back / `agnes-3.0-flash`**，**保持 D17：单次 600 s、最多 3 次内核尝试**，不关 TLS、不改系统代理。

依据：

- back 在同一 TUN 上 TCP/TLS/无认证 HTTP/非流式/流式均成功；实际返回模型 `agnes-3.0-flash`。
- primary 流式仍出现 `SSLEOFError`，与 F 缺口同类，不适合作为 2.1.3 主通道。
- 本窗口无 429，没有证据要求放宽或收紧 D17 次数；长任务仍可能需要这 3 次重试。
- 小窗验收窗口按合同为 `context_window=32000` 加参考资料，不用历史 8000。

**当前 back 端点可用于 2.1.3 真实验收。** 2.1.3 仍须用真实 Web / 小窗跑到 DONE，本诊断不是流程验收通过。
