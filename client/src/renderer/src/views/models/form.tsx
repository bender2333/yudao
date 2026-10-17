// 添加与编辑 Provider 配置的表单（模型管理设计说明第 9.1 节，工单 #93）。
// 表单就地展开，高级选项折叠；标题为「添加 Provider 配置」「编辑 Provider 配置」。
// 模型访问定义表在这里行内编辑：容量逐行填写或修改，齐全且有效即可保存，推理档位声明三项，
// 输入方式为「支持图像输入」勾选框，准入列只读。Key 输入框始终为空，不回填。
// 取值与判断都在 model-logic.ts 里，这个文件只做渲染。

import { useState } from "react";
import type { CatalogAdmission, CatalogCredential } from "../../api/generated/types.gen";
import {
  CUSTOM_PRESET_ID,
  DEFAULT_PROTOCOL,
  PROTOCOL_LABELS,
  REASONING_MODE_LABELS,
  REASONING_LEVELS,
  admissionLabel,
  admissionOf,
  capacityIssueText,
  connectionTestable,
  defaultModelsUrl,
  effectiveModelsUrl,
  formPatchForBaseUrl,
  formPatchForPreset,
  defaultLevelOptions,
  intFromInput,
  patchRowCapacity,
  presetBaseUrlFor,
  presetById,
  normalizeBaseUrl,
  reasoningModeOptions,
  type CandidateState,
  type FormRow,
  type FormState,
  type ServicePreset,
  type UpstreamCandidate,
} from "./model-logic";

export type ProviderFormProps = {
  mode: "add" | "edit";
  state: FormState;
  onPatch: (patch: Partial<FormState>) => void;
  onPatchRow: (key: string, patch: Partial<FormRow>) => void;
  onAddRow: (row: FormRow) => void;
  onRemoveRow: (key: string) => void;
  // 行的构造：点击候选按第 4.3 节预填，手动添加一个空行（取值都在 model-logic.ts）
  rowFromCandidate: (candidate: UpstreamCandidate) => FormRow;
  blankRow: () => FormRow;
  presets: ServicePreset[];
  presetRevision: string;
  presetSource: string;
  capabilityRevision: string;
  capabilitySnapshotDate: string;
  capabilitySource: string;
  credential: CatalogCredential | null;
  candidate: CandidateState | null;
  collecting: boolean;
  admissions: CatalogAdmission[];
  impact: string;
  busy: boolean;
  testing: Record<string, boolean>;
  // 已完成的模型测试结果，按 model:<id> 存（工单 #294：行里要显示通过或原因）
  tests: Record<string, string>;
  status: { kind: "ok" | "error"; message: string } | null;
  onSubmit: (secret: string, persist: boolean) => void;
  onCancel: () => void;
  onDelete: () => void;
  onTestConnection: () => void;
  onCollectCandidates: () => void;
  onCredential: (action: "set" | "clear_override" | "remove_persisted", secret: string, persist: boolean) => void;
  onTestModel: (modelId: string) => void;
};

export function ProviderForm(props: ProviderFormProps) {
  const { state, mode } = props;
  // Key 只保存在这里：保存以后清空，任何时候都不从查询结果回填（第 9.4 节删除的元素）
  const [secret, setSecret] = useState("");
  const [persist, setPersist] = useState(false);
  const editing = mode === "edit";
  const preset = presetById(props.presets, state.preset_id);
  const connectionKey = `connection:${state.id}`;
  const connectionTesting = editing && props.testing[connectionKey] === true;

  const choosePreset = (presetId: string) => {
    const next = presetById(props.presets, presetId);
    const patch: Partial<FormState> = mode === "add"
      ? formPatchForPreset(state, next)
      : { preset_id: presetId, base_url: next ? presetBaseUrlFor(next, state.rows[0]?.protocol ?? DEFAULT_PROTOCOL) : state.base_url,
          models_url: "" };
    props.onPatch(patch);
  };

  // 切换一行定义上的调用协议（ADR-0033）：内置服务方案的地址按协议取预置表基址；
  // 推理参数方式与协议不符时清空推理档位声明（第 7.1、7.4 节）：支持档位、默认档位与推理参数方式
  // 三项一起声明，缺任一项时请求不带推理参数，所以清空方式时三项一起清空
  const chooseProtocol = (row: FormRow, protocol: string) => {
    props.onPatchRow(row.key, { protocol });
    if (preset) {
      props.onPatch({ base_url: presetBaseUrlFor(preset, protocol) });
    }
    const modes = reasoningModeOptions(protocol);
    if (row.reasoning_mode !== "" && !modes.includes(row.reasoning_mode)) {
      props.onPatchRow(row.key, { reasoning_mode: "", reasoning_levels: [], default_reasoning_level: "" });
    }
  };

  const toggleLevel = (row: FormRow, level: string) => {
    const selected = row.reasoning_levels.includes(level)
      ? row.reasoning_levels.filter((item) => item !== level)
      : [...row.reasoning_levels, level];
    const patch: Partial<FormRow> = { reasoning_levels: selected };
    // 取消勾选以后默认档位不再属于支持档位，回到未选择（默认档位只能从支持档位中选）
    if (!selected.includes(row.default_reasoning_level)) {
      patch.default_reasoning_level = "";
    }
    props.onPatchRow(row.key, patch);
  };

  const canSubmit = state.id.trim() !== "" && state.name.trim() !== "" && state.base_url.trim() !== ""
    && !props.busy;

  return (
    <form className="y10-block y10-form-block mm-form" onSubmit={(event) => {
      event.preventDefault();
      props.onSubmit(secret, persist);
    }}>
      <h3 className="y10-block-title">{editing ? "编辑 Provider 配置" : "添加 Provider 配置"}</h3>

      <div className="y10-field mm-field">
        <span className="mm-label">服务方案</span>
        <div className="y10-pill-row mm-chips" role="group" aria-label="服务方案">
          {props.presets.map((item) => (
            <button key={item.id} type="button"
                    className={item.id === state.preset_id ? "y10-pill is-on chip selected" : "y10-pill chip"}
                    aria-pressed={item.id === state.preset_id}
                    onClick={() => choosePreset(item.id)}>
              {item.name}
            </button>
          ))}
          <button type="button" className={state.preset_id === CUSTOM_PRESET_ID ? "y10-pill is-on chip selected" : "y10-pill chip"}
                  aria-pressed={state.preset_id === CUSTOM_PRESET_ID}
                  onClick={() => choosePreset(CUSTOM_PRESET_ID)}>
            自定义
          </button>
        </div>
      </div>
      <p className="y10-small y10-muted mm-meta">
        预置表 {props.presetRevision} · 来源 {props.presetSource}；模型能力表 {props.capabilityRevision}
        （快照日期 {props.capabilitySnapshotDate}）· 来源 {props.capabilitySource}
      </p>
      {preset?.docs_url && <p className="y10-small y10-muted mm-meta">文档 <code>{preset.docs_url}</code></p>}

      <label className="y10-field mm-field">
        <span className="mm-label">ID</span>
        <input className="y10-input" value={state.id} readOnly={editing} required placeholder="opencode-go"
               onChange={(event) => props.onPatch({ id: event.target.value })} />
      </label>
      <label className="y10-field mm-field">
        <span className="mm-label">名称</span>
        <input className="y10-input" value={state.name} required placeholder="OpenCode Go"
               onChange={(event) => props.onPatch({ name: event.target.value })} />
      </label>
      <label className="y10-field mm-field">
        <span className="mm-label">地址</span>
        <input className="y10-input" value={state.base_url} required placeholder="https://.../v1" data-testid="provider-base-url"
               readOnly={mode === "add" && preset !== null}
               onChange={(event) => props.onPatch(mode === "add"
                 ? formPatchForBaseUrl(state, event.target.value) : { base_url: event.target.value })}
               onBlur={() => { if (!preset) props.onPatch(mode === "add"
                 ? formPatchForBaseUrl(state, normalizeBaseUrl(state.base_url))
                 : { base_url: normalizeBaseUrl(state.base_url) }); }} />
      </label>
      {preset === null ? (
        <label className="y10-field mm-field">
          <span className="mm-label">模型列表地址</span>
          <input className="y10-input" value={state.models_url || defaultModelsUrl(state.base_url)}
                 placeholder={defaultModelsUrl(state.base_url) || "填写连接地址后自动给出默认值"}
                 data-testid="provider-models-url"
                 onChange={(event) => {
                   const fallback = defaultModelsUrl(state.base_url);
                   props.onPatch({ models_url: event.target.value === fallback ? "" : event.target.value });
                 }} />
        </label>
      ) : (
        <p className="y10-small y10-muted mm-meta" data-testid="preset-models-url">
          模型列表地址 {preset.models_url}（取自服务方案，只读）
        </p>
      )}
      {connectionTestable(state, preset) ? (
        <p className="y10-small y10-muted mm-meta" data-testid="models-url-effect">
          本次请求 {effectiveModelsUrl(state, preset)}
        </p>
      ) : (
        <p className="y10-small y10-muted mm-hint" role="status" data-testid="models-url-hint">
          填写连接地址后，模型列表地址默认使用连接地址加 /models。
        </p>
      )}

      <label className="y10-field mm-field">
        <span className="mm-label">凭据引用</span>
        <input className="y10-input" value={state.credential_ref} placeholder="OPENCODE_GO_KEY"
               onChange={(event) => props.onPatch({ credential_ref: event.target.value })} />
      </label>

      <details className="y10-details mm-advanced">
        <summary>高级选项</summary>
        <label className="y10-field mm-field">
          <span className="mm-label">超时（秒）</span>
        <input className="y10-input" type="number" min="1" value={state.timeout_sec} data-testid="provider-timeout"
                 onChange={(event) => props.onPatch({ timeout_sec: event.target.value })} />
        </label>
      </details>

      <p className="y10-small y10-muted mm-hint">Key 在添加连接时保存；编辑连接时也可单独保存 Key。</p>
      {props.impact && <p className="y10-warn-text mm-warn" role="status" data-testid="impact-notice">{props.impact}</p>}

      <section className="y10-cred-form mm-credential" data-testid="credential-section">
        <h4 className="y10-h3">凭据</h4>
        <p className="y10-small y10-muted mm-meta" data-testid="credential-status">
          {editing && props.credential
            ? `凭据引用 ${props.credential.ref || "（未填写）"}：${credentialText(props.credential)}`
            : "保存连接以后显示实际生效来源。"}
        </p>
        <label className="y10-field mm-field">
          <span className="mm-label">API Key</span>
        <input className="y10-input" type="password" autoComplete="new-password" value={secret} placeholder="仅本次输入，不回填"
                 data-testid="credential-secret"
                 onChange={(event) => setSecret(event.target.value)} />
        </label>
        <label className="y10-check mm-check">
          <input type="checkbox" checked={persist} data-testid="credential-persist"
                 onChange={(event) => setPersist(event.target.checked)} /> 写入 .env
        </label>
        <p className="y10-small y10-muted mm-hint">不勾选时只在本进程有效，重启后需重新提供。</p>
        <div className="y10-row mm-actions">
          <button type="button" className="y10-btn" disabled={!editing || secret.trim() === "" || props.busy}
                  onClick={() => {
                    props.onCredential("set", secret, persist);
                    setSecret("");
                  }}>
            保存 Key
          </button>
          <button type="button" className="y10-btn" disabled={!editing || props.busy}
                  onClick={() => props.onCredential("clear_override", "", false)}>
            清除内存覆盖
          </button>
          <button type="button" className="y10-btn danger" disabled={!editing || props.busy}
                  onClick={() => props.onCredential("remove_persisted", "", false)}>
            删除持久凭据
          </button>
        </div>
      </section>

      <section className="y10-candidates mm-candidates" data-testid="candidate-section">
        <h4 className="y10-h3">获取模型列表</h4>
        <div className="y10-row mm-actions">
          <button type="button" className="y10-btn" disabled={!editing || props.collecting} onClick={props.onCollectCandidates}>
            {props.collecting ? "候选获取中…" : "获取模型列表"}
          </button>
        </div>
        {props.candidate === null && <p className="y10-small y10-muted mm-hint">尚未获取；结果只服务本次设置，不写入目录。</p>}
        {props.candidate?.status === "unknown" && (
          <p className="y10-warn-text mm-warn" role="status" data-testid="candidates-unknown">
            请求 {props.candidate.source_url || "（没有模型列表地址）"} 时候选未知：{props.candidate.error || "上游模型列表不可用"}
          </p>
        )}
        {props.candidate?.status === "ok" && (
          <>
            <p className="y10-small y10-muted mm-meta" data-testid="candidates-source">
              来源 {props.candidate.source_url} · 采集时间 {props.candidate.fetched_at}
            </p>
            <ul className="y10-chip-row mm-candidates">
              {props.candidate.candidates.map((item) => (
                <li key={item.id}>
                  <code>{item.id}</code>
                  <button type="button" className="y10-chip" data-testid={`admit-candidate-${item.id}`}
                          onClick={() => props.onAddRow(props.rowFromCandidate(item))}>
                    建立访问定义
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      <section className="y10-form-block mm-models" data-testid="model-rows">
        <h4 className="y10-h3">模型访问定义</h4>
        <p className="y10-small y10-muted mm-hint">
          ID 是本系统内的标识，只能使用字母、数字与 <code>.</code> <code>-</code> <code>_</code> <code>:</code>；
          上游模型 ID 保持上游的写法，请求发往上游时用的就是它。
        </p>
        {state.rows.length === 0 && <p className="y10-small y10-muted mm-hint">还没有模型访问定义；获取模型列表以后点击候选，或手动添加。</p>}
        {state.rows.map((row) => {
          const admission = admissionOf(state.id, row.id, props.admissions);
          const levelChoices = defaultLevelOptions(row.reasoning_levels);
          const modeChoices = reasoningModeOptions(row.protocol);
          const rowKey = row.id || row.key;
          // 容量的问题（缺少哪一项或哪一项的关系不成立）与目录文档校验同一份判断（工单 #294）
          const capacityIssue = capacityIssueText({
            context_window: intFromInput(row.context_window),
            max_output_tokens: intFromInput(row.max_output_tokens),
          });
          return (
            <fieldset className="y10-block is-compact mm-row" key={row.key} data-testid={`model-row-${rowKey}`}>
              <legend>{row.id || "新的定义"}</legend>
              <label className="y10-field mm-field">
                <span className="mm-label">ID</span>
                <input className="y10-input" value={row.id} required data-testid={`row-id-${rowKey}`}
                       onChange={(event) => props.onPatchRow(row.key, { id: event.target.value })} />
              </label>
              <label className="y10-field mm-field">
                <span className="mm-label">上游模型 ID</span>
                <input className="y10-input" value={row.model} required data-testid={`row-model-${rowKey}`}
                       onChange={(event) => props.onPatchRow(row.key, { model: event.target.value })} />
              </label>
              {row.model.trim() !== "" && row.model !== row.id && (
                <p className="y10-small y10-muted mm-hint" data-testid={`id-differs-${rowKey}`}>
                  发给上游的是「{row.model}」，ID「{row.id}」只在本系统内使用。
                </p>
              )}
              <label className="y10-field mm-field">
                <span className="mm-label">调用协议</span>
                <select className="y10-select" value={row.protocol} data-testid={`row-protocol-${rowKey}`}
                        onChange={(event) => chooseProtocol(row, event.target.value)}>
                  {Object.entries(PROTOCOL_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>{label}</option>
                  ))}
                </select>
              </label>
              <label className="y10-field mm-field">
                <span className="mm-label">窗口</span>
                <input className="y10-input" type="number" min="1" value={row.context_window} data-testid={`row-window-${rowKey}`}
                       onChange={(event) => props.onPatchRow(row.key, patchRowCapacity(row, "context_window", event.target.value))} />
              </label>
              <label className="y10-field mm-field">
                <span className="mm-label">输出上限</span>
                <input className="y10-input" type="number" min="1" value={row.max_output_tokens} data-testid={`row-output-${rowKey}`}
                       onChange={(event) => props.onPatchRow(row.key, patchRowCapacity(row, "max_output_tokens", event.target.value))} />
              </label>
              <div className="y10-row y10-row-actions mm-actions mm-row-actions">
                {capacityIssue !== "" && (
                  <span className="y10-warn-text mm-warn" role="status" data-testid={`capacity-issue-${rowKey}`}>
                    {capacityIssue}
                  </span>
                )}
                <span className="spacer" />
                {editing && row.id && (
                  <button type="button" className="y10-btn small" data-testid={`test-model-${row.id}`}
                          disabled={props.testing[`model:${row.id}`] === true || props.busy}
                          onClick={() => props.onTestModel(row.id)}>
                    {props.testing[`model:${row.id}`] ? "测试中…" : "模型测试"}
                  </button>
                )}
                {/* 行内测试按钮旁边同样显示这一行的模型测试结果（工单 #294） */}
                {editing && row.id && (props.testing[`model:${row.id}`] === true || props.tests[`model:${row.id}`] !== undefined) && (
                  <span className="y10-test-mini mm-meta" role="status" data-testid={`form-model-result-${row.id}`}>
                    {props.testing[`model:${row.id}`] ? "模型测试中…" : props.tests[`model:${row.id}`]}
                  </span>
                )}
                <button type="button" className="y10-btn small" data-testid={`remove-model-${rowKey}`}
                        onClick={() => props.onRemoveRow(row.key)}>移除</button>
              </div>
              <label className="y10-check mm-check">
                <input type="checkbox" checked={row.image_input} data-testid={`image-input-${rowKey}`}
                       onChange={(event) => props.onPatchRow(row.key, { image_input: event.target.checked })} />
                支持图像输入
              </label>
              <label className="y10-check mm-check">
                <input type="checkbox" checked={row.accepts_required_tool_call}
                       data-testid={`accepts-tool-call-${rowKey}`}
                       onChange={(event) => props.onPatchRow(row.key, { accepts_required_tool_call: event.target.checked })} />
                接受要求调用工具
              </label>
              <div className="y10-field mm-field">
                <span className="mm-label">支持档位</span>
                <div className="y10-chip-row mm-chips" role="group" aria-label="支持的推理档位">
                  {REASONING_LEVELS.map((level) => (
                    <button key={level} type="button"
                            className={row.reasoning_levels.includes(level) ? "y10-chip chip selected" : "y10-chip chip"}
                            aria-pressed={row.reasoning_levels.includes(level)}
                            data-testid={`level-${rowKey}-${level}`}
                            onClick={() => toggleLevel(row, level)}>
                      {level}
                    </button>
                  ))}
                </div>
              </div>
              <label className="y10-field mm-field">
                <span className="mm-label">默认档位</span>
                <select className="y10-select" value={row.default_reasoning_level} data-testid={`default-level-${rowKey}`}
                        onChange={(event) => props.onPatchRow(row.key, { default_reasoning_level: event.target.value })}>
                  <option value="">未选择</option>
                  {levelChoices.map((level) => <option key={level} value={level}>{level}</option>)}
                </select>
              </label>
              <label className="y10-field mm-field">
                <span className="mm-label">推理参数方式</span>
                <select className="y10-select" value={row.reasoning_mode} data-testid={`reasoning-mode-${rowKey}`}
                        onChange={(event) => props.onPatchRow(row.key, { reasoning_mode: event.target.value })}>
                  <option value="">未声明</option>
                  {modeChoices.map((mode) => (
                    <option key={mode} value={mode}>{REASONING_MODE_LABELS[mode]}</option>
                  ))}
                </select>
              </label>
              <p className="y10-small y10-muted mm-meta" data-testid={`capability-source-${rowKey}`}>能力来源：{row.capability_source}</p>
              {editing && (
                <p className="y10-small y10-muted mm-meta" data-testid={`admission-${row.id}`}>准入：{admissionLabel(admission)}</p>
              )}
            </fieldset>
          );
        })}
        <div className="y10-row mm-actions">
          <button type="button" className="y10-btn" data-testid="add-model-row" onClick={() => props.onAddRow(props.blankRow())}>
            手动添加一行
          </button>
        </div>
      </section>

      {props.status && (
        <p className={props.status.kind === "ok" ? "y10-small mm-ok" : "y10-warn-text mm-warn"} role="status" data-testid="form-status">
          {props.status.message}
        </p>
      )}
      <div className="y10-row mm-actions">
        <button className="y10-btn primary" type="submit" disabled={!canSubmit} data-testid="submit-provider">
          {props.busy ? "保存中…" : editing ? "保存" : "添加"}
        </button>
        {editing && (
          <>
            <button type="button" className="y10-btn" data-testid="test-connection" disabled={connectionTesting || props.busy}
                    onClick={props.onTestConnection}>
              {connectionTesting ? "测试中…" : "测试连接"}
            </button>
            <button type="button" className="y10-btn danger" data-testid="delete-provider" disabled={props.busy} onClick={props.onDelete}>
              删除
            </button>
          </>
        )}
        <button type="button" className="y10-btn" onClick={props.onCancel}>取消</button>
      </div>
    </form>
  );
}

// 凭据状态与来源（设计说明第 9.1 节）：缺失，或来源为内存、环境、.env
function credentialText(credential: CatalogCredential): string {
  if (!credential.configured) {
    return "缺失，请填写 API Key";
  }
  const source = credential.source === "override" ? "内存"
    : credential.source === "env" ? "环境"
      : credential.source === "dotenv" ? ".env"
        : credential.source === "none" ? "不需要凭据"
          : credential.source;
  const override = credential.has_override && credential.source !== "override" ? "，内存覆盖当前生效" : "";
  return `已配置，来源 ${source}${override}`;
}
