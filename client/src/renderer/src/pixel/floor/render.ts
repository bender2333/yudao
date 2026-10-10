// 项目楼层的画法：把房间、管道、包裹、小人、信息条、覆盖层与决定板画到 2D 画布上
// （原型 v9 floor.js 的绘制部分与设计说明第 5.2 至 5.7 节，工单 #82）。
//
// 画法复用已有的画布原语（paint、shapes、char），与原型逐行对应；渲染层把这张画布交给 PixiJS
// 显示（floor-view.ts），最近邻放大到容器宽度。

import { bitmapDef } from "../char.ts";
import { paint } from "../paint.ts";
import { DEPTS, ITEM_COLORS, ITEM_SHADES, PAL, PIXEL_FONT_STACK } from "../registry.ts";
import {
  drawActor, drawArrow, drawBitmap, drawBubble, drawIcon, drawPixelText, drawSign, drawText, headTop, measure,
} from "../shapes.ts";
import { polyLength, pointAt, roomOf } from "../world/declare.ts";
import { ACTIVE, IN_ROOM, itemColor, visibleDecisions, type FloorDriver, type BoardRect } from "../world/floor.ts";
import { actorOf, charsOf, primaryOf } from "../world/scene.ts";
import type { Character, LoopItem, MachineView, Room, SceneLike, World } from "../world/types.ts";

export const W = 640;
export const H = 320;
export const BAR = 18;

const PIPE_Y = 138;
const TUBE_Y = 104;
const TUBE = "#7fc3e8";
const TUBE_D = "#3f86b0";

const STATUS_TEXT: Record<string, string> = {
  queued: "排队中", waiting_slot: "等待执行槽位", running: "运行中", asking: "询问中", waiting_provider: "等待模型服务", paused: "已暂停",
  failed: "失败", done: "已完成", cancelled: "已取消", interrupted: "中断", pending_verification: "待核实", waiting_resume: "待恢复",
  stopped: "已停止", stopped_for_upgrade: "因升级停止", adopted: "已采纳", waiting_decision: "等待你的决定", released_unsettled: "已放行",
};
const STATUS_CHIP: Record<string, string> = {
  waiting_decision: PAL.yellow2,
  running: PAL.green2, asking: PAL.blue2, queued: PAL.grey2, waiting_slot: PAL.grey2, waiting_provider: PAL.grey3, paused: PAL.blue1,
  failed: PAL.red2, done: PAL.green1, cancelled: PAL.grey2, interrupted: PAL.grey3, pending_verification: PAL.yellow2,
  stopped: PAL.grey3, waiting_resume: PAL.yellow2, stopped_for_upgrade: PAL.orange2, adopted: PAL.green3, released_unsettled: PAL.green3,
};

/** 房间外壳的画法配色（部门配色取 DEPTS 的子集）。 */
interface ShellPaint {
  wall: string;
  wall2: string;
  trim: string;
  floor: string;
  floor2?: string;
}

/** 部门配色（与原型 sprites.js 的 DEPTS 一致）。 */
interface Shell extends ShellPaint {
  name: string;
  main: string;
  shade: string;
  light: string;
  wall: string;
  wall2: string;
  trim: string;
  floor: string;
  floor2?: string;
}

/** 画一个实心矩形（画面与决定卡片共用的画布原语，坐标取整保证像素清晰）。 */
export const R = (c: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, col: string): void => {
  c.fillStyle = col;
  c.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h));
};
/** 画一个带描边的矩形（画面与决定卡片共用）。 */
export const RB = (c: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, col: string, ink?: string): void => {
  R(c, x - 1, y - 1, w + 2, h + 2, ink ?? PAL.ink);
  R(c, x, y, w, h, col);
};

/** 项目楼层的绘制：背景、大厅、部门房间、成果库、管道、包裹、机房的门、气泡、覆盖层与信息条。 */
export class FloorRenderer {
  private bg: HTMLCanvasElement | null = null;
  private bgKey = "";
  /** 覆盖层的数据由宿主设置（setOverlay）。 */
  overlay: { id: string | null; data: Record<string, unknown> | null } = { id: null, data: null };
  /** 最近一帧画出的覆盖层标签的矩形（画面逻辑坐标），供端到端测试核对标签互不遮挡（工单 #415）。 */
  overlayLabels: { x: number; y: number; w: number; h: number; key: string }[] = [];
  /** 世界里的决定卡片：打开时画在最上层（工单 #179）。 */
  card: { draw: (c: CanvasRenderingContext2D) => void } | null = null;

  constructor(private readonly driver: FloorDriver, private readonly scene: SceneLike) {}

  /** 画一帧。 */
  draw(c: CanvasRenderingContext2D): void {
    const t = this.scene.animT;
    c.imageSmoothingEnabled = false;
    c.drawImage(this.background(), 0, 0);
    this.hall(c, t);
    const lay = this.rooms();
    for (const room of lay.depts) this.department(c, room, t);
    this.library(c);
    this.pipes(c, t);
    this.packages(c);
    this.machineDoor(c, t);
    this.flyers(c);
    this.particles(c);
    this.lights(c, t);
    this.roomLabels(c, t);
    for (const actor of this.scene.actors) {
      if (!actor.icon) continue;
      c.globalAlpha = actor.dim;
      drawIcon(c, this.scene, actor);
      c.globalAlpha = 1;
    }
    this.bubbles(c);
    this.arrows(c);
    this.overlayLayer(c);
    this.infoBar(c);
    this.card?.draw(c);
  }

  private rooms(): { hall: Room; lib: Room; depts: Room[]; door: NonNullable<World["machineDoor"]>; gate: Room } {
    const world = this.driver.world;
    const list = world.roomOrder.map((id) => world.rooms[id]);
    const hall = list.find((r) => r.roomKind === "hall");
    const out = Object.values(world.links).find((l) => l.from === hall?.id && l.linkKind === "handoff");
    if (!hall || !out || !world.machineDoor) throw new Error("楼层缺少大厅、交接管道或者通往机房的门");
    return {
      hall,
      lib: list.find((r) => r.roomKind === "shelf")!,
      depts: list.filter((r) => r.roomKind === "dept"),
      door: world.machineDoor,
      gate: world.rooms[out.to],
    };
  }

  private background(): HTMLCanvasElement {
    const key = this.driver.world.roomOrder.join(",");
    if (this.bg && this.bgKey === key) return this.bg;
    this.bgKey = key;
    const cv = document.createElement("canvas");
    cv.width = W;
    cv.height = H;
    const c = cv.getContext("2d")!;
    c.imageSmoothingEnabled = false;
    const lay = this.rooms();
    R(c, 0, BAR, W, 32, "#9fd0ee");
    for (const [x, y] of [[30, 28], [250, 24], [470, 30]]) {
      R(c, x, y, 26, 5, PAL.white);
      R(c, x + 6, y - 3, 14, 3, PAL.white);
    }
    R(c, 0, 44, W, 6, "#6f7a8c");
    R(c, 0, 44, W, 1, "#8e98a9");
    R(c, 0, 48, W, 168, "#4d5466");
    // 走廊与地面
    R(c, 0, 214, W, 48, "#d8cfbd");
    for (let x = 0; x < W; x += 16) R(c, x, 214, 1, 48, "#cbc1ad");
    R(c, 0, 262, W, 3, "#b3a78e");
    R(c, 0, 265, W, 38, "#8a7f6c");
    for (let x = 6; x < W; x += 12) R(c, x, 266, 1, 36, "#7c725f");
    R(c, 0, H - 16, W, 16, "#7fae62");
    for (let x = 0; x < W; x += 6) R(c, x + (x % 12 ? 2 : 0), H - 16, 2, 2, "#6c9a52");
    const hall = lay.hall;
    R(c, hall.x, 50, hall.w, 100, "#e9e2d2");
    for (let y = 58; y < 150; y += 14) R(c, hall.x, y, hall.w, 1, "#ddd4c1");
    R(c, hall.x, 150, hall.w, 64, "#c9a77a");
    for (let x = hall.x; x < hall.x + hall.w; x += 10) R(c, x, 150, 1, 64, "#b8966a");
    for (const room of lay.depts) this.roomShell(c, room, DEPT_SHELL[room.id]);
    this.roomShell(c, lay.lib, { wall: "#efe6d2", wall2: "#e2d5b8", floor: "#b88a58", floor2: "#a37748", trim: "#6a4a2e" });
    this.bg = cv;
    return cv;
  }

  private roomShell(c: CanvasRenderingContext2D, r: Room, d: ShellPaint): void {
    R(c, r.x, 50, r.w, 100, d.wall);
    for (let y = 56; y < 150; y += 10) R(c, r.x + 4, y, r.w - 8, 1, d.wall2);
    R(c, r.x, 150, r.w, 64, d.floor);
    for (let y = 154; y < 214; y += 8) R(c, r.x, y, r.w, 1, d.floor2 ?? d.floor);
    R(c, r.x, 148, r.w, 3, d.trim);
    R(c, r.x - 3, 48, 3, 168, "#2e3240");
    R(c, r.x + r.w, 48, 3, 168, "#2e3240");
    R(c, r.x - 3, 212, r.w + 6, 5, "#2e3240");
  }

  // -------------------------------------------------------------------------
  // 管道

  private pipeState(pipe: World["links"][string]): "flowing" | "idle" | "stopped" {
    return (this.scene.pipeState(pipe.id)?.state as "flowing" | "idle" | "stopped" | undefined) ?? "idle";
  }

  private pipes(c: CanvasRenderingContext2D, t: number): void {
    const world = this.driver.world;
    for (const p of Object.values(world.links)) this.pipe(c, p, t);
    for (const id of world.roomOrder) {
      const r = world.rooms[id];
      const ports = r.def.ports ?? [];
      if (ports.includes("in")) this.port(c, r.inPort, PIPE_Y, "handoff");
      if (ports.includes("out")) this.port(c, r.outPort, PIPE_Y, "handoff");
      if (ports.includes("tubeIn")) this.port(c, r.inPort, TUBE_Y, "tube");
      if (ports.includes("tubeOut")) this.port(c, r.outPort, TUBE_Y, "tube");
    }
    // Stage 6 的判定阀门位置：交接管道上的空卡座
    for (const p of Object.values(world.links)) {
      if (!p.def.valve) continue;
      const mx = Math.round((p.pts[0][0] + p.pts[1][0]) / 2);
      R(c, mx - 3, PIPE_Y - 9, 6, 2, PAL.metal4);
    }
    // 停止流动的说明：等待模型服务
    for (const w of this.driver.model.waiting_provider) {
      const r = roomOf(world, w.department);
      if (!r) continue;
      const text = `等待模型服务${w.next_retry_at ? " · 重试中" : ""}`;
      drawSign(c, r.x + r.w / 2, PIPE_Y - 12, text, { size: 5.5, bg: PAL.grey1, stripe: PAL.grey3, maxW: r.w + 20 });
    }
    // 未回答的询问：信件停在接收方的传信管出口
    this.driver.model.open_requests.forEach((q, i) => {
      const pts = tubePts(world, q.from, q.to);
      if (!pts) return;
      const [x, y] = pts[pts.length - 1];
      const bob = this.scene.reduced ? 0 : Math.round(Math.sin(t / 300 + i) * 1);
      RB(c, Math.round(x) - 4, Math.round(y) + 5 + bob, 8, 5, PAL.white);
      R(c, Math.round(x) - 3, Math.round(y) + 6 + bob, 6, 1, PAL.blue2);
    });
  }

  private pipe(c: CanvasRenderingContext2D, p: World["links"][string], t: number): void {
    const state = this.pipeState(p);
    const tube = p.linkKind === "tube";
    const thick = tube ? 3 : 8;
    const flashing = (this.driver.state.pipeFlash[p.id] ?? 0) > this.scene.realT && Math.floor(t / 180) % 2 === 0;
    const body = flashing ? PAL.red2 : tube ? TUBE : state === "stopped" ? "#9aa0aa" : p.linkKind === "return" ? "#c9b48a" : PAL.glass;
    for (let i = 1; i < p.pts.length; i++) {
      const [x0, y0] = p.pts[i - 1];
      const [x1, y1] = p.pts[i];
      const x = Math.min(x0, x1) - thick / 2;
      const y = Math.min(y0, y1) - thick / 2;
      const w = Math.abs(x1 - x0) + thick;
      const h = Math.abs(y1 - y0) + thick;
      RB(c, x, y, w, h, body, PAL.ink);
      if (y0 === y1) R(c, x + 1, y + 1, w - 2, 1, PAL.white);
      else R(c, x + 1, y + 1, 1, h - 2, PAL.white);
    }
    if (!tube) for (const [x, y] of p.pts) RB(c, x - thick / 2 - 1, y - thick / 2 - 1, thick + 2, thick + 2, PAL.metal3);
    if (this.scene.reduced) return;
    const len = polyLength(p.pts);
    const gap = tube ? 14 : 22;
    const f = p.flow;
    let off: number;
    let alpha: number;
    if (this.scene.autonomy) {
      if (!f || f.load <= 0.02) return;
      off = (f.phase / (tube ? 30 : 45)) % gap;
      alpha = f.load;
    } else {
      if (state !== "flowing" || this.scene.frozen) return;
      off = (t / (tube ? 30 : 45)) % gap;
      alpha = 1;
    }
    c.globalAlpha = alpha;
    c.fillStyle = tube ? TUBE_D : "rgba(74,144,217,0.55)";
    for (let d = off; d < len; d += gap) {
      const [x, y] = pointAt(p.pts, d);
      c.fillRect(Math.round(x) - 1, Math.round(y) - (tube ? 0 : 1), 2, tube ? 1 : 2);
    }
    c.globalAlpha = 1;
  }

  private port(c: CanvasRenderingContext2D, x: number, y: number, kind: string): void {
    if (kind === "tube") {
      RB(c, x - 3, y - 4, 6, 8, TUBE_D);
      R(c, x - 1, y - 2, 2, 4, PAL.ink);
      return;
    }
    RB(c, x - 6, y - 8, 12, 16, PAL.metal2);
    R(c, x - 4, y - 5, 8, 10, PAL.ink2);
    R(c, x - 4, y - 5, 8, 1, PAL.metal1);
  }

  // -------------------------------------------------------------------------
  // 大厅与队列

  private queueItems(): LoopItem[] {
    return this.driver.model.items
      .filter((it) => it.status === "queued" || it.status === "waiting_slot")
      .sort((a, b) => (Number(b.kind === "repair") - Number(a.kind === "repair")) || ((a.queue_pos ?? 99) - (b.queue_pos ?? 99)));
  }

  private hall(c: CanvasRenderingContext2D, t: number): void {
    const lay = this.rooms();
    const hall = lay.hall;
    const x = hall.x;
    drawSign(c, x + 40, 66, "大厅", { size: 7, bg: PAL.paper, stripe: PAL.wood3 });
    paint.clock(c, x + hall.w - 22, 56, { time: this.driver.state.clock, stopped: this.driver.model.interrupted });
    // 信箱：用户的输入以信件投进来，管道从这里出发
    RB(c, x + 8, PIPE_Y - 2, 14, 18, PAL.red2);
    R(c, x + 10, PIPE_Y + 1, 10, 2, PAL.ink);
    RB(c, x + 12, PIPE_Y - 7, 6, 3, this.sig("mail") ? PAL.yellow2 : PAL.grey4);
    drawText(c, "信箱", x + 15, PIPE_Y + 24, { size: 5.5, weight: 700, align: "center", color: PAL.ink2 });
    // 执行槽位灯（3.4A）：整个系统的占用数与总数
    const slots = this.driver.model.slots;
    if (slots) {
      const total = Math.max(1, slots.total);
      const used = slots.used;
      const pw = Math.min(hall.w - 12, 12 + total * 11);
      RB(c, x + 6, 80, pw, 28, PAL.grey5);
      drawText(c, `执行槽位 ${used}/${total}`, x + 6 + pw / 2, 86, { size: 5.5, weight: 700, align: "center", color: PAL.white, max: pw - 4 });
      for (let i = 0; i < total; i++) {
        const on = i < used;
        RB(c, x + 11 + i * 11, 94, 7, 7, on ? PAL.green2 : PAL.grey4);
        if (on) R(c, x + 12 + i * 11, 95, 2, 2, PAL.green1);
      }
    }
    // 队列：管道入口前的一串包裹；修复事项带红色十字
    const queue = this.queueItems();
    const slotWait = queue.some((it) => it.status === "waiting_slot");
    queue.forEach((it, i) => {
      const target = lay.gate.inPort - 20 - i * 15;
      const cur = this.driver.state.queueX[it.work_item_id] ?? target;
      const next = this.scene.reduced ? target : cur + (target - cur) * 0.12;
      this.driver.state.queueX[it.work_item_id] = next;
      const px = Math.round(next);
      if (px < x + 24) return;
      drawBitmap(c, "box", px - 6, PIPE_Y - 16);
      R(c, px - 6, PIPE_Y - 4, 12, 2, ITEM_COLORS[it.color_index % ITEM_COLORS.length]);
      if (it.kind === "repair") {
        R(c, px - 1, PIPE_Y - 14, 2, 6, PAL.red2);
        R(c, px - 3, PIPE_Y - 12, 6, 2, PAL.red2);
      }
      if (it.queue_pos) drawPixelText(c, String(it.queue_pos), px, PIPE_Y - 24, PAL.ink, "center");
    });
    // 入口阀门：等待执行槽位时关闭
    const vx = lay.gate.inPort - 8;
    RB(c, vx - 2, PIPE_Y - 7, 4, 14, PAL.metal3);
    RB(c, vx - 5, PIPE_Y - 12, 10, 3, slotWait ? PAL.red2 : PAL.green2);
    if (slotWait) drawSign(c, x + hall.w / 2 + 6, PIPE_Y + 38, "等待执行槽位", { size: 5.5, bg: PAL.yellow1, stripe: PAL.orange2, maxW: hall.w });
    if ((this.driver.state.flash[hall.id]?.until ?? 0) > this.scene.realT) {
      paint.blinkFrame(c, x + 26, PIPE_Y - 20, { w: lay.gate.inPort - x - 30, h: 22 });
    }
    // 长椅与植物
    RB(c, x + 30, 200, 34, 4, PAL.wood2);
    R(c, x + 32, 204, 2, 8, PAL.wood4);
    R(c, x + 60, 204, 2, 8, PAL.wood4);
    paint.plant(c, x + hall.w - 16, 212);
    this.board(c);
    void t;
  }

  /** 大厅的决定板：立在大厅地面上的告示板，等待回答的决定请求一张一张贴在上面。 */
  boardRect(): BoardRect {
    return this.driver.boardRect();
  }

  private board(c: CanvasRenderingContext2D): void {
    const decisions = visibleDecisions(this.driver.model.decisions, this.driver.state.hidden, this.scene.realT);
    if (!decisions.length) return;
    const b = this.boardRect();
    drawSign(c, b.x + b.w / 2, b.y - 3, "待你决定", { size: 5.5, bg: PAL.yellow1, stripe: PAL.orange2 });
    R(c, b.x + 3, b.y + b.h + 2, 2, 8, PAL.wood4);
    R(c, b.x + b.w - 5, b.y + b.h + 2, 2, 8, PAL.wood4);
    RB(c, b.x - 2, b.y - 2, b.w + 4, b.h + 4, PAL.wood3);
    R(c, b.x, b.y, b.w, b.h, "#c9955c");
    decisions.slice(0, 6).forEach((d, i) => {
      const nx = b.x + 3 + (i % 3) * 10;
      const ny = b.y + 3 + Math.floor(i / 3) * 12;
      RB(c, nx, ny, 8, 10, PAL.white);
      const item = d.work_item_id ? this.driver.model.items.find((x) => x.work_item_id === d.work_item_id) : null;
      R(c, nx, ny, 8, 2, item ? itemColor(item) : PAL.grey2);
      R(c, nx + 2, ny + 4, 4, 1, PAL.grey2);
      R(c, nx + 2, ny + 6, 4, 1, PAL.grey2);
    });
    if (decisions.length > 6) {
      drawText(c, `+${decisions.length - 6}`, b.x + b.w - 3, b.y + b.h - 4, { size: 5.5, weight: 800, align: "right", color: PAL.ink });
    }
    if (this.sig("board") && !this.scene.reduced) paint.blinkFrame(c, b.x - 3, b.y - 3, { w: b.w + 6, h: b.h + 6 });
  }

  // -------------------------------------------------------------------------
  // 部门房间与成果库

  private department(c: CanvasRenderingContext2D, r: Room, t: number): void {
    const world = this.driver.world;
    const here = this.itemsIn(r.id);
    const working = here.some((it) => ACTIVE.includes(it.status));
    const sx = r.x + Math.round(r.w / 2) - 22;
    const sy = 68;
    RB(c, sx - 2, sy - 2, 32, 22, PAL.beige2);
    paint.screen(c, sx, sy, { w: 28, h: 18, mode: this.driver.model.interrupted ? "off" : working ? "code" : "idle", seed: r.x }, t);
    paint.scanlines(c, sx, sy, { a: 0.18 });
    paint.lamp(c, r.x + r.w - 30, 58, { on: working, from: 50 });
    r.def.props?.(c, r, t, this.driver.declCtx());
    const chars = charsOf(world, r.id).sort((p, q) => p.seatIndex - q.seatIndex);
    const prim = primaryOf(world, r.id);
    const standing: Character[] = [];
    for (const ch of chars) {
      const a = actorOf(this.scene, ch.id);
      if (!a) continue;
      const desk = (r.seats && r.seats[ch.seatIndex]) || r.desk;
      paint.chair(c, desk.seatX, desk.seatY, { color: DEPT_SHELL[r.id]?.shade ?? PAL.metal3 });
      const sitting = a.seat === desk;
      if (sitting) drawActor(c, this.scene, a, "base");
      paint.desk(c, desk.x, desk.seatY, { w: desk.w });
      // 显示器：桌子太窄时不画
      if (desk.w >= 30) {
        R(c, desk.x + desk.w - 11, desk.seatY - 9, 9, 6, PAL.ink);
        paint.screen(c, desk.x + desk.w - 10, desk.seatY - 8, { w: 7, h: 4, mode: this.deskMode(ch, prim), seed: desk.x }, t);
      }
      if (ch === prim && ch.item) {
        R(c, desk.x + 2, desk.seatY - 12, 1, 7, PAL.metal3);
        R(c, desk.x + 3, desk.seatY - 12, 5, 3, ITEM_COLORS[ch.item.color_index % ITEM_COLORS.length]);
      }
      if (sitting) {
        c.save();
        c.beginPath();
        c.rect(0, 0, W, desk.seatY);
        c.clip();
        drawActor(c, this.scene, a, "front");
        c.restore();
      } else {
        standing.push(ch);
      }
    }
    standing.sort((p, q) => (actorOf(this.scene, p.id)?.y ?? 0) - (actorOf(this.scene, q.id)?.y ?? 0)).forEach((ch) => {
      const a = actorOf(this.scene, ch.id);
      if (a) drawActor(c, this.scene, a);
    });
    this.door(c, r);
  }

  /** 房间里多个角色时：中心角色的屏幕反映事项的状态，其余看自己有没有在工作。 */
  private deskMode(ch: Character, primary: Character | null): string {
    if (this.driver.model.interrupted) return "off";
    const info = ch.roleInfo;
    if (info && primary && primary !== ch) return info.status === "working" ? "code" : "idle";
    const it = ch.item;
    return it && it.status === "running" ? "code" : it && it.status === "failed" ? "error" : it && it.status === "pending_verification" ? "alert" : "idle";
  }

  private door(c: CanvasRenderingContext2D, r: Room): void {
    const dx = r.door - 9;
    R(c, dx - 1, 211, 20, 7, PAL.ink);
    R(c, dx, 212, 18, 5, PAL.wood2);
    R(c, dx + 1, 212, 16, 1, PAL.wood1);
    R(c, dx + 13, 214, 2, 2, PAL.yellow2);
  }

  private library(c: CanvasRenderingContext2D): void {
    const r = this.rooms().lib;
    drawSign(c, r.x + r.w / 2, 68, "成果库", { size: 7, bg: PAL.paper, stripe: PAL.green3 });
    const adopted = this.driver.model.shelves.adopted;
    drawText(c, "已采纳", r.x + 20, 82, { size: 6, weight: 700, color: PAL.green3 });
    paint.shelf(c, r.x + 18, 126, { w: r.w - 24 });
    const per = Math.max(1, Math.floor((r.w - 26) / 18));
    const shown = adopted.slice(-per);
    shown.forEach((v, i) => {
      const bx = r.x + 20 + i * 18;
      drawBitmap(c, "box_sealed", bx, 117);
      RB(c, bx + 1, 130, 13, 7, PAL.white);
      drawText(c, v, bx + 7.5, 133.8, { size: 6, weight: 800, align: "center", color: PAL.green3, max: 13 });
      if (i === shown.length - 1 && this.sig("shelf")) paint.blinkFrame(c, bx - 1, 115, { w: 15, h: 23 });
    });
    if (!adopted.length) drawText(c, "尚未采纳", r.x + r.w / 2, 120, { size: 6, align: "center", color: PAL.grey3 });
    this.door(c, r);
  }

  /** 通往机房的门：门上列出本项目正在使用的机器与其上的动作数。 */
  private machineDoor(c: CanvasRenderingContext2D, t: number): void {
    const machines = this.driver.model.machines as MachineView[] | null;
    if (!machines) return;
    const d = this.rooms().door;
    const acts = machines.reduce((n, m) => n + m.actions, 0);
    const unknown = machines.some((m) => m.unknown);
    RB(c, d.x, d.y, d.w, d.h, "#3b3f4c");
    R(c, d.x + 2, d.y + 2, d.w - 4, d.h - 2, "#565c6c");
    R(c, d.x + d.w - 7, d.y + d.h / 2, 2, 3, PAL.yellow2);
    if (acts || this.sig("door")) {
      const k = this.scene.reduced ? 0.8 : 0.5 + 0.3 * Math.sin(t / 200);
      c.fillStyle = `rgba(255,214,107,${k.toFixed(3)})`;
      c.fillRect(d.x + 2, d.y + d.h - 2, d.w - 4, 2);
      c.fillRect(d.x + d.w - 3, d.y + 4, 1, d.h - 6);
    }
    drawText(c, "机房", d.x + d.w / 2, d.y + 8, { size: 5.5, weight: 700, align: "center", color: PAL.white });
    const lines = machines.map((m) => `${m.name.replace(/（.*）/, "")} · ${m.actions}${m.online === false ? " · 离线" : ""}`);
    if (lines.length) {
      const w = 74;
      const h = lines.length * 8 + 4;
      const px = d.x - w - 4;
      const py = d.y + 2;
      RB(c, px, py, w, h, PAL.paper);
      lines.forEach((line, i) => drawText(c, line, px + 3, py + 6 + i * 8, { size: 5.5, weight: 600, color: PAL.ink, max: w - 6 }));
    }
    if (unknown) drawBitmap(c, "question", d.x + 10, d.y + 14);
    for (const dot of this.driver.state.remoteDots) {
      const k = Math.min(1, (this.scene.realT - dot.t0) / dot.ms);
      const x = dot.from[0] + (dot.to[0] - dot.from[0]) * k;
      const y = dot.from[1] + (dot.to[1] - dot.from[1]) * k;
      R(c, Math.round(x) - 1, Math.round(y) - 1, 3, 3, PAL.yellow2);
    }
  }

  // -------------------------------------------------------------------------
  // 包裹、飞行物与粒子

  private packages(c: CanvasRenderingContext2D): void {
    for (const pk of Object.values(this.driver.world.packages)) {
      const pos = pk.transit?.pos ?? null;
      if (!pos) continue;
      const [x, y] = pos;
      if (pk.small) {
        RB(c, Math.round(x) - 2, Math.round(y) - 1, 5, 3, PAL.white);
        R(c, Math.round(x) - 1, Math.round(y), 3, 1, pk.color ?? PAL.blue2);
      } else {
        const b = bitmapDef(pk.bmp ?? "box_sealed");
        const w = b.rows[0].length;
        const h = b.rows.length;
        drawBitmap(c, pk.bmp ?? "box_sealed", Math.round(x - w / 2), Math.round(y - h / 2));
        if (pk.color) R(c, Math.round(x - w / 2), Math.round(y + h / 2), w, 2, pk.color);
      }
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
        c.fillStyle = `rgba(92,96,107,${(0.75 * k).toFixed(3)})`;
        c.fillRect(Math.round(p.x) - r, Math.round(p.y) - r + 1, r * 2, r * 2 - 2);
        continue;
      }
      c.globalAlpha = p.kind === "confetti" ? Math.min(1, k * 3) : k;
      c.fillStyle = p.color;
      c.fillRect(Math.round(p.x), Math.round(p.y), p.size, p.size);
      c.globalAlpha = 1;
    }
  }

  // -------------------------------------------------------------------------
  // 灯光、房间名与气泡

  private lights(c: CanvasRenderingContext2D, t: number): void {
    const ctx = this.driver.declCtx();
    for (const r of this.rooms().depts) {
      const here = this.itemsIn(r.id);
      const lit = here.some((it) => ACTIVE.includes(it.status) || it.status === "done") || Boolean(r.def.lit?.(ctx));
      if (!lit) {
        c.fillStyle = "rgba(14,12,34,0.32)";
        c.fillRect(r.x, 50, r.w, 164);
      }
      if (this.driver.model.waiting_provider.some((w) => w.department === r.id)) {
        c.fillStyle = "rgba(40,44,60,0.25)";
        c.fillRect(r.x, 50, r.w, 164);
      }
      if (here.some((it) => it.status === "pending_verification")) {
        const k = this.scene.reduced ? 0.14 : 0.1 + 0.08 * Math.sin(t / 240);
        c.fillStyle = `rgba(255,196,40,${k.toFixed(3)})`;
        c.fillRect(r.x, 50, r.w, 164);
        paint.beacon(c, r.x + r.w - 14, 54, { on: true }, t);
      }
      const fl = this.driver.state.flash[r.id];
      if (fl && fl.until > this.scene.realT) {
        c.fillStyle = rgbaOf(fl.color, Math.min(0.35, ((fl.until - this.scene.realT) / 900) * 0.35));
        c.fillRect(r.x, 50, r.w, 164);
      }
      r.def.tint?.(c, r, t, ctx);
    }
    if (this.driver.model.interrupted) {
      c.fillStyle = "rgba(8,8,24,0.55)";
      c.fillRect(0, BAR, W, H - BAR);
    }
  }

  private roomLabels(c: CanvasRenderingContext2D, t: number): void {
    for (const r of this.rooms().depts) {
      const dept = DEPT_SHELL[r.id];
      drawSign(c, r.x + r.w / 2, 54, dept?.name ?? r.label, { size: 7, bg: dept?.main ?? PAL.paper, fg: PAL.white, hi: dept?.light, lo: dept?.shade, minW: 30 });
      this.itemsIn(r.id).forEach((it, i) => {
        drawBitmap(c, (Math.floor(t / 320) + i) % 2 && !this.scene.reduced ? "flag2" : "flag", r.door - 22 - i * 9, 218, {
          recolor: { X: ITEM_COLORS[it.color_index % 6], x: ITEM_SHADES[it.color_index % 6] },
        });
      });
    }
  }

  /** 头顶的对话框：说话气泡是正在做的任务，思考气泡是队列里的下一项。 */
  private bubbles(c: CanvasRenderingContext2D): void {
    const list: { a: NonNullable<ReturnType<typeof actorOf>>; text: string; kind: "say" | "think"; tail: boolean; until: number }[] = [];
    for (const ch of Object.values(this.driver.world.characters)) {
      const a = actorOf(this.scene, ch.id);
      const bubble = ch.bubble;
      let said = this.driver.state.said[ch.id];
      if (bubble && (!said || said.text !== bubble.text)) {
        said = { text: bubble.text, until: this.scene.realT + sayMs(bubble.text) };
        this.driver.state.said[ch.id] = said;
      }
      if (!a || !a.visible || !said || (!bubble && said.until <= this.scene.realT)) continue;
      list.push({ a, text: said.text, kind: bubble?.kind ?? "say", tail: Boolean(bubble?.tail), until: bubble ? 0 : said.until });
    }
    drawSpeeches(c, this.scene, list);
  }

  private arrows(c: CanvasRenderingContext2D): void {
    for (const ar of this.driver.state.arrows) {
      drawArrow(c, ar.pts, ar.color, { dash: ar.dash });
      const mid = pointAt(ar.pts, polyLength(ar.pts) / 2);
      const b = bitmapDef(ar.bmp);
      drawBitmap(c, ar.bmp, mid[0] - b.rows[0].length / 2, mid[1] - b.rows.length - 3);
    }
  }

  // -------------------------------------------------------------------------
  // 覆盖层与信息条

  private overlayLayer(c: CanvasRenderingContext2D): void {
    const overlay = this.overlay;
    if (!overlay.id || !overlay.data) return;
    this.overlayLabels = [];
    c.fillStyle = "rgba(12,14,30,0.35)";
    c.fillRect(0, BAR, W, H - BAR);
    const world = this.driver.world;
    const label = (key: string, x: number, y: number, text: string, bg?: string): void => {
      const rect = drawSign(c, x, y, text, { size: 6, bg: bg ?? PAL.white, stripe: PAL.blue2, maxW: 150 });
      this.overlayLabels.push({ ...rect, key });
    };
    const data = overlay.data;
    if (overlay.id === "flow") {
      const segments = (data.segments ?? []) as { from: string; to: string; count: number; last_at: string; kind: string }[];
      // 同一对部门的非返工行与返工行走同一条路径（工单 #415 的分组）：都画在中点时两块牌子叠在一起。
      // 同一条路径上的第二块牌子往上抬一行，两块牌子因此错开，落点仍在这条路径的中点上
      const lanes = new Map<string, number>();
      for (const seg of segments) {
        const path = pathFor(world, seg.from, seg.to);
        if (!path) continue;
        const key = `${seg.from}>${seg.to}`;
        const lane = lanes.get(key) ?? 0;
        lanes.set(key, lane + 1);
        const [x, y] = pointAt(path, polyLength(path) / 2);
        label(key, x, y - 6 - lane * 15, `${seg.count} 次`, seg.kind === "rework" ? PAL.red1 : PAL.white);
      }
    } else if (overlay.id === "waiting") {
      for (const e of (data.entries ?? []) as { department: string; text: string; waited_sec: number; row?: number }[]) {
        const r = roomOf(world, e.department) ?? this.rooms().hall;
        label(e.department, r.x + r.w / 2, (e.row ?? 0) * 14 + 94, `${e.text} · ${Math.round(e.waited_sec)} 秒`, PAL.yellow1);
      }
    } else if (overlay.id === "recovery") {
      for (const e of (data.entries ?? []) as { department: string; text: string; state: string }[]) {
        const r = roomOf(world, e.department);
        if (!r) continue;
        label(e.department, r.x + r.w / 2, 94, e.text, e.state === "pending_verification" ? PAL.yellow1 : PAL.white);
      }
    } else if (overlay.id === "context_usage") {
      for (const e of (data.entries ?? []) as { department: string; role: string; ratio: number }[]) {
        const r = roomOf(world, e.department);
        if (!r) continue;
        const ch = charsOf(world, e.department).find((x) => x.id === e.role || x.roleKind === e.role);
        const seat = ch ? (r.seats && r.seats[ch.seatIndex]) || r.desk : null;
        const x = seat ? seat.seatX : r.x + r.w / 2;
        const row = ch ? ch.seatIndex % 2 : 0;
        label(e.department, x, 152 - row * 11, `${(ch && ch.name) || e.role} ${Math.round(e.ratio * 100)}%`, e.ratio >= 0.8 ? PAL.orange1 : PAL.green1);
      }
    } else if (overlay.id === "semantic_records") {
      for (const e of (data.entries ?? []) as { department: string; valid: number; conflicts: number }[]) {
        const r = roomOf(world, e.department);
        if (!r) continue;
        label(e.department, r.x + r.w / 2, 94, `有效 ${e.valid} · 冲突 ${e.conflicts}`, e.conflicts ? PAL.orange1 : PAL.white);
      }
    }
  }

  /** 上传不进行中的事项的信息条：轮次、已用时间与上限、当前部门、状态。 */
  private infoBar(c: CanvasRenderingContext2D): void {
    R(c, 0, 0, W, BAR, "#1f2230");
    R(c, 0, BAR - 1, W, 1, "#3a3f52");
    const focus = this.scene.focusId;
    const items = this.driver.model.items;
    const it = (focus ? items.find((x) => x.work_item_id === focus) : null)
      ?? items.find((x) => ACTIVE.includes(x.status) || x.status === "waiting_provider")
      ?? items.find((x) => IN_ROOM.includes(x.status))
      ?? null;
    if (!it) {
      drawText(c, "没有进行中的事项", 8, 9, { size: 7, color: PAL.grey1 });
      return;
    }
    R(c, 6, 5, 8, 8, PAL.ink);
    R(c, 7, 6, 6, 6, ITEM_COLORS[it.color_index % 6]);
    let x = 18;
    x += drawText(c, it.sign || it.work_item_id, x, 9, { size: 7, weight: 700, color: PAL.white, max: 170 }) + 8;
    const chip = (text: string, bg: string, fg?: string): void => {
      c.font = `700 6.5px ${PIXEL_FONT_STACK}`;
      const w = c.measureText(text).width + 8;
      R(c, x, 4, w, 10, bg);
      drawText(c, text, x + w / 2, 9, { size: 6.5, weight: 700, align: "center", color: fg ?? PAL.ink });
      x += w + 4;
    };
    if (it.round) chip(`第 ${it.round} 轮`, PAL.paper);
    const dept = it.department ? DEPT_SHELL[it.department] : null;
    if (dept) chip(`当前部门：${dept.name}`, dept.light);
    chip(STATUS_TEXT[it.status] ?? it.status, STATUS_CHIP[it.status] ?? PAL.grey2, ["running", "failed", "adopted", "asking"].includes(it.status) ? PAL.white : PAL.ink);
    if (it.time_limit_sec) {
      const k = Math.min(1, (it.elapsed_sec ?? 0) / it.time_limit_sec);
      const bw = 110;
      const bx = W - bw - 8;
      const col = k >= 0.95 ? PAL.red2 : k >= 0.8 ? PAL.orange2 : PAL.green2;
      drawText(c,
        `已用 ${Math.round((it.elapsed_sec ?? 0) / 60)} 分 / 上限 ${Math.round(it.time_limit_sec / 60)} 分${it.waiting_provider_sec ? ` · 等待 ${Math.round(it.waiting_provider_sec / 60)} 分不计入` : ""}`,
        bx - 6, 9, { size: 6.5, weight: 600, align: "right", color: k >= 0.8 ? PAL.orange1 : PAL.grey1 });
      R(c, bx, 5, bw, 8, PAL.ink);
      R(c, bx + 1, 6, bw - 2, 6, "#383d50");
      const ew = Math.round((bw - 2) * k);
      R(c, bx + 1, 6, ew, 6, col);
      if (it.waiting_provider_sec) {
        const wk = Math.min(1 - k, it.waiting_provider_sec / it.time_limit_sec);
        const ww = Math.max(2, Math.round((bw - 2) * wk));
        R(c, bx + 1 + ew, 6, ww, 6, PAL.grey3);
        c.fillStyle = PAL.grey1;
        for (let i = 0; i < ww; i += 3) c.fillRect(bx + 1 + ew + i, 6 + (i % 6 < 3 ? 0 : 3), 1, 3);
      }
    }
  }

  // -------------------------------------------------------------------------

  private itemsIn(department: string): LoopItem[] {
    return this.driver.model.items.filter((it) => it.department === department && IN_ROOM.includes(it.status));
  }

  private sig(name: string): boolean {
    const s = this.driver.world.signals[name];
    return Boolean(s) && s.until > this.scene.realT;
  }
}

/** 部门配色：与原型 sprites.js 的 DEPTS 一致。 */
const DEPT_SHELL: Record<string, Shell> = DEPTS as unknown as Record<string, Shell>;

/** 一句话在头顶停留的毫秒数（原型 say.js 的 P.sayMs）。 */
export function sayMs(text: string): number {
  return Math.min(4600, 1800 + String(text).length * 170);
}

/** 说话气泡的排版与绘制（原型 say.js 的 P.drawSpeeches）：折成最多两行，重叠时依次往上抬。 */
export function drawSpeeches(
  c: CanvasRenderingContext2D,
  scene: SceneLike,
  list: { a: NonNullable<ReturnType<typeof actorOf>>; text: string; kind: "say" | "think"; tail: boolean; until: number }[],
  opts: { size?: number; maxW?: number } = {},
): void {
  const size = opts.size ?? 6;
  const maxW = opts.maxW ?? 84;
  const lh = size + 2;
  const rects: { x: number; y: number; w: number; h: number }[] = [];
  for (const it of list.slice().sort((p, q) => p.a.x - q.a.x)) {
    const a = it.a;
    const [hx, hy] = headTop(scene, a);
    const text = it.tail && it.text.length > 24 ? `…${it.text.slice(-23)}` : it.text;
    const lay = layoutSpeech(c, text, size, maxW);
    const w = lay.w;
    const h = lay.lines.length * lh + 3;
    const x = Math.max(2, Math.min(W - w - 2, Math.round(hx - w / 2 + 3)));
    // 头顶有状态图标或者举着的牌子时，气泡画在它们上方
    let y = hy - 9 - h - (a.icon || a.sign ? 14 : 0);
    while (rects.some((r) => x < r.x + r.w + 1 && x + w + 1 > r.x && y < r.y + r.h + 1 && y + h + 1 > r.y) && y > 2) y -= h + 2;
    y = Math.max(2, y);
    rects.push({ x, y, w, h });
    const fade = it.until && !scene.reduced ? Math.max(0, Math.min(1, (it.until - scene.realT) / 350)) : 1;
    c.globalAlpha = fade;
    drawBubble(c, x, y, w, h, { kind: it.kind === "think" ? "think" : "say", tx: hx + 3 });
    lay.lines.forEach((line, i) => drawText(c, line, x + 4, y + 2 + i * lh + size / 2 + 0.5, { size, color: PAL.ink2 }));
    c.globalAlpha = 1;
  }
}

/** 一句话按宽度折成最多两行；超出时第二行用省略号。 */
function layoutSpeech(c: CanvasRenderingContext2D, text: string, size: number, maxW: number): { lines: string[]; w: number } {
  const lines: string[] = [];
  let cur = "";
  for (const ch of Array.from(text)) {
    if (cur && measure(c, cur + ch, size, 500) > maxW) {
      lines.push(cur);
      cur = ch;
    } else {
      cur += ch;
    }
  }
  if (cur) lines.push(cur);
  if (lines.length > 2) {
    lines.length = 2;
    let last = lines[1];
    while (last.length > 1 && measure(c, `${last}…`, size, 500) > maxW) last = last.slice(0, -1);
    lines[1] = `${last}…`;
  }
  return { lines, w: Math.round(Math.max(...lines.map((l) => measure(c, l, size, 500))) + 8) };
}

function tubePts(world: World, from: string, to: string): [number, number][] | null {
  const sep = "~";
  const direct = world.links[from + sep + to];
  if (direct) return direct.pts;
  const back = world.links[to + sep + from];
  return back ? back.pts.slice().reverse() : null;
}

function pathFor(world: World, from: string, to: string): [number, number][] | null {
  const direct = world.links[from + ">" + to];
  if (direct) return direct.pts;
  const back = world.links[to + ">" + from];
  if (back) return back.pts.slice().reverse();
  return tubePts(world, from, to);
}

function rgbaOf(hex: string, a: number): string {
  return `rgba(${parseInt(hex.slice(1, 3), 16)},${parseInt(hex.slice(3, 5), 16)},${parseInt(hex.slice(5, 7), 16)},${a})`;
}
