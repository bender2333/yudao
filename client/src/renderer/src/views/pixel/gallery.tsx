// 动作图鉴页（工单 #176 验收标准 1、#956）：列出原型 v13 的 y13.js、sprites.js 与 engine.js 的全部公开画法，
// 一项不少。每个画法都用同一套 TypeScript 画法渲染一张点阵预览（整数倍最近邻放大，像素不模糊），
// 与原型逐项对照画风。页面只在开发时使用：路径 #/gallery 不进入正式的页面入口（页签与侧栏）。

import { useEffect, useMemo, useRef } from "react";
import { GALLERY_MEMBERS, type GalleryMember, type GallerySample } from "../../pixel/gallery-data";
import { paletteSwatch } from "../../pixel/preview";
import { sampleDrawing } from "../../pixel/samples";
import { ACTIONS, BASE_MOTIONS, PIXEL_FONT_STACK, PUBLIC_MEMBERS, ROLE_NAMES, registry } from "../../pixel/registry";
import type { Grid } from "../../pixel/grid";

/** 把点阵画到底图上，按整数倍放大，采样最近邻。 */
function GridPreview({ grid, w, h, zoom = 3 }: { grid: Grid; w: number; h: number; zoom?: number }): React.JSX.Element {
  const ref = useRef<HTMLCanvasElement | null>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    canvas.width = w * zoom;
    canvas.height = h * zoom;
    ctx.imageSmoothingEnabled = false;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    // 先画棋盘格底，透明像素也看得清
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const col = grid[y * w + x];
        ctx.fillStyle = (x + y) % 2 === 0 ? "#20222c" : "#282b36";
        ctx.fillRect(x * zoom, y * zoom, zoom, zoom);
        if (col) {
          ctx.fillStyle = col;
          ctx.fillRect(x * zoom, y * zoom, zoom, zoom);
        }
      }
    }
  }, [grid, w, h, zoom]);
  return (
    <canvas
      className="gallery-grid"
      ref={ref}
      style={{ imageRendering: "pixelated" }}
      // 逻辑尺寸写在属性上：测试据此核对画布是逻辑尺寸的整数倍
      data-grid-w={w}
      data-grid-h={h}
      data-grid-zoom={zoom}
    />
  );
}

function SampleView({ member }: { member: GalleryMember }): React.JSX.Element {
  // 有离屏取样时把画法真画一遍再看效果；取样失败或没有取样时退回静态的 sample
  const live = useMemo(() => (member.sampler ? sampleDrawing(member.sampler) : null), [member.sampler]);
  if (live) {
    return (
      <div className="gallery-sample">
        <GridPreview grid={live.grid} w={live.w} h={live.h} zoom={2} />
        <span className="gallery-caption">{member.sampler}</span>
      </div>
    );
  }
  return <StaticSample member={member} />;
}

function StaticSample({ member }: { member: GalleryMember }): React.JSX.Element {
  const sample: GallerySample = member.sample;
  if (sample.type === "grid") {
    return (
      <div className="gallery-sample">
        <GridPreview grid={sample.grid} w={sample.w} h={sample.h} />
        <span className="gallery-caption">{sample.caption}</span>
      </div>
    );
  }
  if (sample.type === "value") {
    return (
      <div className="gallery-sample">
        <code className="gallery-value">{sample.value}</code>
        <span className="gallery-caption">{sample.caption}</span>
      </div>
    );
  }
  return (
    <div className="gallery-sample gallery-sample-data">
      <span className="gallery-count">{sample.count} 条</span>
      <ul className="gallery-entries">
        {sample.entries.slice(0, 12).map((e, i) => (
          <li key={i}>{e}</li>
        ))}
      </ul>
      <span className="gallery-caption">{sample.caption}</span>
    </div>
  );
}

/** 动作图鉴页：全部公开画法逐项列出，可逐个对照画风。 */
export function GalleryPage(): React.JSX.Element {
  const groups = useMemo(() => {
    const byKind: Record<string, GalleryMember[]> = { function: [], data: [] };
    for (const m of GALLERY_MEMBERS) byKind[m.kind].push(m);
    return byKind;
  }, []);
  const swatches = useMemo(() => paletteSwatch(), []);

  return (
    <div className="gallery-page" style={{ fontFamily: PIXEL_FONT_STACK }}>
      <header className="gallery-head">
        <h1>动作图鉴</h1>
        <p>
          列出原型 v13 的 <code>y13.js</code>、<code>sprites.js</code> 与 <code>engine.js</code> 的全部公开画法，一项不少：
          共 <strong>{PUBLIC_MEMBERS.all.length}</strong> 项（函数 {PUBLIC_MEMBERS.functions.length}、
          数据 {PUBLIC_MEMBERS.data.length}）。每项用同一套 TypeScript 画法渲染，画风与原型一致。
        </p>
        <div className="gallery-swatches">
          {swatches.map((s) => (
            <span key={s.name} className="gallery-swatch">
              <i style={{ background: s.color }} />
              {s.name}
            </span>
          ))}
        </div>
      </header>

      <section className="gallery-section">
        <h2>画法（{groups.function.length}）</h2>
        <div className="gallery-items">
          {groups.function.map((m) => (
            <article key={m.name} className="gallery-item" data-member={m.name}>
              <h3>{m.name}</h3>
              <p>{m.note}</p>
              <SampleView member={m} />
            </article>
          ))}
        </div>
      </section>

      <section className="gallery-section">
        <h2>数据（{groups.data.length}）</h2>
        <div className="gallery-items">
          {groups.data.map((m) => (
            <article key={m.name} className="gallery-item" data-member={m.name}>
              <h3>{m.name}</h3>
              <p>{m.note}</p>
              <SampleView member={m} />
            </article>
          ))}
        </div>
      </section>

      <ActionGallery />
    </div>
  );
}

/** 部门房间与项目楼层里的动作：动作说明、状态姿势与基础动作，一项不漏（v13 设计说明、设计说明第 8.3、8.4 节）。 */
function ActionGallery(): React.JSX.Element {
  const actions = Object.entries(ACTIONS);
  const motions = Object.entries(BASE_MOTIONS);
  // 原型仍导出 STATUS_ACTIONS，画面 3、4 以后没有画法用它：这里按登记表读，只为图鉴「一项不少」
  const statuses = Object.entries(registry.registries.STATUS_ACTIONS);
  return (
    <section className="gallery-section">
      <h2>部门房间的动作（{actions.length + motions.length}）</h2>
      <p className="gallery-caption">
        每项写明驱动它的事实、小人动作、房间变化与所属档位；每个动作由哪种事件给出写在翻译层（v13 设计说明第 4 节）。
        当前客户端实现全部动作的播放，Stage 4 与 Stage 5 的动作随对应工作包加入画面。
      </p>
      <table className="gallery-actions">
        <thead>
          <tr>
            <th>动作</th>
            <th>事实</th>
            <th>小人动作</th>
            <th>房间变化</th>
            <th>档位</th>
          </tr>
        </thead>
        <tbody>
          {actions.map(([name, a]) => (
            <tr key={name} data-action={name}>
              <td>{a.label}</td>
              <td>{a.fact}</td>
              <td>{a.action}</td>
              <td>{a.room ?? "—"}</td>
              <td>{a.level === "ui" ? "界面工作线" : a.level}</td>
            </tr>
          ))}
          {motions.map(([name, m]) => (
            <tr key={name} data-action={name}>
              <td>{m.label}</td>
              <td>{m.fact}</td>
              <td>{m.anim}</td>
              <td>—</td>
              <td>界面工作线</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3 className="gallery-caption">部门状态对应的姿势（{statuses.length}）</h3>
      <table className="gallery-actions">
        <thead>
          <tr>
            <th>状态</th>
            <th>标识</th>
            <th>姿势</th>
          </tr>
        </thead>
        <tbody>
          {statuses.map(([status, action]) => (
            <tr key={status} data-status={status}>
              <td>{status}</td>
              <td><code>{action}</code></td>
              <td>{ACTIONS[action]?.label ?? action}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="gallery-caption">角色：{Object.values(ROLE_NAMES).join("、")}。</p>
    </section>
  );
}
