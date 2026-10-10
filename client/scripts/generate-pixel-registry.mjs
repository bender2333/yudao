// 由原型 v10 的 sprites.js 与 engine.js 生成像素画法的登记表 JSON（工单 #176）。
// 原型代码自定稿起不再修改（ADR-0021）；这里只读取，把纯数据的注册表导出为 JSON，
// 作为客户端的单一事实来源：画法、姿势、动作、位图、配色与图鉴「一项不少」的核对基准都取自这份导出。
// 输出：src/renderer/src/pixel/generated/registry.json
// 用法：node scripts/generate-pixel-registry.mjs

import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const clientRoot = path.resolve(__dirname, '..');
const v10Root = path.resolve(clientRoot, '..', 'docs', 'prototypes', 'v10', 'js');

// ---------------------------------------------------------------------------
// 最小的浏览器环境：原型只用 document.createElement('canvas') 与窗口尺寸相关的全局，
// 在 Node 里以替身画布运行；不改变原型的任何代码。

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
    measureText: () => ({ width: 0 }),
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

// 按原型的加载顺序执行（index.html 第 36、48、49 行）：y10.js → sprites.js → engine.js
for (const [label, file] of [
  ['y10.js', path.join(v10Root, 'y10.js')],
  ['sprites.js', path.join(v10Root, 'pixel', 'sprites.js')],
  ['engine.js', path.join(v10Root, 'pixel', 'engine.js')],
]) {
  vm.runInContext(readFileSync(file, 'utf8'), sandbox, { filename: label });
}

const Y10 = sandbox.window.Y10;
const P = Y10.pixel;

// ---------------------------------------------------------------------------
// 导出：纯数据的注册表 + 公开成员清单。
// VIGNETTES 里是函数（每个动作的小场景），不进 JSON；TS 一侧按 engine.js 第 9 节重写。
// 清单（inventory）列出 sprites.js 与 engine.js 设置的全部 P.* 公开成员，图鉴与测试按它核对「一项不少」。

const DATA_REGISTRIES = [
  // sprites.js：色板、部门与角色、小人部件、位图、配色与档位
  'PAL', 'CHAR', 'DEPTS', 'SKINS', 'HAIRS', 'ROLE_KINDS', 'ROLE_NAMES', 'ITEM_COLORS', 'ITEM_SHADES',
  'SPRITE_LEVELS', 'BITMAPS',
  // engine.js：姿势、动作帧序列、事实与动作对照表、3×5 字体、循环画面默认小人
  'POSES', 'ANIMS', 'ACTIONS', 'BASE_MOTIONS', 'STATUS_ACTIONS', 'EVENT_ACTIONS', 'VIGNETTE_SPRITES', 'FONT3',
];

const functionMembers = Object.keys(P).filter((k) => typeof P[k] === 'function').sort();
const dataMembers = Object.keys(P).filter((k) => typeof P[k] !== 'function').sort();

const registries = {};
for (const name of DATA_REGISTRIES) {
  if (P[name] === undefined) throw new Error('原型注册表缺失：' + name);
  registries[name] = JSON.parse(JSON.stringify(P[name]));
}

const out = {
  generatedFrom: 'docs/prototypes/v10/js/pixel/{sprites.js,engine.js}',
  inventory: {
    functions: functionMembers,
    data: dataMembers,
    all: [...functionMembers, ...dataMembers].sort(),
  },
  levels: Y10.LEVELS,
  levelLabels: Y10.LEVEL_LABELS,
  levelTags: Y10.LEVEL_TAGS,
  charW: P.CHAR_W,
  charH: P.CHAR_H,
  font: P.FONT,
  registries,
};

const targetDir = path.join(clientRoot, 'src', 'renderer', 'src', 'pixel', 'generated');
mkdirSync(targetDir, { recursive: true });
const target = path.join(targetDir, 'registry.json');
writeFileSync(target, JSON.stringify(out, null, 1) + '\n', 'utf8');

const sizeKB = Math.round(readFileSync(target).length / 1024);
console.log(`registry.json 已生成：${sizeKB} KB，公开成员 ${out.inventory.all.length} 个（函数 ${functionMembers.length}、数据 ${dataMembers.length}），位图 ${Object.keys(registries.BITMAPS).length}、姿势 ${Object.keys(registries.POSES).length}、动作 ${Object.keys(registries.ANIMS).length}、画法说明 ${Object.keys(registries.ACTIONS).length}`);
