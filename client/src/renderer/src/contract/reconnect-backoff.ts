// 断线以后的等待时间（工单 #679）。
//
// 计数只在连接站得住以后清零：收到过至少一帧才算站得住。仅仅「打开」不算——
// 服务端在流中途抛异常时，客户端先收到 open 再收到 error，一打开就清零会让退避
// 永远停在 1 秒，每个打开的标签页都以每秒一轮的节奏压服务端。

// 重连的递增间隔（工单 #301）：第一次 1 秒，以后每次翻倍，30 秒封顶
const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30000;

export class ReconnectBackoff {
  private failures = 0;
  private readonly baseMs: number;
  private readonly maxMs: number;

  constructor(baseMs: number = RECONNECT_BASE_MS, maxMs: number = RECONNECT_MAX_MS) {
    this.baseMs = baseMs;
    this.maxMs = maxMs;
  }

  /** 一次断线以后的等待时间：1 秒、2 秒、4 秒……到上限为止。 */
  nextDelayMs(): number {
    this.failures += 1;
    return Math.min(this.maxMs, this.baseMs * 2 ** (this.failures - 1));
  }

  /** 这条连接站住了（收到过至少一帧）：下一次断线重新从 1 秒算起。 */
  stoodUp(): void {
    this.failures = 0;
  }

  /** 到目前为止断过几次（界面上不显示，测试与排查用）。 */
  get count(): number {
    return this.failures;
  }
}
