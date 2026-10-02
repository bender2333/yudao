// 由原型 v9 的 floor-decl.js 与 say.js 导出项目楼层的声明数据（工单 #82）。
// 原型代码自定稿起不再修改（ADR-0021）；这里只读取，把「数据与规则」导出为 JSON：
// 房间与管道的声明、任务目录、待机活动、事件到任务的解析（keyOf）、持续状态表、说话目录。
// 输出：src/renderer/src/pixel/generated/floor-decl.json
// 用法：node scripts/generate-floor-decl.mjs

import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const clientRoot = path.resolve(__dirname, '..');
const v9Root = path.resolve(clientRoot, '..', 'docs', 'prototypes', 'v9', 'js');

// 最小的浏览器环境：与 generate-pixel-registry.mjs 同一做法，原型代码不改。
function makeCtx2d() {
  const noop = () => {};
  return {
    createImageData: (w, h) => ({ data: new Uint8ClampedArray(Math.max(0, w * h * 4)) }),
    putImageData: noop,
    drawImage: noop,
    getImageData: (x, y, w, h) => ({ data: new Uint8ClampedArray(Math.max(0, w * h * 4)) }),
    fillRect: noop,
    save: noop,
    restore: noop,
    translate: noop,
    scale: noop,
    rotate: noop,
    beginPath: noop,
    arc: noop,
    fill: noop,
    stroke: noop,
    moveTo: noop,
    lineTo: noop,
    closePath: noop,
    rect: noop,
    clip: noop,
    setTransform: noop,
    clearRect: noop,
    createPattern: () => null,
    createLinearGradient: () => ({ addColorStop: noop }),
    measureText: (s) => ({ width: String(s).length * 4 }),
    fillText: noop,
    strokeText: noop,
    font: '',
    textAlign: '',
    textBaseline: '',
    fillStyle: '',
    strokeStyle: '',
    lineWidth: 1,
    globalAlpha: 1,
    imageSmoothingEnabled: true,
  };
}

const storeStub = () => ({ getItem: () => null, setItem: () => {}, removeItem: () => {} });
const canvasStub = () => ({
  tagName: 'CANVAS',
  getContext: makeCtx2d,
  width: 0,
  height: 0,
  style: {},
  toDataURL: () => 'data:,',
  addEventListener: () => {},
  removeEventListener: () => {},
});

const sandbox = {
  console,
  Math,
  JSON,
  Object,
  Array,
  String,
  Number,
  Boolean,
  Date,
  Error,
  Map,
  Set,
  RegExp,
  document: {
    createElement: canvasStub,
    addEventListener: () => {},
    getElementById: () => null,
    querySelector: () => null,
    body: { appendChild: () => {} },
    head: { appendChild: () => {} },
    documentElement: { style: {} },
  },
  localStorage: storeStub(),
  sessionStorage: storeStub(),
  matchMedia: () => ({ matches: false, addEventListener: () => {}, addListener: () => {} }),
  performance: { now: () => 0 },
  requestAnimationFrame: () => 0,
  cancelAnimationFrame: () => {},
  devicePixelRatio: 1,
  setTimeout,
  clearTimeout,
  setInterval,
  clearInterval,
  addEventListener: () => {},
  removeEventListener: () => {},
};
sandbox.window = sandbox;
sandbox.self = sandbox;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

// 按 index.html 的脚本顺序执行：y9.js → sprites.js → engine.js → ecs.js → say.js → floor-decl.js
for (const [label, file] of [
  ['y9.js', path.join(v9Root, 'y9.js')],
  ['sprites.js', path.join(v9Root, 'pixel', 'sprites.js')],
  ['engine.js', path.join(v9Root, 'pixel', 'engine.js')],
  ['ecs.js', path.join(v9Root, 'pixel', 'ecs.js')],
  ['say.js', path.join(v9Root, 'pixel', 'say.js')],
  ['floor-decl.js', path.join(v9Root, 'pixel', 'floor-decl.js')],
]) {
  vm.runInContext(readFileSync(file, 'utf8'), sandbox, { filename: label });
}

const P = sandbox.window.Y9.pixel;
if (!P.floorDecl || !P.say) throw new Error('原型没有导出 floorDecl 或 say');

// ---------------------------------------------------------------------------
// 导出：房间与管道声明里的 props/lit/tint/rest 是函数（画法与规则），不进 JSON；
// 它们在 TS 一侧按 floor-decl.js 逐行改写（与 #176 把 engine.js 的画法改写为 TS 同一做法）。
// 清单列出声明的全部键，测试按它核对「一项不少」。

const D = P.floorDecl;
const rooms = D.rooms.map((d) => {
  const keys = Object.keys(d).sort();
  return { id: d.id, label: d.label, roomKind: d.roomKind, keys };
});
const links = D.links.map((d) => ({
  from: d.from, to: d.to, kind: d.kind,
  ...(d.via !== undefined ? { via: d.via } : {}),
  ...(d.optional !== undefined ? { optional: d.optional } : {}),
  ...(d.valve !== undefined ? { valve: d.valve } : {}),
}));

const out = {
  generatedFrom: 'docs/prototypes/v9/js/pixel/{floor-decl.js,say.js,ecs.js}',
  // 房间与管道的声明：函数字段（props、lit、tint、rest）在 TS 一侧改写，这里只记录结构。
  rooms,
  links,
  // 任务目录与待机活动是纯数据，整份搬过来。
  tasks: JSON.parse(JSON.stringify(D.tasks)),
  idle: JSON.parse(JSON.stringify(D.idle)),
  flags: D.flags.slice(),
  // 说话目录是「事件类型 → 一句话」的规则（函数），不进 JSON；这里只导出它登记的事件类型，
  // TS 一侧按 say.js 逐行改写规则，测试按这份清单核对目录齐全。
  sayCatalog: Object.keys(P.say.catalog).sort(),
  // 会引起动作的事件类型（engine.js 的 P.EVENT_ACTIONS）：说话目录应当覆盖它们
  eventActions: Object.keys(P.EVENT_ACTIONS).sort(),
  geo: P.ecs.GEO,
  // 任务目录与待机活动里出现过的字段名，TS 类型按它核对
  taskKeys: [...new Set(Object.values(D.tasks).flatMap((t) => Object.keys(t)))].sort(),
  idleKeys: [...new Set(D.idle.flatMap((t) => Object.keys(t)))].sort(),
};

const targetDir = path.join(clientRoot, 'src', 'renderer', 'src', 'pixel', 'generated');
mkdirSync(targetDir, { recursive: true });
const target = path.join(targetDir, 'floor-decl.json');
writeFileSync(target, JSON.stringify(out, null, 1) + '\n', 'utf8');

console.log(
  `floor-decl.json 已生成：房间 ${rooms.length}、管道 ${links.length}、任务 ${Object.keys(out.tasks).length}、` +
  `待机活动 ${out.idle.length}、说话目录 ${out.sayCatalog.length}、会引起动作的事件 ${out.eventActions.length}`,
);
