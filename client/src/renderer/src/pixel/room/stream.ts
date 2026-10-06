// 部门房间的思考气泡与流式输出（工单 #177，原型 v9 设计说明第 6 节）：
// 打开房间时先查询 attempt.live 得到已收到的文字，再接上事件流中 offset 不小于已有字数的模型输出片段。
// 片段按 offset 拼接，位置不连续的片段（缺口）丢弃；同一个通道只保留 output。
//
// 这里只做拼接规则，不接触网络：房间画面把 attempt.live 的文字与片段交给它，取出当前该显示的整段文字。

export interface StreamFragment {
  attemptId: string;
  channel: string;
  offset: number;
  text: string;
}

export class StreamBubble {
  private attemptId: string | null = null;
  private text = "";

  /** 开始观察一次调用尝试（模型请求的进度事件到达时）。 */
  observe(attemptId: string): void {
    if (this.attemptId !== attemptId) {
      this.attemptId = attemptId;
      this.text = "";
    }
  }

  /** 以 attempt.live 已收到的文字作为起点；已经接上的片段更长时保留，不以查询结果覆盖。 */
  seed(attemptId: string, live: string): void {
    if (this.attemptId !== attemptId) {
      this.attemptId = attemptId;
      this.text = "";
    }
    if (live.length >= this.text.length) {
      this.text = live;
    }
  }

  /** 收下一条模型输出片段：只有 output 通道、offset 不小于已有字数的片段才接上。
   *  还没有观察的尝试时以这条片段所属的尝试开始观察（片段可能先于进度事件到达）。 */
  absorb(fragment: StreamFragment): boolean {
    if (fragment.channel !== "output") {
      return false;
    }
    if (this.attemptId === null) {
      this.attemptId = fragment.attemptId;
    } else if (fragment.attemptId !== this.attemptId) {
      return false;
    }
    if (fragment.offset < this.text.length) {
      // 与已经接上的文字重叠的片段丢弃：同一个偏移只接一次
      return false;
    }
    this.text += fragment.text;
    return true;
  }

  /** 当前该显示的整段文字；没有在观察的尝试时为空。 */
  get current(): string {
    return this.attemptId === null ? "" : this.text;
  }

  /** 停止观察（尝试结束）。 */
  clear(): void {
    this.attemptId = null;
    this.text = "";
  }
}
