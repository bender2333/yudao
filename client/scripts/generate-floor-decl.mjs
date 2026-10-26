// 由原型 v13 的 floor-decl.js 与 translate/ 导出项目楼层的声明数据（工单 #953，改自 v10 的那一版）。
// 原型代码自定稿起不再修改（ADR-0021）；这里只读取，把「数据与规则」导出为 JSON：
// 房间与管道的声明、任务目录、不是角色一件事的动作（effects）、画面认的动作种类（kinds，带级别与时长）、
// 待机活动、持续状态表与说话目录的登记、翻译覆盖。
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
const v13Root = path.resolve(clientRoot, '..', 'docs', 'prototypes', 'v13', 'js');

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
  Promise,
  Symbol,
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
  innerWidth: 1440,
  innerHeight: 900,
  location: { hash: '' },
};
sandbox.window = sandbox;
sandbox.self = sandbox;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

// 按 index.html 的脚本顺序执行：声明表要用到 Y13 的取色、画布原语与 ecs 的几何，
// 翻译层导出说话目录与覆盖核对。
for (const [label, file] of [
  ['y13.js', path.join(v13Root, 'y13.js')],
  ['contract/registry.js', path.join(v13Root, 'contract', 'registry.js')],
  ['pixel/sprites.js', path.join(v13Root, 'pixel', 'sprites.js')],
  ['pixel/engine.js', path.join(v13Root, 'pixel', 'engine.js')],
  ['pixel/ecs.js', path.join(v13Root, 'pixel', 'ecs.js')],
  ['pixel/say.js', path.join(v13Root, 'pixel', 'say.js')],
  ['pixel/floor-decl.js', path.join(v13Root, 'pixel', 'floor-decl.js')],
  ['translate/say.js', path.join(v13Root, 'translate', 'say.js')],
  ['translate/translate.js', path.join(v13Root, 'translate', 'translate.js')],
]) {
  vm.runInContext(readFileSync(file, 'utf8'), sandbox, { filename: label });
}

const P = sandbox.window.Y13.pixel;
const T = sandbox.window.Y13.translate;
if (!P.floorDecl) throw new Error('原型没有导出 floorDecl');
if (!T || !T.coverage || !T.say || !T.say.catalog) throw new Error('原型没有导出 translate 的覆盖核对或说话目录');

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
  generatedFrom: 'docs/prototypes/v13/js/pixel/{floor-decl.js,say.js,ecs.js}、js/translate/{say.js,translate.js}',
  // 房间与管道的声明：函数字段（props、lit、tint、rest）在 TS 一侧改写，这里只记录结构。
  rooms,
  links,
  // 任务目录、不是角色一件事的动作与画面上认的动作种类（带级别与时长）都是纯数据，整份搬过来。
  tasks: JSON.parse(JSON.stringify(D.tasks)),
  effects: JSON.parse(JSON.stringify(D.effects)),
  kinds: JSON.parse(JSON.stringify(D.kinds)),
  idle: JSON.parse(JSON.stringify(D.idle)),
  flags: D.flags.slice(),
  // 说话目录是「事件类型 → 一句话」的规则（函数），不进 JSON；这里只导出它登记的事件类型，
  // TS 一侧按 translate/say.js 逐行改写规则（translate/say.ts），测试按这份清单核对目录齐全。
  sayCatalog: Object.keys(T.say.catalog).sort(),
  // 翻译覆盖：三个场景里每种事件是翻成动作、转交实时内容还是不画（画面与播放设计说明第 6 节）。
  coverage: JSON.parse(JSON.stringify(T.coverage)),
  // 会引起动作的事件类型：楼、楼层与房间三个场景的覆盖里翻成动作的那些
  eventActions: [...new Set([
    ...T.coverage.floor.drawn, ...T.coverage.room.drawn, ...T.coverage.building.drawn,
  ])].sort(),
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
  `动作种类 ${Object.keys(out.kinds).length}、待机活动 ${out.idle.length}、说话目录 ${out.sayCatalog.length}、` +
  `会引起动作的事件 ${out.eventActions.length}`,
);
