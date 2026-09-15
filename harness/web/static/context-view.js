(() => {
  "use strict";

  const FEATURED = [
    { source: "department_rules", title: "Developer 指令" },
    { source: "department_history", title: "部门历史" },
    { source: "tool_schemas", title: "工具 schema" },
    { source: "current_contract", title: "合同摘要" },
  ];
  const MEMORY_MARKER = "[department_memory]";

  function parseMemory(content) {
    if (typeof content !== "string") return null;
    const at = content.indexOf(MEMORY_MARKER);
    const raw = (at >= 0 ? content.slice(at + MEMORY_MARKER.length) : content).trim();
    if (!raw) return null;
    try {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed;
    } catch {}
    return { summary: raw };
  }

  function summariesFromPart(part) {
    const result = [];
    const text = part && part.text;
    if (typeof text !== "string" || !text) return result;
    if (part.source === "department_history") {
      try {
        const history = JSON.parse(text);
        if (Array.isArray(history)) {
          history.forEach(item => {
            const content = item && item.content;
            if (typeof content === "string" && content.includes(MEMORY_MARKER)) {
              const parsed = parseMemory(content);
              if (parsed) result.push(parsed);
            }
          });
          return result;
        }
      } catch {}
    }
    if (text.includes(MEMORY_MARKER) || part.source === "department_memory") {
      const parsed = parseMemory(text);
      if (parsed) result.push(parsed);
    }
    return result;
  }

  function coverageRangeText(host, coverage, summary) {
    const { text } = host;
    const coveredId = coverage?.covered_through_event_id || summary?.covered_through_event_id;
    const from = coverage?.source_seq_from;
    const through = coverage?.source_seq_through ?? coverage?.covered_through_seq;
    const parts = [];
    if (typeof from === "number" && typeof through === "number") parts.push(`seq ${from}–${through}`);
    else if (typeof through === "number") parts.push(`seq ${through}`);
    else if (typeof from === "number") parts.push(`seq ${from}`);
    if (coveredId) parts.push(`covered_through ${coveredId}`);
    return parts.length ? `覆盖范围 ${parts.join(" · ")}` : "";
  }

  function coverageMarkup(host, detail, selectedPart) {
    const { escapeHtml, text } = host;
    const context = detail?.context || {};
    const coverage = context.coverage;
    const summaries = Array.isArray(context.summaries) && context.summaries.length
      ? context.summaries
      : summariesFromPart(selectedPart);
    if (!coverage && !summaries.length) return "";
    const range = coverageRangeText(host, coverage, summaries[0]);
    const compactionId = coverage?.compaction_event_id;
    const coveredId = coverage?.covered_through_event_id || summaries[0]?.covered_through_event_id;
    const summaryRows = summaries.map((item, index) => {
      const body = item.summary || item.text || "";
      const itemRange = coverageRangeText(host, coverage, item);
      return `<article class="dw-context-summary"><strong>摘要 ${index + 1}</strong>${itemRange ? `<span class="dw-coverage-range">${text(itemRange)}</span>` : ""}<p>${text(body, "摘要原文不可用")}</p>${coveredId ? `<button class="dw-observation-link" type="button" data-event-id="${escapeHtml(coveredId)}">查看原始事件</button>` : ""}</article>`;
    }).join("");
    return `<div class="dw-context-coverage">${range ? `<p class="dw-coverage-range">${text(range)}</p>` : ""}${compactionId ? `<button class="dw-observation-link" type="button" data-event-id="${escapeHtml(compactionId)}">打开摘要来源事件</button>` : ""}${summaryRows}</div>`;
  }

  function featuredMarkup(host, parts, selectedSource) {
    const { escapeHtml, text } = host;
    const list = Array.isArray(parts) ? parts : [];
    return `<div class="dw-context-featured" aria-label="本次实际输入">${FEATURED.map(item => {
      const part = list.find(entry => entry.source === item.source);
      const selected = selectedSource === item.source;
      const meta = !Array.isArray(parts) ? "读取中" : part ? (part.version == null ? "已注入" : `v${part.version}`) : "未包含";
      return `<button class="dw-context-part dw-context-featured-item ${selected ? "is-selected" : ""}" type="button" data-context-part-source="${escapeHtml(item.source)}" aria-pressed="${selected}"><strong>${text(item.title)}</strong><span>${text(meta)}</span></button>`;
    }).join("")}</div>`;
  }

  function render(host, department, data) {
    const {
      escapeHtml, text, formatTime, state, focusedRunId, contextDetailFor,
      attemptIdFromContext, contextSourceLabel,
    } = host;
    const contexts = Array.isArray(data?.contexts) ? data.contexts : [];
    const contextKey = `${focusedRunId()}/${department}`;
    const requestedId = state.selectedContext[contextKey];
    const selected = contexts.find(item => item.id === requestedId) || contexts.filter(item => item.purpose === "work").at(-1) || contexts.at(-1) || null;
    const selectedId = selected?.id || null;
    state.selectedContext[contextKey] = selectedId;
    const items = contexts.map(item => `<button class="dw-context-item ${item.id === selectedId ? "is-selected" : ""}" type="button" data-context-id="${escapeHtml(item.id)}" aria-pressed="${item.id === selectedId}"><strong>${text(item.title)}</strong><span>${text(item.meta || formatTime(item.snapshot_at))}</span></button>`).join("");
    const selectedAttempt = attemptIdFromContext(selected);
    const detail = contextDetailFor(selectedAttempt);
    const parts = detail?.context && Object.prototype.hasOwnProperty.call(detail.context, "parts") ? detail.context.parts : null;
    const partKey = `${focusedRunId()}/${selectedAttempt || "none"}`;
    const selectedSource = state.selectedContextPart[partKey];
    const featuredSelected = FEATURED.some(item => item.source === selectedSource);
    const selectedPart = Array.isArray(parts)
      ? (parts.find(item => item.source === selectedSource) || (featuredSelected ? null : parts[0]) || null)
      : null;
    if (selectedPart) state.selectedContextPart[partKey] = selectedPart.source;
    else if (featuredSelected) state.selectedContextPart[partKey] = selectedSource;
    const activeSource = selectedPart?.source || state.selectedContextPart[partKey];
    const partItems = Array.isArray(parts) ? parts.map(item => `<button class="dw-context-part ${item.source === selectedPart?.source ? "is-selected" : ""}" type="button" data-context-part-source="${escapeHtml(item.source)}"><strong>${text(contextSourceLabel(item.source))}</strong><span>${item.version == null ? "版本未知" : `v${escapeHtml(item.version)}`} · ${text(String(item.digest || "").slice(0, 12), "摘要未知")}</span></button>`).join("") : "";
    const sourceBody = !selectedAttempt ? "当前没有可查看的 Context 原文" : !detail ? "正在读取本次快照来源…" : detail.error ? `本次 Context 来源读取失败：${detail.error}` : !Array.isArray(parts) ? "本次 Context 来源未记录" : !selectedPart ? "本次 Context 没有可显示来源" : selectedPart.text;
    const observe = selectedAttempt ? `<button class="dw-observation-link" type="button" data-observe-attempt="${escapeHtml(selectedAttempt)}"><i data-lucide="activity" aria-hidden="true"></i>查看模型请求</button>` : `<span class="dw-observation-link is-disabled"><i data-lucide="circle-help" aria-hidden="true"></i>本次 Context 尚未发起模型请求</span>`;
    return `<div class="dw-inspect-panel" id="dw-panel-context" role="tabpanel" aria-labelledby="dw-tab-context"><h3>Context 快照</h3><div class="dw-context-snapshot-meta"><strong>本次工作输入</strong><time>快照时间 · ${text(formatTime(selected?.snapshot_at || data?.snapshot_at))}</time></div><div class="dw-context-list">${items || '<p class="dw-small">暂无 Context 快照</p>'}</div>${featuredMarkup(host, parts, activeSource)}<div class="dw-context-part-list" aria-label="本次快照来源">${partItems || (detail && Array.isArray(parts) ? '<p class="dw-small">本次 Context 没有来源条目</p>' : '<p class="dw-small">本次 Context 来源未记录</p>')}</div><div class="dw-context-body"><p>${text(sourceBody, "当前没有可查看的 Context 原文")}</p></div>${coverageMarkup(host, detail, selectedPart)}${observe}</div>`;
  }

  globalThis.YudaoContextView = { render, summariesFromPart, coverageRangeText, FEATURED };
})();
