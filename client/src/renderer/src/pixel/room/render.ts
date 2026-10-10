// 部门房间的画法：背景、墙上的物件、地面陈设、小人、说话气泡与管道口
// （原型 v10 room.js 的 draw 与 buildBackground，工单 #177）。
//
// 画法复用已有的画布原语（paint、shapes、char），与原型逐行对应；渲染层把这张画布交给 PixiJS
// 显示（room-view.ts），最近邻放大到容器宽度。

import { bitmapDef } from "../char.ts";
import { paint } from "../paint.ts";
import { DEPTS, PAL } from "../registry.ts";
import { drawActor, drawBitmap, drawIcon, drawSign, drawStampMark, drawText, headTop } from "../shapes.ts";
import { drawSpeeches } from "../floor/render.ts";
import type { Actor, SceneLike } from "../world/types.ts";
import { poseAnim } from "./decl.ts";
import { BASE, BENCH_LABEL, H, L, ROW_A, ROW_B, STATUS_COLOR, STATUS_TEXT, W } from "./layout.ts";
import type { RoomDriver } from "./driver.ts";

const R = (c: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, col: string): void => {
  c.fillStyle = col;
  c.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h));
};
const RB = (c: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, col: string, ink?: string): void => {
  R(c, x - 1, y - 1, w + 2, h + 2, ink ?? PAL.ink);
  R(c, x, y, w, h, col);
};

interface Shell {
  name: string;
  main: string;
  shade: string;
  light: string;
  wall: string;
  wall2: string;
  wall3?: string;
  trim: string;
  floor: string;
  floor2?: string;
  floor3?: string;
  rug: string;
  rug2: string;
}

/** 部门房间的绘制：每帧按驱动的房间数据与场景里 actor 的状态画一遍。 */
export class RoomRenderer {
  private bg: HTMLCanvasElement | null = null;
  private bgKey = "";

  constructor(private readonly driver: RoomDriver, private readonly scene: SceneLike) {}

  draw(c: CanvasRenderingContext2D): void {
    const t = this.scene.animT;
    const dept = this.driver.model.department;
    const D = (DEPTS as Record<string, Shell>)[dept];
    const status = this.driver.state.eventStatus || this.driver.model.status || "idle";
    const off = status === "interrupted";
    c.imageSmoothingEnabled = false;
    c.drawImage(this.background(), 0, 0);

    // 墙上物件
    if (!this.isOps()) paint.window(c, L.window.x, L.window.y, { w: L.window.w, h: L.window.h, night: off }, t);
    paint.clock(c, L.clock.x, L.clock.y, { time: this.driver.state.clock, stopped: off });
    paint.whiteboard(c, L.wb.x, L.wb.y, { w: L.wb.w, h: L.wb.h, floor: L.wb.floor, title: this.wbTitle(), lines: this.wbLines() }, t);
    const pinned = Math.max(0, (this.driver.model.pinned_notes || 0) - (this.driver.state.noteHide > this.scene.realT ? 1 : 0));
    paint.corkboard(c, L.cork.x, L.cork.y, {
      w: L.cork.w, h: L.cork.h, notes: pinned,
      doneIndex: this.driver.state.replyUntil > this.scene.realT ? Math.min(pinned, 6) - 1 : -1, label: "部门指导",
    });
    paint.door(c, L.door.x, L.door.base, { w: L.door.w, h: L.door.h, open: this.driver.state.door });
    const doorNail: [number, number] = [L.door.x + Math.round(L.door.w / 2), L.door.base - L.door.h + 2];
    R(c, L.door.x + 4, L.door.base - L.door.h - 12, L.door.w - 8, 8, PAL.ink);
    R(c, L.door.x + 5, L.door.base - L.door.h - 11, L.door.w - 10, 6, D.main);
    paint.beacon(c, L.beacon.x, L.beacon.y, { on: this.driver.state.yellow }, t);
    for (const lx of L.lamps) paint.lamp(c, lx, 6, { on: this.driver.state.darkTarget === 0 });

    // 地面物件与小人：按深度排序
    const items: { y: number; draw: () => void }[] = [];
    items.push({
      y: BASE, draw: () => {
        paint.cabinet(c, L.cabinet.x, L.cabinet.base, { open: this.driver.state.drawer }, t);
        paint.archive(c, L.cabinet.x + 2, L.cabinet.base - 40, { n: this.driver.model.summaries || 0, flash: this.scene.realT < this.driver.state.archiveFlash }, t);
      },
    });
    items.push({ y: BASE, draw: () => paint.terminal(c, L.terminal.x, L.terminal.base, this.termOpts(), t) });
    items.push({ y: BASE + 2, draw: () => paint.tray(c, L.tray.x, L.tray.base, { count: this.driver.state.trayPaper ? 1 : 0 }) });
    items.push({ y: BASE + 2, draw: () => paint.mailbox(c, L.mailbox.x, L.mailbox.base, { count: this.driver.model.mailbox || 0 }, t) });
    items.push({ y: BASE + 4, draw: () => paint.plant(c, L.plant.x, L.plant.base) });
    items.push({ y: 160, draw: () => paint.plant(c, 452, 160) });
    items.push({ y: L.pipe.base, draw: () => paint.pipe(c, L.pipe.x, L.pipe.base, { out: this.pipeMode(), letters: 0 }, t) });
    items.push({ y: L.tube.base, draw: () => paint.tube(c, L.tube.x, L.tube.base, { letters: this.driver.model.pipes?.letters_waiting || 0 }) });
    items.push({ y: ROW_A + 0.5, draw: () => this.drawBench(c, t) });
    for (const d of this.driver.state.desks) {
      items.push({ y: ROW_B - 1, draw: () => paint.chair(c, d.seatX, ROW_B, { color: D.shade }) });
      items.push({ y: ROW_B + 0.5, draw: () => this.drawDesk(c, d, t) });
    }
    items.push({ y: this.driver.state.bin.y, draw: () => paint.bin(c, this.driver.state.bin.x, this.driver.state.bin.y, { count: this.driver.state.binUntil > this.scene.realT ? 1 : 0 }) });
    items.push({ y: ROW_B + 12, draw: () => this.drawTeaStation(c, D) });
    for (const actor of this.scene.actors) if (!actor.seat && actor.data.room) items.push({ y: actor.y, draw: () => drawActor(c, this.scene, actor) });
    items.sort((p, q) => p.y - q.y);
    for (const it of items) it.draw();

    this.flyers(c);
    this.particles(c);

    // 灯光
    if (this.driver.state.dark > 0.01) {
      c.fillStyle = `rgba(14,12,34,${this.driver.state.dark.toFixed(3)})`;
      c.fillRect(0, 0, W, H);
    }
    if (this.driver.state.yellow) {
      const k = this.scene.reduced ? 0.1 : 0.07 + 0.05 * Math.sin(t / 240);
      c.fillStyle = `rgba(255,196,40,${k.toFixed(3)})`;
      c.fillRect(0, 0, W, H);
    }
    if (this.driver.state.darkTarget === 0 && !off) for (const lx of L.lamps) paint.lightCone(c, lx, 12, { len: 150, w: 110, color: "#fff1c9", alpha: 0.1 });

    // 发光物件：画在灯光之上
    paint.crt(c, L.crt.x, L.crt.y, this.crtOpts(), t);
    this.drawScreens(c, t);

    // 门牌、举牌、头顶图标
    const doorText = this.driver.model.door || this.driver.state.doorEvent;
    if (doorText) {
      drawSign(c, doorNail[0], doorNail[1] + 18, doorText, { size: 7, bg: PAL.paper, stripe: PAL.red2, nail: doorNail[1], maxW: 96 });
    }
    drawText(c, `${D.name}部门`, L.door.x + L.door.w / 2, L.door.base - L.door.h - 8, { size: 5.5, weight: 700, align: "center", color: PAL.white });
    for (const actor of this.scene.actors) {
      if (!actor.visible || !actor.data.room) continue;
      if (actor.sign && actor.anim === "hold_sign") this.drawHeldSign(c, actor, actor.sign);
      const room = this.driver.actors().find((a) => `ch-${a.id}` === actor.id);
      if (room?.formSign && actor.anim === "hold_form") {
        const [hx, hy] = headTop(this.scene, actor);
        drawSign(c, hx, hy - 4, room.formSign, { size: 6.5, bg: PAL.white, stripe: PAL.orange2, maxW: 150 });
      }
      drawIcon(c, this.scene, actor);
    }
    // 说话气泡：画在最上层，减少动画时也照说
    const says: { a: Actor; text: string; kind: "say" | "think"; tail: boolean; until: number }[] = [];
    for (const a of this.driver.actors()) {
      const actor = this.scene.actors.find((x) => x.id === `ch-${a.id}`);
      if (a.say && actor && actor.visible && this.scene.realT < a.say.until) {
        says.push({ a: actor, text: a.say.text, kind: "say", tail: false, until: a.say.until });
      }
    }
    drawSpeeches(c, this.scene, says, { size: 7, maxW: 108 });
  }

  private isOps(): boolean {
    return this.driver.model.department === "operations";
  }

  private pipeMode(): string {
    const status = this.driver.state.eventStatus || this.driver.model.status || "idle";
    if (status === "interrupted" || this.driver.model.waiting_provider) return "stopped";
    return this.driver.model.pipes?.out || "idle";
  }

  private wbTitle(): string {
    return this.driver.model.level === "S5" ? "部门账本" : "工作计划";
  }

  private wbLines(): { text?: string; color?: string }[] {
    return [0, 1, 2, 3].map((i) => ({ color: [PAL.blue3, PAL.ink2, PAL.red3, PAL.ink2][(i + this.driver.state.wbSeed) % 4] }));
  }

  private drawHeldSign(c: CanvasRenderingContext2D, actor: Actor, text: string): void {
    const [hx, hy] = headTop(this.scene, actor);
    drawSign(c, hx, hy - 1, text, { size: 7, bg: PAL.paper, stripe: PAL.red2, maxW: 210, nail: 3 });
  }

  private drawTeaStation(c: CanvasRenderingContext2D, D: Shell): void {
    const x = 404;
    const y = ROW_B + 12;
    RB(c, x, y - 18, 40, 18, this.isOps() ? PAL.grey4 : PAL.wood2);
    R(c, x, y - 18, 40, 2, this.isOps() ? PAL.grey3 : PAL.wood1);
    R(c, x + 3, y - 13, 16, 10, this.isOps() ? PAL.grey5 : PAL.wood3);
    R(c, x + 21, y - 13, 16, 10, this.isOps() ? PAL.grey5 : PAL.wood3);
    RB(c, x + 24, y - 34, 12, 16, PAL.white2);
    RB(c, x + 25, y - 46, 10, 11, "#8fc8f0");
    R(c, x + 27, y - 44, 2, 7, "#c4e4fa");
    R(c, x + 26, y - 28, 3, 2, PAL.red2);
    R(c, x + 31, y - 28, 3, 2, PAL.blue2);
    drawBitmap(c, "teapot", x + 4, y - 26);
    drawBitmap(c, "cup", x + 14, y - 23);
    void D;
  }

  private termOpts(): Record<string, unknown> {
    const off = (this.driver.state.eventStatus || this.driver.model.status) === "interrupted";
    const snow = Boolean(this.driver.model.remote_unknown || this.driver.state.eventRemote);
    return {
      lever: this.driver.state.lever,
      exit: off ? null : this.driver.state.exit,
      screen: off ? "off" : snow ? "snow" : this.driver.state.termRun ? "term" : "idle",
      blink: snow,
    };
  }

  private crtOpts(): Record<string, unknown> {
    const status = this.driver.state.eventStatus || this.driver.model.status || "idle";
    const cr = this.driver.model.crt ?? {};
    const lines = [
      { k: "目标", v: cr.target || "—" },
      { k: "模型", v: cr.model || "—" },
      { k: "协议", v: cr.protocol || "—" },
      { k: "状态", v: cr.status || STATUS_TEXT[status] || status, color: STATUS_COLOR[status] },
      { k: "循环", v: cr.cycle ? `第 ${cr.cycle} 轮` : "—" },
    ];
    return {
      w: L.crt.w, h: L.crt.h, lines, power: status === "interrupted" ? 0 : 1,
      boot: this.driver.state.crtBoot < 1 ? this.driver.state.crtBoot : undefined,
      dim: status === "idle", cursor: status === "working",
      alert: status === "pending_verification" || status === "waiting_resume",
      label: `${(DEPTS as Record<string, Shell>)[this.driver.model.department].name} CRT`,
    };
  }

  private drawBench(c: CanvasRenderingContext2D, t: number): void {
    const dept = this.driver.model.department;
    const D = (DEPTS as Record<string, Shell>)[dept];
    const b = L.bench;
    const bs = this.driver.state.bench;
    const top = dept === "engineering" ? PAL.metal1 : dept === "quality" ? PAL.white : PAL.wood1;
    const face = dept === "engineering" ? PAL.metal3 : dept === "quality" ? D.light : PAL.wood2;
    paint.table(c, b.x, b.y, { w: b.w, top, face, label: BENCH_LABEL[dept] });
    const cx = b.x + Math.round(b.w / 2);
    if (dept === "engineering") {
      RB(c, b.x + b.w - 16, b.y - 9, 12, 5, PAL.red3);
      drawBitmap(c, "tape", b.x + b.w - 13, b.y - 12);
      RB(c, b.x + 5, b.y - 6, 10, 3, PAL.blue3);
    }
    if (dept === "quality") {
      R(c, b.x + b.w - 10, b.y - 26, 2, 21, PAL.grey3);
      R(c, b.x + b.w - 20, b.y - 28, 12, 2, PAL.grey3);
      RB(c, b.x + b.w - 26, b.y - 30, 9, 5, PAL.grey4);
      RB(c, b.x + 5, b.y - 6, 14, 5, PAL.white);
      for (let i = 0; i < 3; i++) R(c, b.x + 7 + i * 4, b.y - 5, 2, 2, i < bs.ticks ? PAL.green2 : PAL.grey2);
    }
    if (bs.item === "scroll_open") {
      RB(c, cx - 18, b.y - 6, 36, 5, PAL.paper);
      R(c, cx - 20, b.y - 7, 3, 7, PAL.wood3);
      R(c, cx + 17, b.y - 7, 3, 7, PAL.wood3);
    } else if (bs.item) {
      const bm = bitmapDef(bs.item);
      drawBitmap(c, bs.item, cx - Math.floor(bm.rows[0].length / 2), b.y - 3 - bm.rows.length);
    }
    if (bs.mark) drawStampMark(c, cx, b.y - 8, bs.mark.text, bs.mark.color, { size: 6 });
    if (bs.slip) {
      drawBitmap(c, bs.slip === "release" ? "slip_release" : "slip_defect", cx + 14, b.y - 8);
      if (bs.slipMark) drawStampMark(c, cx + 17, b.y - 8, bs.slipMark.text, bs.slipMark.color, { size: 6, rot: -0.2 });
    }
    void t;
  }

  private drawDesk(c: CanvasRenderingContext2D, d: { x: number; w: number; seatY: number; roleId: string; role: { name: string } }, t: number): void {
    const actor = this.scene.actors.find((x) => x.id === `ch-${d.roleId}`);
    const s = this.driver.state.deskState[d.roleId];
    const dept = this.driver.model.department;
    const seated = actor && actor.seat && actor.visible;
    if (seated && actor) drawActor(c, this.scene, actor, "base");
    paint.desk(c, d.x, d.seatY, { w: d.w, wood: dept === "operations" ? [PAL.grey2, PAL.grey3, PAL.grey4, PAL.grey5] : dept === "quality" ? [PAL.white, PAL.white2, PAL.white3, PAL.grey3] : null });
    const cancelled = (this.driver.state.eventStatus || this.driver.model.status) === "cancelled";
    const writing = Boolean(this.driverRoom(d.roleId)?.persist?.write);
    paint.deskItems(c, d.x, d.seatY, {
      w: d.w, papers: cancelled || s.hidePapers ? 0 : s.papers, folder: !cancelled && s.folder > this.scene.realT,
      docOnDesk: !cancelled && (s.doc > this.scene.realT || writing), box: cancelled || s.box > this.scene.realT,
      card: s.card > this.scene.realT, cardResult: s.cardResult > this.scene.realT, cup: !(actor && actor.anim === "tea"),
      lamp: s.redLamp ? "red" : null, nameplate: d.role.name,
    }, t);
  }

  private driverRoom(id: string): { persist: { write?: boolean } | null } | null {
    return this.driver.actors().find((a) => a.id === id) ?? null;
  }

  private drawScreens(c: CanvasRenderingContext2D, t: number): void {
    const status = this.driver.state.eventStatus || this.driver.model.status || "idle";
    for (const d of this.driver.state.desks) {
      const mode: string = status === "interrupted" ? "off" : status === "failed" || this.driver.state.deskState[d.roleId].redLamp ? "error"
        : status === "done" ? "ok" : "code";
      const mx = d.x + d.w - 19;
      const my = d.seatY - 17;
      paint.screen(c, mx, my, { w: 14, h: 9, mode, seed: d.x }, t);
      if (mode !== "off" && mode !== "idle") paint.glow(c, mx + 7, my + 4, { r: 12, color: mode === "error" ? PAL.red2 : PAL.screen3, alpha: 0.18 });
    }
    paint.screen(c, L.terminal.x + 3, L.terminal.base - 31, { w: 22, h: 13, mode: status === "interrupted" ? "off" : this.driver.state.termRun ? "term" : "idle", seed: 3 }, t);
  }

  private flyers(c: CanvasRenderingContext2D): void {
    for (const f of this.scene.flyers) {
      const k = Math.min(1, (this.scene.realT - f.t0) / f.ms);
      const x = f.from[0] + (f.to[0] - f.from[0]) * k;
      const y = f.from[1] + (f.to[1] - f.from[1]) * k - Math.sin(k * Math.PI) * f.arc;
      const b = bitmapDef(f.bmp);
      drawBitmap(c, f.bmp, Math.round(x - b.rows[0].length / 2), Math.round(y - b.rows.length / 2));
    }
  }

  private particles(c: CanvasRenderingContext2D): void {
    for (const p of this.scene.particles) {
      const k = 1 - p.age / p.life;
      if (p.kind === "smoke") {
        const r = 2 + Math.floor((p.age / p.life) * 5);
        c.fillStyle = `rgba(92,96,107,${(0.75 * k).toFixed(3)})`;
        c.fillRect(Math.round(p.x) - r, Math.round(p.y) - r + 1, r * 2, r * 2 - 2);
      } else {
        c.fillStyle = p.color;
        c.globalAlpha = Math.max(0, k);
        c.fillRect(Math.round(p.x), Math.round(p.y), p.size, p.size);
        c.globalAlpha = 1;
      }
    }
  }

  private background(): HTMLCanvasElement {
    const dept = this.driver.model.department;
    const key = `${dept}|${this.driver.model.level ?? "ui"}`;
    if (this.bg && this.bgKey === key) return this.bg;
    this.bgKey = key;
    const cv = document.createElement("canvas");
    cv.width = W;
    cv.height = H;
    const c = cv.getContext("2d")!;
    c.imageSmoothingEnabled = false;
    const D = (DEPTS as Record<string, Shell>)[dept];
    R(c, 0, 0, W, 120, D.wall);
    paint.rug(c, 4, 200, { w: 300, h: 34, col: D.rug, col2: D.rug2 });
    R(c, 0, 0, W, 5, D.trim);
    R(c, 0, 114, W, 6, D.trim);
    R(c, 0, 120, W, H - 120, D.floor);
    R(c, 0, 120, W, 3, "rgba(0,0,0,0.12)");
    this.bg = cv;
    return cv;
  }
}

export { poseAnim };
