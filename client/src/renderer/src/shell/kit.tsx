// 原型 v10 的图标与通用组件（工单 #377）：16×16 SVG 图标、状态标记、按钮、区块、
// 表格、页签、弹窗与页面标题。图标路径直接取自原型 docs/prototypes/v10/js/ui/kit.js，
// 用 React 组件画出来；样式类名沿用原型的 y10- 前缀。

import type { ReactNode } from "react";

const ICON_PATHS: Record<string, string> = {
  running: '<circle cx="8" cy="8" r="3.6" fill="currentColor" stroke="none"/><circle cx="8" cy="8" r="6.2" opacity=".35"/>',
  succeeded: '<path d="M3.2 8.4l3 3 6.6-7"/>',
  queued: '<rect x="2" y="4" width="12" height="8" rx="1.5"/><path d="M6 4v8"/><path d="M8.6 7h3M8.6 9h2"/>',
  asking: '<path d="M1.8 7.6L14 2.4l-3.6 11.2-2.6-4.4z"/><path d="M7.8 9.2L14 2.4"/>',
  paused: '<path d="M5.5 3.5v9M10.5 3.5v9"/>',
  failed: '<circle cx="8" cy="8" r="6"/><path d="M5.8 5.8l4.4 4.4M10.2 5.8l-4.4 4.4"/>',
  done: '<path d="M4 14.2V2.4"/><path d="M4 2.8h7.6l-1.8 2.6 1.8 2.6H4"/>',
  cancelled: '<circle cx="8" cy="8" r="6"/><path d="M3.8 12.2l8.4-8.4"/>',
  interrupted: '<path d="M9.2 1.6L3.8 9h4l-1 5.4L12.2 7h-4z"/>',
  pending: '<circle cx="8" cy="8" r="6"/><path d="M6.2 6.2a1.9 1.9 0 1 1 2.6 1.8c-.5.2-.8.6-.8 1.1v.5"/><path d="M8 11.4v.2"/>',
  waiting: '<path d="M5 2.2L8 4.4l3-2.2"/><rect x="2" y="4.4" width="12" height="7.4" rx="1"/><path d="M5 8.1h6"/>',
  waiting_slot: '<rect x="2" y="3" width="3.2" height="10" rx=".6"/><rect x="6.4" y="3" width="3.2" height="10" rx=".6"/><rect x="10.8" y="3" width="3.2" height="10" rx=".6"/><path d="M1.5 14.5h13"/>',
  waiting_provider: '<circle cx="8" cy="8" r="6"/><path d="M8 4.6V8l2.4 1.6"/>',
  offline: '<path d="M2.4 6.4a8 8 0 0 1 11.2 0"/><path d="M4.6 8.8a4.8 4.8 0 0 1 6.8 0"/><circle cx="8" cy="11.6" r=".9" fill="currentColor"/><path d="M2.6 2.6l10.8 10.8"/>',
  repair: '<path d="M10.4 2.2a3.2 3.2 0 0 0-3.6 4.4L2.6 10.8a1.3 1.3 0 0 0 1.8 1.8l4.2-4.2a3.2 3.2 0 0 0 4.4-3.6l-2 2-1.8-.4-.4-1.8z"/>',
  adopted: '<rect x="1.8" y="2.4" width="12.4" height="3.2" rx=".6"/><path d="M2.8 5.6v7.8h10.4V5.6"/><path d="M6.2 8.4h3.6"/>',
  released: '<path d="M6.2 2h3.6v3.8l2.4 1.6v2.2H3.8V7.4l2.4-1.6z"/><path d="M2.6 13.6h10.8"/>',
  candidate: '<circle cx="8" cy="8" r="5.6" stroke-dasharray="2.2 2"/>',
  admitted: '<path d="M8 1.6l5.2 2v4.2c0 3-2.2 5.3-5.2 6.6-3-1.3-5.2-3.6-5.2-6.6V3.6z"/><path d="M5.6 8l1.7 1.7 3.1-3.3"/>',
  unusable: '<path d="M8 1.8l6.6 11.6H1.4z"/><path d="M8 6.4v3.2"/><path d="M8 11.4v.2"/>',
  unknown: '<path d="M5.6 5.6a2.4 2.4 0 1 1 3.4 2.2c-.7.3-1 .8-1 1.5v.6"/><path d="M8 12.4v.2"/>',
  idle: '<circle cx="8" cy="8" r="5.6"/>',
};

const GLYPHS: Record<string, string> = {
  brand: '<path d="M2.5 3.5h11v9h-11z"/><path d="M2.5 7.5h11M6.5 7.5v5M9.5 3.5v4"/>',
  home: '<path d="M2.2 7.6L8 2.6l5.8 5"/><path d="M3.8 6.4v7h8.4v-7"/><path d="M6.6 13.4V9.6h2.8v3.8"/>',
  menu: '<path d="M2.5 4h11M2.5 8h11M2.5 12h11"/>',
  close: '<path d="M4 4l8 8M12 4l-8 8"/>',
  plus: '<path d="M8 3v10M3 8h10"/>',
  search: '<circle cx="7" cy="7" r="4.3"/><path d="M10.2 10.2l3.3 3.3"/>',
  back: '<path d="M9.8 3.6L5.4 8l4.4 4.4"/>',
  link: '<path d="M6.6 9.4l2.8-2.8"/><path d="M7.2 4.6l1.2-1.2a2.6 2.6 0 0 1 3.7 3.7l-1.2 1.2"/><path d="M8.8 11.4l-1.2 1.2a2.6 2.6 0 0 1-3.7-3.7l1.2-1.2"/>',
  import: '<path d="M8 2.4v7.2"/><path d="M5 6.8L8 9.8l3-3"/><path d="M2.6 10.6v2.8h10.8v-2.8"/>',
  models: '<rect x="3.5" y="3.5" width="9" height="9" rx="1.5"/><path d="M6.2 1.5v2M9.8 1.5v2M6.2 12.5v2M9.8 12.5v2M1.5 6.2h2M1.5 9.8h2M12.5 6.2h2M12.5 9.8h2"/>',
  machines: '<rect x="2.5" y="2" width="11" height="4.6" rx="1"/><rect x="2.5" y="9.4" width="11" height="4.6" rx="1"/><path d="M5 4.3h.1M5 11.7h.1"/>',
  runtime: '<rect x="2" y="3" width="3.2" height="10" rx=".6"/><rect x="6.4" y="3" width="3.2" height="10" rx=".6"/><rect x="10.8" y="3" width="3.2" height="10" rx=".6"/>',
  tools: '<path d="M10.4 2.2a3.2 3.2 0 0 0-3.6 4.4L2.6 10.8a1.3 1.3 0 0 0 1.8 1.8l4.2-4.2a3.2 3.2 0 0 0 4.4-3.6l-2 2-1.8-.4-.4-1.8z"/>',
  meta: '<path d="M1.6 8s2.4-4.4 6.4-4.4S14.4 8 14.4 8 12 12.4 8 12.4 1.6 8 1.6 8z"/><circle cx="8" cy="8" r="2"/>',
  evolution: '<circle cx="4.5" cy="3.5" r="1.6"/><circle cx="4.5" cy="12.5" r="1.6"/><circle cx="11.5" cy="6" r="1.6"/><path d="M4.5 5.1v5.8M11.5 7.6c0 2.4-2.6 2.6-5.6 3.9"/>',
  lessons: '<path d="M2.5 3.2c2-.8 3.8-.6 5.5.6 1.7-1.2 3.5-1.4 5.5-.6v9.6c-2-.8-3.8-.6-5.5.6-1.7-1.2-3.5-1.4-5.5-.6z"/><path d="M8 3.8v9.6"/>',
  gallery: '<rect x="2.5" y="2.5" width="11" height="11" rx="1.5"/><circle cx="6" cy="6" r="1.3"/><path d="M13.5 10.5L10 7l-7 6.5"/>',
  more: '<circle cx="3.5" cy="8" r=".9" fill="currentColor"/><circle cx="8" cy="8" r=".9" fill="currentColor"/><circle cx="12.5" cy="8" r=".9" fill="currentColor"/>',
  chevron: '<path d="M4.5 6.2L8 9.8l3.5-3.6"/>',
  restart: '<path d="M13 8a5 5 0 1 1-1.5-3.6"/><path d="M13 2.6v2.6h-2.6"/>',
  lock: '<rect x="3.5" y="7" width="9" height="6.5" rx="1"/><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2"/>',
  play: '<path d="M5 3.2l7.6 4.8L5 12.8z" fill="currentColor"/>',
  pause: '<path d="M5.4 3.4v9.2M10.6 3.4v9.2"/>',
  step: '<path d="M4 3.4l6.4 4.6L4 12.6z"/><path d="M12.4 3.4v9.2"/>',
  reset: '<path d="M3 8a5 5 0 1 0 1.5-3.6"/><path d="M3 2.6v2.6h2.6"/>',
  tag: '<path d="M2.4 2.4h5.8l5.4 5.4-5.8 5.8-5.4-5.4z"/><circle cx="5.4" cy="5.4" r="1"/>',
  bell: '<path d="M4 11V7.4a4 4 0 0 1 8 0V11l1.2 1.4H2.8z"/><path d="M6.6 13.8a1.5 1.5 0 0 0 2.8 0"/>',
  disk: '<ellipse cx="8" cy="4" rx="5.5" ry="2"/><path d="M2.5 4v8c0 1.1 2.5 2 5.5 2s5.5-.9 5.5-2V4"/><path d="M2.5 8c0 1.1 2.5 2 5.5 2s5.5-.9 5.5-2"/>',
  decide: '<path d="M3 2.5h7l3 3v8H3z"/><path d="M10 2.5v3h3"/><path d="M5.5 9l1.6 1.6L10.6 7"/>',
  plug: '<path d="M6 2v3M10 2v3"/><path d="M4.4 5h7.2v2.6a3.6 3.6 0 0 1-7.2 0z"/><path d="M8 11.2V14"/>',
};

export function Icon(props: { name: string; className?: string }) {
  const inner = GLYPHS[props.name] ?? ICON_PATHS[props.name];
  if (!inner) {
    throw new Error(`未知图标：${props.name}`);
  }
  return (
    <svg
      className={props.className ?? "y10-icon"}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      dangerouslySetInnerHTML={{ __html: inner }}
    />
  );
}

export function StatusMark(props: { kind: string; text: string }) {
  return (
    <span className={`y10-status is-${props.kind}`}>
      <Icon name={props.kind} className="y10-status-icon" />
      <span>{props.text}</span>
    </span>
  );
}

export function PageHead(props: { eyebrow?: string; title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="y10-page-head">
      <div className="y10-page-titles">
        {props.eyebrow ? <div className="y10-eyebrow">{props.eyebrow}</div> : null}
        <h1>{props.title}</h1>
        {props.subtitle ? <p className="y10-subtitle">{props.subtitle}</p> : null}
      </div>
      {props.actions ? <div className="y10-page-actions">{props.actions}</div> : null}
    </div>
  );
}

export function Block(props: {
  // 区块标识：状态项点击以后按它滚到对应区块（原型 shell.js 的 anchor）
  id?: string;
  title?: string;
  subtitle?: string;
  actions?: ReactNode;
  className?: string;
  compact?: boolean;
  "data-testid"?: string;
  dataTestId?: string;
  children: ReactNode;
}) {
  return (
    <section
      id={props.id}
      data-testid={props["data-testid"] ?? props.dataTestId}
      className={`y10-block${props.className ? ` ${props.className}` : ""}${props.compact ? " is-compact" : ""}`}
    >
      {props.title || props.actions ? (
        <header className="y10-block-head">
          <div className="y10-block-titles">
            {props.title ? <h2 className="y10-block-title">{props.title}</h2> : null}
            {props.subtitle ? <p className="y10-block-sub">{props.subtitle}</p> : null}
          </div>
          {props.actions ? <div className="y10-block-actions">{props.actions}</div> : null}
        </header>
      ) : null}
      <div className="y10-block-body">{props.children}</div>
    </section>
  );
}
