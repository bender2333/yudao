// 部门房间的画法：背景、墙上的物件、地面陈设、小人、说话气泡与管道口
// （原型 v13 room.js 的 draw 与 buildBackground，工单 #177、#1069）。
//
// 画法复用已有的画布原语（paint、shapes、char），与原型逐行对应；渲染层把这张画布交给 PixiJS
// 显示（room-view.ts），最近邻放大到容器宽度。

import { hash } from "../anims.ts";
import { bitmapDef } from "../char.ts";
import { mix, rgba } from "../grid.ts";
import { paint } from "../paint.ts";
import { DEPTS, PAL } from "../registry.ts";
import { drawActor, drawBitmap, drawIcon, drawSign, drawStampMark, drawText, headTop, signStyle } from "../shapes.ts";
import { drawSpeeches } from "../floor/render.ts";
import type { Actor, SceneLike } from "../world/types.ts";
import { BASE, BENCH_LABEL, H, L, ROW_A, ROW_B, STATUS_COLOR, STATUS_TEXT, W, levelAtLeast, type RoomSeat } from "./layout.ts";
import { rolesOf } from "./decl.ts";
import type { RoomDriver } from "./driver.ts";
import type { DeskState } from "./room.ts";

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
  private termInfo?: { lampX: number; lampY: number };
  private mailInfo?: { lamp: [number, number]; nail: [number, number] };
  private doorInfo?: { nail: [number, number]; slot: [number, number]; w: number; h: number };

  constructor(private readonly driver: RoomDriver, private readonly scene: SceneLike) {}

  draw(c: CanvasRenderingContext2D): void {
    const sc = this.scene;
    const t = sc.animT;
    const dept = this.driver.model.department;
    const D = (DEPTS as Record<string, Shell>)[dept];
    const status = this.effStatus();
    const off = status === "interrupted";
    const level = this.driver.model.level ?? "S5";
    c.imageSmoothingEnabled = false;
    c.drawImage(this.background(), 0, 0);

    // 墙上物件
    if (!this.isOps()) paint.window(c, L.window.x, L.window.y, { w: L.window.w, h: L.window.h, night: off }, t);
    paint.clock(c, L.clock.x, L.clock.y, this.driver.state.clock, { stopped: off });
    paint.whiteboard(c, L.wb.x, L.wb.y, this.whiteboardOpts(), t);
    const pinned = this.driver.model.pinned_notes || 0;
    paint.corkboard(c, L.cork.x, L.cork.y, {
      w: L.cork.w, h: L.cork.h, notes: pinned,
      doneIndex: this.driver.state.replyUntil > sc.realT ? Math.min(pinned, 6) - 1 : -1, label: "部门指导",
    });
    this.doorInfo = paint.door(c, L.door.x, L.door.base, { w: L.door.w, h: L.door.h, open: this.driver.state.door });
    R(c, L.door.x + 4, L.door.base - L.door.h - 12, L.door.w - 8, 8, PAL.ink);
    R(c, L.door.x + 5, L.door.base - L.door.h - 11, L.door.w - 10, 6, D.main);
    if (levelAtLeast(level, "3.1")) paint.beacon(c, L.beacon.x, L.beacon.y, { on: false }, t);
    if (this.isOps()) paint.beacon(c, L.back.x + 11, 50, { on: this.alarmOn(), color: "red" }, t);
    if (levelAtLeast(level, "3.2B")) {
      paint.toolPanel(c, L.tool.x, L.tool.y, { w: L.tool.w, h: L.tool.h, buttons: this.toolLabels().length, lit: this.toolLit(), labels: this.toolLabels() });
    }
    if (levelAtLeast(level, "3.2C")) this.drawMachineLink(c, t);
    for (const lx of L.lamps) paint.lamp(c, lx, 6, this.driver.state.darkTarget === 0);

    // 地面物件与小人：按深度排序
    const items: { y: number; draw: () => void }[] = [];
    items.push({
      y: BASE, draw: () => {
        paint.cabinet(c, L.cabinet.x, L.cabinet.base, { open: this.driver.state.drawer, blink: false }, t);
        paint.archive(c, L.cabinet.x + 2, L.cabinet.base - 40, { n: this.driver.model.summaries || 0, flash: sc.realT < this.driver.state.archiveFlash }, t);
      },
    });
    if (levelAtLeast(level, "S5")) {
      items.push({
        y: BASE, draw: () => paint.cardCabinet(c, L.cards.x, L.cards.base, { cards: this.driver.model.semantic_cards || 0, flash: sc.realT < this.driver.state.cardFlash, label: "语义记录" }, t),
      });
    }
    items.push({
      y: BASE,
      draw: () => {
        this.termInfo = paint.terminal(c, L.terminal.x, L.terminal.base, this.termOpts(), t) as { lampX: number; lampY: number } | undefined;
      },
    });
    items.push({ y: BASE + 2, draw: () => paint.tray(c, L.tray.x, L.tray.base, { count: this.driver.state.trayPaper ? 1 : 0 }) });
    items.push({ y: BASE, draw: () => this.drawBackPiece(c, t) });
    items.push({ y: BASE + 2, draw: () => { this.mailInfo = paint.mailbox(c, L.mailbox.x, L.mailbox.base, { count: this.mailCount() }, t) as unknown as typeof this.mailInfo; } });
    items.push({ y: BASE + 4, draw: () => paint.plant(c, L.plant.x, L.plant.base) });
    items.push({ y: 160, draw: () => paint.plant(c, 452, 160) });
    // 交接管道口与传信管口
    items.push({ y: L.pipe.base, draw: () => paint.pipe(c, L.pipe.x, L.pipe.base, { out: this.pipeMode(), letters: 0 }, t) });
    items.push({ y: L.tube.base, draw: () => paint.tube(c, L.tube.x, L.tube.base, { letters: this.lettersWaiting() }) });
    if (levelAtLeast(level, "3.2B")) items.push({ y: L.post.base, draw: () => paint.postbox(c, L.post.x, L.post.base, { flag: this.driver.state.postFlag }) });
    if (dept === "quality" && this.driver.state.trialSeat) items.push({ y: L.trial.y + 0.5, draw: () => this.drawTrialTable(c, t) });
    if (this.isOps()) {
      if (this.opsRoom()) {
        items.push({ y: L.mdoor.base, draw: () => paint.machineDoor(c, L.mdoor.x, L.mdoor.base, { w: L.mdoor.w, h: L.mdoor.h, glow: this.driver.state.mdoorGlow }, t) });
      }
    }
    if (dept !== "operations") items.push({ y: ROW_A + 0.5, draw: () => this.drawBench(c, t) });
    else if (this.opsRoom()) {
      const cp = this.cartPos();
      items.push({ y: cp[1] - 1, draw: () => paint.cart(c, Math.round(cp[0]), Math.round(cp[1]), { box: this.driver.state.cart.box }) });
    }
    for (const d of this.driver.state.desks) {
      items.push({ y: ROW_B - 1, draw: () => paint.chair(c, d.seatX, ROW_B, { color: D.shade }) });
      items.push({ y: ROW_B + 0.5, draw: () => this.drawDesk(c, d, t) });
    }
    items.push({ y: this.driver.state.bin.y, draw: () => paint.bin(c, this.driver.state.bin.x, this.driver.state.bin.y, { count: this.driver.state.binUntil > sc.realT ? 1 : 0 }) });
    if (!this.isOps()) items.push({ y: ROW_B + 12, draw: () => this.drawTeaStation(c) });
    for (const actor of sc.actors) {
      if (!actor.seat) items.push({ y: actor.y, draw: () => drawActor(c, sc, actor) });
    }
    items.sort((p, q) => p.y - q.y);
    for (const it of items) it.draw();

    this.particles(c);
    this.flyers(c);

    // 灯光
    if (this.driver.state.dark > 0.01) {
      c.fillStyle = `rgba(14,12,34,${this.driver.state.dark.toFixed(3)})`;
      c.fillRect(0, 0, W, H);
    }
    if (this.alarmOn()) {
      const k = sc.reduced ? 0.1 : 0.06 + 0.06 * Math.max(0, Math.sin(t / 160));
      c.fillStyle = `rgba(255,50,50,${k.toFixed(3)})`;
      c.fillRect(0, 0, W, H);
    }
    if (this.driver.state.darkTarget === 0 && !off) for (const lx of L.lamps) paint.lightCone(c, lx, 12, 150, 110, "#fff1c9", 0.1);

    // 发光物件：画在灯光之上
    paint.crt(c, L.crt.x, L.crt.y, this.crtOpts(), t);
    this.drawScreens(c, t);
    if (dept === "engineering" && levelAtLeast(level, "3.2D") && (this.driver.state.selfShot || this.driver.model.self_test)) this.drawSelfShot(c, t);
    if (this.isOps()) paint.beaconLight(c, L.back.x + 11, 50, { on: this.alarmOn(), color: "red", reduced: sc.reduced, len: 120 }, t);
    if (this.mailInfo && this.mailCount() > 0) paint.glow(c, this.mailInfo.lamp[0], this.mailInfo.lamp[1], 7, PAL.yellow2, 0.7);

    // 门牌、举牌、头顶图标
    const doorText = this.driver.model.door || this.driver.state.doorEvent;
    if (doorText && this.doorInfo) {
      const ss = signStyle(doorText);
      drawSign(c, this.doorInfo.nail[0], this.doorInfo.nail[1] + 18, doorText, { size: 7, bg: ss.bg, fg: ss.fg, stripe: ss.stripe, nail: this.doorInfo.nail[1], maxW: 96 });
    }
    drawText(c, `${D.name}部门`, L.door.x + L.door.w / 2, L.door.base - L.door.h - 8, { size: 5.5, weight: 700, align: "center", color: PAL.white });
    for (const a of sc.actors) {
      if (!a.visible) continue;
      if (a.sign && a.anim === "hold_sign") this.drawHeldSign(c, sc, a, a.sign);
      const roomActor = this.driver.actors().find((ra) => ra.id === a.id || `ch-${ra.id}` === a.id);
      if (roomActor?.formSign && a.anim === "hold_form") {
        const [hx, hy] = headTop(sc, a);
        drawSign(c, hx, hy - 4, roomActor.formSign, { size: 6.5, bg: PAL.white, stripe: PAL.orange2, maxW: 150 });
      }
      drawIcon(c, sc, a);
    }
    // 说话气泡：画在最上层，减少动画时也照说
    const says: { a: Actor; text: string; kind: "say" | "think"; tail: boolean; until: number }[] = [];
    for (const a of sc.actors) {
      const roomActor = this.driver.actors().find((ra) => ra.id === a.id || `ch-${ra.id}` === a.id);
      const s = roomActor?.say;
      if (s && a.visible && sc.realT < s.until) says.push({ a, text: s.text, kind: "say", tail: false, until: s.until });
    }
    drawSpeeches(c, sc, says, { size: 7, maxW: 108 });
  }

  private isOps(): boolean {
    return this.driver.model.department === "operations";
  }

  private opsRoom(): boolean {
    return Boolean(this.driver.model.ops);
  }

  private alarmOn(): boolean {
    return this.isOps() && (this.driver.state.alarmUntil > this.scene.realT || this.driver.state.monitorAlarmUntil > this.scene.realT || Boolean(this.driver.model.monitor_alarm));
  }

  private mailCount(): number {
    return this.driver.model.mailbox || 0;
  }

  private effStatus(): string {
    return this.driver.state.eventStatus || this.driver.model.status || "idle";
  }

  private remoteUnknown(): boolean {
    return Boolean(this.driver.state.eventRemote || this.driver.model.remote_unknown);
  }

  private machineName(): string | null {
    return this.driver.state.eventMachine || this.driver.model.machine || null;
  }

  private pipeMode(): string {
    const s = this.effStatus();
    const wait = Boolean(this.driver.model.waiting_provider || this.driver.state.eventWaiting);
    if (s === "interrupted" || wait) return "stopped";
    return this.driver.model.pipes?.out || "idle";
  }

  private lettersWaiting(): number {
    return this.driver.model.pipes?.letters_waiting || 0;
  }

  private toolLabels(): string[] {
    const tp = this.driver.model.tool_panel;
    if (tp && Array.isArray(tp.buttons)) return tp.buttons;
    return ["检", "网", "图"];
  }

  private toolLit(): number {
    if (this.driver.state.toolLit >= 0) return this.driver.state.toolLit;
    if (this.driver.model.tool_panel && this.driver.model.tool_panel.lit !== undefined) return this.driver.model.tool_panel.lit;
    return -1;
  }

  private drawMachineLink(c: CanvasRenderingContext2D, t: number): void {
    const name = this.machineName();
    if (!name) return;
    const y0 = L.terminal.base + 8;
    drawText(c, name, L.terminal.x + 14, y0 - 7, { size: 5, weight: 600, align: "center", color: PAL.ink2, max: 76 });
    const span = L.door.x - (L.terminal.x + 14) + 16;
    R(c, L.terminal.x + 14, y0, span, 1, PAL.metal3);
    if (this.remoteUnknown()) return;
    const off = Math.floor(t / 130);
    for (let i = 0; i < 36; i++) R(c, L.terminal.x + 16 + ((i * 8 + off) % span), y0, 2, 1, PAL.yellow2);
  }

  private cartPos(): [number, number] {
    if (!this.driver.state.cart.pushed) return [this.driver.state.cart.x, ROW_A + 12];
    const a = this.driver.primary();
    if (!a) return [this.driver.state.cart.x, ROW_A + 12];
    const actor = this.scene.actors.find((x) => x.id === a.id || x.id === `ch-${a.id}`);
    if (!actor) return [this.driver.state.cart.x, ROW_A + 12];
    return [actor.x + (actor.facing > 0 ? 6 : -32), actor.y + 1];
  }

  private drawSelfShot(c: CanvasRenderingContext2D, t: number): void {
    const pa = this.driver.primary();
    if (!pa) return;
    const d = pa.desk;
    const shot = this.driver.model.trial || this.driver.model.self_test || {};
    paint.shot(c, d.x + d.w - 52, d.seatY - 74, 48, 32, { screenshot: shot.screenshot, text_lines: shot.text_lines || this.driver.state.eventLines, text_only: shot.model_saw === false }, t);
    drawText(c, "本机浏览器", d.x + d.w - 28, d.seatY - 78, { size: 5, align: "center", color: PAL.ink2, max: 60 });
  }

  private drawTrialTable(c: CanvasRenderingContext2D, t: number): void {
    const tb = L.trial;
    const D = (DEPTS as Record<string, Shell>)["quality"];
    const a = this.scene.actors.find((x) => (x.seat as unknown) === this.driver.state.trialSeat && x.visible);
    if (a) drawActor(c, this.scene, a, "base");
    paint.table(c, tb.x, tb.y, tb.w, { top: PAL.white, face: D.light, edge: mix(D.light, PAL.ink, 0.3), label: "试用台" });
    const trial = this.driver.model.trial || {};
    const step = this.driver.state.eventStep || trial.step || 0;
    const lines = this.driver.state.eventLines || trial.text_lines || null;
    const textOnly = trial.model_saw === false;
    paint.shot(c, tb.x + tb.w - 34, tb.y - 42, 30, 22, { screenshot: trial.screenshot, text_lines: lines, text_only: textOnly }, t);
    if (step) drawText(c, `第 ${step} 步`, tb.x + 8, tb.y + 4, { size: 5, color: PAL.ink2, max: 50 });
    if (textOnly) drawSign(c, tb.x + tb.w - 19, tb.y - 44, "模型只读取文字", { size: 4.5, bg: PAL.yellow1, stripe: PAL.orange2, maxW: 70 });
    if (a) {
      c.save();
      c.beginPath();
      c.rect(0, 0, W, tb.y);
      c.clip();
      drawActor(c, this.scene, a, "front");
      c.restore();
    }
  }

  private drawBackPiece(c: CanvasRenderingContext2D, t: number): void {
    const x = L.back.x;
    const dept = this.driver.model.department;
    if (dept === "product") {
      paint.scrollRack(c, x, BASE, { count: Math.max(0, (this.driver.model.scrolls || 0) - (this.driver.state.scrollHide > this.scene.realT ? 1 : 0)), flash: this.scene.realT < this.driver.state.scrollFlash, label: "卷轴架" }, t);
    } else if (dept === "engineering") {
      RB(c, x, BASE - 50, 60, 50, PAL.metal3);
      R(c, x, BASE - 50, 60, 2, PAL.metal2);
      [BASE - 34, BASE - 17].forEach((sy) => R(c, x, sy, 60, 2, PAL.metal4));
      [[x + 4, BASE - 48], [x + 20, BASE - 48], [x + 38, BASE - 48], [x + 8, BASE - 31], [x + 30, BASE - 31], [x + 14, BASE - 14]].forEach(([bx, by], i) => {
        drawBitmap(c, i % 3 === 0 ? "box_sealed" : "box", bx, by + 3);
      });
      drawText(c, "交付存放", x + 30, BASE - 56, { size: 6, weight: 700, align: "center", color: PAL.ink2 });
    } else if (dept === "quality") {
      RB(c, x, BASE - 50, 60, 50, PAL.white2);
      R(c, x, BASE - 50, 60, 2, PAL.white);
      [BASE - 34, BASE - 17].forEach((sy) => R(c, x, sy, 60, 2, PAL.grey2));
      for (let r = 0; r < 3; r++) {
        for (let q = 0; q < 5; q++) {
          const jx = x + 4 + q * 11;
          const jy = BASE - 47 + r * 17;
          R(c, jx, jy + 2, 7, 11, PAL.ink);
          R(c, jx + 1, jy + 3, 5, 9, [PAL.blue1, PAL.green1, PAL.pink1, PAL.yellow1, PAL.glass][(q + r) % 5]);
          R(c, jx + 1, jy + 1, 5, 2, PAL.grey3);
        }
      }
      drawText(c, "样本柜", x + 30, BASE - 56, { size: 6, weight: 700, align: "center", color: PAL.ink2 });
    } else {
      paint.monitor(c, L.monitor.x, L.monitor.y, { w: L.monitor.w, h: L.monitor.h, alarm: this.alarmOn() }, t);
      paint.backup(c, L.backup.x, L.backup.base, { lit: this.driver.state.backupLit || (this.driver.model.ops as { backup?: number } | undefined)?.backup || 0, flash: this.scene.realT < this.driver.state.backupFlash });
    }
  }

  private whiteboardOpts(): Record<string, unknown> {
    const level = this.driver.model.level ?? "S5";
    const s5 = levelAtLeast(level, "S5");
    const roles = rolesOf(this.driver.model);
    let lines: { text?: string; color?: string; tag?: string | null; tagColor?: string; done?: boolean }[];
    if (s5 && roles.length === 1) {
      const r = roles[0];
      lines = [
        { text: r.task || this.driver.model.crt?.target || r.name, color: PAL.ink2 },
        { color: PAL.blue3 },
        { color: PAL.ink2 },
      ];
    } else if (s5) {
      const nonManagers = roles.filter((r) => r.kind !== "manager");
      lines = nonManagers.map((r) => ({
        text: r.task || r.name,
        tag: (this.driver.state.wbTags[r.id] || r.status === "assigned" || r.status === "working" || r.status === "returned" || r.status === "away") ? r.name : null,
        tagColor: r.status === "returned" || this.driver.state.wbDone[r.id] ? PAL.green1 : PAL.yellow1,
        done: r.status === "returned" || Boolean(this.driver.state.wbDone[r.id]),
      }));
    } else {
      lines = [0, 1, 2, 3].map((i) => ({ color: [PAL.blue3, PAL.ink2, PAL.red3, PAL.ink2][(i + this.driver.state.wbSeed) % 4] }));
    }
    if (this.driver.state.wbExisting || this.driver.model.existing_read) {
      lines = [{ text: "现有行为", color: PAL.blue3 }, { color: PAL.ink2 }, { color: PAL.ink2 }, { color: PAL.ink2 }];
    }
    return {
      w: L.wb.w, h: L.wb.h, floor: L.wb.floor,
      title: s5 ? "部门账本" : "工作计划",
      lines,
      sheet: this.driver.state.wbSheetUntil > this.scene.realT,
      erase: this.driver.state.wbErase,
      blink: false,
    };
  }

  private drawHeldSign(c: CanvasRenderingContext2D, sc: SceneLike, a: Actor, text: string): void {
    const [hx, hy] = headTop(sc, a);
    const ss = signStyle(/待恢复|缺少|凭据|模型/.test(text) ? "待恢复" : text);
    drawSign(c, hx, hy - 1, text, { size: 7, bg: ss.bg, fg: ss.fg, stripe: ss.stripe, maxW: 210, pole: 3 });
  }

  private drawTeaStation(c: CanvasRenderingContext2D): void {
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
  }

  private termOpts(): Record<string, unknown> {
    const off = this.effStatus() === "interrupted";
    const snow = this.remoteUnknown();
    return {
      lever: this.driver.state.lever,
      exit: off ? null : this.driver.state.exit,
      screen: off ? "off" : snow ? "snow" : this.driver.state.termRun ? "term" : "idle",
      blink: snow,
    };
  }

  private crtOpts(): Record<string, unknown> {
    const status = this.effStatus();
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
      alert: status === "waiting_resume",
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
    paint.table(c, b.x, b.y, b.w, { top, face, edge: mix(face, PAL.ink, 0.3), label: BENCH_LABEL[dept] });
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
      if (this.driver.state.darkTarget === 0 || bs.ticks) paint.lightCone(c, b.x + b.w - 22, b.y - 25, 18, 26, "#fff4c4", 0.28);
      RB(c, b.x + 5, b.y - 6, 14, 5, PAL.white);
      for (let i = 0; i < 3; i++) R(c, b.x + 7 + i * 4, b.y - 5, 2, 2, i < bs.ticks ? PAL.green2 : PAL.grey2);
    }
    if (bs.item === "scroll_open") {
      RB(c, cx - 18, b.y - 6, 36, 5, PAL.paper);
      R(c, cx - 20, b.y - 7, 3, 7, PAL.wood3);
      R(c, cx + 17, b.y - 7, 3, 7, PAL.wood3);
      for (let i = 0; i < 3; i++) R(c, cx - 14 + i * 3, b.y - 4, 1, 1, PAL.pline);
      R(c, cx - 14, b.y - 4, 12, 1, PAL.pline);
    } else if (bs.item === "scroll") {
      drawBitmap(c, "scroll", cx - 5, b.y - 5);
    } else if (bs.item) {
      const bm = bitmapDef(bs.item);
      drawBitmap(c, bs.item, cx - Math.floor(bm.rows[0].length / 2), b.y - 3 - bm.rows.length);
      if (bs.item === "box" && bs.tape > 0 && bs.tape < 1) R(c, cx - 1, b.y - 11, 2, Math.round(8 * bs.tape), "#efe0b8");
    }
    if (bs.mark) drawStampMark(c, cx + (bs.item === "scroll_open" ? 6 : 0), b.y - (bs.item === "scroll_open" ? 5 : 8), bs.mark.text, bs.mark.color, { size: 6 });
    if (bs.slip) {
      drawBitmap(c, bs.slip === "release" ? "slip_release" : "slip_defect", cx + 14, b.y - 8);
      if (bs.slipMark) drawStampMark(c, cx + 17, b.y - 8, bs.slipMark.text, bs.slipMark.color, { size: 6, rot: -0.2 });
    }
    void t;
  }

  private ds(_a: Actor | undefined, roleId: string): DeskState {
    return this.driver.state.deskState[roleId] ?? {
      papers: 0, hidePapers: false, folder: 0, doc: 0, box: 0, card: 0, cardResult: 0, scroll: 0, letter: 0, redLamp: false,
    };
  }

  private shown(time: number): boolean {
    return time > this.scene.realT;
  }

  private drawDesk(c: CanvasRenderingContext2D, d: RoomSeat, t: number): void {
    const actor = this.scene.actors.find((x) => x.id === d.roleId || x.id === `ch-${d.roleId}`);
    const s = this.ds(actor, d.roleId);
    const dept = this.driver.model.department;
    const D = (DEPTS as Record<string, Shell>)[dept];
    const seated = actor && (actor.seat as unknown) === d && actor.visible;
    if (seated && actor) drawActor(c, this.scene, actor, "base");
    paint.desk(c, d.x, d.seatY, { w: d.w, wood: dept === "operations" ? [PAL.grey2, PAL.grey3, PAL.grey4, PAL.grey5] : dept === "quality" ? [PAL.white, PAL.white2, PAL.white3, PAL.grey3] : null });
    const cancelled = this.effStatus() === "cancelled";
    const roomActor = this.driver.actors().find((ra) => ra.id === d.roleId || `ch-${ra.id}` === actor?.id);
    const writing = Boolean(roomActor?.persist?.write);
    paint.deskItems(c, d.x, d.seatY, {
      w: d.w, papers: cancelled || s.hidePapers ? 0 : s.papers, folder: !cancelled && this.shown(s.folder),
      docOnDesk: !cancelled && (this.shown(s.doc) || writing), box: cancelled || this.shown(s.box),
      card: this.shown(s.card), cardResult: this.shown(s.cardResult), cup: !(actor && (actor.anim === "tea" || actor.anim === "tea0")),
      monitor: null, lamp: s.redLamp ? "red" : null, nameplate: d.role.name,
      plateColor: D.light, seed: d.i ?? 0,
    }, t);
    if (this.shown(s.scroll)) drawBitmap(c, "scroll", d.x + 6, d.seatY - 5);
    if (this.shown(s.letter)) drawBitmap(c, "letter", d.x + d.w / 2 - 12, d.seatY - 6);
    if (seated && actor) {
      c.save();
      c.beginPath();
      c.rect(0, 0, W, d.seatY);
      c.clip();
      drawActor(c, this.scene, actor, "front");
      c.restore();
    }
  }

  private monitorMode(a: Actor | undefined, d: RoomSeat): string {
    const s = this.effStatus();
    if (s === "interrupted") return "off";
    const prim = this.driver.primary();
    if (this.driver.state.crtBoot < 1 && a && prim && (a.id === prim.id || a.id === `ch-${prim.id}`)) return "boot";
    if (!a || !a.visible) return "idle";
    const ds = this.ds(a, d.roleId);
    if (s === "failed" || ds.redLamp) return "error";
    if (s === "done") return "ok";
    if (s === "idle" || s === "paused" || s === "cancelled" || s === "waiting_resume") return "idle";
    const roomActor = this.driver.actors().find((ra) => ra.id === d.roleId || `ch-${ra.id}` === a.id);
    if (a.anim === "write" || Boolean(roomActor?.persist?.write)) return "diff";
    if (a.anim === "type" || a.anim === "think") return "code";
    return "idle";
  }

  private drawScreens(c: CanvasRenderingContext2D, t: number): void {
    for (const d of this.driver.state.desks) {
      const a = this.scene.actors.find((x) => x.id === d.roleId || x.id === `ch-${d.roleId}`);
      const mode = this.monitorMode(a, d);
      const mx = d.x + d.w - 22 + 3;
      const my = d.seatY - 19 + 2;
      paint.screen(c, mx, my, 14, 9, mode, t, { seed: d.i ?? 0, k: this.driver.state.crtBoot });
      if (mode !== "off" && mode !== "idle") paint.glow(c, mx + 7, my + 4, 12, mode === "error" ? PAL.red2 : PAL.screen3, 0.18);
      const ds = this.ds(a, d.roleId);
      if (ds.redLamp) {
        const on = this.scene.reduced || Math.floor(t / 350) % 2 === 0;
        if (on) paint.glow(c, d.x + d.w - 3, d.seatY - 8, 8, PAL.red2, 0.7);
      }
    }
    const ti = this.termInfo;
    if (ti) {
      const off = this.effStatus() === "interrupted";
      const mode = off ? "off" : this.remoteUnknown() ? "snow" : this.driver.state.termRun ? "term" : "idle";
      paint.screen(c, L.terminal.x + 3, L.terminal.base - 34 + 3, 22, 13, mode, t, { seed: 3 });
      paint.scanlines(c, L.terminal.x + 3, L.terminal.base - 31, 22, 13, 0.18);
      if (this.driver.state.exit && !off) paint.glow(c, ti.lampX, ti.lampY, 9, this.driver.state.exit === "green" ? PAL.green2 : PAL.red2, 0.8);
    }
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
        const x = Math.round(p.x);
        const y = Math.round(p.y);
        c.fillStyle = rgba("#5c606b", 0.75 * k);
        c.fillRect(x - r, y - r + 1, r * 2, r * 2 - 2);
        c.fillRect(x - r + 1, y - r, r * 2 - 2, r * 2);
        c.fillStyle = rgba("#a9adb6", 0.7 * k);
        c.fillRect(x - r + 1, y - r + 1, r * 2 - 3, r - 1);
        continue;
      }
      if (p.kind === "paper") {
        c.fillStyle = PAL.ink;
        c.fillRect(Math.round(p.x) - 2, Math.round(p.y) - 1, 5, 3);
        c.fillStyle = (Math.floor(p.age / 90) % 2) ? PAL.white : PAL.white2;
        c.fillRect(Math.round(p.x) - 1, Math.round(p.y), 3, 1);
        continue;
      }
      c.globalAlpha = p.kind === "confetti" ? Math.min(1, k * 3) : k;
      c.fillStyle = p.color;
      c.fillRect(Math.round(p.x), Math.round(p.y), p.size, p.size);
      c.globalAlpha = 1;
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
    // 墙
    R(c, 0, 0, W, 120, D.wall);
    if (dept === "product") {
      for (let x = 4; x < W; x += 12) R(c, x, 6, 2, 88, D.wall2);
      R(c, 0, 92, W, 3, D.trim);
      R(c, 0, 95, W, 21, D.wall3 ?? D.wall2);
      for (let x = 0; x < W; x += 20) R(c, x, 95, 1, 21, D.trim);
    } else if (dept === "engineering") {
      for (let y = 6; y < 116; y += 16) R(c, 0, y, W, 1, D.wall2);
      for (let x = 0; x < W; x += 24) R(c, x, 6, 1, 110, D.wall2);
      R(c, 0, 7, W, 4, PAL.metal3);
      R(c, 0, 7, W, 1, PAL.metal2);
      for (let x = 30; x < W; x += 90) R(c, x, 5, 4, 8, PAL.metal4);
    } else if (dept === "quality") {
      R(c, 0, 86, W, 5, D.rug);
      R(c, 0, 91, W, 25, D.wall2);
      for (let x = 6; x < W; x += 30) R(c, x, 20, 1, 60, mix(D.wall, D.wall2, 0.5));
    } else {
      for (let x = 0; x < W; x += 24) {
        R(c, x, 6, 1, 110, D.wall3 ?? D.wall2);
        R(c, x + 3, 12, 1, 1, PAL.grey3);
        R(c, x + 3, 100, 1, 1, PAL.grey3);
      }
      R(c, 0, 6, W, 6, PAL.grey5);
      R(c, 0, 12, W, 1, PAL.grey4);
      [PAL.red3, PAL.blue3, PAL.yellow3, PAL.green3].forEach((col, i) => {
        for (let x = 0; x < W; x += 2) R(c, x, 12 + Math.round(2 + Math.sin(x / (18 + i * 5) + i) * 2) + i, 1, 1, col);
      });
    }
    // 天花板与踢脚线
    R(c, 0, 0, W, 5, D.trim);
    R(c, 0, 5, W, 1, mix(D.trim, PAL.ink, 0.3));
    R(c, 0, 114, W, 6, D.trim);
    R(c, 0, 114, W, 1, mix(D.trim, PAL.white, 0.2));
    // 地面
    R(c, 0, 120, W, H - 120, D.floor);
    if (dept === "product") {
      for (let y = 120, i = 0; y < H; y += 8, i++) {
        R(c, 0, y, W, 1, D.floor3 ?? D.floor);
        for (let x = (i % 2) * 24; x < W; x += 48) R(c, x, y, 1, 8, D.floor2 ?? D.floor);
      }
    } else if (dept === "engineering") {
      for (let y = 120; y < H; y += 20) {
        for (let x = 0; x < W; x += 20) {
          R(c, x, y, 20, 20, ((x + y) / 20) % 2 ? D.floor : (D.floor2 ?? D.floor));
          R(c, x, y, 20, 1, D.floor3 ?? D.floor);
          R(c, x, y, 1, 20, D.floor3 ?? D.floor);
        }
      }
    } else if (dept === "quality") {
      for (let y = 120; y < H; y += 12) {
        for (let x = 0; x < W; x += 12) {
          R(c, x, y, 12, 12, ((x + y) / 12) % 2 ? D.floor : (D.floor2 ?? D.floor));
        }
      }
    } else {
      for (let y = 122; y < H; y += 4) {
        for (let x = (y % 8 ? 2 : 0); x < W; x += 4) R(c, x, y, 1, 1, D.floor3 ?? D.floor);
      }
      for (let x = 280; x < 400; x += 8) {
        R(c, x, 150, 4, 3, PAL.yellow2);
        R(c, x + 4, 150, 4, 3, PAL.ink);
      }
    }
    R(c, 0, 120, W, 3, "rgba(0,0,0,0.12)");
    // 地毯：铺在工位下面
    if (dept !== "operations") paint.rug(c, 4, 200, 300, 34, D.rug, D.rug2);
    // 装饰
    if (dept === "product") {
      paint.poster(c, 236, 20, 28, 34, PAL.white, (cc: CanvasRenderingContext2D, x: number, y: number) => {
        R(cc, x + 4, y + 5, 20, 14, "#ffe3a3");
        R(cc, x + 11, y + 8, 6, 6, PAL.yellow2);
        R(cc, x + 13, y + 14, 2, 3, PAL.grey3);
        R(cc, x + 4, y + 23, 16, 1, PAL.pline);
        R(cc, x + 4, y + 27, 12, 1, PAL.pline);
      });
      RB(c, 272, 44, 34, 3, PAL.wood3);
      [PAL.red2, PAL.blue2, PAL.green2, PAL.yellow2, D.main].forEach((col, i) => R(c, 274 + i * 6, 32 + (i % 2) * 2, 5, 12 - (i % 2) * 2, col));
    } else if (dept === "engineering") {
      paint.poster(c, 234, 18, 42, 36, "#2f5da8", (cc: CanvasRenderingContext2D, x: number, y: number, w = 42, h = 36) => {
        for (let i = 4; i < w; i += 6) R(cc, x + i, y + 2, 1, h - 4, "#4a78c2");
        for (let i = 4; i < h; i += 6) R(cc, x + 2, y + i, w - 4, 1, "#4a78c2");
        R(cc, x + 12, y + 10, 16, 16, PAL.white);
        R(cc, x + 14, y + 12, 12, 12, "#2f5da8");
        R(cc, x + 18, y + 16, 4, 4, PAL.white);
      });
      RB(c, 282, 22, 24, 30, "#c79a62");
      for (let i = 0; i < 4; i++) for (let j = 0; j < 5; j++) R(c, 284 + i * 6, 24 + j * 6, 1, 1, "#8a6238");
      R(c, 286, 26, 2, 10, PAL.grey3);
      R(c, 292, 28, 6, 2, PAL.red2);
      R(c, 298, 26, 2, 12, PAL.yellow3);
    } else if (dept === "quality") {
      paint.poster(c, 236, 20, 30, 34, PAL.white, (cc: CanvasRenderingContext2D, x: number, y: number) => {
        [[6, 16], [8, 18], [10, 20], [12, 18], [14, 16], [16, 14], [18, 12], [20, 10]].forEach(([dx, dy]) => R(cc, x + dx, y + dy, 3, 3, PAL.green2));
        R(cc, x + 5, y + 27, 20, 1, PAL.pline);
      });
      RB(c, 276, 24, 30, 22, PAL.white2);
      for (let i = 0; i < 4; i++) {
        R(c, 279 + i * 7, 30, 4, 12, [PAL.blue1, PAL.pink1, PAL.green1, PAL.yellow1][i]);
        R(c, 279 + i * 7, 29, 4, 1, PAL.grey3);
      }
    } else {
      paint.poster(c, 236, 20, 40, 30, PAL.grey6, (cc: CanvasRenderingContext2D, x: number, y: number, w = 40) => {
        let py = y + 20;
        for (let i = 0; i < w - 6; i += 2) {
          const ny = y + 8 + Math.round(hash(i) * 14);
          R(cc, x + 3 + i, Math.min(py, ny), 1, Math.abs(py - ny) + 1, PAL.green2);
          py = ny;
        }
      });
      for (let i = 0; i < 3; i++) RB(c, 12, 18 + i * 12, 46, 8, PAL.grey4);
      for (let i = 0; i < 3; i++) for (let x = 14; x < 56; x += 3) R(c, x, 20 + i * 12, 1, 4, PAL.grey6);
    }
    this.bg = cv;
    return cv;
  }
}
