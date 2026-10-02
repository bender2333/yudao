// 世界与声明（原型 v9 设计说明第 3 节、BUILD.md 第 3.2 节，工单 #82）。
// 房间按声明顺序从左到右排布，管道按 kind 对应的路由规则算折线，节点由声明直接给出几何。
// 这里不依赖渲染：房间、管道、工位与路由都是纯计算，可以在 node --test 下核对。

import type { Catalog, Endpoint, Geo, LinkDef, LinkHop, Pipe, Room, RoomDef, World } from "./types.ts";

/** 沿用 v8 floor.js 与原型 ecs.js 的常量（像素级一致）。 */
export const GEO: Geo = {
  TOP: 50,
  ROOM_B: 214,
  FLOOR_LINE: 150,
  DESK_Y: 196,
  PORT_STAND: 176,
  PIPE_Y: 138,
  TUBE_Y: 104,
  DUCT_Y: 30,
  DUCT_TUBE_Y: 42,
  UNDER_Y: 276,
  GAP: 6,
};

/** 建立世界：房间、管道、角色、包裹、信号与任务目录都挂在这个对象上。 */
export function createWorld(catalog: Catalog): World {
  return {
    rooms: {},
    roomOrder: [],
    links: {},
    characters: {},
    packages: {},
    signals: {},
    catalog,
  };
}

/** 行为开关：autonomy 为假时待机活动与管道的惯性都关闭，静止的画面只由快照决定。 */
export const config = { autonomy: true };

/** 按声明排布房间：起点 x 为 4，房间之间 6 个像素；when 不满足的房间不生成。 */
export function declareRooms(world: World, defs: RoomDef[], flags: Record<string, boolean>): World {
  world.rooms = {};
  world.roomOrder = [];
  let x = 4;
  for (const d of defs) {
    if (d.when && !flags[d.when]) continue;
    const w = typeof d.w === "function" ? d.w(flags) : d.w;
    if (!(w > 0)) throw new Error(`房间没有声明宽度：${d.id}`);
    const room: Room = {
      kind: "room",
      id: d.id,
      label: d.label,
      roomKind: d.roomKind,
      x,
      y: GEO.TOP,
      w,
      door: x + Math.round(w / 2),
      inPort: x + 12,
      outPort: x + w - 12,
      pipeOut: d.pipeOutX !== undefined ? x + d.pipeOutX : x + w - 12,
      desk: { x: x + Math.round(w / 2) - 17, w: 34, seatX: x + Math.round(w / 2) - 5, seatY: GEO.DESK_Y },
      cabinet: { x: x + 8, y: GEO.FLOOR_LINE + 6 },
      terminal: { x: x + w - 16, y: GEO.PORT_STAND },
      monitor: { x: x + w - 26, y: GEO.PORT_STAND },
      seats: null,
      def: d,
    };
    for (const key of Object.keys(d.spots ?? {})) {
      const spotAt = d.spots![key](room);
      (room as unknown as Record<string, { x: number; y: number }>)[key] = { ...(room as unknown as Record<string, { x: number; y: number }>)[key], x: spotAt };
    }
    world.rooms[d.id] = room;
    world.roomOrder.push(d.id);
    x += w + GEO.GAP;
  }
  // 通往机房的门：走廊尽头，位置固定（跟 v8 一样不随房间数量变化）
  world.machineDoor = { x: 606, y: 218, w: 28, h: 40 };
  return world;
}

/** 不是房间排布的节点（机房里的设备）：几何由声明直接给出。 */
export function declareNodes(world: World, defs: Partial<RoomDef>[]): World {
  world.rooms = {};
  world.roomOrder = [];
  for (const d of defs) {
    const node = { kind: "room", seats: null, ...d } as unknown as Room;
    world.rooms[d.id!] = node;
    world.roomOrder.push(d.id!);
  }
  return world;
}

function roomIndex(world: World, id: string): number {
  return world.roomOrder.indexOf(id);
}

function adjacent(world: World, a: string, b: string): boolean {
  return Math.abs(roomIndex(world, a) - roomIndex(world, b)) === 1;
}

/** 管道端点：房间，或者走廊尽头通往机房的门（它不是房间，位置固定）。 */
function endpoint(world: World, id: string): Endpoint | null {
  if (world.rooms[id]) return world.rooms[id];
  if (id === "machine_room" && world.machineDoor) return { pipeOut: 0, inPort: 0, outPort: 0, ...world.machineDoor };
  return null;
}

/** 按 kind 对应的路由规则算折线（原型 ecs.js 的 routeLink）。 */
function routeLink(world: World, d: LinkDef, a: Endpoint, b: Endpoint): [number, number][] {
  const isMachine = d.to === "machine_room";
  if (d.kind === "handoff" && !isMachine) {
    return [[a.pipeOut, GEO.PIPE_Y], [b.inPort, GEO.PIPE_Y]];
  }
  if (d.kind === "handoff" && isMachine) {
    return [[a.outPort, GEO.PIPE_Y], [a.outPort, GEO.ROOM_B + 10], [b.x + 14, GEO.ROOM_B + 10], [b.x + 14, b.y + 12]];
  }
  if (d.kind === "tube") {
    if (adjacent(world, d.from, d.to)) return [[a.outPort, GEO.TUBE_Y], [b.inPort, GEO.TUBE_Y]];
    // 跨过一个房间的传信管，走天花板的长传信管
    return [[a.x + 22, GEO.TUBE_Y - 12], [a.x + 22, GEO.DUCT_TUBE_Y], [b.x + b.w - 22, GEO.DUCT_TUBE_Y], [b.x + b.w - 22, GEO.TUBE_Y - 12]];
  }
  if (d.kind === "return") {
    // via 由声明指定：'under' 走地板下（隔得远的回流），省略时走天花板
    if (d.via === "under") {
      return [[a.x + 20, GEO.ROOM_B - 4], [a.x + 20, GEO.UNDER_Y], [b.x + 12, GEO.UNDER_Y], [b.x + 12, GEO.ROOM_B + 26]];
    }
    return [[a.outPort - 8, GEO.PIPE_Y - 8], [a.outPort - 8, GEO.DUCT_Y], [b.inPort + 8, GEO.DUCT_Y], [b.inPort + 8, GEO.PIPE_Y - 8]];
  }
  throw new Error(`未知的管道种类：${d.kind}`);
}

/** 声明管道；重新声明时同一根管道保留原来的流动状态。 */
export function declareLinks(world: World, defs: LinkDef[]): World {
  const old = world.links ?? {};
  world.links = {};
  for (const d of defs) {
    const isTube = d.kind === "tube";
    const key = d.from + (isTube ? "~" : ">") + d.to;
    let pts = d.pts;
    if (!pts) {
      const a = endpoint(world, d.from);
      const b = endpoint(world, d.to);
      if (!a || !b) {
        if (d.optional) continue;
        throw new Error(`管道的端点未声明：${d.from} → ${d.to}`);
      }
      pts = routeLink(world, d, a, b);
    }
    const pipe: Pipe = {
      kind: "pipe", id: key, from: d.from, to: d.to, linkKind: d.kind, pts,
      flow: old[key] ? old[key].flow : null,
      def: d,
    };
    world.links[key] = pipe;
  }
  return world;
}

export function roomOf(world: World, id: string): Room | null {
  return world.rooms[id] ?? null;
}

/** 两个房间之间已声明的管道（反向也可以，返回 reversed 标记）。 */
export function linkBetween(world: World, from: string, to: string, kind?: string): LinkHop | null {
  const sep = kind === "tube" ? "~" : ">";
  const direct = world.links[from + sep + to];
  if (direct) return { pts: direct.pts, key: direct.id, reversed: false, link: direct };
  const back = world.links[to + sep + from];
  if (back) return { pts: back.pts.slice().reverse(), key: back.id, reversed: true, link: back };
  return null;
}

/** 一次交接经过的管道：直接有就是它（反向也可以），没有就沿声明的交接管道找一条最短的路。 */
export function route(world: World, from: string, to: string): LinkHop[] {
  const direct = linkBetween(world, from, to, "handoff");
  if (direct) return [direct];
  const edges = Object.values(world.links).filter((l) => l.linkKind === "handoff");
  const prev: Record<string, Pipe | null> = { [from]: null };
  const queue = [from];
  while (queue.length) {
    const at = queue.shift()!;
    if (at === to) break;
    for (const l of edges.filter((e) => e.from === at && !(e.to in prev))) {
      prev[l.to] = l;
      queue.push(l.to);
    }
  }
  if (!(to in prev)) return [];
  const hops: LinkHop[] = [];
  for (let l: Pipe | null = prev[to]; l; l = prev[l.from]) {
    hops.unshift({ pts: l.pts, key: l.id, reversed: false, link: l });
  }
  return hops;
}

// ---------------------------------------------------------------------------
// 几何：折线长度与沿线取点（与 v8 floor.js 的 polyLength/pointAt 相同算法）

export function polyLength(pts: [number, number][]): number {
  let len = 0;
  for (let i = 1; i < pts.length; i++) len += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
  return len;
}

export function pointAt(pts: [number, number][], d: number): [number, number] {
  let left = d;
  for (let i = 1; i < pts.length; i++) {
    const seg = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
    if (left <= seg || i === pts.length - 1) {
      const k = seg ? Math.min(1, left / seg) : 1;
      return [pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * k, pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * k];
    }
    left -= seg;
  }
  return pts[pts.length - 1];
}
