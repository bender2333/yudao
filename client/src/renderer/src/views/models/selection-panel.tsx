// 已选模型清单（工单 #1297；模型管理设计说明第 9.1 节「候选与已选模型」行、第 4.3 节「选用」）。
// 每个选用的模型一行，持续显示它的状态：补全参数、等待验证、验证调用、已启用、验证失败、容量未知。
// 失败写出原因与「重新验证」；容量未知的在这一行填写窗口与输出上限；已启用的可以展开看参数与来源。
// 取消勾选就是取消选用（catalog.model.remove）：被引用的取消不了，这一行写明引用方。

import { PROTOCOL_LABELS, SOURCE_LABELS, capacityMissingText, selectionStatusKind, selectionStatusLabel,
  type SelectedModelRow } from "./model-logic";
import { StatusMark } from "../../shell/kit";

export type { SelectedModelRow };

export type SelectionStatus = { kind: "ok" | "error"; message: string };

export type SelectionPanelProps = {
  rows: SelectedModelRow[];
  /** 容量未知时用户填的窗口与输出上限 */
  capacity: Record<string, { context_window: string; max_output_tokens: string }>;
  /** 每个模型旁的结果（取消选用被拒绝时写引用方） */
  status: Record<string, SelectionStatus>;
  /** 最近一次验证的用时与实际返回的模型 */
  tests: Record<string, { elapsed_ms: number; actual_model: string | null }>;
  busy: boolean;
  onCapacity: (key: string, field: "context_window" | "max_output_tokens", value: string) => void;
  onContinue: (row: SelectedModelRow) => void;
  onRetry: (row: SelectedModelRow) => void;
  onRemove: (row: SelectedModelRow) => void;
};

function sourceText(sources: string): string {
  if (sources.trim() === "") {
    return "未标明";
  }
  return sources
    .split(" · ")
    .map((part) => {
      const [name, source] = part.split("：");
      if (source === undefined) {
        return part;
      }
      return `${name}：${SOURCE_LABELS[source] ?? source}`;
    })
    .join(" · ");
}

export function SelectionPanel(props: SelectionPanelProps) {
  if (props.rows.length === 0) {
    return (
      <aside className="mm-selection" aria-label="已选模型" data-testid="selection-panel">
        <h3 className="y10-h3">已选模型</h3>
        <p className="y10-small y10-muted">在左侧勾选你想使用的模型。<br />容量和协议由系统处理。</p>
      </aside>
    );
  }
  return (
    <aside className="mm-selection" aria-label="已选模型" data-testid="selection-panel">
      <h3 className="y10-h3">已选模型 <span className="y10-count">{props.rows.length}</span></h3>
      <p className="y10-small y10-muted">勾选后自动补全参数并验证</p>
      <ul className="mm-selection-list">
        {props.rows.map((row) => {
          const enabled = row.status === "enabled";
          const capacity = props.capacity[row.key];
          const test = props.tests[row.model_id];
          const status = props.status[row.key];
          return (
            <li className={`mm-selection-item${enabled ? " is-on" : ""}`} key={row.key}
                data-testid={`selected-${row.upstream_model}`}>
              <div className="y10-row mm-selection-head">
                <strong>{row.upstream_model}</strong>
                <button type="button" className="y10-btn small danger" data-testid={`selected-remove-${row.upstream_model}`}
                        disabled={props.busy}
                        aria-label={`取消选用 ${row.upstream_model}`}
                        onClick={() => props.onRemove(row)}>
                  取消选用
                </button>
              </div>
              <p className="y10-small mm-selection-status" data-testid={`selected-status-${row.upstream_model}`}>
                <StatusMark kind={enabled ? "admitted" : selectionStatusKind(row.status)}
                           text={selectionStatusLabel(row.status)} />
              </p>
              {row.error ? (
                <p className="y10-warn-text mm-warn" role="alert"
                   data-testid={`selected-error-${row.upstream_model}`}>
                  {row.error}
                </p>
              ) : null}
              {status ? (
                <p className={status.kind === "ok" ? "y10-small mm-ok" : "y10-warn-text mm-warn"}
                   role="status" data-testid={`selected-status-text-${row.upstream_model}`}>
                  {status.message}
                </p>
              ) : null}
              {row.status === "capacity_unknown" ? (
                <div className="mm-capacity" data-testid={`selected-capacity-${row.upstream_model}`}>
                  <p className="y10-warn-text mm-warn">{capacityMissingText(row.missing)}</p>
                  <label className="y10-field" htmlFor={`capacity-window-${row.key}`}>
                    <span>上下文窗口</span>
                    <input id={`capacity-window-${row.key}`} className="y10-input" type="text" inputMode="numeric"
                           value={capacity?.context_window ?? ""}
                           data-testid={`capacity-window-${row.upstream_model}`}
                           onChange={(event) => props.onCapacity(row.key, "context_window", event.target.value)} />
                  </label>
                  <label className="y10-field" htmlFor={`capacity-output-${row.key}`}>
                    <span>最大输出</span>
                    <input id={`capacity-output-${row.key}`} className="y10-input" type="text" inputMode="numeric"
                           value={capacity?.max_output_tokens ?? ""}
                           data-testid={`capacity-output-${row.upstream_model}`}
                           onChange={(event) => props.onCapacity(row.key, "max_output_tokens", event.target.value)} />
                  </label>
                  <button type="button" className="y10-btn small primary"
                          data-testid={`selected-continue-${row.upstream_model}`}
                          disabled={props.busy}
                          onClick={() => props.onContinue(row)}>
                    填写完成，继续验证
                  </button>
                </div>
              ) : null}
              {row.status === "failed" || row.status === "not_in_list" ? (
                <button type="button" className="y10-btn small"
                        data-testid={`selected-retry-${row.upstream_model}`}
                        disabled={props.busy}
                        onClick={() => props.onRetry(row)}>
                  重新验证
                </button>
              ) : null}
              {enabled ? (
                <details className="y10-details mm-detail"
                         data-testid={`selected-detail-${row.upstream_model}`}>
                  <summary>已自动配置 · 查看参数与验证结果</summary>
                  <dl className="y10-kv is-inline">
                    <div>
                      <dt>上下文窗口</dt>
                      <dd>{row.context_window === null ? "未标明" : row.context_window.toLocaleString("en-US")}</dd>
                    </div>
                    <div>
                      <dt>最大输出</dt>
                      <dd>{row.max_output_tokens === null ? "未标明" : row.max_output_tokens.toLocaleString("en-US")}</dd>
                    </div>
                    <div>
                      <dt>协议</dt>
                      <dd>{PROTOCOL_LABELS[row.protocol] ?? row.protocol}</dd>
                    </div>
                    <div>
                      <dt>工具调用</dt>
                      <dd>{row.accepts_required_tool_call ? "验证通过" : "不要求调用工具"}</dd>
                    </div>
                    <div>
                      <dt>图像输入</dt>
                      <dd>{row.input_modalities.includes("image") ? "支持" : "不支持"}</dd>
                    </div>
                    <div>
                      <dt>参数来源</dt>
                      <dd>{sourceText(row.sources)}</dd>
                    </div>
                    <div>
                      <dt>验证用时</dt>
                      <dd>{test ? `${test.elapsed_ms} 毫秒` : "未读到"}</dd>
                    </div>
                    <div>
                      <dt>实际返回的模型</dt>
                      <dd>{row.admitted_model ?? test?.actual_model ?? "未读到"}</dd>
                    </div>
                  </dl>
                </details>
              ) : null}
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
