// 动作图鉴的数据层：列出原型 sprites.js 与 engine.js 的全部公开画法，一项不少（工单 #176 验收标准 1）。
// 公开成员来自生成脚本导出的登记表（generated/registry.json），与原型运行时逐项对照；
// 每个成员给出一个可运行的示例，图鉴页面照此渲染，方便逐项与原型对照画风。

import { EASE, animDuration, animFrameAt, ease, hash, reducedMotion } from "./anims.ts";
import { bitmapGrid, composeChar, resolveSpriteKey, rolePalette } from "./char.ts";
import { gridImageData } from "./textures.ts";
import { linePts, mix, rgba, type Grid } from "./grid.ts";
import { PAINT_NAMES } from "./paint.ts";
import {
  ACTIONS,
  ANIMS,
  BASE_MOTIONS,
  BITMAPS,
  CHAR,
  CHAR_H,
  CHAR_W,
  DEPTS,
  EVENT_ACTIONS,
  FONT3,
  HAIRS,
  ITEM_COLORS,
  ITEM_SHADES,
  PAL,
  POSES,
  PUBLIC_MEMBERS,
  ROLE_KINDS,
  ROLE_NAMES,
  SKINS,
  SPRITE_LEVELS,
  STATUS_ACTIONS,
  VIGNETTE_SPRITES,
} from "./registry.ts";

export type MemberKind = "function" | "data";

export type GallerySample =
  /** 画一个点阵：小人帧、位图或位图的改色。 */
  | { type: "grid"; grid: Grid; w: number; h: number; caption: string }
  /** 展示数据内容：条目数与若干条示例。 */
  | { type: "data"; count: number; entries: string[]; caption: string }
  /** 展示一个数值或一段行为。 */
  | { type: "value"; value: string; caption: string };

export interface GalleryMember {
  /** 原型里的成员名。 */
  name: string;
  kind: MemberKind;
  /** 一句话说明这个画法画的是什么。 */
  note: string;
  sample: GallerySample;
  /**
   * 画法的离屏取样名（samples.ts 里的键）。有值时图鉴与联系表在浏览器里把画法真画一遍再看效果；
   * 没有值时用上面的 sample（点阵、数据或数值）。
   */
  sampler?: string;
}

/** 小人帧取样：把身体层与前景层合成一张点阵（与原型 renderSprite 的取样一致）。 */
function charSample(key: string, pose: string, caption: string): GallerySample {
  const f = composeChar({ key, pose, face: null, hold: null });
  const merged: Grid = f.base.map((c, i) => f.front[i] ?? c);
  return { type: "grid", grid: merged, w: CHAR_W, h: CHAR_H, caption };
}

/** 位图取样：位图点阵已含描边。 */
function bitmapSample(name: string, caption: string): GallerySample {
  const b = bitmapGrid(name);
  return { type: "grid", grid: b.grid, w: b.w, h: b.h, caption };
}

const dataSample = (count: number, entries: string[], caption: string): GallerySample => ({ type: "data", count, entries, caption });
const valueSample = (value: string, caption: string): GallerySample => ({ type: "value", value, caption });

/** 每一项的说明与取样：engine.js 的 39 个函数与 25 个数据，共 64 项。 */
export const GALLERY_MEMBERS: GalleryMember[] = [
  // ---- engine.js 的函数（39 个） ----
  { name: "R", kind: "function", sampler: "RB", note: "实心矩形，坐标取整到像素（房间陈设的基本笔）", sample: valueSample("fillRect(取整坐标)", "实心矩形") },
  { name: "RB", kind: "function", sampler: "RB", note: "带墨色外框的实心矩形", sample: valueSample("矩形 + 1 像素墨色描边", "描边矩形") },
  { name: "actorFrame", kind: "function", note: "取某个小人在某时刻该画的姿势与表情（待机时按固定间隔眨眼）", sample: valueSample(animFrameAt("walk", 190), "walk + 190ms") },
  { name: "animDuration", kind: "function", note: "动作总时长（毫秒）", sample: valueSample(`${animDuration("tea")} ms`, "tea 时长") },
  { name: "animFrame", kind: "function", note: "按经过时间取动作帧序列的姿势名", sample: valueSample(animFrameAt("type", 120), "type + 120ms") },
  { name: "arrow", kind: "function", sampler: "arrow", note: "折线加箭头的画法（减少动画时用它表示交接）", sample: valueSample("折线 + 箭头 + 描边", "箭头") },
  { name: "bitmap", kind: "function", note: "按名称取位图点阵（自动描边，支持改色）", sample: bitmapSample("clipboard", "clipboard") },
  { name: "bitmapDef", kind: "function", note: "按名称取位图定义（处理 stamp_valid 等别名）", sample: valueSample(`${Object.keys(BITMAPS).length} 张位图`, "位图登记表") },
  { name: "box", kind: "function", sampler: "box", note: "像素圆角框：外边墨色、内部填色、上沿高光（卡片、面板、气泡的边框）", sample: valueSample("外边墨色 + 内部填色 + 高光", "边框框") },
  { name: "bubble", kind: "function", sampler: "bubble", note: "对话气泡：say 三角尾巴、think 小圆点尾巴", sample: valueSample("边框框 + 尾巴", "气泡边框") },
  { name: "charFrame", kind: "function", note: "取小人一帧的身体层与前景层（带缓存）", sample: charSample("product.manager", "hold_sign", "产品经理举牌") },
  { name: "createScene", kind: "function", note: "建立画面：整数倍最近邻缩放、动画循环、脚本与粒子", sample: valueSample("PixiJS 8 画面", "画面") },
  { name: "createVignette", kind: "function", note: "建立一个动作的循环小画面（动作图鉴逐项播放）", sample: valueSample("动作循环小画面", "小画面") },
  { name: "drawActor", kind: "function", note: "在画面上画一个小人：身体层 + 前景层 + 脚底阴影", sample: charSample("engineering.lead", "walk1", "主程走路") },
  { name: "drawBitmap", kind: "function", note: "在 (x, y) 画一张位图，支持改色、翻转与透明度", sample: bitmapSample("box_sealed", "封好的箱子") },
  { name: "drawIcon", kind: "function", note: "头顶图标：思考、逐字、灯泡、沙漏、问号、叹号、对勾、叉、zzz、爱心、文字", sample: bitmapSample("bulb", "灯泡图标") },
  { name: "drawShadow", kind: "function", sampler: "drawShadow", note: "小人脚下的椭圆阴影", sample: valueSample("两段椭圆填充", "脚底阴影") },
  { name: "fitText", kind: "function", note: "把一段文字收缩到给定的像素宽内，超出用省略号", sample: valueSample("按像素宽收缩", "文字收缩") },
  { name: "hash", kind: "function", note: "稳定散列：同一个整数每次得到同一个 0..1（陈设的噪点靠它）", sample: valueSample(hash(42).toFixed(6), "hash(42)") },
  { name: "headTop", kind: "function", note: "小人头顶坐标（对齐名牌、图标与气泡）", sample: valueSample("(x, y - 24 + 起伏)", "头顶锚点") },
  { name: "hourglass", kind: "function", sampler: "hourglass", note: "沙漏：等待与超时的标记，沙子按时间下落", sample: valueSample("木框 + 玻璃 + 下落沙子", "沙漏") },
  { name: "itemRect", kind: "function", note: "手持物件在画面上的矩形（号码牌数字、点击与描边用）", sample: valueSample("[x, y, w, h]", "物件矩形") },
  { name: "levelAtLeast", kind: "function", note: "判断动作的档位是否达到给定档位（ui ≤ S4 ≤ S5）", sample: valueSample("ui ≤ S4 ≤ S5", "档位比较") },
  { name: "linePts", kind: "function", note: "Bresenham 直线上的整数点（腿与手臂按它逐像素画）", sample: valueSample(`${linePts(13, 32, 15, 36).length} 个点`, "直线取点") },
  { name: "makeCanvas", kind: "function", note: "建一张离屏画布（位图先画在上面再贴）", sample: valueSample("离屏画布", "离屏画布") },
  { name: "measure", kind: "function", note: "量一段文字的像素宽（画面文字用微软雅黑）", sample: valueSample("像素字体量宽", "量文字") },
  { name: "mix", kind: "function", note: "两色按比例混合（阴影、渐层、面板暗色）", sample: valueSample(mix(PAL.white, PAL.ink, 0.5), "white → ink 0.5") },
  { name: "parseSpriteKey", kind: "function", note: "解析小人标识（部门.种类:事项颜色，ops 是 operations 的简写）", sample: valueSample(JSON.stringify(resolveSpriteKey("engineering.lead:2")), "engineering.lead:2") },
  { name: "pixText", kind: "function", sampler: "pixText", note: "3×5 像素字模画数字与符号（信箱未读数、设备计数）", sample: valueSample("3×5 字模逐像素", "3×5 字模") },
  { name: "reducedMotion", kind: "function", note: "读系统的「减少动效」偏好（命中时只画静止帧）", sample: valueSample(String(reducedMotion()), "减少动效") },
  { name: "renderSprite", kind: "function", note: "把一个动作的某一帧渲染成单张图（缩略图与图鉴用）", sample: charSample("quality.reviewer", "inspect0", "质检审查者检查") },
  { name: "resolveAction", kind: "function", note: "把状态名或事件名解析成对应动作", sample: valueSample("state / event → action", "解析动作") },
  { name: "rgba", kind: "function", note: "十六进制颜色加透明度（阴影、玻璃、屏幕高光）", sample: valueSample(rgba(PAL.ink, 0.28), "ink 28%") },
  { name: "rolePalette", kind: "function", note: "角色配色表：皮肤、发色、衣服、袖标、事项色（按角色种类逐项改色）", sample: valueSample(`${Object.keys(rolePalette("engineering", "lead", 0).map).length} 个颜色键`, "主程配色") },
  { name: "shotImage", kind: "function", note: "取 assets/ 下的一张截图；没加载出来时调用方画占位", sample: valueSample("Image 缓存", "截图加载") },
  { name: "sign", kind: "function", sampler: "sign", note: "牌子：cx 为中心、bottom 为下沿；可带挂绳钉子、手柄与侧边色条", sample: valueSample("边框框 + 文字 + 挂绳 + 手柄", "门口立牌") },
  { name: "signStyle", kind: "function", note: "牌子配色：按牌上的文字决定（中断、待恢复、暂停、失败、完成、取消）", sample: valueSample("按文字匹配颜色", "牌子样式") },
  { name: "stampMark", kind: "function", sampler: "stampMark", note: "印章印记：双线方框加文字（有效、放行、返工、封存）", sample: bitmapSample("stamp", "印章位图") },
  { name: "text", kind: "function", note: "用微软雅黑画一段文字，支持描边与发光", sample: valueSample("微软雅黑 + 描边 + 发光", "像素文字") },

  // ---- engine.js 与 sprites.js 的数据（25 个） ----
  { name: "ACTIONS", kind: "data", note: "事实与动作的对照表：什么事实对应哪个动作、在哪个画面里", sample: dataSample(Object.keys(ACTIONS).length, Object.entries(ACTIONS).slice(0, 8).map(([k, v]) => `${k}：${v.label}`), "事实 → 动作") },
  { name: "ANIMS", kind: "data", note: "动作帧序列：每个动作由哪些姿势、每帧多少毫秒组成", sample: dataSample(Object.keys(ANIMS).length, Object.entries(ANIMS).slice(0, 8).map(([k, v]) => `${k}：${v.frames.length} 帧 / ${v.total}ms`), "动作帧序列") },
  { name: "BASE_MOTIONS", kind: "data", note: "基础动作：待机、走路、搬运、跑步、坐、打字", sample: dataSample(Object.keys(BASE_MOTIONS).length, Object.entries(BASE_MOTIONS).map(([k, v]) => `${k}：${v.label}`), "基础动作") },
  { name: "BITMAPS", kind: "data", note: "位图：手持物件、图标与小物件的点阵定义（点阵 + 颜色表 + 是否描边）", sample: dataSample(Object.keys(BITMAPS).length, Object.keys(BITMAPS).slice(0, 12), "位图") },
  { name: "CHAR", kind: "data", note: "小人部件：头、发型、表情、配件、服装、腿、帽兜、背包", sample: dataSample(Object.keys(CHAR).length, Object.keys(CHAR), "小人部件") },
  { name: "CHAR_H", kind: "data", note: "小人帧缓冲高：40 像素，脚底在第 37 行", sample: valueSample(`${CHAR_H} 像素`, "帧高") },
  { name: "CHAR_W", kind: "data", note: "小人帧缓冲宽：32 像素", sample: valueSample(`${CHAR_W} 像素`, "帧宽") },
  { name: "DEPTS", kind: "data", note: "部门：衣服颜色、墙面、地面与地毯颜色", sample: dataSample(Object.keys(DEPTS).length, Object.entries(DEPTS).map(([k, v]) => `${k}：${v.name} ${v.main}`), "部门") },
  { name: "EVENT_ACTIONS", kind: "data", note: "事件名到动作的映射（工具调用、提案、交付、恢复）", sample: dataSample(Object.keys(EVENT_ACTIONS).length, Object.keys(EVENT_ACTIONS).slice(0, 12), "事件 → 动作") },
  { name: "FONT", kind: "data", note: "字体栈：画面文字用微软雅黑（ADR-0021 第 4 条）", sample: valueSample("Microsoft YaHei UI", "画面字体栈") },
  { name: "FONT3", kind: "data", note: "3×5 像素字模：数字与符号", sample: dataSample(Object.keys(FONT3).length, Object.keys(FONT3), "3×5 字模") },
  { name: "HAIRS", kind: "data", note: "发色表（每种两个色：主色与暗色）", sample: dataSample(Object.keys(HAIRS).length, Object.entries(HAIRS).map(([k, v]) => `${k} ${v[0]}`), "发色") },
  { name: "ITEM_COLORS", kind: "data", note: "事项颜色 0-5：门口小旗、包裹与看板卡片同一种颜色", sample: dataSample(ITEM_COLORS.length, ITEM_COLORS, "事项颜色") },
  { name: "ITEM_SHADES", kind: "data", note: "事项颜色的暗色（包裹阴影与封条）", sample: dataSample(ITEM_SHADES.length, ITEM_SHADES, "事项暗色") },
  { name: "PAL", kind: "data", note: "色板：全局像素配色（灰、木、金属、屏幕、卡片、玻璃、植物）", sample: dataSample(Object.keys(PAL).length, Object.entries(PAL).slice(0, 12).map(([k, v]) => `${k} ${v}`), "色板") },
  { name: "POSES", kind: "data", note: "姿势：小人一帧的骨架参数（视角、腿、双臂、手持物、起伏、表情）", sample: dataSample(Object.keys(POSES).length, Object.keys(POSES).slice(0, 12), "姿势") },
  { name: "ROLE_KINDS", kind: "data", note: "角色种类：发型、发色、肤色、服装、配件、待机时手里的物件", sample: dataSample(Object.keys(ROLE_KINDS).length, Object.entries(ROLE_KINDS).map(([k, v]) => `${k}：${v.label}（${v.outfit}）`), "角色种类") },
  { name: "ROLE_NAMES", kind: "data", note: "角色的中文名称", sample: dataSample(Object.keys(ROLE_NAMES).length, Object.values(ROLE_NAMES), "角色名称") },
  { name: "SKINS", kind: "data", note: "肤色表（每种两个色：主色与暗色）", sample: dataSample(SKINS.length, SKINS.map((s, i) => `肤色 ${i} ${s[0]}`), "肤色") },
  { name: "SPRITE_LEVELS", kind: "data", note: "角色标识的档位（ui 界面工作线 / S4 / S5）", sample: dataSample(Object.keys(SPRITE_LEVELS).length, Object.entries(SPRITE_LEVELS).slice(0, 8).map(([k, v]) => `${k}：${v}`), "角色档位") },
  { name: "STATUS_ACTIONS", kind: "data", note: "运行状态到动作的映射（暂停、失败、完成、取消、待恢复）", sample: dataSample(Object.keys(STATUS_ACTIONS).length, Object.entries(STATUS_ACTIONS).map(([k, v]) => `${k} → ${v}`), "状态 → 动作") },
  { name: "VIGNETTES", kind: "data", note: "每个动作的循环小画面脚本：走位、播放动作、等待、拿物件、转头、图标、坐下、淡入淡出", sample: dataSample(Object.keys(VIGNETTE_SPRITES).length, Object.keys(VIGNETTE_SPRITES).slice(0, 12), "小画面脚本") },
  { name: "VIGNETTE_SPRITES", kind: "data", note: "每个动作小画面默认用哪个小人", sample: dataSample(Object.keys(VIGNETTE_SPRITES).length, Object.entries(VIGNETTE_SPRITES).slice(0, 8).map(([k, v]) => `${k} → ${v}`), "小画面小人") },
  { name: "ease", kind: "data", note: "缓动曲线：linear、inOut、out、in、outBack、bounce（小画面移动用）", sample: dataSample(Object.keys(EASE).length, Object.keys(EASE).map((k) => `${k}(0.5) = ${ease(k, 0.5).toFixed(4)}`), "缓动曲线") },
  { name: "paint", kind: "data", sampler: "paint.terminal", note: "共用陈设的画法：屏幕、桌子、椅子、终端、门、白板、管道、包裹、设备、架子、警示灯等", sample: dataSample(PAINT_NAMES.length, PAINT_NAMES, "陈设画法") },
];

/** 图鉴项的键，与原型成员名一一对应。 */
export const GALLERY_BY_NAME: ReadonlyMap<string, GalleryMember> = new Map(GALLERY_MEMBERS.map((m) => [m.name, m]));

/** 核对「一项不少」：图鉴列出的项必须与原型公开成员完全一致（不多不少）。 */
export function galleryGaps(): { missing: string[]; extra: string[] } {
  const mine = new Set(GALLERY_MEMBERS.map((m) => m.name));
  const theirs = new Set(PUBLIC_MEMBERS.all);
  return {
    missing: [...theirs].filter((n) => !mine.has(n)).sort(),
    extra: [...mine].filter((n) => !theirs.has(n)).sort(),
  };
}

/** 图鉴里点阵取样的 ImageData：页面按整数倍最近邻放大显示。 */
export function sampleImageData(sample: GallerySample): ImageData | null {
  if (sample.type !== "grid") return null;
  return gridImageData(sample.grid, sample.w, sample.h);
}

