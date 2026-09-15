(() => {
  "use strict";

  const DEPARTMENTS = [
    ["product", "产品"],
    ["engineering", "工程"],
    ["quality", "质检"],
  ];

  const emptyProvider = () => ({
    id: "", name: "", protocol: "responses", base_url: "", credential_ref: "", timeout_sec: 600,
  });
  const emptyModel = () => ({
    id: "", provider_id: "", model: "", context_window: "", max_output_tokens: "",
  });

  let root = null;
  let data = { providers: [], models: [], bindings: {} };
  let selectedProviderId = null;
  let selectedModelId = null;
  let providerForm = emptyProvider();
  let modelForm = emptyModel();
  let bindingForm = { product: "", engineering: "", quality: "" };
  let creatingProvider = true;
  let creatingModel = true;
  let message = "";
  let messageKind = "";
  let testing = false;

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
      id: item.id, name: item.name, protocol: item.protocol, base_url: item.base_url || "",
      credential_ref: item.credential_ref || "", timeout_sec: item.timeout_sec ?? 600,
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
      context_window: item.context_window ?? "", max_output_tokens: item.max_output_tokens ?? "",
    } : { ...emptyModel(), provider_id: providerId || "" };
  }

  function providerRows() {
    return (data.providers || []).map(item => {
      const ready = item.credential_configured !== false;
      const selected = item.id === selectedProviderId ? " is-selected" : "";
      return `<tr class="${selected}" data-provider-id="${escapeHtml(item.id)}"><td>${escapeHtml(item.name)}</td><td>${escapeHtml(item.protocol)}</td><td>${escapeHtml(item.base_url || "—")}</td><td>${escapeHtml(item.credential_ref || "—")}</td><td class="${ready ? "ok" : "bad"}">${ready ? "已配置" : "缺失"}</td></tr>`;
    }).join("") || `<tr><td colspan="5" class="yp-small">还没有 Provider</td></tr>`;
  }

  function modelRows() {
    const rows = allModels();
    return rows.map(item => {
      const selected = item.id === selectedModelId ? " is-selected" : "";
      return `<tr class="${selected}" data-model-id="${escapeHtml(item.id)}"><td>${escapeHtml(item.id)}</td><td>${escapeHtml(item.model)}</td><td>${escapeHtml(item.context_window ?? "—")}</td><td>${escapeHtml(item.max_output_tokens ?? "—")}</td></tr>`;
    }).join("") || `<tr><td colspan="4" class="yp-small">还没有模型</td></tr>`;
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
      const label = `${provider ? provider.name : model.provider_id} / ${model.id} · 窗口 ${model.context_window ?? "?"} · 输出 ${model.max_output_tokens ?? "?"}`;
      options.push(`<option value="${escapeHtml(value)}"${value === current ? " selected" : ""}>${escapeHtml(label)}</option>`);
    }
    return options.join("");
  }

  function markup() {
    const idReadonly = creatingProvider ? "" : " readonly";
    return `<div class="yp-provider-page">
      <div class="yp-heading"><div><div class="yp-eyebrow">系统目录</div><h1>模型与 Provider</h1><p class="yp-subtitle">保存后只影响新事项；密钥只存在环境变量里。</p></div>
        <div class="yp-heading-actions">
          <button class="yp-btn" type="button" data-pc-action="import">导入 JSON</button>
          <button class="yp-btn" type="button" data-pc-action="export">导出</button>
          <button class="yp-btn" type="button" data-action="home">返回项目列表</button>
          <input id="yp-provider-import" type="file" accept="application/json,.json" hidden>
        </div>
      </div>
      <p class="yp-provider-msg ${messageKind}" role="status"${message ? "" : " hidden"}>${escapeHtml(message)}</p>
      <section class="yp-section">
        <h2>Provider</h2>
        <div class="yp-provider-row">
          <div class="yp-provider-table-wrap"><table class="yp-provider-table"><thead><tr><th>名称</th><th>协议</th><th>地址</th><th>凭据引用</th><th>状态</th></tr></thead><tbody>${providerRows()}</tbody></table></div>
          <form class="yp-provider-form" data-pc-form="provider">
            <label>ID<input name="id" value="${escapeHtml(providerForm.id)}"${idReadonly} required></label>
            <label>名称<input name="name" value="${escapeHtml(providerForm.name)}" required></label>
            <label>协议<select name="protocol"><option value="responses"${providerForm.protocol === "responses" ? " selected" : ""}>responses</option><option value="fake"${providerForm.protocol === "fake" ? " selected" : ""}>fake（测试）</option></select></label>
            <label>地址<input name="base_url" value="${escapeHtml(providerForm.base_url)}" placeholder="https://..."></label>
            <label>凭据引用<input name="credential_ref" value="${escapeHtml(providerForm.credential_ref)}" placeholder="YUDAO_BACK_KEY"></label>
            <label>超时（秒）<input name="timeout_sec" type="number" min="1" value="${escapeHtml(providerForm.timeout_sec)}"></label>
            <p class="yp-small">测试会发一次最小请求，不创建事项。表单不保存密钥。</p>
            <div class="yp-heading-actions">
              <button class="yp-btn" type="button" data-pc-action="new-provider">新建</button>
              <button class="yp-btn primary" type="submit">保存</button>
              <button class="yp-btn" type="button" data-pc-action="test" ${testing ? "disabled" : ""}>${testing ? "测试中…" : "测试连接"}</button>
              <button class="yp-btn" type="button" data-pc-action="delete-provider" ${creatingProvider ? "disabled" : ""}>删除</button>
            </div>
          </form>
        </div>
      </section>
      <section class="yp-section">
        <h2>模型</h2>
        <div class="yp-provider-row">
          <div class="yp-provider-table-wrap"><table class="yp-provider-table"><thead><tr><th>ID</th><th>模型</th><th>窗口</th><th>输出上限</th></tr></thead><tbody>${modelRows()}</tbody></table></div>
          <form class="yp-provider-form" data-pc-form="model">
            <label>ID<input name="id" value="${escapeHtml(modelForm.id)}" required></label>
            <label>所属 Provider<select name="provider_id">${providerOptions()}</select></label>
            <label>模型名<input name="model" value="${escapeHtml(modelForm.model)}" required></label>
            <label>context_window<input name="context_window" type="number" min="1" value="${escapeHtml(modelForm.context_window)}" required></label>
            <label>max_output_tokens<input name="max_output_tokens" type="number" min="1" value="${escapeHtml(modelForm.max_output_tokens)}" required></label>
            <div class="yp-heading-actions">
              <button class="yp-btn" type="button" data-pc-action="new-model">新建模型</button>
              <button class="yp-btn primary" type="submit">保存模型</button>
            </div>
          </form>
        </div>
      </section>
      <section class="yp-section">
        <h2>三部门绑定</h2>
        <form class="yp-provider-form yp-provider-bindings" data-pc-form="bindings">
          ${DEPARTMENTS.map(([id, label]) => `<label>${label}<select name="${id}">${pairOptions(bindingForm[id])}</select></label>`).join("")}
          <p class="yp-small">缺任一部门时创建事项会指出该部门。在途事项仍用创建时的快照。</p>
          <div class="yp-heading-actions"><button class="yp-btn primary" type="submit">保存绑定</button></div>
        </form>
      </section>
    </div>`;
  }

  function bind() {
    if (!root) return;
    root.querySelectorAll("[data-provider-id]").forEach(row => {
      row.addEventListener("click", () => {
        selectProvider(row.dataset.providerId);
        render();
      });
    });
    root.querySelectorAll("[data-model-id]").forEach(row => {
      row.addEventListener("click", () => {
        const model = allModels().find(item => item.id === row.dataset.modelId);
        if (model) selectProvider(model.provider_id);
        selectModel(row.dataset.modelId);
        render();
      });
    });
    root.querySelector("[data-pc-form='provider']")?.addEventListener("submit", saveProvider);
    root.querySelector("[data-pc-form='model']")?.addEventListener("submit", saveModel);
    root.querySelector("[data-pc-form='bindings']")?.addEventListener("submit", saveBindings);
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

  async function saveProvider(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = formObject(form);
    const payload = {
      id: String(fields.id || "").trim(),
      name: String(fields.name || "").trim(),
      protocol: String(fields.protocol || "responses"),
      base_url: String(fields.base_url || "").trim(),
      credential_ref: String(fields.credential_ref || "").trim(),
      timeout_sec: Number(fields.timeout_sec),
    };
    if (payload.protocol === "fake") {
      payload.base_url = "";
      payload.credential_ref = "";
    }
    try {
      if (creatingProvider) {
        const currentModels = modelsOf(payload.id);
        if (currentModels.length) payload.models = currentModels;
        await fetchJSON("/api/providers", jsonHeaders(payload));
      } else {
        payload.models = modelsOf(payload.id);
        await fetchJSON(`/api/providers/${encodeURIComponent(payload.id)}`, { ...jsonHeaders(payload), method: "PUT" });
      }
      setMessage("Provider 已保存", "ok");
      await load();
      selectProvider(payload.id);
      render();
    } catch (error) {
      setMessage(error.message, "bad");
      render();
    }
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
    const model = {
      id: String(fields.id || "").trim(),
      provider_id: providerId,
      model: String(fields.model || "").trim(),
      context_window: Number(fields.context_window),
      max_output_tokens: Number(fields.max_output_tokens),
    };
    const models = modelsOf(providerId).filter(item => item.id !== selectedModelId || creatingModel);
    if (!creatingModel) {
      const rest = models.filter(item => item.id !== model.id);
      rest.push(model);
      models.length = 0;
      models.push(...rest);
    } else {
      models.push(model);
    }
    const provider = (data.providers || []).find(item => item.id === providerId);
    if (!provider) {
      setMessage("所属 Provider 不存在", "bad");
      render();
      return;
    }
    const payload = {
      id: provider.id, name: provider.name, protocol: provider.protocol,
      base_url: provider.base_url, credential_ref: provider.credential_ref,
      timeout_sec: provider.timeout_sec, models,
    };
    try {
      await fetchJSON(`/api/providers/${encodeURIComponent(providerId)}`, { ...jsonHeaders(payload), method: "PUT" });
      setMessage("模型已保存", "ok");
      await load();
      selectProvider(providerId);
      selectModel(model.id);
      render();
    } catch (error) {
      setMessage(error.message, "bad");
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
      setMessage("部门绑定已保存", "ok");
      await load();
      render();
    } catch (error) {
      setMessage(error.message, "bad");
      render();
    }
  }

  async function deleteProvider() {
    if (!selectedProviderId || creatingProvider) return;
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
    testing = true;
    render();
    try {
      const result = await fetchJSON(`/api/providers/${encodeURIComponent(selectedProviderId)}/test`, { method: "POST" });
      if (result.ok) setMessage(`连接成功 · ${result.actual_model || "未知模型"} · ${result.elapsed_ms} ms`, "ok");
      else setMessage(result.error || "连接失败", "bad");
    } catch (error) {
      setMessage(error.message, "bad");
    } finally {
      testing = false;
      render();
    }
  }

  function exportDocument() {
    return {
      providers: (data.providers || []).map(item => ({
        id: item.id, name: item.name, protocol: item.protocol, base_url: item.base_url,
        credential_ref: item.credential_ref, timeout_sec: item.timeout_sec,
      })),
      models: allModels().map(item => ({
        id: item.id, provider_id: item.provider_id, model: item.model,
        context_window: item.context_window, max_output_tokens: item.max_output_tokens,
      })),
      bindings: data.bindings || {},
    };
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
    if (!selectedProviderId || !(data.providers || []).some(item => item.id === selectedProviderId)) {
      selectProvider((data.providers || [])[0]?.id || null, { asNew: !(data.providers || []).length });
    } else {
      selectProvider(selectedProviderId);
    }
    syncBindingsFromData();
  }

  async function mount(node) {
    root = node;
    setMessage("");
    if (root) root.innerHTML = `<div class="yp-empty"><div class="dw-load-state">正在读取 Provider 目录…</div></div>`;
    try {
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
