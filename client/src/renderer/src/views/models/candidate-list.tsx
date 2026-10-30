// 候选列表（工单 #1297；模型管理设计说明第 4.3 节「候选的内容与呈现」、第 9.1 节「选择模型」行）。
// 搜索（名称、提供方、上游模型 ID）、筛选（可自动配置、支持图像、支持推理、全部模型、已选用）与分批显示。
// 候选带勾选框；勾选即补全参数并验证（catalog.model.select），页面不预填参数：
// 协议、窗口与输出上限按服务端给的候选值显示，来源一并标出。
// 列表里没有的模型用「找不到模型？手动添加」：填上游模型 ID 即可选用，其余与勾选相同。

import {
  CANDIDATE_FILTERS,
  PROTOCOL_LABELS,
  SOURCE_LABELS,
  candidateApplicable,
  moreCount,
  type CandidateFilterId,
  type CandidateRow,
} from "./model-logic";

export type CandidateStatus = { kind: "ok" | "error"; message: string };

export type CandidateListProps = {
  /** 已经按搜索与筛选过滤好的候选 */
  rows: CandidateRow[];
  /** 全部候选的数量（筛选前） */
  total: number;
  search: string;
  filter: CandidateFilterId;
  /** 已经选用的模型：连接与上游模型 ID 合成的一把键 */
  selected: ReadonlySet<string>;
  /** 还剩多少个没有显示 */
  remaining: number;
  /** 每个候选旁的结果（选它时服务端给的原因） */
  status: Record<string, CandidateStatus>;
  /** 手动添加：表单是否展开、填的上游模型 ID、选的是哪一份连接 */
  manualOpen: boolean;
  manualModel: string;
  manualProvider: string;
  providers: { id: string; base_url: string }[];
  disabled: boolean;
  onSearch: (value: string) => void;
  onFilter: (value: CandidateFilterId) => void;
  onMore: () => void;
  onToggle: (row: CandidateRow) => void;
  onManualOpen: () => void;
  onManualClose: () => void;
  onManualModel: (value: string) => void;
  onManualProvider: (value: string) => void;
  onManualSubmit: () => void;
};

// 一个值的来源标注（设计说明第 4.3 节「界面标明每个预填值的来源」）
function sourceLabel(source: string | null | undefined): string {
  if (!source) {
    return "";
  }
  return SOURCE_LABELS[source] ?? source;
}

// 窗口与输出上限的一行文字；容量未知时写明「容量未知」
function capacityText(candidate: CandidateRow["candidate"]): string {
  const window = candidate.context_window;
  const output = candidate.max_output_tokens;
  if (typeof window !== "number" || typeof output !== "number") {
    return "容量未知";
  }
  return `上下文 ${window.toLocaleString("en-US")} / 最大输出 ${output.toLocaleString("en-US")}`;
}

export function CandidateList(props: CandidateListProps) {
  return (
    <div className="mm-candidates">
      <div className="y10-search mm-search">
        <input type="search" aria-label="搜索模型" placeholder="搜索模型名称、提供方或模型 ID…"
               value={props.search} data-testid="candidate-search" disabled={props.disabled}
               onChange={(event) => props.onSearch(event.target.value)} />
      </div>
      <div className="y10-seg mm-filters" role="group" aria-label="筛选模型">
        {CANDIDATE_FILTERS.map((item) => (
          <button key={item.id} type="button"
                  className={`y10-seg-btn${props.filter === item.id ? " is-on" : ""}`}
                  aria-pressed={props.filter === item.id}
                  data-testid={`candidate-filter-${item.id}`}
                  disabled={props.disabled}
                  onClick={() => props.onFilter(item.id)}>
            {item.label}
          </button>
        ))}
      </div>
      <p className="y10-small y10-muted mm-meta" role="status" data-testid="candidate-count">
        {props.filter === "auto"
          ? `${props.rows.length} 个模型可自动配置 · 其他候选可在「全部模型」中查看`
          : `找到 ${props.rows.length} 个模型`}
        {props.total !== props.rows.length ? ` · 共 ${props.total} 个候选` : ""}
      </p>
      {props.rows.length === 0 ? (
        <div className="y10-empty mm-empty" data-testid="candidate-empty">
          <strong>没有符合条件的模型</strong>
          <p>试试模型名称、提供方或上游模型 ID。</p>
          <button type="button" className="y10-btn small" data-testid="candidate-clear"
                  onClick={() => {
                    props.onSearch("");
                    props.onFilter("all");
                  }}>
            清除搜索和筛选
          </button>
        </div>
      ) : (
        <ul className="mm-candidate-list">
          {props.rows.map((row) => {
            const candidate = row.candidate;
            const key = `${row.provider_id}::${candidate.id}`;
            const applicable = candidateApplicable(candidate);
            const checked = props.selected.has(key);
            const status = props.status[key];
            return (
              <li className={`mm-candidate${checked ? " is-on" : ""}`} key={key}
                  data-testid={`candidate-${candidate.id}`}>
                <label className="mm-candidate-main">
                  <input type="checkbox" className="mm-check" checked={checked}
                         disabled={props.disabled || !applicable}
                         aria-label={`选用 ${candidate.id}`}
                         data-testid={`candidate-check-${candidate.id}`}
                         onChange={() => props.onToggle(row)} />
                  <span className="mm-candidate-info">
                    <span className="mm-candidate-name">
                      {candidate.id}
                      {candidate.input_modalities.includes("image") ? <span className="y10-tag">图像输入</span> : null}
                      {candidate.reasoning === true ? <span className="y10-tag">推理</span> : null}
                    </span>
                    <span className="y10-small y10-muted">
                      {candidate.provider ? `${candidate.provider} · ` : ""}{row.provider_address}
                    </span>
                    <span className="y10-small mm-candidate-specs">
                      {capacityText(candidate)}
                      <span className="mm-sep"> · </span>
                      {PROTOCOL_LABELS[candidate.protocol] ?? candidate.protocol}
                    </span>
                    <span className="y10-small y10-muted">
                      来源：{sourceLabel(candidate.context_window_source) || "未标明"} · 输出上限来源：
                      {sourceLabel(candidate.max_output_tokens_source) || "未标明"}
                    </span>
                  </span>
                </label>
                <span className="y10-small mm-candidate-state">
                  {!applicable ? "不适用于部门任务"
                    : checked ? "已选用" : "选择即配置"}
                </span>
                {status ? (
                  <p className={status.kind === "ok" ? "y10-small mm-ok" : "y10-warn-text mm-warn"}
                     role="status" data-testid={`candidate-status-${candidate.id}`}>
                    {status.message}
                  </p>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
      {props.remaining > 0 ? (
        <button type="button" className="y10-btn small mm-more" data-testid="candidate-more"
                onClick={props.onMore}>
          继续显示 {moreCount(props.remaining)} 个模型
        </button>
      ) : null}
      <div className="y10-row mm-actions">
        <button type="button" className="y10-btn small" data-testid="candidate-manual"
                disabled={props.disabled}
                onClick={props.manualOpen ? props.onManualClose : props.onManualOpen}>
          找不到模型？手动添加
        </button>
      </div>
      {props.manualOpen ? (
        <form className="y10-form mm-manual" data-testid="manual-form"
              onSubmit={(event) => {
                event.preventDefault();
                props.onManualSubmit();
              }}>
          <label className="y10-field" htmlFor="manual-provider">
            <span>连接</span>
            <select id="manual-provider" className="y10-select" value={props.manualProvider}
                    data-testid="manual-provider"
                    onChange={(event) => props.onManualProvider(event.target.value)}>
              {props.providers.map((provider) => (
                <option key={provider.id} value={provider.id}>{provider.base_url}</option>
              ))}
            </select>
          </label>
          <label className="y10-field" htmlFor="manual-model">
            <span>上游模型 ID</span>
            <input id="manual-model" className="y10-input" type="text" autoComplete="off" spellCheck={false}
                   placeholder="例如 glm-4.6" value={props.manualModel} data-testid="manual-model"
                   onChange={(event) => props.onManualModel(event.target.value)} />
            <small>协议、窗口与输出上限按服务端能查到的来源补全；查不到时在已选模型里填写。</small>
          </label>
          <div className="y10-row mm-actions">
            <button type="submit" className="y10-btn primary" data-testid="manual-submit"
                    disabled={props.disabled || props.manualModel.trim() === ""}>
              选用这个模型
            </button>
            <button type="button" className="y10-btn" data-testid="manual-cancel" onClick={props.onManualClose}>
              取消
            </button>
          </div>
        </form>
      ) : null}
    </div>
  );
}
