// 项目各页共用的界面零件：区块、行、页签、徽标、命令提示、输入框与详情弹窗。
// 全部数据来自应用层的查询结果；没有数据或字段未上报时写明「未上报」或「无」，不用假数据补位。

import { useEffect, useRef, useState } from "react";
import type { Rejected } from "../../api/generated/types.gen";
import type { ClientApp } from "../../contract/client-app";
import { rejectionLabel } from "./use-snapshot";

export type Field = Record<string, unknown>;

export function dict(value: unknown): Field {
  return value === null || typeof value !== "object" || Array.isArray(value) ? {} : value as Field;
}

export function list(value: unknown): Field[] {
  return Array.isArray(value) ? value.map((item) => (item === null || typeof item !== "object" ? {} : item as Field)) : [];
}

// 命令是否在能力清单里登记：界面按它决定按钮是否出现，而不是提交以后再报错
export function hasCommand(app: ClientApp | null, name: string): boolean {
  return (app?.currentCapabilities?.commands ?? []).some((command) => command.name === name);
}

export function text(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return "";
}

export function optionalText(value: unknown): string | null {
  const got = text(value);
  return got === "" ? null : got;
}

export function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

// 取值显示：空值写成「未上报」，避免界面用假数据补位
export function show(value: string | null | undefined, empty = "未上报"): string {
  return value === null || value === undefined || value === "" ? empty : value;
}

export function pageKey(parts: unknown[]): string {
  return JSON.stringify(parts);
}

// 未提交的草稿按项目与位置存放（原型 v8 设计说明第 3.3 节）：刷新、后退与切换标签以后仍在；
// 切换事项（scope 变化）以后显示那一处自己的草稿，这一处没有草稿时用 initial 作为起点
export function useDraft(scope: string, initial = ""): [string, (value: string) => void] {
  const key = `yudao-draft/${scope}`;
  const [value, setValue] = useState(() => window.sessionStorage.getItem(key) ?? initial);
  const currentKey = useRef(key);

  useEffect(() => {
    if (currentKey.current !== key) {
      currentKey.current = key;
      setValue(window.sessionStorage.getItem(key) ?? initial);
    }
  }, [key, initial]);

  const setDraft = (next: string) => {
    setValue(next);
    if (next === "") {
      window.sessionStorage.removeItem(key);
    } else {
      window.sessionStorage.setItem(key, next);
    }
  };

  return [value, setDraft];

}

export function formatNumberOr(value: number | null | undefined, suffix = ""): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "未上报";
  }
  return `${value.toLocaleString("zh-CN")}${suffix}`;
}

export function Section(props: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <section className="card">
      <div className="section-head">
        <h2>{props.title}</h2>
        {props.note ? <p className="note">{props.note}</p> : null}
      </div>
      {props.children}
    </section>
  );
}

export function Line(props: { term: string; value: React.ReactNode }) {
  return (
    <div className="line">
      <span className="term">{props.term}</span>
      <span className="value">{props.value}</span>
    </div>
  );
}

export function Tag(props: { tone?: "ok" | "warn" | "danger" | "muted"; children: React.ReactNode }) {
  return <span className={`tag${props.tone ? ` ${props.tone}` : ""}`}>{props.children}</span>;
}

export function Tabs(props: { items: { id: string; label: string }[]; active: string; onPick: (id: string) => void }) {
  return (
    <div className="tabs" role="tablist">
      {props.items.map((item) => (
        <button
          key={item.id}
          type="button"
          role="tab"
          aria-selected={props.active === item.id}
          className={props.active === item.id ? "active" : ""}
          onClick={() => props.onPick(item.id)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

// 命令提交后的反馈：已提交在快照出现新内容以后恢复；拒绝时显示原因，基准版本过期提示重新读取
export function CommandFeedback(props: { submitted: boolean; rejection: Rejected | null }) {
  if (props.rejection) {
    return (
      <p className="error" role="status">
        {rejectionLabel(props.rejection)}
      </p>
    );
  }
  if (props.submitted) {
    return (
      <p className="hint" role="status">
        已提交，等待写入结果
      </p>
    );
  }
  return null;
}

export function Loading(props: { state: { loading: boolean; data: unknown } }) {
  if (props.state.loading && props.state.data === null) {
    return <p className="note">正在读取数据</p>;
  }
  return null;
}

export function Empty(props: { text: string }) {
  return <p className="note">{props.text}</p>;
}

export function Modal(props: { title: string; onClose: () => void; children: React.ReactNode }) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        props.onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [props]);

  return (
    <div className="modal-backdrop" onClick={props.onClose}>
      <div className="modal" onClick={(event) => event.stopPropagation()}>
        <div className="modal-head">
          <h2>{props.title}</h2>
          <button type="button" onClick={props.onClose}>
            关闭
          </button>
        </div>
        <div className="modal-body">{props.children}</div>
      </div>
    </div>
  );
}

// 事件详情弹窗：原始事件由 event.detail 按序号读取，界面只解释已经存在的事实
export function EventDetail(props: { eventId: string; onClose: () => void; snapshot: { data: unknown; loading: boolean } }) {
  const raw = props.snapshot.data === null ? null : JSON.stringify(props.snapshot.data, null, 2);
  return (
    <Modal title={`事件 ${props.eventId}`} onClose={props.onClose}>
      {props.snapshot.loading && raw === null ? <p className="note">正在读取事件</p> : null}
      {raw !== null ? <pre className="raw">{raw}</pre> : null}
    </Modal>
  );
}

export function TextInput(props: {
  label: string;
  value: string;
  placeholder?: string;
  disabled?: boolean;
  onInput: (value: string) => void;
}) {
  return (
    <label className="field">
      <span>{props.label}</span>
      <input
        type="text"
        value={props.value}
        placeholder={props.placeholder}
        disabled={props.disabled}
        onChange={(event) => props.onInput(event.target.value)}
      />
    </label>
  );
}

export function TextArea(props: {
  label: string;
  value: string;
  rows?: number;
  disabled?: boolean;
  onInput: (value: string) => void;
}) {
  return (
    <label className="field">
      <span>{props.label}</span>
      <textarea
        value={props.value}
        rows={props.rows ?? 4}
        disabled={props.disabled}
        onChange={(event) => props.onInput(event.target.value)}
      />
    </label>
  );
}

export function SubmitButton(props: {
  label: string;
  busy: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button type="button" className="primary" disabled={props.busy || props.disabled} onClick={props.onClick}>
      {props.busy ? "正在提交" : props.label}
    </button>
  );
}

// 表格：窄屏时整行横向滚动容器由样式给出，列宽用 minmax 收缩
export function Table(props: { head: string[]; rows: React.ReactNode[][]; caption?: string }) {
  return (
    <div className="table-scroll">
      <table>
        {props.caption ? <caption>{props.caption}</caption> : null}
        <thead>
          <tr>
            {props.head.map((cell) => (
              <th key={cell} scope="col">
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {props.rows.map((cells, index) => (
            <tr key={index}>
              {cells.map((cell, position) => (
                <td key={position}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function KeyValue(props: { items: [string, React.ReactNode][] }) {
  return (
    <div className="kv">
      {props.items.map(([term, value]) => (
        <Line key={term} term={term} value={value} />
      ))}
    </div>
  );
}
