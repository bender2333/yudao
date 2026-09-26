(() => {
  "use strict";

  const DEPARTMENTS = [
    ["product", "产品"],
    ["engineering", "工程"],
    ["quality", "质检"],
  ];

  const PROTOCOLS = [
    ["responses", "responses"],
    ["chat_completions", "chat_completions"],
    ["messages", "messages"],
    ["fake", "fake（测试）"],
  ];

  // 端点按协议给出时的展示顺序，与 ADR-0001 的协议口径一致
  const PROTOCOL_ORDER = ["responses", "chat_completions", "messages"];

  const emptyProvider = () => ({
    id: "", name: "", base_url: "", credential_ref: "", timeout_sec: 600,
    preset_id: "", models_url: "",
  });
  const emptyModel = () => ({
    id: "", provider_id: "", model: "", protocol: "",
    context_window: "", max_output_tokens: "", capability_source: "",
  });

  let root = null;
  let data = { providers: [], models: [], bindings: {} };
  let presets = { table_version: "", presets: [] };
  let presetError = "";
  // 候选刷新结果只保存在本次页面会话内存，不落盘；unknown 时清空旧列表
  let candidateMap = new Map();
  let selectedProviderId = null;
  let selectedModelId = null;
  let providerForm = emptyProvider();
  let modelForm = emptyModel();
  let bindingForm = { product: "", engineering: "", quality: "" };
  let credentialForm = { ref: "", secret: "", persist: false };
  let creatingProvider = true;
  let creatingModel = true;
  let message = "";
  let messageKind = "";
  let testing = false;
  let testingModelId = "";
  let refreshingCandidates = false;
  let modelTestResult = null;
  let reloadNotice = null;
  let setupChoice = "";

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, char => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[char]));
  }

  async function fetchJSON(url, options = {}) {
    let response;
    try {
      response = await fetch(url, options);
    } catch (error) {
      const failure = new Error(error?.message || "网络请求失败");
      failure.status = 0;
      throw failure;
    }
    const raw = await response.text();
    let payload = {};
    if (raw) {
      try { payload = JSON.parse(raw); } catch {
        const failure = new Error("响应不是有效 JSON");
        failure.status = response.status;
        throw failure;
      }
    }
    if (!response.ok) {
      const failure = new Error(payload.error || response.statusText || "请求失败");
      failure.status = response.status;
      failure.payload = payload;
      throw failure;
    }
    return payload;
  }

  function jsonHeaders(body) {
    return { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  }

  function setMessage(text, kind = "") {
    message = text || "";
    messageKind = kind;
  }

  function selectedProvider() {
    return (data.providers || []).find(item => item.id === selectedProviderId) || null;
  }

  function modelsOf(providerId) {
    return (data.models || []).filter(item => item.provider_id === providerId);
  }

  function allModels() {
    if (Array.isArray(data.models) && data.models.length) return data.models;
    return (data.providers || []).flatMap(item => item.models || []);
  }

  function pairValue(providerId, modelId) {
    return providerId && modelId ? `${providerId}/${modelId}` : "";
  }

  function syncBindingsFromData() {
    const bindings = data.bindings || {};
    bindingForm = {
      product: pairValue(bindings.product?.provider_id, bindings.product?.model_id),
      engineering: pairValue(bindings.engineering?.provider_id, bindings.engineering?.model_id),
      quality: pairValue(bindings.quality?.provider_id, bindings.quality?.model_id),
    };
  }

  function selectProvider(id, { asNew = false } = {}) {
    selectedProviderId = id;
    creatingProvider = asNew || !id;
    const item = selectedProvider();
    providerForm = item ? {
      id: item.id, name: item.name, base_url: item.base_url || "",
      credential_ref: item.credential_ref || "", timeout_sec: item.timeout_sec ?? 600,
      preset_id: item.preset_id || "", models_url: item.models_url || "",
    } : emptyProvider();
    const models = modelsOf(id);
    if (models.length) selectModel(models[0].id);
    else selectModel(null, { asNew: true, providerId: id });
  }

  function selectModel(id, { asNew = false, providerId = selectedProviderId } = {}) {
    selectedModelId = id;
    creatingModel = asNew || !id;
    const item = allModels().find(model => model.id === id) || null;
    modelForm = item ? {
      id: item.id, provider_id: item.provider_id, model: item.model,
      protocol: item.protocol || "",
      context_window: item.context_window ?? "", max_output_tokens: item.max_output_tokens ?? "",
      capability_source: item.capability_source || "",
    } : { ...emptyModel(), provider_id: providerId || "" };
  }

  function credentialSourceLabel(source) {
    return {
      override: "进程内存", env: "宿主进程环境", dotenv: "凭据文件 .yudao/.env",
      none: "无", missing: "缺失",
    }[source] || String(source || "?");
  }

  function credentialLabel(item) {
    const credential = item.credential || {};
    if (!item.credential_ref) return "无需凭据";
    if (credential.configured === false) return "缺失";
    const source = credential.source || "?";
    const sourceLabel = { override: "临时 Key", env: "环境", dotenv: "文件", none: "无" }[source] || source;
    return `已配置 · ${sourceLabel}`;
  }

  // —— 服务方案预置表 ——

  function presetById(presetId) {
    return (presets.presets || []).find(item => item.id === presetId) || null;
  }

  function primaryBaseUrl(preset) {
    // 连接地址是请求基址，请求路径由各协议适配器拼接
    const baseUrls = preset.base_urls || {};
    for (const protocol of PROTOCOL_ORDER) {
      if (baseUrls[protocol]) return baseUrls[protocol];
    }
    return Object.values(baseUrls)[0] || "";
  }

  function defaultCredentialRef(presetId) {
    const base = String(presetId || "").replace(/[^A-Za-z0-9]+/g, "_").toUpperCase();
    return `${base.replace(/^_+|_+$/g, "")}_KEY`;
  }

  function applyPresetToForm(presetId) {
    const preset = presetById(presetId);
    if (!preset) {
      providerForm.preset_id = "";
      return;
    }
    // 选择方案只预填表单，不自动保存任何配置或任务绑定
    providerForm.preset_id = preset.id;
    providerForm.name = preset.name || providerForm.name;
    providerForm.base_url = primaryBaseUrl(preset);
    providerForm.models_url = preset.models_url || "";
    if (preset.auth === "api_key") providerForm.credential_ref = defaultCredentialRef(preset.id);
  }

  async function loadPresets() {
    try {
      presets = await fetchJSON("/api/provider-presets");
    } catch (error) {
      presets = { table_version: "", presets: [] };
      presetError = error.message;
    }
  }

  function presetOptions() {
    const options = [`<option value=""${!providerForm.preset_id ? " selected" : ""}>自定义（手动填写）</option>`];
    for (const preset of presets.presets || []) {
      const selected = providerForm.preset_id === preset.id ? " selected" : "";
      options.push(`<option value="${escapeHtml(preset.id)}"${selected}>${escapeHtml(preset.name)}</option>`);
    }
    return options.join("");
  }

  function presetDetailsMarkup() {
    const preset = presetById(providerForm.preset_id);
    if (!preset) return "";
    const baseUrls = PROTOCOL_ORDER
      .filter(protocol => (preset.base_urls || {})[protocol])
      .map(protocol => `<div class="yp-endpoint-line"><span>${escapeHtml(protocol)}</span><code>${escapeHtml(preset.base_urls[protocol])}</code></div>`)
      .join("");
    return `<div class="yp-preset-panel" data-preset-panel>
      <strong>${escapeHtml(preset.name)}</strong>
      ${preset.notes ? `<p class="yp-small">${escapeHtml(preset.notes)}</p>` : ""}
      ${baseUrls ? `<div class="yp-small">请求基址（按协议）</div>${baseUrls}` : ""}
      <p class="yp-small">模型列表地址 ${escapeHtml(preset.models_url || "—")}</p>
      ${preset.docs_url ? `<a class="yp-link" href="${escapeHtml(preset.docs_url)}" target="_blank" rel="noreferrer">官方文档与 Key 获取</a>` : ""}
      <p class="yp-small">来源 ${escapeHtml(preset.source || "—")} · 预置表版本 ${escapeHtml(presets.table_version || "—")}</p>
    </div>`;
  }

  function presetCardsMarkup() {
    const list = presets.presets || [];
    if (!list.length) {
      return presetError ? "" : '<p class="yp-small" data-preset-empty>预置表为空，可直接使用自定义连接。</p>';
    }
    return list.map(preset => `<div class="yp-preset-card" data-preset-card="${escapeHtml(preset.id)}">
      <strong>${escapeHtml(preset.name)}</strong>
      ${preset.notes ? `<p class="yp-small">${escapeHtml(preset.notes)}</p>` : ""}
      <p class="yp-small">认证 ${escapeHtml(preset.auth === "api_key" ? "API Key" : String(preset.auth || "—"))} · 来源 ${escapeHtml(preset.source || "—")}</p>
      ${preset.docs_url ? `<a class="yp-link" href="${escapeHtml(preset.docs_url)}" target="_blank" rel="noreferrer">官方文档</a>` : ""}
      <div class="yp-heading-actions"><button class="yp-btn" type="button" data-pc-action="choose-preset" data-preset-id="${escapeHtml(preset.id)}">选择</button></div>
    </div>`).join("");
  }

  // —— 准入状态 ——

  function catalogRevision() {
    // 准入跟随目录修订（Provider 与模型定义），部门绑定变化不使模型测试失效
    const value = data.catalog_revision ?? data.revision;
    return value === null || value === undefined || value === "" ? null : Number(value);
  }

  function admissionState(model) {
    const admittedRevision = model.admitted_revision;
    if (admittedRevision === null || admittedRevision === undefined || admittedRevision === "") {
      return { key: "unadmitted", label: "未准入" };
    }
    const current = catalogRevision();
    if (current !== null && !Number.isNaN(current) && Number(admittedRevision) !== current) {
      return { key: "stale", label: "测试结果不对应当前修订" };
    }
    return { key: "admitted", label: "已准入" };
  }

  function applyAdmission(providerId, modelId, result) {
    // 模型测试在服务端记录准入；本地同步徽章与修订，避免整页重拉覆盖正在编辑的表单
    if (result.revision === null || result.revision === undefined) return;
    const model = allModels().find(item => item.provider_id === providerId && item.id === modelId);
    if (model) {
      model.admitted_revision = result.revision;
      model.admitted_model = result.actual_model || model.model;
    }
    data.catalog_revision = result.revision;
  }

  // —— 就绪状态条：配置、凭据、准入、额度分开呈现，不合并成一个绿点 ——

  function readinessGap(item) {
    const credential = item.credential || {};
    if ((item.credential_ref || "") && credential.configured === false) return "credential";
    if (!modelsOf(item.id).length) return "model";
    const bindings = data.bindings || {};
    const bound = Object.values(bindings).some(b => b && b.provider_id === item.id);
    if (!bound) return "binding";
    return null;
  }

  function jumpTargetField(kind) {
    if (kind === "credential") {
      return (providerForm.credential_ref || "") ? "credential-secret" : "provider-credential-ref";
    }
    if (kind === "model") return "model-id";
    return "binding-product";
  }

  function statusStripMarkup() {
    if (creatingProvider || !selectedProviderId) return "";
    const item = selectedProvider();
    if (!item) return "";
    const chips = [];
    const gap = readinessGap(item);
    if (gap) {
      const gapLabel = { credential: "缺凭据", model: "缺模型", binding: "缺部门绑定" }[gap];
      chips.push(`<button class="yp-chip bad" type="button" data-pc-jump="${jumpTargetField(gap)}">配置：已保存但未就绪 · ${gapLabel}（点击跳到对应字段）</button>`);
    } else {
      const models = modelsOf(item.id);
      const admitted = models.filter(model => admissionState(model).key === "admitted").length;
      if (!models.length) {
        chips.push('<span class="yp-chip warn">配置：就绪但未测试</span>');
      } else if (admitted) {
        chips.push(`<span class="yp-chip ok">配置：就绪 · ${admitted}/${models.length} 模型已准入</span>`);
      } else {
        chips.push('<span class="yp-chip warn">配置：就绪但未测试（不宣称远端已通）</span>');
      }
    }
    const credential = item.credential || {};
    if (!item.credential_ref) {
      chips.push('<span class="yp-chip">凭据：无需凭据</span>');
    } else if (credential.configured === false) {
      chips.push('<span class="yp-chip bad">凭据：缺失</span>');
    } else if (credential.source === "override") {
      chips.push('<span class="yp-chip warn">凭据：临时 Key · 本进程有效，重启后需重新提供</span>');
    } else {
      chips.push(`<span class="yp-chip ok">凭据：已配置 · 来源 ${escapeHtml(credentialSourceLabel(credential.source))}</span>`);
    }
    const models = modelsOf(item.id);
    if (models.length) {
      const admitted = models.filter(model => admissionState(model).key === "admitted").length;
      const stale = models.filter(model => admissionState(model).key === "stale").length;
      const label = admitted
        ? `准入：${admitted}/${models.length} 已准入${stale ? ` · ${stale} 测试结果不对应当前修订` : ""}`
        : "准入：候选未准入 · 建访问定义、测试后再绑定";
      chips.push(`<span class="yp-chip ${admitted ? "ok" : "warn"}">${label}</span>`);
    }
    const preset = presetById(item.preset_id);
    const consoleLink = preset?.docs_url
      ? ` <a class="yp-link" href="${escapeHtml(preset.docs_url)}" target="_blank" rel="noreferrer">官方控制台/文档</a>`
      : "";
    chips.push(`<span class="yp-chip">额度：未知（不显示零，也不以此判断可用性）${consoleLink}</span>`);
    return `<div class="yp-status-strip" data-status-strip>${chips.join("")}</div>`;
  }

  // —— 候选模型 ——

  function candidateSectionMarkup() {
    if (creatingProvider || !selectedProviderId) return "";
    const state = candidateMap.get(selectedProviderId);
    if (!state) return "";
    if (state.status !== "ok") {
      return `<section class="yp-section" data-candidates="unknown"><h2>候选模型</h2>
        <div class="yp-notice bad" role="alert"><p>候选未知：${escapeHtml(state.error || "上游模型列表不可用")}（采集时间 ${escapeHtml(state.fetched_at || "—")}）。上游不可用时不沿用上一次列表。</p></div>
        <p class="yp-small">候选不落盘、不自动绑定；请稍后重新刷新候选模型。</p>
      </section>`;
    }
    const rows = (state.candidates || []).map(candidate => {
      const protocolCell = candidate.protocol
        ? escapeHtml(candidate.protocol)
        : '<span class="warn">需选择协议</span>';
      return `<tr data-candidate-id="${escapeHtml(candidate.id)}"><td data-label="模型 ID" title="${escapeHtml(candidate.id)}">${escapeHtml(candidate.id)}</td><td data-label="建议协议">${protocolCell}</td><td data-label="能力来源">${escapeHtml(candidate.capability_source || "—")}</td><td data-label="操作"><button class="yp-btn" type="button" data-pc-action="admit-candidate" data-candidate-id="${escapeHtml(candidate.id)}">建立访问定义</button></td></tr>`;
    }).join("") || '<tr><td colspan="4" class="yp-small">上游返回空列表</td></tr>';
    return `<section class="yp-section" data-candidates="ok"><h2>候选模型</h2>
      <p class="yp-small">来源 ${escapeHtml(state.source_url || "—")} · 采集时间 ${escapeHtml(state.fetched_at || "—")} · 候选不落盘、不自动绑定，需建访问定义并测试准入。</p>
      <div class="yp-provider-table-wrap"><table class="yp-provider-table yp-candidate-table"><thead><tr><th>模型 ID</th><th>建议协议</th><th>能力来源</th><th>操作</th></tr></thead><tbody>${rows}</tbody></table></div>
    </section>`;
  }

  function admitCandidate(candidateId) {
    const state = candidateMap.get(selectedProviderId);
    const candidate = (state?.candidates || []).find(item => item.id === candidateId);
    if (!candidate) return;
    syncFormsFromDom();
    // 建立访问定义只预填表单：协议缺建议时必须手动选择，容量字段不造默认值
    selectedModelId = null;
    creatingModel = true;
    modelForm = {
      id: candidate.id, provider_id: selectedProviderId, model: candidate.id,
      protocol: candidate.protocol || "",
      context_window: "", max_output_tokens: "",
      capability_source: candidate.capability_source || "",
    };
    setMessage(`已填入候选 ${candidate.id}：选择协议、按需填写容量后保存，再执行模型测试`, "");
    render();
  }

  async function refreshCandidates() {
    if (!selectedProviderId || creatingProvider) {
      setMessage("请先保存 Provider 再刷新候选", "bad");
      render();
      return;
    }
    syncFormsFromDom();
    const override = String(providerForm.models_url || "").trim();
    refreshingCandidates = true;
    render();
    try {
      const result = await fetchJSON(
        `/api/providers/${encodeURIComponent(selectedProviderId)}/candidates`,
        jsonHeaders(override ? { models_url: override } : {}),
      );
      candidateMap.set(selectedProviderId, {
        status: result.status === "ok" ? "ok" : "unknown",
        source_url: result.source_url || "",
        fetched_at: result.fetched_at || "",
        candidates: Array.isArray(result.candidates) ? result.candidates : [],
        error: result.error || "",
      });
      if (result.status === "ok") {
        setMessage(`已刷新候选 · ${(result.candidates || []).length} 个`, "ok");
      } else {
        setMessage(`候选未知：${result.error || "上游模型列表不可用"}`, "bad");
      }
    } catch (error) {
      // 拉取失败时同样不沿用旧列表
      candidateMap.set(selectedProviderId, {
        status: "unknown", source_url: "", fetched_at: "",
        candidates: [], error: error.message,
      });
      setMessage(`候选未知：${error.message}`, "bad");
    } finally {
      refreshingCandidates = false;
      render();
    }
  }

  // —— 表格与选项 ——

  function providerRows() {
    return (data.providers || []).map(item => {
      const ready = item.credential_configured !== false;
      const selected = item.id === selectedProviderId ? " is-selected" : "";
      const selectedState = item.id === selectedProviderId ? "true" : "false";
      const modelCount = (item.models || []).length;
      return `<tr class="${selected}" data-provider-id="${escapeHtml(item.id)}" tabindex="0" role="button" aria-selected="${selectedState}" aria-label="选择 Provider ${escapeHtml(item.name)}"><td data-label="名称">${escapeHtml(item.name)}</td><td data-label="模型数">${modelCount}</td><td data-label="地址" title="${escapeHtml(item.base_url || "—")}">${escapeHtml(item.base_url || "—")}</td><td data-label="凭据引用" title="${escapeHtml(item.credential_ref || "—")}">${escapeHtml(item.credential_ref || "—")}</td><td data-label="状态" class="${ready ? "ok" : "bad"}">${escapeHtml(credentialLabel(item))}</td></tr>`;
    }).join("") || `<tr><td colspan="5" class="yp-small">还没有 Provider</td></tr>`;
  }

  function modelRows() {
    const rows = allModels();
    return rows.map(item => {
      const selected = item.id === selectedModelId ? " is-selected" : "";
      const selectedState = item.id === selectedModelId ? "true" : "false";
      const admission = admissionState(item);
      const testingThis = testingModelId === item.id;
      // 任一测试进行中时禁用全部测试按钮，避免并发测试互相覆盖结果
      const testDisabled = testing || testingModelId ? " disabled" : "";
      return `<tr class="${selected}" data-model-id="${escapeHtml(item.id)}" tabindex="0" role="button" aria-selected="${selectedState}" aria-label="选择模型 ${escapeHtml(item.model)}"><td data-label="ID" title="${escapeHtml(item.id)}">${escapeHtml(item.id)}</td><td data-label="模型" title="${escapeHtml(item.model)}">${escapeHtml(item.model)}</td><td data-label="协议">${escapeHtml(item.protocol || "—")}</td><td data-label="窗口">${escapeHtml(item.context_window ?? "—")}</td><td data-label="输出上限">${escapeHtml(item.max_output_tokens ?? "—")}</td><td data-label="准入与测试"><span class="admission ${admission.key}">${escapeHtml(admission.label)}</span> <button class="yp-btn" type="button" data-pc-action="test-model" data-test-model="${escapeHtml(item.id)}"${testDisabled}>${testingThis ? "测试中…" : "测试模型"}</button></td></tr>`;
    }).join("") || `<tr><td colspan="6" class="yp-small">还没有模型</td></tr>`;
  }

  function credentialOptions() {
    const options = (data.providers || [])
      .filter(item => item.credential_ref)
      .map(item => {
        const selected = item.credential_ref === credentialForm.ref ? " selected" : "";
        return `<option value="${escapeHtml(item.credential_ref)}"${selected}>${escapeHtml(item.credential_ref)}（${escapeHtml(credentialLabel(item))}）</option>`;
      }).join("");
    return options || '<option value="">暂无凭据引用（先保存 Provider）</option>';
  }

  function providerOptions() {
    return (data.providers || []).map(item => {
      const selected = item.id === (modelForm.provider_id || selectedProviderId) ? " selected" : "";
      return `<option value="${escapeHtml(item.id)}"${selected}>${escapeHtml(item.id)} · ${escapeHtml(item.name)}</option>`;
    }).join("");
  }

  function pairOptions(current) {
    const options = ['<option value="">未绑定</option>'];
    for (const model of allModels()) {
      const provider = (data.providers || []).find(item => item.id === model.provider_id);
      const value = pairValue(model.provider_id, model.id);
      const base = `${provider ? provider.name : model.provider_id} / ${model.id} · 窗口 ${model.context_window ?? "?"} · 输出 ${model.max_output_tokens ?? "?"}`;
      const admission = admissionState(model);
      // 未准入或测试结果陈旧时在下拉中标注原因并禁止选择；已准入模型不带原因、可直接选择
      const suffix = admission.key === "admitted"
        ? ""
        : admission.key === "stale"
          ? " · 测试结果不对应当前修订，需重新测试"
          : " · 未准入，需先通过模型测试";
      const selectedAttr = value === current ? " selected" : "";
      const disabledAttr = admission.key === "admitted" ? "" : " disabled";
      options.push(`<option value="${escapeHtml(value)}"${selectedAttr}${disabledAttr}>${escapeHtml(base + suffix)}</option>`);
    }
    return options.join("");
  }

  // —— 表单与区块 ——

  function providerFormMarkup({ setup = false } = {}) {
    const idReadonly = creatingProvider ? "" : " readonly";
    return `<form class="yp-provider-form" data-pc-form="provider">
      <label>服务方案<select name="preset_id" data-pc-field="preset-select">${presetOptions()}</select></label>
      ${presetDetailsMarkup()}
      <label>ID<input name="id" value="${escapeHtml(providerForm.id)}"${idReadonly} required></label>
      <label>名称<input name="name" value="${escapeHtml(providerForm.name)}" required></label>
      <label>地址<input name="base_url" value="${escapeHtml(providerForm.base_url)}" placeholder="https://..."></label>
      <label>凭据引用<input name="credential_ref" value="${escapeHtml(providerForm.credential_ref)}" placeholder="YUDAO_BACK_KEY" data-pc-field="provider-credential-ref"></label>
      <label>模型列表地址（可覆写）<input name="models_url" value="${escapeHtml(providerForm.models_url)}" placeholder="留空使用服务方案默认"></label>
      <label>超时（秒）<input name="timeout_sec" type="number" min="1" value="${escapeHtml(providerForm.timeout_sec)}"></label>
      <p class="yp-small">协议在每个模型上声明。测试连接只检查地址与凭据，不创建事项。表单不保存密钥。</p>
      <div class="yp-heading-actions">
        ${setup ? '<button class="yp-btn" type="button" data-pc-action="back-setup">返回选择</button>' : '<button class="yp-btn" type="button" data-pc-action="new-provider">新建</button>'}
        <button class="yp-btn primary" type="submit">保存</button>
        ${setup ? "" : `<button class="yp-btn" type="button" data-pc-action="test" ${testing || testingModelId ? "disabled" : ""}>${testing ? "测试中…" : "测试连接"}</button>
        <button class="yp-btn" type="button" data-pc-action="refresh-candidates" ${refreshingCandidates || creatingProvider ? "disabled" : ""}>${refreshingCandidates ? "候选刷新中…" : "刷新候选模型"}</button>
        <button class="yp-btn" type="button" data-pc-action="delete-provider" ${creatingProvider ? "disabled" : ""}>删除</button>`}
      </div>
    </form>`;
  }

  function modelFormMarkup() {
    const protocolOptions = [`<option value=""${modelForm.protocol ? "" : " selected"}>需选择协议</option>`]
      .concat(PROTOCOLS.map(([value, label]) =>
        `<option value="${value}"${modelForm.protocol === value ? " selected" : ""}>${label}</option>`))
      .join("");
    const admissionInfo = creatingModel ? "" : (() => {
      const item = allModels().find(model => model.id === selectedModelId);
      if (!item) return "";
      const admission = admissionState(item);
      if (admission.key === "admitted") {
        return `<p class="yp-small">上次测试：实际返回 ${escapeHtml(item.admitted_model || item.model)} · 修订 ${escapeHtml(String(item.admitted_revision ?? "—"))} · 已准入</p>`;
      }
      if (admission.key === "stale") {
        return `<p class="yp-small warn">上次测试修订 ${escapeHtml(String(item.admitted_revision ?? "—"))} 不对应当前目录修订 ${escapeHtml(String(catalogRevision() ?? "—"))}，需重新测试后才能绑定。</p>`;
      }
      return '<p class="yp-small warn">尚未通过模型测试，未准入的模型不能绑定到部门。</p>';
    })();
    return `<form class="yp-provider-form" data-pc-form="model">
      <label>ID<input name="id" value="${escapeHtml(modelForm.id)}" required data-pc-field="model-id"></label>
      <label>所属 Provider<select name="provider_id">${providerOptions()}</select></label>
      <label>模型名<input name="model" value="${escapeHtml(modelForm.model)}" required></label>
      <label>协议<select name="protocol">${protocolOptions}</select></label>
      <label>context_window<input name="context_window" type="number" min="1" value="${escapeHtml(modelForm.context_window)}" required></label>
      <label>max_output_tokens<input name="max_output_tokens" type="number" min="1" value="${escapeHtml(modelForm.max_output_tokens)}" required></label>
      <label>能力来源<input name="capability_source" value="${escapeHtml(modelForm.capability_source)}" readonly placeholder="预置提示或手动填写来源"></label>
      ${admissionInfo}
      <div class="yp-heading-actions">
        <button class="yp-btn" type="button" data-pc-action="new-model">新建模型</button>
        <button class="yp-btn primary" type="submit">保存模型</button>
      </div>
    </form>`;
  }

  function credentialSectionMarkup({ emptySetup = false } = {}) {
    const refControl = emptySetup
      ? `<label>凭据引用（来自表单）<input name="ref" value="${escapeHtml(providerForm.credential_ref)}" readonly></label>`
      : `<label>凭据引用<select name="ref" data-pc-field="credential-ref">${credentialOptions()}</select></label>`;
    return `<section class="yp-section" data-credential-section>
      <h2>凭据</h2>
      <form class="yp-provider-form" data-pc-form="credential">
        ${refControl}
        <label>Key<input name="secret" type="password" autocomplete="new-password" placeholder="仅本次输入，不回填" data-pc-field="credential-secret"></label>
        <p class="yp-small">本进程有效，重启后需重新提供；勾选后才写入 .yudao/.env。已保存的 Key 永不回填。</p>
        <label><input name="persist" type="checkbox"${credentialForm.persist ? " checked" : ""}> 持久化到 .yudao/.env</label>
        ${credentialStatusMarkup(emptySetup ? (credentialForm.ref || providerForm.credential_ref) : credentialForm.ref)}
        <p class="yp-small">清除内存覆盖与删除持久凭据是两个动作，操作后显示实际生效来源。</p>
        <div class="yp-heading-actions">
          <button class="yp-btn primary" type="submit">保存 Key</button>
          <button class="yp-btn" type="button" data-pc-action="clear-credential">清除内存覆盖</button>
          <button class="yp-btn" type="button" data-pc-action="remove-credential">删除持久凭据</button>
        </div>
      </form>
    </section>`;
  }

  function credentialStatusMarkup(ref) {
    if (!ref) return '<p class="yp-small" data-credential-status>选择凭据引用后显示实际生效来源与覆盖关系。</p>';
    const provider = (data.providers || []).find(item => (item.credential_ref || "") === ref);
    const credential = provider?.credential || null;
    if (!credential) return `<p class="yp-small" data-credential-status>凭据引用 ${escapeHtml(ref)} 尚未随 Provider 保存，来源未知。</p>`;
    if (credential.configured === false) {
      return `<p class="yp-small bad" data-credential-status>凭据引用 ${escapeHtml(ref)}：缺失，请填写 Key。</p>`;
    }
    if (credential.source === "override") {
      return `<p class="yp-small" data-credential-status>凭据引用 ${escapeHtml(ref)}：临时 Key，来源为进程内存，本进程有效，重启后需重新提供；内存覆盖当前生效（优先于宿主环境与 .yudao/.env）。</p>`;
    }
    return `<p class="yp-small" data-credential-status>凭据引用 ${escapeHtml(ref)}：已配置，来源 ${escapeHtml(credentialSourceLabel(credential.source))}；无内存覆盖。</p>`;
  }

  function bindingsSectionMarkup() {
    return `<section class="yp-section">
      <h2>三部门绑定</h2>
      <form class="yp-provider-form yp-provider-bindings" data-pc-form="bindings">
        ${DEPARTMENTS.map(([id, label], index) => `<label>${label}<select name="${id}"${index === 0 ? ' data-pc-field="binding-product"' : ""}>${pairOptions(bindingForm[id])}</select></label>`).join("")}
        <p class="yp-small">未准入的模型不能绑定到部门，下拉列表中已标注原因。缺任一部门时创建事项会指出该部门。在途事项仍用创建时的快照。</p>
        <div class="yp-heading-actions"><button class="yp-btn primary" type="submit">保存绑定</button></div>
      </form>
    </section>`;
  }

  function modelTestMarkup() {
    if (testingModelId) {
      return `<div class="yp-test-progress" data-test-progress>正在对 ${escapeHtml(testingModelId)} 执行真实最小推理，结果会记录实际返回模型与配置修订…</div>`;
    }
    if (!modelTestResult) return "";
    const result = modelTestResult;
    if (result.ok) {
      return `<div class="yp-test-result ok" data-test-result="ok">模型测试通过 · ${escapeHtml(result.model_id)} · 实际返回 ${escapeHtml(result.actual_model || "未知")} · 协议 ${escapeHtml(result.protocol || "—")} · 修订 ${escapeHtml(String(result.revision ?? "—"))} · 耗时 ${escapeHtml(String(result.elapsed_ms ?? "—"))} ms · ${result.admitted ? "已准入" : "未准入"}</div>${result.admitted ? "" : '<p class="yp-small">未准入的模型不能绑定到部门。</p>'}`;
    }
    return `<div class="yp-test-result bad" data-test-result="bad">模型测试失败 · ${escapeHtml(result.model_id)} · ${escapeHtml(result.error || "未知原因")}</div><p class="yp-small">已填写的非敏感字段保留在表单中，可按原因修正后重试。</p>`;
  }

  function reloadNoticeMarkup() {
    if (!reloadNotice || !reloadNotice.reload_error) return "";
    return `<div class="yp-notice bad" role="alert" data-reload-notice><p>文件更新未生效：${escapeHtml(reloadNotice.reload_error)}；当前仍用修订 ${escapeHtml(String(reloadNotice.revision ?? "—"))}。修复文件后重新读取。</p></div>`;
  }

  function setupSectionMarkup() {
    if (!setupChoice) {
      return `<section class="yp-section" data-setup="paths">
        <h2>添加模型服务</h2>
        <p class="yp-small">还没有 Provider。选择服务方案或自定义连接；此处操作不会自动保存任何任务绑定，未配置不影响浏览历史。</p>
        <div class="yp-setup-paths">
          <div class="yp-setup-path">
            <h3>选择服务方案</h3>
            ${presetError
              ? `<p class="yp-small bad" data-preset-error>服务方案列表读取失败：${escapeHtml(presetError)}；可先使用自定义连接。</p>`
              : `<p class="yp-small">预置表版本 ${escapeHtml(presets.table_version || "—")}；选择后预填请求基址、模型列表地址与凭据引用默认值。</p>`}
            ${presetCardsMarkup()}
          </div>
          <div class="yp-setup-path">
            <h3>自定义连接</h3>
            <p class="yp-small">手动填写地址与凭据引用，可覆写模型列表地址；协议在每个模型访问定义上声明。</p>
            <div class="yp-heading-actions"><button class="yp-btn" type="button" data-pc-action="choose-custom">自定义连接</button></div>
          </div>
        </div>
      </section>`;
    }
    return `<section class="yp-section" data-setup="form">
      <h2>添加模型服务</h2>
      <p class="yp-small">保存第一份 Provider 后进入候选刷新、访问定义与部门绑定。</p>
      <div class="yp-setup-form-wrap">${providerFormMarkup({ setup: true })}</div>
    </section>`;
  }

  function markup() {
    const heading = `<div class="yp-heading"><div><div class="yp-eyebrow">系统目录</div><h1>模型与 Provider</h1><p class="yp-subtitle">保存后只影响新事项，在途事项沿用创建时快照。页面 Key 默认只进内存，勾选才落盘。</p></div>
        <div class="yp-heading-actions">
          <button class="yp-btn" type="button" data-pc-action="reload">重新读取</button>
          <button class="yp-btn" type="button" data-pc-action="import">导入 JSON</button>
          <button class="yp-btn" type="button" data-pc-action="export">导出</button>
          <button class="yp-btn" type="button" data-action="home">返回项目列表</button>
          <input id="yp-provider-import" type="file" accept="application/json,.json" hidden aria-label="导入 Provider 目录 JSON 文件">
        </div>
      </div>
      <p class="yp-provider-msg ${messageKind}" role="status"${message ? "" : " hidden"}>${escapeHtml(message)}</p>
      ${reloadNoticeMarkup()}`;
    const isEmpty = !(data.providers || []).length;
    if (isEmpty) {
      return `<div class="yp-provider-page">
        ${heading}
        ${setupSectionMarkup()}
        ${setupChoice ? credentialSectionMarkup({ emptySetup: true }) : ""}
        ${bindingsSectionMarkup()}
      </div>`;
    }
    return `<div class="yp-provider-page">
      ${heading}
      <section class="yp-section">
        <h2>Provider</h2>
        ${statusStripMarkup()}
        <div class="yp-provider-row">
          <div class="yp-provider-table-wrap"><table class="yp-provider-table"><thead><tr><th>名称</th><th>模型数</th><th>地址</th><th>凭据引用</th><th>状态</th></tr></thead><tbody>${providerRows()}</tbody></table></div>
          ${providerFormMarkup()}
        </div>
      </section>
      ${candidateSectionMarkup()}
      <section class="yp-section">
        <h2>模型</h2>
        ${modelTestMarkup()}
        <div class="yp-provider-row">
          <div class="yp-provider-table-wrap"><table class="yp-provider-table yp-model-table"><thead><tr><th>ID</th><th>模型</th><th>协议</th><th>窗口</th><th>输出上限</th><th>准入与测试</th></tr></thead><tbody>${modelRows()}</tbody></table></div>
          ${modelFormMarkup()}
        </div>
      </section>
      ${credentialSectionMarkup()}
      ${bindingsSectionMarkup()}
    </div>`;
  }

  function bind() {
    if (!root) return;
    root.querySelectorAll("[data-provider-id]").forEach(row => {
      const choose = () => {
        selectProvider(row.dataset.providerId);
        render();
      };
      row.addEventListener("click", event => {
        // 行内按钮的点击不触发整行选择
        if (event.target && event.target !== row && typeof event.target.closest === "function" && event.target.closest("button")) return;
        choose();
      });
      row.addEventListener("keydown", event => {
        if (event.target && event.target !== row) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          choose();
        }
      });
    });
    root.querySelectorAll("[data-model-id]").forEach(row => {
      const choose = () => {
        const model = allModels().find(item => item.id === row.dataset.modelId);
        if (model) selectProvider(model.provider_id);
        selectModel(row.dataset.modelId);
        render();
      };
      row.addEventListener("click", event => {
        if (event.target && event.target !== row && typeof event.target.closest === "function" && event.target.closest("button")) return;
        choose();
      });
      row.addEventListener("keydown", event => {
        if (event.target && event.target !== row) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          choose();
        }
      });
    });
    root.querySelector("[data-pc-form='provider']")?.addEventListener("submit", saveProvider);
    root.querySelector("[data-pc-form='model']")?.addEventListener("submit", saveModel);
    root.querySelector("[data-pc-form='bindings']")?.addEventListener("submit", saveBindings);
    root.querySelector("[data-pc-form='credential']")?.addEventListener("submit", saveCredential);
    root.querySelector("[data-pc-field='preset-select']")?.addEventListener("change", event => {
      syncFormsFromDom();
      applyPresetToForm(String(event.target.value || ""));
      render();
    });
    root.querySelectorAll("[data-pc-action='choose-preset']").forEach(button => {
      button.addEventListener("click", () => {
        applyPresetToForm(button.dataset.presetId);
        setupChoice = "preset";
        render();
      });
    });
    root.querySelector("[data-pc-action='choose-custom']")?.addEventListener("click", () => {
      providerForm = emptyProvider();
      setupChoice = "custom";
      render();
    });
    root.querySelector("[data-pc-action='back-setup']")?.addEventListener("click", () => {
      setupChoice = "";
      providerForm = emptyProvider();
      render();
    });
    root.querySelectorAll("[data-pc-jump]").forEach(chip => {
      chip.addEventListener("click", () => {
        const field = chip.dataset.pcJump;
        root.querySelector(`[data-pc-field='${field}']`)?.focus();
      });
    });
    root.querySelector("[data-pc-action='refresh-candidates']")?.addEventListener("click", refreshCandidates);
    root.querySelectorAll("[data-pc-action='test-model']").forEach(button => {
      button.addEventListener("click", event => {
        event.stopPropagation();
        return testModel(button.dataset.testModel);
      });
    });
    root.querySelectorAll("[data-pc-action='admit-candidate']").forEach(button => {
      button.addEventListener("click", () => admitCandidate(button.dataset.candidateId));
    });
    root.querySelector("[data-pc-field='credential-ref']")?.addEventListener("change", () => {
      // 切换凭据引用时先保留勾选状态，再刷新实际生效来源与覆盖关系说明
      syncFormsFromDom();
      render();
    });
    root.querySelector("[data-pc-action='clear-credential']")?.addEventListener("click", clearCredential);
    root.querySelector("[data-pc-action='remove-credential']")?.addEventListener("click", removeCredential);
    root.querySelector("[data-pc-action='reload']")?.addEventListener("click", reloadFromDisk);
    root.querySelector("[data-pc-action='new-provider']")?.addEventListener("click", () => {
      selectProvider(null, { asNew: true });
      render();
    });
    root.querySelector("[data-pc-action='new-model']")?.addEventListener("click", () => {
      selectModel(null, { asNew: true });
      render();
    });
    root.querySelector("[data-pc-action='test']")?.addEventListener("click", testConnection);
    root.querySelector("[data-pc-action='delete-provider']")?.addEventListener("click", deleteProvider);
    root.querySelector("[data-pc-action='export']")?.addEventListener("click", exportCatalog);
    root.querySelector("[data-pc-action='import']")?.addEventListener("click", () => {
      root.querySelector("#yp-provider-import")?.click();
    });
    root.querySelector("#yp-provider-import")?.addEventListener("change", importCatalog);
  }

  function formObject(form) {
    return Object.fromEntries(new FormData(form).entries());
  }

  function modelDocument(model) {
    // 提交目录时只带文档字段；admitted_* 是服务端记录的视图字段，不随表单回传
    return {
      id: model.id, provider_id: model.provider_id, model: model.model,
      protocol: model.protocol, context_window: model.context_window,
      max_output_tokens: model.max_output_tokens, capability_source: model.capability_source || "",
    };
  }

  function syncFormsFromDom() {
    // 重新渲染前读取表单当前值，避免丢失用户已填的非敏感字段；secret 不进入状态、不回填
    const providerNode = root?.querySelector("[data-pc-form='provider']");
    if (providerNode) {
      const fields = formObject(providerNode);
      providerForm = {
        id: String(fields.id ?? ""),
        name: String(fields.name ?? ""),
        base_url: String(fields.base_url ?? ""),
        credential_ref: String(fields.credential_ref ?? ""),
        timeout_sec: String(fields.timeout_sec ?? "600"),
        preset_id: String(fields.preset_id ?? ""),
        models_url: String(fields.models_url ?? ""),
      };
    }
    const modelNode = root?.querySelector("[data-pc-form='model']");
    if (modelNode) {
      const fields = formObject(modelNode);
      modelForm = {
        id: String(fields.id ?? ""),
        provider_id: String(fields.provider_id ?? ""),
        model: String(fields.model ?? ""),
        protocol: String(fields.protocol ?? ""),
        context_window: String(fields.context_window ?? ""),
        max_output_tokens: String(fields.max_output_tokens ?? ""),
        capability_source: String(fields.capability_source ?? ""),
      };
    }
    const credentialNode = root?.querySelector("[data-pc-form='credential']");
    if (credentialNode) {
      const fields = formObject(credentialNode);
      credentialForm = { ref: String(fields.ref ?? ""), secret: "", persist: fields.persist === "on" };
    }
  }

  async function saveProvider(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = formObject(form);
    const payload = {
      id: String(fields.id || "").trim(),
      name: String(fields.name || "").trim(),
      base_url: String(fields.base_url || "").trim(),
      credential_ref: String(fields.credential_ref || "").trim(),
      timeout_sec: Number(fields.timeout_sec),
      preset_id: String(fields.preset_id || "").trim(),
      models_url: String(fields.models_url || "").trim(),
    };
    try {
      if (creatingProvider) {
        const currentModels = modelsOf(payload.id);
        if (currentModels.length) payload.models = currentModels.map(modelDocument);
        await fetchJSON("/api/providers", jsonHeaders(payload));
      } else {
        payload.models = modelsOf(payload.id).map(modelDocument);
        await fetchJSON(`/api/providers/${encodeURIComponent(payload.id)}`, { ...jsonHeaders(payload), method: "PUT" });
      }
      setMessage("Provider 已保存", "ok");
      setupChoice = "";
      await load();
      selectProvider(payload.id);
      render();
    } catch (error) {
      setMessage(error.message, "bad");
      render();
    }
  }

  function describeError(error) {
    const issues = error && error.payload && error.payload.issues;
    if (Array.isArray(issues) && issues.length) {
      return issues.map(item => {
        if (item && item.location) return `${item.location}: ${item.message || ""}`;
        return String((item && item.message) || item);
      }).join("；");
    }
    return (error && error.message) || "保存失败";
  }

  function moveModelDocument(model, sourceId, targetId, oldId) {
    const document = exportDocument();
    document.models = document.models.filter(item => item.id !== oldId);
    document.models.push(model);
    for (const key of Object.keys(document.bindings || {})) {
      const binding = document.bindings[key];
      if (binding && binding.provider_id === sourceId && binding.model_id === oldId) {
        document.bindings[key] = { provider_id: targetId, model_id: model.id };
      }
    }
    return document;
  }

  async function saveModel(event) {
    event.preventDefault();
    const fields = formObject(event.currentTarget);
    const providerId = String(fields.provider_id || selectedProviderId || "").trim();
    if (!providerId) {
      setMessage("请先选择 Provider", "bad");
      render();
      return;
    }
    if (!String(fields.protocol || "").trim()) {
      setMessage("需选择协议：候选未给出建议协议时必须手动选择一条", "bad");
      render();
      return;
    }
    const model = {
      id: String(fields.id || "").trim(),
      provider_id: providerId,
      model: String(fields.model || "").trim(),
      protocol: String(fields.protocol || "").trim(),
      context_window: Number(fields.context_window),
      max_output_tokens: Number(fields.max_output_tokens),
      capability_source: String(fields.capability_source || "").trim(),
    };
    const provider = (data.providers || []).find(item => item.id === providerId);
    if (!provider) {
      setMessage("所属 Provider 不存在", "bad");
      render();
      return;
    }
    const sourceModel = creatingModel
      ? null
      : allModels().find(item => item.id === selectedModelId) || null;
    const sourceId = sourceModel ? sourceModel.provider_id : null;
    if (sourceId && sourceId !== providerId) {
      // 移动语义：整份目录一次提交，原子地换归属并让引用旧归属的绑定跟随，
      // 旧 Provider 下不残留同 id 条目，也不会留下中间态的重复 id 或悬空绑定。
      try {
        await fetchJSON("/api/providers", jsonHeaders(moveModelDocument(model, sourceId, providerId, selectedModelId)));
        setMessage("模型已保存", "ok");
        await load();
        selectProvider(providerId);
        selectModel(model.id);
        render();
      } catch (error) {
        setMessage(describeError(error), "bad");
        render();
      }
      return;
    }
    const models = modelsOf(providerId)
      .filter(item => item.id !== selectedModelId || creatingModel)
      .map(modelDocument);
    if (!creatingModel) {
      const rest = models.filter(item => item.id !== model.id);
      rest.push(model);
      models.length = 0;
      models.push(...rest);
    } else {
      models.push(model);
    }
    const payload = {
      id: provider.id, name: provider.name,
      base_url: provider.base_url, credential_ref: provider.credential_ref,
      timeout_sec: provider.timeout_sec, models,
      preset_id: provider.preset_id || "", models_url: provider.models_url || "",
    };
    try {
      await fetchJSON(`/api/providers/${encodeURIComponent(providerId)}`, { ...jsonHeaders(payload), method: "PUT" });
      setMessage("模型已保存", "ok");
      await load();
      selectProvider(providerId);
      selectModel(model.id);
      render();
    } catch (error) {
      setMessage(describeError(error), "bad");
      render();
    }
  }

  async function saveBindings(event) {
    event.preventDefault();
    const fields = formObject(event.currentTarget);
    const bindings = {};
    for (const [department] of DEPARTMENTS) {
      const value = String(fields[department] || "");
      if (!value) continue;
      const [providerId, modelId] = value.split("/");
      bindings[department] = { provider_id: providerId, model_id: modelId };
    }
    try {
      await fetchJSON("/api/department-bindings", { ...jsonHeaders(bindings), method: "PUT" });
      setMessage("部门绑定已保存：新任务将使用此配置，已有任务保持原配置", "ok");
      await load();
      render();
    } catch (error) {
      setMessage(error.message, "bad");
      render();
    }
  }

  async function deleteProvider() {
    if (!selectedProviderId || creatingProvider) return;
    const provider = selectedProvider();
    const name = provider?.name || selectedProviderId;
    if (typeof globalThis.confirm === "function" && !globalThis.confirm(`删除 Provider“${name}”？模型和部门绑定也会受到影响。`)) return;
    try {
      const response = await fetch(`/api/providers/${encodeURIComponent(selectedProviderId)}`, { method: "DELETE" });
      const raw = await response.text();
      const payload = raw ? JSON.parse(raw) : {};
      if (!response.ok) throw new Error(payload.error || "删除失败");
      setMessage("Provider 已删除", "ok");
      await load();
      render();
    } catch (error) {
      setMessage(error.message, "bad");
      render();
    }
  }

  async function testConnection() {
    if (!selectedProviderId || creatingProvider) {
      setMessage("请先保存 Provider 再测试", "bad");
      render();
      return;
    }
    syncFormsFromDom();
    testing = true;
    render();
    try {
      const result = await fetchJSON(`/api/providers/${encodeURIComponent(selectedProviderId)}/test`, jsonHeaders({ kind: "connection" }));
      if (result.ok) setMessage(`连接成功 · ${result.actual_model || "未知模型"} · ${result.elapsed_ms} ms · 修订 ${result.revision ?? "—"}`, "ok");
      else setMessage(result.error || "连接失败", "bad");
    } catch (error) {
      setMessage(error.message, "bad");
    } finally {
      testing = false;
      render();
    }
  }

  async function testModel(modelId) {
    const model = allModels().find(item => item.id === modelId);
    if (!model) return;
    const providerId = model.provider_id;
    syncFormsFromDom();
    testingModelId = modelId;
    modelTestResult = null;
    render();
    try {
      const result = await fetchJSON(
        `/api/providers/${encodeURIComponent(providerId)}/test`,
        jsonHeaders({ model_id: modelId, kind: "model" }),
      );
      modelTestResult = { ...result, model_id: modelId };
      if (result.ok && result.admitted) {
        applyAdmission(providerId, modelId, result);
        setMessage(`模型测试通过 · ${modelId}`, "ok");
      } else if (result.ok) {
        setMessage(`模型测试完成但未记录准入 · ${modelId}`, "bad");
      } else {
        setMessage(`模型测试失败 · ${modelId}`, "bad");
      }
    } catch (error) {
      modelTestResult = {
        ok: false, error: error.message, model_id: modelId,
        actual_model: null, elapsed_ms: null, revision: null, admitted: false, protocol: null,
      };
      setMessage(`模型测试失败 · ${modelId}：${error.message}`, "bad");
    } finally {
      testingModelId = "";
      render();
    }
  }

  function exportDocument() {
    return {
      providers: (data.providers || []).map(item => ({
        id: item.id, name: item.name, base_url: item.base_url,
        credential_ref: item.credential_ref, timeout_sec: item.timeout_sec,
        preset_id: item.preset_id || "", models_url: item.models_url || "",
      })),
      models: allModels().map(item => ({
        id: item.id, provider_id: item.provider_id, model: item.model,
        protocol: item.protocol, context_window: item.context_window,
        max_output_tokens: item.max_output_tokens, capability_source: item.capability_source || "",
      })),
      bindings: data.bindings || {},
    };
  }

  function credentialFields() {
    const form = root?.querySelector("[data-pc-form='credential']");
    if (!form) return { ref: credentialForm.ref, secret: "", persist: credentialForm.persist };
    const fields = formObject(form);
    return {
      ref: String(fields.ref || "").trim(),
      secret: String(fields.secret || ""),
      persist: fields.persist === "on",
    };
  }

  async function saveCredential(event) {
    event.preventDefault();
    const fields = credentialFields();
    if (!fields.ref) {
      setMessage("请先选择凭据引用", "bad");
      render();
      return;
    }
    if (!fields.secret) {
      setMessage("请输入 Key，清除请用清除内存覆盖", "bad");
      render();
      return;
    }
    try {
      const result = await fetchJSON("/api/provider-credentials", jsonHeaders({
        ref: fields.ref, action: "set", secret: fields.secret, persist: fields.persist,
      }));
      credentialForm = { ref: fields.ref, secret: "", persist: fields.persist };
      const credential = result.credential || {};
      // set 之后内存覆盖立即生效，持久化只影响重启后的来源恢复
      const source = credential.source || "override";
      const text = fields.persist
        ? `Key 已保存并持久化到 .yudao/.env；当前生效来源 ${credentialSourceLabel(source)}，重启后按 内存 > 宿主环境 > .env 优先级恢复`
        : `Key 已保存：来源为进程内存，本进程有效，重启后需重新提供`;
      setMessage(text, "ok");
      await load();
      render();
    } catch (error) {
      setMessage(error.message, "bad");
      render();
    }
  }

  async function clearCredential() {
    const fields = credentialFields();
    if (!fields.ref) {
      setMessage("请先选择凭据引用", "bad");
      render();
      return;
    }
    try {
      const result = await fetchJSON("/api/provider-credentials", jsonHeaders({
        ref: fields.ref, action: "clear_override",
      }));
      const credential = result.credential || {};
      setMessage(credential.configured
        ? `已清除内存覆盖，当前来源 ${credentialSourceLabel(credential.source)}`
        : "已清除内存覆盖，当前无可用凭据", "ok");
      await load();
      render();
    } catch (error) {
      setMessage(error.message, "bad");
      render();
    }
  }

  async function removeCredential() {
    const fields = credentialFields();
    if (!fields.ref) {
      setMessage("请先选择凭据引用", "bad");
      render();
      return;
    }
    try {
      const result = await fetchJSON("/api/provider-credentials", jsonHeaders({
        ref: fields.ref, action: "remove_persisted",
      }));
      const credential = result.credential || {};
      setMessage(credential.configured
        ? `文件值已删除，当前来源 ${credentialSourceLabel(credential.source)}`
        : "文件值已删除，当前无可用凭据", "ok");
      await load();
      render();
    } catch (error) {
      setMessage(error.message, "bad");
      render();
    }
  }

  async function reloadFromDisk() {
    try {
      const result = await fetchJSON("/api/providers/reload", { method: "POST" });
      if (result.reload_error) {
        reloadNotice = { revision: result.revision, reload_error: result.reload_error };
        setMessage(`重新读取失败，当前仍用修订 ${result.revision ?? "—"}`, "bad");
      } else {
        reloadNotice = null;
        setMessage(`已重读本地配置，生效修订 ${result.revision}`, "ok");
      }
      await load();
      render();
    } catch (error) {
      setMessage(error.message, "bad");
      render();
    }
  }

  function exportCatalog() {
    const blob = new Blob([JSON.stringify(exportDocument(), null, 2)], { type: "application/json" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "providers.json";
    link.click();
    URL.revokeObjectURL(link.href);
  }

  async function importCatalog(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try {
      const text = await file.text();
      const document = JSON.parse(text);
      await fetchJSON("/api/providers", jsonHeaders(document));
      setMessage("目录已导入", "ok");
      await load();
      render();
    } catch (error) {
      setMessage(error.message || "导入失败，已保留原目录", "bad");
      render();
    }
  }

  function render() {
    if (!root) return;
    root.innerHTML = markup();
    bind();
    if (globalThis.lucide && typeof globalThis.lucide.createIcons === "function") {
      globalThis.lucide.createIcons({ attrs: { width: 16, height: 16 } });
    }
  }

  async function load() {
    data = await fetchJSON("/api/providers");
    data.models = allModels();
    // 目录视图若携带重载错误，则持续展示“文件更新未生效”；无错误时清除会话内提示
    if (data && typeof data.reload_error === "string" && data.reload_error) {
      reloadNotice = { revision: data.revision, reload_error: data.reload_error };
    } else if (data && data.reload_error === null) {
      reloadNotice = null;
    }
    if (!selectedProviderId || !(data.providers || []).some(item => item.id === selectedProviderId)) {
      selectProvider((data.providers || [])[0]?.id || null, { asNew: !(data.providers || []).length });
    } else {
      selectProvider(selectedProviderId);
    }
    if (!credentialForm.ref) {
      // 凭据区默认聚焦第一个可用引用，状态行随之显示实际来源
      credentialForm = {
        ...credentialForm,
        ref: (data.providers || []).find(item => item.credential_ref)?.credential_ref || "",
      };
    }
    syncBindingsFromData();
  }

  async function mount(node) {
    root = node;
    setMessage("");
    // 候选与测试结果是页面会话状态：每次打开重新拉取，不沿用上次结果
    candidateMap = new Map();
    modelTestResult = null;
    reloadNotice = null;
    setupChoice = "";
    presetError = "";
    if (root) root.innerHTML = `<div class="yp-empty"><div class="dw-load-state">正在读取 Provider 目录…</div></div>`;
    try {
      await loadPresets();
      await load();
      render();
    } catch (error) {
      if (root) root.innerHTML = `<div class="yp-empty"><div class="dw-load-state error">${escapeHtml(error.message)}</div></div>`;
    }
  }

  function unmount() {
    root = null;
  }

  globalThis.harnessProviderConfig = { mount, unmount, reload: load };
})();
