(() => {
  "use strict";

  function optionMarkup(host, value, selected, label) {
    const { escapeHtml, text } = host;
    return `<option value="${escapeHtml(value)}" ${selected === value ? "selected" : ""}>${text(label)}</option>`;
  }

  function uniqueValues(items, keys) {
    const seen = new Set();
    (items || []).forEach(item => {
      keys.forEach(key => {
        const value = item && item[key];
        if (value !== null && value !== undefined && value !== "") seen.add(String(value));
      });
    });
    return [...seen].sort();
  }

  function filtersMarkup(host, filters, workOptions) {
    const { escapeHtml } = host;
    const items = host.state.observationData?.items || [];
    const groups = host.state.usageData?.groups || {};
    const providers = uniqueValues([
      ...items,
      ...(groups.models || []),
    ], ["requested_provider", "actual_provider", "provider"]);
    const requestedModels = uniqueValues(items, ["requested_model"]);
    const actualModels = uniqueValues(items, ["actual_model"]);
    if (filters.provider && filters.provider !== "all" && !providers.includes(filters.provider)) providers.unshift(filters.provider);
    if (filters.requested_model && filters.requested_model !== "all" && !requestedModels.includes(filters.requested_model)) requestedModels.unshift(filters.requested_model);
    if (filters.actual_model && filters.actual_model !== "all" && !actualModels.includes(filters.actual_model)) actualModels.unshift(filters.actual_model);
    return `<div class="dw-observation-filters"><label class="dw-filter-field"><span>事项</span><select class="dw-filter-select" data-obs-work-item aria-label="按事项筛选">${workOptions}</select></label><label class="dw-filter-field"><span>部门</span><select class="dw-filter-select" data-obs-department aria-label="按部门筛选">${optionMarkup(host, "all", filters.department, "全部部门")}${optionMarkup(host, "product", filters.department, "产品部")}${optionMarkup(host, "engineering", filters.department, "工程部")}${optionMarkup(host, "quality", filters.department, "质检部")}</select></label><label class="dw-filter-field"><span>状态</span><select class="dw-filter-select" data-obs-status aria-label="按状态筛选">${optionMarkup(host, "all", filters.status, "全部状态")}${optionMarkup(host, "success", filters.status, "成功")}${optionMarkup(host, "failed", filters.status, "失败")}${optionMarkup(host, "running", filters.status, "进行中")}${optionMarkup(host, "cancelled", filters.status, "取消")}</select></label><label class="dw-filter-field"><span>Provider</span><select class="dw-filter-select" data-obs-provider aria-label="按 Provider 筛选">${optionMarkup(host, "all", filters.provider, "全部 Provider")}${providers.map(value => optionMarkup(host, value, filters.provider, value)).join("")}</select></label><label class="dw-filter-field"><span>请求模型</span><select class="dw-filter-select" data-obs-requested-model aria-label="按请求模型筛选">${optionMarkup(host, "all", filters.requested_model, "全部请求模型")}${requestedModels.map(value => optionMarkup(host, value, filters.requested_model, value)).join("")}</select></label><label class="dw-filter-field"><span>实际模型</span><select class="dw-filter-select" data-obs-actual-model aria-label="按实际模型筛选">${optionMarkup(host, "all", filters.actual_model, "全部实际模型")}${actualModels.map(value => optionMarkup(host, value, filters.actual_model, value)).join("")}</select></label><label class="dw-filter-field dw-filter-search"><span>搜索</span><input class="dw-search-input" type="search" data-obs-search aria-label="搜索调用 ID、Provider 或模型" placeholder="调用 ID、Provider 或模型" value="${escapeHtml(filters.q)}"></label></div>`;
  }

  function attemptRowMarkup(host, item) {
    const { escapeHtml, text, number, formatTime, duration, usageValue, usageRawValue, departmentName, attemptRequestedText, attemptActualText, requestStateMarkup } = host;
    const logical = item.logical_call_id || "未知调用";
    const attemptText = `${number(item.attempt, "?")}/${number(item.attempt_count, "?")}`;
    const started = item.started_at || item.created_at;
    const elapsed = duration(item.duration_ms ?? usageRawValue(item, "latency_ms"), item.status);
    return `<button class="dw-request-row" type="button" data-obs-request="${escapeHtml(item.id)}" aria-label="查看 ${escapeHtml(logical)} 第 ${escapeHtml(item.attempt ?? "?")} 次尝试"><span class="dw-request-time">${text(formatTime(started))}${requestStateMarkup(item)}<span>尝试 ${escapeHtml(attemptText)} · ${text(elapsed)}</span></span><span class="dw-request-main"><strong>${text(departmentName(item.department))}</strong><span>请求：${text(attemptRequestedText(item))}</span><span>返回：${text(attemptActualText(item))} · ${text(item.provider_response_id)} · ${text(item.work_round)} · ${text(item.step)}</span></span><span class="dw-request-metrics"><span>Input <strong>${usageValue(item, "input_tokens")}</strong> · Output <strong>${usageValue(item, "output_tokens", "等待响应")}</strong></span><span>耗时 <strong>${duration(item.duration_ms ?? usageRawValue(item, "latency_ms"), item.status)}</strong></span></span></button>`;
  }

  function diagnosticsBits(item) {
    const diag = item?.diagnostics;
    if (!diag || typeof diag !== "object") return [];
    const bits = [];
    if (diag.error_type) bits.push(String(diag.error_type));
    if (diag.error_code) bits.push(String(diag.error_code));
    if (diag.status_code != null) bits.push(`HTTP ${diag.status_code}`);
    if (diag.finish_reason) bits.push(String(diag.finish_reason));
    return bits;
  }

  function unknownUsage(host, item, key) {
    const value = host.usageRawValue(item, key);
    if (typeof value === "number" && Number.isFinite(value)) return host.number(value);
    if (item?.status === "running" && item?.stage !== "prepared" && key === "output_tokens") return "等待响应";
    return "未知";
  }

  function detailHeaderExtras(host, detail) {
    const { text, formatTime, duration, attemptRequestedText, attemptActualText } = host;
    const item = detail?.attempt || {};
    const started = item.started_at || item.created_at;
    const elapsed = duration(item.duration_ms, item.status);
    const retry = `第 ${text(item.attempt, "?")}/${text(item.attempt_count, "?")} 次`;
    const errorClass = item.error_class || item.reason;
    const bits = diagnosticsBits(item);
    const failed = item.status === "failed" || item.status === "cancelled";
    const identity = `<span>请求 ${text(attemptRequestedText(item))}</span><span>返回 ${text(attemptActualText(item))}</span>`;
    const flags = [
      `<span>开始 ${text(formatTime(started))}</span>`,
      `<span>耗时 ${text(elapsed === "未上报" ? "未知" : elapsed)}</span>`,
      `<span>${retry}</span>`,
      identity,
      item.partial_output ? `<span class="dw-attempt-flag">部分输出${item.output_item_count ? ` · ${text(item.output_item_count)} 项` : ""}</span>` : "",
      failed ? `<span class="dw-attempt-error">错误分类 ${text(errorClass, "未知")}</span>` : "",
      failed && bits.length ? `<span class="dw-attempt-error">${text(bits.join(" · "))}</span>` : "",
      failed && item.error ? `<span class="dw-attempt-error">${text(item.error)}</span>` : "",
    ].filter(Boolean).join("");
    return `<div class="dw-attempt-diagnostics" aria-label="尝试诊断">${flags}</div>`;
  }

  function usageUnknown(host, item) {
    return {
      input: unknownUsage(host, item, "input_tokens"),
      output: unknownUsage(host, item, "output_tokens"),
      total: unknownUsage(host, item, "total_tokens"),
    };
  }

  globalThis.YudaoTraceView = {
    filtersMarkup,
    attemptRowMarkup,
    detailHeaderExtras,
    diagnosticsBits,
    usageUnknown,
  };
})();
