// 世界里的决定卡片：点大厅的板子，一张纸在画面里摊开，材料写在纸上，选项是盖在纸上的章，
// 说明写在纸下方的横线上（原型 v10 decision-card.js 与设计说明第 9 节，工单 #179）。
//
// 卡片不依赖渲染与 PixiJS：它读一份份 face（来自决定请求的纯文字版本），把纸画到给定的 2D 画布上，
// 同时收集这一帧的可点击区域；点击、鼠标与键盘由画面层转发。说明栏叠一个 textarea（加在画布父元素里），
// 中文输入法需要它。回答调用 onDecide，返回命令的结果。

import { drawBitmap, drawText, measure } from "../shapes.ts";
import { PAL, PIXEL_FONT_STACK } from "../registry.ts";
import { mix } from "../grid.ts";
import { R, RB } from "./render.ts";
import type { DecisionFace } from "../world/types.ts";
import { missingNoteText } from "../../views/decisions/card-logic.ts";

export type { DecisionFace };

export type DecisionAnswer = { decision_id: string; option: string; note: string; base_version: number };

/** 回答命令的结果：接受或者被拒绝（拒绝时给出原因）。 */
export type DecisionResult = { accepted: boolean; message?: string };

/** 回答以后事件流送来的盖章。 */
export interface DecisionStamp {
  id: string;
  text: string;
  t0: number;
}

export interface DecisionCardOptions {
  /** 说明栏的输入框加在这个元素里；省略时用画布父元素。 */
  cardHost?: HTMLElement | null;
  /** 点选项时调用；返回命令的结果。 */
  onDecide?: (payload: DecisionAnswer) => Promise<DecisionResult> | DecisionResult;
  /** 材料里指向别的页面的内容。 */
  onGo?: (target: string) => void;
  /** 现在的时间（毫秒），由画面层的共用时钟给出。 */
  now: () => number;
  /** 到达时刻执行一次的回调（原型 scene.after）。 */
  after: (ms: number, fn: () => void) => void;
  /** 画布的逻辑尺寸与拿它的当前缩放（说明栏定位用）。 */
  W: number;
  H: number;
}

export interface DecisionCard {
  setDecisions(faces: DecisionFace[]): void;
  open(id?: string): void;
  close(): void;
  isOpen(): boolean;
  openId(): string | null;
  /** 每帧在最上层画；同时收集这一帧的可点击区域。 */
  draw(c: CanvasRenderingContext2D): void;
  /** 世界坐标；卡片打开时处理点击并返回 true（点在纸的外面是关上）。 */
  click(x: number, y: number): boolean;
  /** 鼠标在可点击区域上返回 'pointer'。 */
  cursor(x: number, y: number): string | null;
  /** 回答事件到达时在纸上盖章；自己刚回答过的已经盖着章，不重盖。 */
  stamp(id: string, text: string): void;
  /** 按选项标识回答当前打开的决定（点击章走同一条路）；需要说明而没有写时不提交。 */
  answer(option: string): Promise<void>;
  destroy(): void;
  /** 测试读取：当前画出的状态。 */
  inspect(): { openId: string | null; submitted: string[]; message: string | null; stamp: DecisionStamp | null };
}

/** 卡片左边的色条：需要马上处理的种类偏橙，会造成损失的偏红，通知类偏蓝，其余是琥珀色。 */
const KIND_COLOR: Record<string, string> = {
  model_unavailable: PAL.orange2,
  unknown_action: PAL.orange2,
  rollback_restore: PAL.red2,
  repair_stopped: PAL.red2,
  no_tool_call: PAL.blue2,
  workspace_unrepresentable: PAL.blue2,
};

const BAR = 18;
const PAPER = { x: 92, y: 26, w: 456, h: 270 };
const LABEL_W = 78;

interface Hit {
  x: number;
  y: number;
  w: number;
  h: number;
  act: "close" | "prev" | "next" | "go" | "option";
  arg?: string;
}

/** 建立一张决定卡片：内容来自 faces，画到给定的 2D 画布上。 */
export function createDecisionCard(canvas: HTMLCanvasElement, opts: DecisionCardOptions): DecisionCard {
  const o = opts;
  const W = o.W;
  const H = o.H;

  let faces: DecisionFace[] = [];
  let openId: string | null = null;
  let hits: Hit[] = [];
  let msg: { text: string; until: number } | null = null;
  let stamp: DecisionStamp | null = null;
  // 回答以后事件流带来的新列表里已经没有这个决定：纸留着这份内容，盖章结束再收起
  let ghost: DecisionFace | null = null;
  const submitted: Record<string, boolean> = {};
  const notes: Record<string, string> = {};
  let wrapCache: Record<string, string[]> = {};
  let noteEl: HTMLTextAreaElement | null = null;

  // ---------------------------------------------------------------------------
  // 文字：按宽度折行（中文没有空格，逐字量）

  function wrap(c: CanvasRenderingContext2D, str: string, maxW: number, size: number, weight: number): string[] {
    const lines: string[] = [];
    let cur = "";
    for (const ch of Array.from(String(str))) {
      if (ch === "\n") {
        lines.push(cur);
        cur = "";
        continue;
      }
      if (cur && measure(c, cur + ch, size, weight) > maxW) {
        lines.push(cur);
        cur = ch;
      } else {
        cur += ch;
      }
    }
    if (cur || !lines.length) lines.push(cur);
    return lines;
  }

  function rowLines(c: CanvasRenderingContext2D, face: DecisionFace, i: number, valueW: number): string[] {
    const text = face.rows[i].value;
    const key = `${face.id}|${i}|${valueW}|${text}`;
    if (!wrapCache[key]) {
      if (Object.keys(wrapCache).length > 400) wrapCache = {};
      wrapCache[key] = wrap(c, text, valueW, 6.5, 500);
    }
    return wrapCache[key];
  }

  const faceOf = (id: string | null): DecisionFace | null => (id ? faces.find((f) => f.id === id) ?? null : null);
  const shown = (): DecisionFace | null => (openId ? faceOf(openId) ?? (ghost && ghost.id === openId ? ghost : null) : null);

  // ---------------------------------------------------------------------------
  // 说明的输入框：画面里的横线纸上叠一个透明的输入框，中文输入法需要它

  function ensureNote(): HTMLTextAreaElement {
    if (noteEl) return noteEl;
    const parent = o.cardHost ?? canvas.parentElement;
    if (!parent) throw new Error("决定卡片需要画布的父元素承载说明栏");
    if (getComputedStyle(parent).position === "static") parent.style.position = "relative";
    noteEl = document.createElement("textarea");
    noteEl.setAttribute("aria-label", "决定的说明");
    noteEl.style.cssText =
      `position:absolute;display:none;box-sizing:border-box;resize:none;border:1px solid #6a4a2e;background:#fff7dc;color:#1c1a26;padding:2px 4px;margin:0;outline:none;font-family:${PIXEL_FONT_STACK};line-height:1.35;z-index:3`;
    noteEl.addEventListener("input", () => {
      if (openId) notes[openId] = noteEl!.value;
    });
    noteEl.addEventListener("keydown", (e) => {
      e.stopPropagation();
      if (e.key === "Escape") close();
    });
    parent.appendChild(noteEl);
    return noteEl;
  }

  function placeNote(x: number, y: number, w: number, h: number, disabled: boolean): void {
    const el = ensureNote();
    const parent = o.cardHost ?? canvas.parentElement!;
    const r = canvas.getBoundingClientRect();
    const pr = parent.getBoundingClientRect();
    const sx = r.width / W;
    const sy = r.height / H;
    el.style.left = `${r.left - pr.left - parent.clientLeft + x * sx}px`;
    el.style.top = `${r.top - pr.top - parent.clientTop + y * sy}px`;
    el.style.width = `${w * sx}px`;
    el.style.height = `${h * sy}px`;
    el.style.fontSize = `${6.5 * sy}px`;
    el.style.display = "block";
    el.disabled = Boolean(disabled);
    const want = (openId && notes[openId]) || "";
    if (el.value !== want) el.value = want;
  }

  function hideNote(): void {
    if (noteEl) noteEl.style.display = "none";
  }

  // ---------------------------------------------------------------------------
  // 打开、关闭、翻页

  function onKey(e: KeyboardEvent): void {
    if (!openId) return;
    // 别处的文本框里打字（方向键移动光标）不算对卡片的操作
    const t = e.target as HTMLElement | null;
    if (t && t !== noteEl && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable)) return;
    if (e.key === "Escape") close();
    else if (e.key === "ArrowLeft") flip(-1);
    else if (e.key === "ArrowRight") flip(1);
  }

  function open(id?: string): void {
    const face = (id && faceOf(id)) || faces[0];
    if (!face) return;
    if (!openId) document.addEventListener("keydown", onKey);
    openId = face.id;
    msg = null;
  }

  function close(): void {
    if (openId) {
      document.removeEventListener("keydown", onKey);
      // 提交过的说明随卡片收起；列表里已经没有的决定，提交记录也一起清掉
      if (submitted[openId]) delete notes[openId];
      if (!faceOf(openId)) {
        delete submitted[openId];
        delete notes[openId];
      }
    }
    openId = null;
    ghost = null;
    msg = null;
    hideNote();
  }

  function flip(d: number): void {
    const i = faces.findIndex((f) => f.id === openId);
    if (i < 0 || faces.length < 2) return;
    openId = faces[(i + d + faces.length) % faces.length].id;
    msg = null;
  }

  // ---------------------------------------------------------------------------
  // 回答

  async function answer(face: DecisionFace, op: DecisionFace["options"][number]): Promise<void> {
    if (submitted[face.id]) return;
    const note = (notes[face.id] || "").trim();
    const missing = missingNoteText(op, note);
    if (missing !== "") {
      msg = { text: missing, until: o.now() + 2600 };
      return;
    }
    const result = o.onDecide ? await o.onDecide({ decision_id: face.id, option: op.id, note, base_version: face.version }) : null;
    if (!result || !result.accepted) {
      msg = { text: (result && result.message) || "控制主机没有接受这个回答", until: o.now() + 3200 };
      return;
    }
    submitted[face.id] = true;
    stamp = { id: face.id, text: `已回答：${op.label}`, t0: o.now() };
    o.after(1200, () => {
      stamp = null;
      if (openId === face.id) close();
    });
  }

  // ---------------------------------------------------------------------------
  // 绘制

  function button(
    c: CanvasRenderingContext2D,
    x: number,
    y: number,
    w: number,
    h: number,
    text: string,
    style: string | null | undefined,
    act: Hit["act"],
    arg?: string,
    disabled?: boolean,
  ): void {
    const bg = disabled ? PAL.grey1 : style === "primary" ? PAL.green2 : style === "danger" ? PAL.red2 : PAL.white;
    const fg = disabled ? PAL.grey3 : style === "primary" || style === "danger" ? PAL.white : PAL.ink;
    RB(c, x, y, w, h, bg);
    R(c, x + 1, y + 1, w - 2, 1, disabled ? PAL.grey1 : mix(bg, PAL.white, 0.35));
    drawText(c, text, x + w / 2, y + h / 2 + 0.5, { size: 6.5, weight: 700, align: "center", color: fg, max: w - 6 });
    if (!disabled && act) hits.push({ x, y, w, h, act, arg });
  }

  function draw(c: CanvasRenderingContext2D): void {
    hits = [];
    const face = shown();
    if (!face) {
      hideNote();
      return;
    }
    const px = PAPER.x;
    const py = PAPER.y;
    const pw = PAPER.w;
    const ph = PAPER.h;
    c.fillStyle = "rgba(12,14,30,0.58)";
    c.fillRect(0, BAR, W, H - BAR);
    // 纸：木框、纸面、左边的色条、上面的图钉
    RB(c, px - 3, py - 3, pw + 6, ph + 6, PAL.wood3);
    RB(c, px, py, pw, ph, PAL.paper);
    R(c, px, py, 4, ph, KIND_COLOR[face.kind] || PAL.yellow2);
    RB(c, px + pw / 2 - 4, py - 6, 8, 8, PAL.red2);
    // 抬头：图标、种类、翻页与关闭
    drawBitmap(c, "decision", px + 12, py + 8);
    drawText(c, face.title, px + 28, py + 14, { size: 8.5, weight: 800, color: PAL.ink, max: pw - 132 });
    const idx = faces.findIndex((f) => f.id === face.id);
    // 翻页在左，关闭在右，两组按钮之间留出间隔
    const bx = px + pw - 88;
    if (faces.length > 1 && idx >= 0) {
      button(c, bx, py + 6, 12, 12, "‹", null, "prev");
      drawText(c, `${idx + 1}/${faces.length}`, bx + 26, py + 12.5, { size: 6.5, weight: 700, align: "center", color: PAL.ink2 });
      button(c, bx + 40, py + 6, 12, 12, "›", null, "next");
    }
    button(c, px + pw - 18, py + 6, 12, 12, "×", null, "close");
    drawText(c, face.where, px + 14, py + 30, { size: 6.5, weight: 600, color: PAL.ink2, max: pw - 28 });
    drawText(c, `${face.waited} · ${face.blocks}`, px + 14, py + 40, { size: 6, color: PAL.grey3, max: pw - 28 });
    R(c, px + 10, py + 46, pw - 20, 1, PAL.wood2);
    // 材料：标题在左，内容在右，按宽度折行；放不下的行截断，链接固定在说明栏上方的一行
    const valueX = px + 14 + LABEL_W;
    const valueW = pw - 28 - LABEL_W;
    const noteY = py + ph - 74;
    const linksY = noteY - 34;
    const limit = (face.links.length ? linksY : noteY - 22) - 6;
    let y = py + 54;
    let cut = false;
    face.rows.forEach((row, i) => {
      if (cut) return;
      const lines = rowLines(c, face, i, valueW);
      // 这一行放不下：能放下几行画几行，最后一行以省略号结尾，后面的行不画
      const fit = Math.min(lines.length, Math.floor((limit - y) / 8));
      if (fit < lines.length) cut = true;
      if (fit < 1) return;
      drawText(c, row.term, px + 14, y + 4, { size: 6, weight: 600, color: PAL.grey3, max: LABEL_W - 4 });
      lines.slice(0, fit).forEach((line, k) =>
        drawText(c, cut && k === fit - 1 ? `${line}…` : line, valueX, y + 4 + k * 8, {
          size: 6.5, weight: 500, color: PAL.ink, max: valueW,
        }),
      );
      y += fit * 8 + 3;
    });
    if (cut) drawText(c, "材料较长，其余内容在页面下方的文字列表里", px + pw - 14, noteY - 5, { size: 6, align: "right", color: PAL.grey3 });
    // 材料里的链接（去别的页面）
    let lx = px + 14;
    face.links.forEach((l) => {
      const w = Math.min(150, Math.ceil(measure(c, l.label, 6.5, 700)) + 14);
      button(c, lx, linksY, w, 12, l.label, null, "go", l.href);
      lx += w + 6;
    });
    // 说明
    const done = Boolean(submitted[face.id]);
    drawText(c, "说明（可选）", px + 14, noteY - 5, { size: 6, weight: 600, color: PAL.grey3 });
    placeNote(px + 10, noteY, pw - 20, 30, done);
    // 选项：盖在纸上的章；选项太多放不下时按比例收窄
    const oy = py + ph - 34;
    let ox = px + 12;
    const natural = face.options.map((op) => Math.max(58, Math.ceil(measure(c, op.label, 6.5, 700)) + 18));
    const gap = 8;
    const room = pw - 24 - gap * Math.max(0, natural.length - 1);
    const sum = natural.reduce((s, w) => s + w, 0);
    const k = sum > room ? room / sum : 1;
    face.options.forEach((op, i) => {
      const w = Math.max(30, Math.floor(natural[i] * k));
      button(c, ox, oy, w, 18, op.label, op.kind, "option", op.id, done);
      ox += w + gap;
    });
    if (done) drawText(c, "已提交，等待控制主机确认", ox + 4, oy + 9, { size: 6.5, weight: 600, color: PAL.green3 });
    if (msg && msg.until > o.now()) drawText(c, msg.text, px + 14, oy - 8, { size: 6.5, weight: 700, color: PAL.red3, max: pw - 28 });
    // 回答以后盖上的章
    if (stamp && stamp.id === face.id) {
      const k2 = Math.min(1, (o.now() - stamp.t0) / 220);
      c.save();
      c.translate(px + pw / 2, py + ph / 2 - 8);
      c.rotate(-0.16);
      c.globalAlpha = 0.9 * k2;
      const s = 1.6 - 0.6 * k2;
      c.scale(s, s);
      const w = Math.ceil(measure(c, stamp.text, 12, 900)) + 24;
      c.fillStyle = PAL.green3;
      c.fillRect(-w / 2, -14, w, 28);
      c.fillStyle = PAL.paper;
      c.fillRect(-w / 2 + 2, -12, w - 4, 24);
      drawText(c, stamp.text, 0, 0.5, { size: 12, weight: 900, align: "center", color: PAL.green3 });
      c.restore();
    }
  }

  // ---------------------------------------------------------------------------
  // 点击与鼠标

  function hitAt(x: number, y: number): Hit | null {
    for (let i = hits.length - 1; i >= 0; i--) {
      const h = hits[i];
      if (x >= h.x && x <= h.x + h.w && y >= h.y && y <= h.y + h.h) return h;
    }
    return null;
  }

  function click(x: number, y: number): boolean {
    if (!openId) return false;
    const face = shown();
    const h = hitAt(x, y);
    if (h && face) {
      if (h.act === "close") close();
      else if (h.act === "prev") flip(-1);
      else if (h.act === "next") flip(1);
      else if (h.act === "go") {
        if (o.onGo && h.arg) o.onGo(h.arg);
      } else if (h.act === "option") {
        const op = face.options.find((item) => item.id === h.arg);
        if (op) void answer(face, op);
      }
      return true;
    }
    const inside = x >= PAPER.x && x <= PAPER.x + PAPER.w && y >= PAPER.y && y <= PAPER.y + PAPER.h;
    if (!inside && y > BAR) close();
    return true;
  }

  function cursor(x: number, y: number): string | null {
    return openId && hitAt(x, y) ? "pointer" : null;
  }

  // ---------------------------------------------------------------------------
  // 数据

  function setDecisions(list: DecisionFace[]): void {
    const next = list || [];
    // 正在盖章的决定被回答事件带来的新列表拿掉了：留下这份内容，盖章结束（1.2 秒）再收起
    if (openId && stamp && stamp.id === openId && !next.some((f) => f.id === openId)) ghost = faceOf(openId) || ghost;
    faces = next;
    const alive = (id: string): boolean => Boolean(faceOf(id)) || Boolean(ghost && ghost.id === id);
    Object.keys(submitted).forEach((id) => {
      if (!alive(id)) delete submitted[id];
    });
    Object.keys(notes).forEach((id) => {
      if (!alive(id)) delete notes[id];
    });
    if (openId && !alive(openId)) close();
  }

  function destroy(): void {
    close();
    if (noteEl) {
      noteEl.remove();
      noteEl = null;
    }
  }

  return {
    setDecisions,
    open,
    close,
    isOpen: () => Boolean(openId),
    openId: () => openId,
    draw,
    click,
    cursor,
    stamp: (id, text) => {
      if (!stamp || stamp.id !== id) stamp = { id, text, t0: o.now() };
    },
    answer: async (option) => {
      const face = shown();
      const op = face?.options.find((item) => item.id === option);
      if (face && op) await answer(face, op);
    },
    destroy,
    inspect: () => ({ openId, submitted: Object.keys(submitted), message: msg ? msg.text : null, stamp }),
  };
}
