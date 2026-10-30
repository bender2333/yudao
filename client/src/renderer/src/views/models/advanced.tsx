// 高级（工单 #1297；模型管理设计说明第 9.1 节「高级」行）。
// 折叠着的一块：目录文档（编辑 JSON 的弹窗、导入与导出在弹窗里）、重新读取目录文件、
// 各模型访问定义的协议、推理档位声明、输入方式与是否接受要求调用工具、
// 连接的 ID、名称、凭据引用、模型列表地址与超时、预置表与能力表的 revision 与来源。
// 主路径上没有这些内容：它们只在展开以后出现（工单验收第 5 条）。

import { useState } from "react";
import type { Catalog, CatalogModel, CatalogProvider } from "../../api/generated/types.gen";
import { PROTOCOL_LABELS, REASONING_LEVELS, REASONING_MODE_LABELS, reasoningModeOptions }
  from "./model-logic";

export type ConnectionDraft = {
  name: string;
  credential_ref: string;
  models_url: string;
  timeout_sec: string;
};

export type ModelDraft = {
  protocol: string;
  reasoning_levels: string[];
  default_reasoning_level: string;
  reasoning_mode: string;
  input_image: boolean;
  accepts_required_tool_call: boolean;
};

export type AdvancedProps = {
  catalog: Catalog;
  busy: boolean;
  onReload: () => void;
  onEditDocument: () => void;
  onSaveConnection: (providerId: string, draft: ConnectionDraft) => void;
  onSaveModel: (providerId: string, modelId: string, draft: ModelDraft) => void;
};

function connectionDraft(provider: CatalogProvider): ConnectionDraft {
  return {
    name: provider.name,
    credential_ref: provider.credential_ref,
    models_url: provider.models_url,
    timeout_sec: String(provider.timeout_sec),
  };
}

function modelDraft(model: CatalogModel): ModelDraft {
  return {
    protocol: model.protocol,
    reasoning_levels: [...model.reasoning_levels],
    default_reasoning_level: model.default_reasoning_level ?? "",
    reasoning_mode: model.reasoning_mode,
    input_image: model.input_modalities.includes("image"),
    accepts_required_tool_call: model.accepts_required_tool_call,
  };
}

export function Advanced(props: AdvancedProps) {
  const [connectionDrafts, setConnectionDrafts] = useState<Record<string, ConnectionDraft>>({});
  const [modelDrafts, setModelDrafts] = useState<Record<string, ModelDraft>>({});
  const [open, setOpen] = useState(false);

  const patchConnection = (providerId: string, patch: Partial<ConnectionDraft>) => {
    setConnectionDrafts((current) => ({
      ...current,
      [providerId]: { ...(current[providerId] ?? connectionDraft(
        props.catalog.providers.find((item) => item.id === providerId) ?? props.catalog.providers[0])), ...patch },
    }));
  };
  const patchModel = (modelId: string, patch: Partial<ModelDraft>) => {
    setModelDrafts((current) => ({
      ...current,
      [modelId]: { ...(current[modelId] ?? modelDraft(
        props.catalog.models.find((item) => item.id === modelId) ?? props.catalog.models[0])), ...patch },
    }));
  };

  return (
    <details className="y10-details mm-advanced" open={open}
             data-testid="advanced"
             onToggle={(event) => setOpen((event.target as HTMLDetailsElement).open)}>
      <summary>高级</summary>
      <div className="mm-advanced-body">
        <section className="mm-advanced-block">
          <h4 className="y10-h3">目录文件</h4>
          <dl className="y10-kv is-inline">
            <div>
              <dt>目录修订</dt>
              <dd><code>{props.catalog.revision}</code></dd>
            </div>
            <div>
              <dt>配置状态</dt>
              <dd>{props.catalog.config_state}</dd>
            </div>
            <div>
              <dt>重读错误</dt>
              <dd>{props.catalog.reload_error ?? "无"}</dd>
            </div>
            <div>
              <dt>预置表</dt>
              <dd>revision {props.catalog.presets.revision} · 来源 {props.catalog.presets.source}</dd>
            </div>
            <div>
              <dt>模型能力表</dt>
              <dd>revision {props.catalog.capability_table.revision} · 快照 {props.catalog.capability_table.snapshot_date}
                · 来源 {props.catalog.capability_table.source}</dd>
            </div>
          </dl>
          <div className="y10-row mm-actions">
            <button type="button" className="y10-btn small" data-testid="advanced-reload"
                    disabled={props.busy} onClick={props.onReload}>
              重新读取目录文件
            </button>
            <button type="button" className="y10-btn small" data-testid="advanced-edit-document"
                    onClick={props.onEditDocument}>
              编辑目录文档（JSON）
            </button>
          </div>
        </section>

        {props.catalog.providers.map((provider) => {
          const draft = connectionDrafts[provider.id] ?? connectionDraft(provider);
          return (
            <section className="mm-advanced-block" key={provider.id}
                     data-testid={`advanced-connection-${provider.id}`}>
              <h4 className="y10-h3">连接 {provider.id}</h4>
              <div className="y10-grid-2">
                <label className="y10-field" htmlFor={`advanced-name-${provider.id}`}>
                  <span>名称</span>
                  <input id={`advanced-name-${provider.id}`} className="y10-input" type="text"
                         value={draft.name} data-testid={`advanced-name-${provider.id}`}
                         onChange={(event) => patchConnection(provider.id, { name: event.target.value })} />
                </label>
                <label className="y10-field" htmlFor={`advanced-credential-${provider.id}`}>
                  <span>凭据引用</span>
                  <input id={`advanced-credential-${provider.id}`} className="y10-input" type="text"
                         value={draft.credential_ref} data-testid={`advanced-credential-${provider.id}`}
                         onChange={(event) => patchConnection(provider.id, { credential_ref: event.target.value })} />
                  <small>可以改为环境变量的名字。</small>
                </label>
                <label className="y10-field" htmlFor={`advanced-models-url-${provider.id}`}>
                  <span>模型列表地址</span>
                  <input id={`advanced-models-url-${provider.id}`} className="y10-input" type="text"
                         value={draft.models_url} data-testid={`advanced-models-url-${provider.id}`}
                         onChange={(event) => patchConnection(provider.id, { models_url: event.target.value })} />
                </label>
                <label className="y10-field" htmlFor={`advanced-timeout-${provider.id}`}>
                  <span>超时（秒）</span>
                  <input id={`advanced-timeout-${provider.id}`} className="y10-input" type="text" inputMode="numeric"
                         value={draft.timeout_sec} data-testid={`advanced-timeout-${provider.id}`}
                         onChange={(event) => patchConnection(provider.id, { timeout_sec: event.target.value })} />
                </label>
              </div>
              <div className="y10-row mm-actions">
                <button type="button" className="y10-btn small" data-testid={`advanced-save-connection-${provider.id}`}
                        disabled={props.busy}
                        onClick={() => props.onSaveConnection(provider.id, draft)}>
                  保存连接
                </button>
              </div>

              {provider.models.map((model) => {
                const modelKey = model.id;
                const modelState = modelDrafts[modelKey] ?? modelDraft(model);
                const modes = reasoningModeOptions(modelState.protocol);
                return (
                  <div className="mm-advanced-model" key={modelKey}
                       data-testid={`advanced-model-${provider.id}-${model.model}`}>
                    <h5 className="y10-h3">{model.model}</h5>
                    <div className="y10-grid-2">
                      <label className="y10-field" htmlFor={`advanced-protocol-${modelKey}`}>
                        <span>协议</span>
                        <select id={`advanced-protocol-${modelKey}`} className="y10-select"
                                value={modelState.protocol}
                                data-testid={`advanced-protocol-${provider.id}-${model.model}`}
                                onChange={(event) => patchModel(modelKey, { protocol: event.target.value })}>
                          {Object.entries(PROTOCOL_LABELS).map(([value, label]) => (
                            <option key={value} value={value}>{label}</option>
                          ))}
                        </select>
                      </label>
                      <label className="y10-field" htmlFor={`advanced-mode-${modelKey}`}>
                        <span>推理参数方式</span>
                        <select id={`advanced-mode-${modelKey}`} className="y10-select"
                                value={modelState.reasoning_mode}
                                data-testid={`advanced-mode-${provider.id}-${model.model}`}
                                onChange={(event) => patchModel(modelKey, { reasoning_mode: event.target.value })}>
                          <option value="">不声明</option>
                          {modes.map((mode) => (
                            <option key={mode} value={mode}>{REASONING_MODE_LABELS[mode] ?? mode}</option>
                          ))}
                        </select>
                      </label>
                    </div>
                    <fieldset className="y10-field">
                      <legend>支持档位</legend>
                      <div className="y10-row mm-actions">
                        {REASONING_LEVELS.map((level) => (
                          <label className="y10-check" key={level}>
                            <input type="checkbox" checked={modelState.reasoning_levels.includes(level)}
                                   data-testid={`advanced-level-${provider.id}-${model.model}-${level}`}
                                   onChange={(event) => patchModel(modelKey, {
                                     reasoning_levels: event.target.checked
                                       ? [...modelState.reasoning_levels, level]
                                       : modelState.reasoning_levels.filter((item) => item !== level),
                                   })} />
                            <span>{level}</span>
                          </label>
                        ))}
                      </div>
                    </fieldset>
                    <label className="y10-field" htmlFor={`advanced-default-level-${modelKey}`}>
                      <span>默认档位</span>
                      <select id={`advanced-default-level-${modelKey}`} className="y10-select"
                              value={modelState.default_reasoning_level}
                              data-testid={`advanced-default-level-${provider.id}-${model.model}`}
                              onChange={(event) => patchModel(modelKey, { default_reasoning_level: event.target.value })}>
                        <option value="">未选择</option>
                        {REASONING_LEVELS.filter((level) => modelState.reasoning_levels.includes(level)).map((level) => (
                          <option key={level} value={level}>{level}</option>
                        ))}
                      </select>
                    </label>
                    <div className="y10-row mm-actions">
                      <label className="y10-check">
                        <input type="checkbox" checked={modelState.input_image}
                               data-testid={`advanced-image-${provider.id}-${model.model}`}
                               onChange={(event) => patchModel(modelKey, { input_image: event.target.checked })} />
                        <span>图像输入</span>
                      </label>
                      <label className="y10-check">
                        <input type="checkbox" checked={modelState.accepts_required_tool_call}
                               data-testid={`advanced-tool-${provider.id}-${model.model}`}
                               onChange={(event) => patchModel(modelKey, {
                                 accepts_required_tool_call: event.target.checked,
                               })} />
                        <span>接受要求调用工具</span>
                      </label>
                    </div>
                    <div className="y10-row mm-actions">
                      <button type="button" className="y10-btn small"
                              data-testid={`advanced-save-model-${provider.id}-${model.model}`}
                              disabled={props.busy}
                              onClick={() => props.onSaveModel(provider.id, modelKey, modelState)}>
                        保存这个模型
                      </button>
                    </div>
                  </div>
                );
              })}
            </section>
          );
        })}
      </div>
    </details>
  );
}
