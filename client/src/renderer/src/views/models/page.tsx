// 模型管理页（原型 v8 设计说明第 9.1 节与模型管理设计说明第 9.1 节，工单 #93）。
// 页面读取两个视图：catalog（连接、模型访问定义、准入与部门默认）与 catalog.document（编辑 JSON）。
// 命令经 app.command 提交；两种测试与候选采集的结果内容在事件里，页面订阅事件取回。
// 显示与判断都在 model-logic.ts 与 form.tsx 里，这个文件负责取数、提交与把结果放回界面。

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CommandOutcome } from "../../contract/invoke";
import type { ViewSync } from "../../contract/view-sync";
import type {
  Catalog,
  CatalogDocument,
  CatalogTestFinishedPayload,
  EventObject,
} from "../../api/generated/types.gen";
import { JsonDialog } from "./json-dialog";
import { ProviderForm } from "./form";
import {
  DEPARTMENT_LABELS,
  PROTOCOL_LABELS,
  admissionLabel,
  admissionOf,
  admissionSummary,
  admittedModels,
  affectedReferences,
  credentialStatusLabel,
  emptyFormState,
  formStateFromProvider,
  impactNotice,
  presetById,
  providerInputFromForm,
  rowFromCandidate,
  rowFromManual,
  rowToModelInput,
  rowsSavable,
  tierOptions,
  type CandidateState,
  type FormState,
  type ModelOption,
  type ServicePreset,
  type UpstreamCandidate,
} from "./model-logic";

export type ModelManagementPageProps = {
  views: ViewSync | null;
  command: (name: string, body: unknown) => Promise<CommandOutcome>;
  subscribeEvents: (listener: (event: EventObject) => void) => () => void;
  onBack: () => void;
};

// 提交结果：命令被接受或按原因拒绝，两者都在界面上说明
type SubmitResult = { ok: boolean; message: string };

const DEPARTMENTS = ["product", "engineering", "quality"] as const;

export function ModelManagementPage(props: ModelManagementPageProps) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [document, setDocument] = useState<CatalogDocument | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [form, setForm] = useState<{ mode: "add" | "edit"; state: FormState } | null>(null);
  const [candidates, setCandidates] = useState<Record<string, CandidateState>>({});
  const [collecting, setCollecting] = useState<string | null>(null);
  const [testing, setTesting] = useState<Record<string, boolean>>({});
  const [tests, setTests] = useState<Record<string, string>>({});
  const [formStatus, setFormStatus] = useState<{ kind: "ok" | "error"; message: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [editingDefaults, setEditingDefaults] = useState<Record<string, { modelId: string; tier: string }>>({});
  const [defaultsStatus, setDefaultsStatus] = useState<{ kind: "ok" | "error"; message: string } | null>(null);
  const [jsonOpen, setJsonOpen] = useState(false);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; message: string } | null>(null);

  const views = props.views;
  const catalogRef = useRef<Catalog | null>(null);

  const presets = useMemo(
    () => (catalog?.presets.presets ?? []) as unknown as ServicePreset[],
    [catalog],
  );
  // 部门默认与项目设置的选项：按连接分组的已准入定义（第 9.1 节）
  const choices = useMemo(
    () => (catalog ? admittedModels(catalog.models, catalog.providers, catalog.admissions) : []),
    [catalog],
  );

  useEffect(() => {
    if (!views) {
      return;
    }
    void views.open<Catalog>("models.catalog", { query: "catalog", params: undefined }, (data) => {
      catalogRef.current = data;
      setCatalog(data);
      setEditingDefaults((current) => {
        // 部门默认的草稿：目录更新时保留用户未提交的选择，其余按目录重建
        if (Object.keys(current).length > 0) {
          return current;
        }
        const next: Record<string, { modelId: string; tier: string }> = {};
        for (const [department, binding] of Object.entries(data.bindings)) {
          next[department] = { modelId: binding.model_id, tier: binding.requested_tier ?? "" };
        }
        return next;
      });
    });
    void views.open<CatalogDocument>("models.document", { query: "catalog.document", params: undefined }, (data) => {
      setDocument(data);
    });
    return () => {
      views.close("models.catalog");
      views.close("models.document");
    };
  }, [views]);

  // 事件：候选采集与两种测试的结果内容都在事件里；按同一把键把「测试中」换成结果
  useEffect(() => {
    return props.subscribeEvents((event) => {
      if (event.type === "catalog_candidates_collected") {
        const payload = event.payload;
        const collected: CandidateState = {
          status: payload.status,
          source_url: payload.source_url,
          fetched_at: payload.fetched_at,
          candidates: payload.candidates.filter(isUpstreamCandidate),
          error: payload.error,
        };
        setCandidates((current) => ({ ...current, [payload.provider_id]: collected }));
        setCollecting(null);
        return;
      }
      if (event.type === "catalog_test_finished") {
        setTesting((current) => ({ ...current, [testKeyOf(event.payload)]: false }));
        setTests((current) => ({ ...current, [testKeyOf(event.payload)]: testText(event.payload) }));
      }
    });
  }, [props]);

  // 提交一个命令：结果交回接受或按原因拒绝；两个测试与候选的命令先登记命令身份，结果随后由事件到达
  const submit = useCallback(async (name: string, body: Record<string, unknown>): Promise<SubmitResult> => {
    const current = catalogRef.current;
    if (current === null) {
      return { ok: false, message: "尚未读取目录，请稍后再试" };
    }
    const outcome = await props.command(name, {
      command_id: crypto.randomUUID(),
      base_version: current.revision,
      ...body,
    });
    return interpret(outcome);
  }, [props]);

  const reload = useCallback(async () => {
    setNotice(null);
    setBusy(true);
    const result = await submit("catalog.reload", {});
    setBusy(false);
    setNotice({ kind: result.ok ? "ok" : "error", message: result.ok ? "已重新读取目录文件。" : result.message });
  }, [submit]);

  const openEdit = useCallback((providerId: string) => {
    const current = catalogRef.current;
    const provider = current?.providers.find((item) => item.id === providerId);
    if (!provider) {
      return;
    }
    setFormStatus(null);
    setForm({ mode: "edit", state: formStateFromProvider(provider) });
  }, []);

  const openAdd = useCallback(() => {
    setFormStatus(null);
    setForm({ mode: "add", state: emptyFormState() });
  }, []);

  const submitForm = useCallback(async () => {
    if (!form) {
      return;
    }
    const rows = form.state.rows;
    if (!rowsSavable(rows)) {
      setFormStatus({ kind: "error", message: "窗口与输出上限没有「接受」或修改的行不能保存。" });
      return;
    }
    setBusy(true);
    const result = await submit("catalog.connection.save", {
      provider: providerInputFromForm(form.state),
      models: rows.map(rowToModelInput),
    });
    setBusy(false);
    setFormStatus({ kind: result.ok ? "ok" : "error", message: result.ok ? "已保存 Provider 配置。" : result.message });
    if (result.ok) {
      setForm(null);
    }
  }, [form, submit]);

  const deleteProvider = useCallback(async (providerId: string) => {
    setBusy(true);
    const result = await submit("catalog.connection.delete", { provider_id: providerId });
    setBusy(false);
    setNotice({ kind: result.ok ? "ok" : "error", message: result.ok ? "已删除 Provider 配置。" : result.message });
    if (result.ok) {
      setForm(null);
    }
  }, [submit]);

  const testConnection = useCallback(async (providerId: string) => {
    setTesting((current) => ({ ...current, [`connection:${providerId}`]: true }));
    const result = await submit("catalog.connection.test", { provider_id: providerId });
    if (!result.ok) {
      setTesting((current) => ({ ...current, [`connection:${providerId}`]: false }));
      setNotice({ kind: "error", message: result.message });
    }
  }, [submit]);

  const testModel = useCallback(async (providerId: string, modelId: string) => {
    setTesting((current) => ({ ...current, [`model:${modelId}`]: true }));
    const result = await submit("catalog.model.test", { provider_id: providerId, model_id: modelId });
    if (!result.ok) {
      setTesting((current) => ({ ...current, [`model:${modelId}`]: false }));
      setNotice({ kind: "error", message: result.message });
    }
  }, [submit]);

  const collectCandidates = useCallback(async (providerId: string, modelsUrl: string) => {
    setCollecting(providerId);
    const result = await submit("catalog.candidates.collect", {
      provider_id: providerId,
      models_url: modelsUrl.trim() === "" ? null : modelsUrl.trim(),
    });
    if (!result.ok) {
      setCollecting(null);
      setNotice({ kind: "error", message: result.message });
    }
  }, [submit]);

  const saveCredential = useCallback(async (ref: string, secret: string, persist: boolean, baseVersion: number) => {
    setBusy(true);
    const outcome = await props.command("credential.set", {
      command_id: crypto.randomUUID(),
      base_version: baseVersion,
      ref,
      secret,
      persist,
    });
    setBusy(false);
    const result = interpret(outcome);
    setFormStatus({ kind: result.ok ? "ok" : "error", message: result.ok ? "已保存 API Key。" : result.message });
  }, [props]);

  const credentialAction = useCallback(async (
    action: "clear_override" | "remove_persisted",
    ref: string,
    baseVersion: number,
  ) => {
    setBusy(true);
    const name = action === "clear_override" ? "credential.clear_override" : "credential.remove_persisted";
    const outcome = await props.command(name, {
      command_id: crypto.randomUUID(), base_version: baseVersion, ref,
    });
    setBusy(false);
    const result = interpret(outcome);
    setFormStatus({
      kind: result.ok ? "ok" : "error",
      message: result.ok ? (action === "clear_override" ? "已清除内存覆盖。" : "已删除持久凭据。") : result.message,
    });
  }, [props]);

  const saveDefaults = useCallback(async () => {
    const bindings: Record<string, { provider_id: string; model_id: string; requested_tier: string | null }> = {};
    for (const department of DEPARTMENTS) {
      const choice = editingDefaults[department];
      if (!choice || choice.modelId === "") {
        continue;
      }
      const option = choices.find((item) => item.id === choice.modelId);
      if (!option) {
        continue;
      }
      bindings[department] = {
        provider_id: option.provider_id,
        model_id: option.id,
        requested_tier: choice.tier === "" ? null : choice.tier,
      };
    }
    setDefaultsStatus(null);
    setBusy(true);
    const result = await submit("catalog.department_defaults.save", { bindings });
    setBusy(false);
    setDefaultsStatus({ kind: result.ok ? "ok" : "error", message: result.ok ? "已保存部门默认。" : result.message });
  }, [editingDefaults, choices, submit]);

  const saveDocument = useCallback(async (next: unknown): Promise<SubmitResult> => {
    const result = await submit("catalog.document.save", { document: next });
    return result;
  }, [submit]);

  const formCredential = useMemo(() => {
    if (!form || form.mode !== "edit" || !catalog) {
      return null;
    }
    return catalog.providers.find((item) => item.id === form.state.id)?.credential ?? null;
  }, [form, catalog]);
  const impact = useMemo(() => {
    if (!form || form.mode !== "edit" || !catalog) {
      return "";
    }
    const before = catalog.providers.find((item) => item.id === form.state.id);
    if (!before) {
      return "";
    }
    const rowsBefore = before.models.map((model) => ({
      id: model.id, model: model.model, reasoning_mode: model.reasoning_mode,
    }));
    const rowsNow = form.state.rows.map((row) => ({
      id: row.id, model: row.model, reasoning_mode: row.reasoning_mode,
    }));
    const departments = affectedReferences(
      { ...before, base_url: form.state.base_url, credential_ref: form.state.credential_ref, protocol: form.state.protocol },
      before,
      rowsNow,
      rowsBefore,
      Object.fromEntries(Object.entries(catalog.bindings).map(([key, value]) => [
        key, { provider_id: value.provider_id, model_id: value.model_id },
      ])),
    );
    return impactNotice(departments);
  }, [form, catalog]);

  if (catalog === null) {
    return <div className="card"><h1>模型管理</h1><p className="note">正在读取目录…</p></div>;
  }

  return (
    <div className="mm-page">
      <div className="mm-head">
        <h1>模型管理</h1>
        <p className="mm-meta">
          目录修订 {catalog.revision} · 配置状态 {catalog.config_state}
          {catalog.reload_error && <span className="mm-warn"> · 文件更新未生效：{catalog.reload_error}</span>}
        </p>
        <div className="mm-actions">
          <button type="button" className="primary" onClick={openAdd}>添加 Provider 配置</button>
          <button type="button" data-testid="reload" disabled={busy} onClick={() => void reload()}>重新读取</button>
          <button type="button" data-testid="edit-json" onClick={() => setJsonOpen(true)}>编辑 JSON</button>
          <button type="button" onClick={props.onBack}>返回原界面</button>
        </div>
        {notice && (
          <p className={notice.kind === "ok" ? "mm-ok" : "mm-warn"} role="status" data-testid="page-notice">
            {notice.message}
          </p>
        )}
      </div>

      {catalog.providers.length === 0 && (
        <p className="mm-hint">还没有 Provider 配置。添加一份连接，选择服务方案与协议，保存以后再获取模型列表。</p>
      )}

      {catalog.providers.map((provider) => {
        const summary = admissionSummary(provider, catalog.admissions);
        const preset = presetById(presets, provider.preset_id);
        const open = expanded[provider.id] === true;
        return (
          <section className="mm-card" key={provider.id} data-testid={`provider-${provider.id}`}>
            <div className="mm-summary">
              <button type="button" className="mm-toggle" aria-expanded={open}
                      onClick={() => setExpanded((current) => ({ ...current, [provider.id]: !open }))}>
                {open ? "收起" : "展开"}
              </button>
              <span className="mm-name">{provider.name}</span>
              <span className="mm-meta">
                服务方案 {preset?.name ?? "自定义"} · 协议 {PROTOCOL_LABELS[provider.protocol] ?? provider.protocol}
                {" · "}{provider.base_url || "（没有地址）"}
              </span>
              <span className="mm-meta">凭据：{credentialStatusLabel(provider.credential)}</span>
              <span className="mm-count">已准入 {summary.admitted} · 候选 {summary.candidates}</span>
            </div>

            {open && (
              <div className="mm-body">
                <div className="mm-actions">
                  <button type="button" onClick={() => openEdit(provider.id)}>编辑</button>
                  <button type="button" data-testid={`test-connection-${provider.id}`}
                          disabled={testing[`connection:${provider.id}`] === true}
                          onClick={() => void testConnection(provider.id)}>
                    {testing[`connection:${provider.id}`] ? "测试中…" : "测试连接"}
                  </button>
                  <button type="button" data-testid={`collect-${provider.id}`}
                          disabled={collecting === provider.id}
                          onClick={() => void collectCandidates(provider.id, provider.models_url)}>
                    {collecting === provider.id ? "候选获取中…" : "获取模型列表"}
                  </button>
                  <button type="button" data-testid={`delete-${provider.id}`}
                          onClick={() => void deleteProvider(provider.id)}>删除</button>
                </div>
                {(tests[`connection:${provider.id}`] || testing[`connection:${provider.id}`]) && (
                  <p className="mm-meta" data-testid={`connection-result-${provider.id}`}>
                    连接测试：{testing[`connection:${provider.id}`] ? "测试中…" : tests[`connection:${provider.id}`]}
                  </p>
                )}

                {candidates[provider.id] && (
                  <div className="mm-candidates" data-testid={`candidates-${provider.id}`}>
                    {candidates[provider.id].status === "unknown" ? (
                      <p className="mm-warn" role="status">候选未知：{candidates[provider.id].error || "上游模型列表不可用"}</p>
                    ) : (
                      <>
                        <p className="mm-meta">
                          来源 {candidates[provider.id].source_url} · 采集时间 {candidates[provider.id].fetched_at}
                        </p>
                        <ul>
                          {candidates[provider.id].candidates.map((item) => (
                            <li key={item.id}>
                              <code>{item.id}</code>
                              <button type="button" data-testid={`add-candidate-${provider.id}-${item.id}`}
                                      onClick={() => {
                                        setFormStatus(null);
                                        setForm((current) => {
                                          const base = current ?? {
                                            mode: "edit" as const,
                                            state: formStateFromProvider(provider),
                                          };
                                          const row = rowFromCandidate(item, catalog.capability_table, provider.preset_id);
                                          return { mode: "edit", state: { ...base.state, rows: [...base.state.rows, row] } };
                                        });
                                      }}>
                                建立访问定义
                              </button>
                            </li>
                          ))}
                        </ul>
                      </>
                    )}
                  </div>
                )}

                <table className="mm-table">
                  <thead>
                    <tr>
                      <th>上游模型 ID</th>
                      <th>窗口</th>
                      <th>输出上限</th>
                      <th>推理档位声明</th>
                      <th>输入方式</th>
                      <th>准入</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {provider.models.map((model) => {
                      const admission = admissionOf(provider.id, model.id, catalog.admissions);
                      return (
                        <tr key={model.id} data-testid={`model-${model.id}`}>
                          <td>{model.model}</td>
                          <td>{model.context_window ?? "—"}</td>
                          <td>{model.max_output_tokens ?? "—"}</td>
                          <td>{model.reasoning_levels.length === 0 ? "未声明" : model.reasoning_levels.join("、")}</td>
                          <td>{model.input_modalities.includes("image") ? "文本与图像" : "文本"}</td>
                          <td>{admissionLabel(admission)}</td>
                          <td>
                            <button type="button" data-testid={`row-test-${model.id}`}
                                    disabled={testing[`model:${model.id}`] === true}
                                    onClick={() => void testModel(provider.id, model.id)}>
                              {testing[`model:${model.id}`] ? "测试中…" : "模型测试"}
                            </button>
                            <button type="button" data-testid={`row-remove-${model.id}`}
                                    onClick={() => {
                                      const rows = provider.models
                                        .filter((item) => item.id !== model.id)
                                        .map((item) => ({
                                          ...item,
                                        }));
                                      void submit("catalog.connection.save", {
                                        provider: providerInputOf(provider),
                                        models: rows.map(rowInputOf),
                                      }).then((result) => setNotice({
                                        kind: result.ok ? "ok" : "error",
                                        message: result.ok ? "已移除访问定义。" : result.message,
                                      }));
                                    }}>
                              移除
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                {provider.models.length === 0 && <p className="mm-hint">还没有模型访问定义。</p>}
              </div>
            )}
          </section>
        );
      })}

      {form && (
        <ProviderForm
          mode={form.mode}
          state={form.state}
          onPatch={(patch) => setForm((current) => (current ? { ...current, state: { ...current.state, ...patch } } : current))}
          onPatchRow={(key, patch) => setForm((current) => {
            if (!current) {
              return current;
            }
            return {
              ...current,
              state: {
                ...current.state,
                rows: current.state.rows.map((row) => (row.key === key ? { ...row, ...patch } : row)),
              },
            };
          })}
          onAddRow={(row) => setForm((current) => (
            current ? { ...current, state: { ...current.state, rows: [...current.state.rows, row] } } : current
          ))}
          onRemoveRow={(key) => setForm((current) => (
            current ? { ...current, state: { ...current.state, rows: current.state.rows.filter((row) => row.key !== key) } } : current
          ))}
          rowFromCandidate={(item) => rowFromCandidate(item, catalog.capability_table, form.state.preset_id)}
          blankRow={() => rowFromManual(form.state.rows.length)}
          presets={presets}
          presetRevision={catalog.presets.revision}
          presetSource={catalog.presets.source}
          capabilityRevision={catalog.capability_table.revision}
          capabilitySnapshotDate={catalog.capability_table.snapshot_date}
          capabilitySource={catalog.capability_table.source}
          credential={formCredential}
          candidate={candidates[form.state.id] ?? null}
          collecting={collecting === form.state.id}
          admissions={catalog.admissions}
          impact={impact}
          busy={busy}
          testing={testing}
          status={formStatus}
          onSubmit={() => void submitForm()}
          onCancel={() => setForm(null)}
          onDelete={() => void deleteProvider(form.state.id)}
          onTestConnection={() => void testConnection(form.state.id)}
          onCollectCandidates={() => void collectCandidates(form.state.id, form.state.models_url)}
          onCredential={(action, secret, persist) => {
            if (action === "set") {
              void saveCredential(form.state.credential_ref, secret, persist, formCredential?.version ?? 0);
            } else {
              void credentialAction(action, form.state.credential_ref, formCredential?.version ?? 0);
            }
          }}
          onTestModel={(modelId) => void testModel(form.state.id, modelId)}
        />
      )}

      <section className="mm-defaults" data-testid="department-defaults">
        <h2>部门默认</h2>
        <p className="mm-hint">从各部门下一次模型请求起生效，没有另选模型的项目同样生效，包括进行中的事项。</p>
        <div className="mm-defaults-grid">
          {DEPARTMENTS.map((department) => {
            const choice = editingDefaults[department] ?? { modelId: "", tier: "" };
            const option = choices.find((item) => item.id === choice.modelId);
            const model = catalog.models.find((item) => item.id === choice.modelId);
            const saved = catalog.bindings[department];
            const tiers = tierOptions(model?.reasoning_levels ?? [], saved?.model_id === choice.modelId ? saved.requested_tier ?? "" : "");
            const reminders = catalog.department_reminders[department] ?? [];
            return (
              <div className="mm-default" key={department} data-testid={`default-${department}`}>
                <h3>{DEPARTMENT_LABELS[department]}</h3>
                <label className="mm-field">
                  <span className="mm-label">模型</span>
                  <select value={choice.modelId}
                          data-testid={`default-model-${department}`}
                          onChange={(event) => setEditingDefaults((current) => ({
                            ...current,
                            [department]: { ...choice, modelId: event.target.value, tier: "" },
                          }))}>
                    <option value="">未设置</option>
                    {groupByProvider(choices).map((group) => (
                      <optgroup key={group.provider} label={group.label}>
                        {group.options.map((item) => (
                          <option key={item.id} value={item.id}>{item.model}</option>
                        ))}
                      </optgroup>
                    ))}
                  </select>
                </label>
                <label className="mm-field">
                  <span className="mm-label">推理档位</span>
                  <select value={choice.tier} data-testid={`default-tier-${department}`}
                          disabled={(model?.reasoning_levels ?? []).length === 0 && choice.tier === ""}
                          onChange={(event) => setEditingDefaults((current) => ({
                            ...current,
                            [department]: { ...choice, tier: event.target.value },
                          }))}>
                    <option value="">跟随（不使用档位）</option>
                    {tiers.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                  </select>
                </label>
                {(model?.reasoning_levels ?? []).length === 0 && !choice.tier && (
                  <p className="mm-hint">该模型未声明推理档位，请求不带推理参数。</p>
                )}
                {choice.modelId !== "" && !option && (
                  <p className="mm-warn">该模型不在已准入的定义中，请先做模型测试。</p>
                )}
                {reminders.map((text) => <p className="mm-warn" key={text} data-testid={`reminder-${department}`}>{text}</p>)}
              </div>
            );
          })}
        </div>
        <div className="mm-actions">
          <button type="button" className="primary" data-testid="save-defaults" disabled={busy}
                  onClick={() => void saveDefaults()}>
            保存部门默认
          </button>
        </div>
        {defaultsStatus && (
          <p className={defaultsStatus.kind === "ok" ? "mm-ok" : "mm-warn"} role="status" data-testid="defaults-status">
            {defaultsStatus.message}
          </p>
        )}
      </section>

      {jsonOpen && (
        <JsonDialog
          document={document === null ? null : {
            providers: document.providers,
            models: document.models,
            bindings: document.bindings,
          }}
          onSave={saveDocument}
          onClose={() => setJsonOpen(false)}
        />
      )}
    </div>
  );
}

// 一条命令的结果：200 是 Accepted，409 是 Rejected；拒绝时把原因与当前版本一起显示
function interpret(outcome: CommandOutcome): SubmitResult {
  const error = outcome.error;
  if (error && typeof error === "object" && "message" in error) {
    const message = error.message;
    const current = "current_version" in error ? error.current_version : null;
    return {
      ok: false,
      message: typeof current === "number" ? `${String(message)}（当前版本 ${current}）` : String(message),
    };
  }
  if (error) {
    return { ok: false, message: String(error) };
  }
  return { ok: true, message: "" };
}

function testKeyOf(payload: CatalogTestFinishedPayload): string {
  return payload.kind === "connection" ? `connection:${payload.provider_id}` : `model:${payload.model_id}`;
}

function testText(payload: CatalogTestFinishedPayload): string {
  if (payload.ok) {
    return payload.kind === "model"
      ? `模型测试通过（${payload.elapsed_ms} 毫秒${payload.actual_model ? `，实际返回 ${payload.actual_model}` : ""}${payload.admitted ? "，已准入" : ""}）`
      : `连接测试通过（${payload.elapsed_ms} 毫秒）`;
  }
  return payload.kind === "model" ? `模型测试未通过：${payload.error ?? ""}` : `连接测试未通过：${payload.error ?? ""}`;
}

function groupByProvider(choices: ModelOption[]): { provider: string; label: string; options: ModelOption[] }[] {
  const groups: Record<string, { provider: string; label: string; options: ModelOption[] }> = {};
  for (const choice of choices) {
    const group = groups[choice.provider_id] ?? {
      provider: choice.provider_id, label: choice.provider_name, options: [],
    };
    group.options.push(choice);
    groups[choice.provider_id] = group;
  }
  return Object.values(groups);
}

// 卡片里「移除」与表单保存用的是同一份连接内容，取值口径一致
function providerInputOf(provider: Catalog["providers"][number]): Record<string, unknown> {
  return {
    id: provider.id, name: provider.name, protocol: provider.protocol, base_url: provider.base_url,
    credential_ref: provider.credential_ref, timeout_sec: provider.timeout_sec,
    preset_id: provider.preset_id, models_url: provider.models_url,
  };
}

function rowInputOf(model: Catalog["models"][number]): Record<string, unknown> {
  return {
    id: model.id, model: model.model, context_window: model.context_window,
    max_output_tokens: model.max_output_tokens, capability_source: model.capability_source,
    accepts_required_tool_call: model.accepts_required_tool_call, input_modalities: model.input_modalities,
    reasoning_levels: model.reasoning_levels, default_reasoning_level: model.default_reasoning_level,
    reasoning_mode: model.reasoning_mode,
  };
}

// 候选事件里的每一项按第 4.3 节的字段读取：id 必须有，容量与来源可选
function isUpstreamCandidate(value: Record<string, unknown>): value is UpstreamCandidate {
  return typeof value.id === "string" && value.id.trim() !== "";
}
