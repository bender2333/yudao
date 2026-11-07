// 模型管理页（工单 #1297；模型管理 docs/design/model-management.md「模型管理页」，原型 docs/prototypes/v14）。
// 页面按「连接服务 → 搜索筛选候选 → 勾选模型即补全参数并验证 → 部门使用」的单页流程组织。
// 页面只读写服务端交付的命令与查询：连接与取候选用 catalog.connect 与 catalog.candidates.collect，
// 选用用 catalog.model.select，取消选用用 catalog.model.remove，部门使用用 catalog.department_defaults.save，
// 高级部分用 catalog.document.save 与 catalog.reload。
// 客户端不预填参数、不判断准入：协议、窗口、输出上限与准入都按服务端的值显示（工单正文第 1 条）。
// 反馈的位置：每个操作的进度、成功与失败写在被操作的对象旁边（连接卡片、模型的那一行、部门使用的那一项）。

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CommandOutcome } from "../../contract/invoke";
import { newCommandId } from "../../contract/command-id.ts";
import { commandProblemText } from "../../contract/command-problem.ts";
import { readFailureText } from "../../contract/read-failure.ts";
import type { ViewSync } from "../../contract/view-sync";
import type { Catalog, CatalogDocument, EventObject } from "../../api/generated/types.gen";
import { JsonDialog, type EditableDocument } from "./json-dialog";
import { Advanced, type ConnectionDraft, type ModelDraft } from "./advanced";
import { CandidateList, type CandidateStatus } from "./candidate-list";
import { ConnectCard, type ConnectStatus, type ConnectTarget } from "./connect-card";
import { DepartmentUsage, type DepartmentStatus } from "./department-usage";
import { SelectionPanel, type SelectionStatus } from "./selection-panel";
import { Block, PageHead } from "../../shell/kit";
import {
  FIRST_PAGE,
  admittedModels,
  candidateKey,
  candidatePageAfter,
  candidatePageView,
  candidateRowsOf,
  candidatesLocked,
  capacityInputIssue,
  collectingProvider,
  departmentBindings,
  departmentTierBindings,
  departmentsOf,
  fetchNoteText,
  filterCandidates,
  groupAdmittedModels,
  intFromInput,
  modelInputOf,
  removalRejectionText,
  selectedModelRows,
  type BindingInput,
  type CandidateFilterId,
  type CandidateRow,
  type PendingFetch,
} from "./model-logic";

export type ModelManagementPageProps = {
  views: ViewSync | null;
  query: <T>(name: string, params: Record<string, unknown> | undefined) => Promise<{ position: number; data: T }>;
  command: (name: string, body: Record<string, unknown>) => Promise<CommandOutcome>;
  subscribeEvents: (listener: (event: EventObject) => void) => () => void;
  onBack: () => void;
};

// 一次保存部门默认要写的三项

export function ModelManagementPage(props: ModelManagementPageProps) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [document, setDocument] = useState<CatalogDocument | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [documentError, setDocumentError] = useState<string | null>(null);
  const [target, setTarget] = useState<ConnectTarget | null>(null);
  const [address, setAddress] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [busy, setBusy] = useState(false);
  // 已经发出去、结果还没回来的那次获取模型列表（工单 #1355）：
  // 服务端在后台取，结果以后以新的一份目录出现；页面据此说明正在取，但不因此停住操作
  const [pendingFetch, setPendingFetch] = useState<PendingFetch | null>(null);
  const [connectStatus, setConnectStatus] = useState<Record<string, ConnectStatus>>({});
  const [candidateStatus, setCandidateStatus] = useState<Record<string, CandidateStatus>>({});
  const [selectionStatus, setSelectionStatus] = useState<Record<string, SelectionStatus>>({});
  const [departmentStatus, setDepartmentStatus] = useState<Record<string, DepartmentStatus>>({});
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<CandidateFilterId>("auto");
  // 候选分页（工单 #1585）：每页最多 8 个；取消选用使最后一页消失时显示取合法页
  const [page, setPage] = useState(FIRST_PAGE);
  const [capacity, setCapacity] = useState<Record<string, { context_window: string; max_output_tokens: string }>>({});
  const [manualOpen, setManualOpen] = useState(false);
  const [manualModel, setManualModel] = useState("");
  const [manualProvider, setManualProvider] = useState("");
  const [tests, setTests] = useState<Record<string, { elapsed_ms: number; actual_model: string | null }>>({});
  const [jsonOpen, setJsonOpen] = useState(false);
  // 页面级提示：只用于整页的事（目录文件的重新读取）
  const [pageNotice, setPageNotice] = useState<{ kind: "ok" | "error"; message: string } | null>(null);

  const catalogRef = useRef<Catalog | null>(null);
  const views = props.views;
  // 还没有任何连接时表单直接展开：第一次连接不用先点「添加服务」
  const formOpened = useRef(false);

  useEffect(() => {
    if (catalog === null || formOpened.current) {
      return;
    }
    formOpened.current = true;
    if (catalog.providers.length === 0) {
      setTarget({ mode: "new" });
    }
  }, [catalog]);

  useEffect(() => {
    if (!views) {
      return;
    }
    void views.open<Catalog>("models.catalog", { query: "catalog", params: undefined }, (data) => {
      catalogRef.current = data;
      setCatalogError(null);
      setCatalog(data);
    }, (reason) => {
      setCatalogError(reason);
    });
    void views.open<CatalogDocument>("models.document", { query: "catalog.document", params: undefined }, (data) => {
      setDocumentError(null);
      setDocument(data);
    }, (reason) => {
      setDocumentError(reason);
    });
    return () => {
      views.close("models.catalog");
      views.close("models.document");
    };
  }, [views]);

  // 事件：模型测试的结果在事件里（工单 #1355 之前「获取模型列表」的结果也靠这里复位，
  // 但那条事件不是一定会到：服务端在连接已变化或任务异常时会提前结束而不写事件）。
  // 订阅用 ref 拿进来，页面每次重画都重新订阅的话，事件可能在退订与重订之间丢掉
  const subscribeRef = useRef(props.subscribeEvents);
  subscribeRef.current = props.subscribeEvents;
  // 这次获取到哪一份连接上（事件里认这一份）：结果到了就结束「正在获取」的说明
  const pendingRef = useRef<PendingFetch | null>(null);
  pendingRef.current = pendingFetch;
  useEffect(() => {
    return subscribeRef.current((event) => {
      if (event.type === "catalog_candidates_collected") {
        if (pendingRef.current !== null && event.payload.provider_id === pendingRef.current.provider_id) {
          setPendingFetch(null);
        }
        return;
      }
      if (event.type === "catalog_test_finished" && event.payload.kind === "model"
          && event.payload.model_id !== null) {
        const payload = event.payload;
        setTests((current) => ({
          ...current,
          [payload.model_id as string]: {
            elapsed_ms: payload.elapsed_ms,
            actual_model: payload.actual_model,
          },
        }));
      }
    });
  }, []);

  // 提交一个命令：结果交回接受或按原因拒绝；接受以后重新读取目录，下一条命令用刷新后的修订号。
  // 命令在途时页面上的操作先停住：部门默认是整份保存的，两次改动叠在一起会被服务端按版本过期拒绝。
  // busy 只罩住命令本身（工单 #1355）：重新读取目录是另一次请求，它挂住时不该让整页一直停着
  const submit = useCallback(async (name: string, body: Record<string, unknown>): Promise<CommandOutcome> => {
    setBusy(true);
    let outcome: CommandOutcome;
    try {
      outcome = await props.command(name, {
        command_id: newCommandId(),
        base_version: catalogRef.current?.revision ?? 0,
        ...body,
      });
    } finally {
      setBusy(false);
    }
    if (outcome.ok) {
      await props.views?.refresh("models.catalog");
    }
    return outcome;
  }, [props]);

  // 发起这次获取之前，各份连接最近一次结果的样子：命令回来以后据此判断结果是否已经变了
  const resultBefore = useCallback((): Map<string, { fetched_at: string | null; status: string | null }> => new Map(
    (catalogRef.current?.providers ?? []).map((provider) => [
      provider.id,
      provider.latest_candidates
        ? { fetched_at: provider.latest_candidates.fetched_at, status: provider.latest_candidates.status }
        : { fetched_at: null, status: null },
    ]),
  ), []);

  // 候选：各连接最近一次取到的模型，按连接汇总
  const candidateRows = useMemo<CandidateRow[]>(
    () => (catalog === null ? [] : candidateRowsOf(catalog)),
    [catalog],
  );

  // 正在取候选的那一份连接（工单 #1355）：目录里这一份的结果时间没变就还在取，
  // 变了（成功写新的时间，失败写空串）就结束，页面上的说明随之消失
  const collecting = useMemo(() => collectingProvider(catalog, pendingFetch), [catalog, pendingFetch]);
  useEffect(() => {
    if (pendingFetch !== null && collecting === null) {
      setPendingFetch(null);
    }
  }, [collecting, pendingFetch]);
  // 候选区只在页面自己发出的命令在途时暂停：服务端在后台取候选时页面照常可以操作
  const locked = candidatesLocked({ busy, connecting });

  // 用户刚勾选的候选：勾选以后服务端要往返一次才建好访问定义，
  // 勾选框先按本地这份显示（命令被拒绝时再撤回）
  const [picked, setPicked] = useState<Record<string, boolean>>({});

  // 已经选用的模型：目录里有访问定义就是选用了
  const selectedKeys = useMemo(() => {
    const keys = new Set<string>();
    for (const model of catalog?.models ?? []) {
      keys.add(candidateKey(model.provider_id, model.model));
    }
    for (const [key, value] of Object.entries(picked)) {
      if (value) {
        keys.add(key);
      }
    }
    return keys;
  }, [catalog, picked]);

  const filteredRows = useMemo(
    () => filterCandidates(candidateRows, search, filter, selectedKeys),
    [candidateRows, search, filter, selectedKeys],
  );
  // 这一页的候选、当前页与页数：页面存的页可能因为列表变短而越界，显示时取合法页
  const pageView = useMemo(() => candidatePageView(filteredRows, page), [filteredRows, page]);

  // 已选模型清单：目录里的定义加上它此刻的状态
  const selectedRows = useMemo(
    () => (catalog === null ? [] : selectedModelRows({
      providers: catalog.providers,
      models: catalog.models,
      admissions: catalog.admissions,
      selections: catalog.selections,
    })),
    [catalog],
  );

  // 部门默认涉及的部门：这一版加载的定义里的部门（catalog 查询的 departments，工单 #1457），
  // 目录里已有绑定的部门也算；显示名同样取查询给的
  const departmentViews = useMemo(() => catalog?.departments ?? [], [catalog]);
  const departments = useMemo(
    () => departmentsOf(catalog?.bindings, departmentViews.map((department) => department.id)),
    [catalog, departmentViews],
  );
  const departmentLabels = useMemo(
    () => Object.fromEntries(departmentViews.map((department) => [department.id, department.label])),
    [departmentViews],
  );

  // 部门使用的选项：已启用的模型，按连接分组
  const departmentGroups = useMemo(
    () => (catalog === null ? [] : groupAdmittedModels(
      admittedModels(catalog.models, catalog.providers, catalog.admissions),
      catalog.providers,
    )),
    [catalog],
  );

  // —— 连接服务 ——

  const connect = useCallback(async () => {
    const current = catalogRef.current;
    const editing = target?.mode === "edit" ? target.provider_id : null;
    const editingProvider = editing === null ? null
      : current?.providers.find((item) => item.id === editing) ?? null;
    const credentialSaved = editingProvider?.credential?.configured === true;
    // 已有凭据的连接不填 Key 也可以：服务端按同一份凭据继续用
    const key = apiKey.trim() === "" ? null : apiKey;
    if (key === null && !credentialSaved) {
      setConnectStatus((current2) => ({
        ...current2,
        [editing ?? "new"]: { kind: "error", message: "请填写 API Key。" },
      }));
      return;
    }
    const before = resultBefore();
    setConnecting(true);
    let outcome: CommandOutcome;
    try {
      outcome = await submit("catalog.connect", {
        base_url: address.trim(),
        api_key: key,
      });
    } finally {
      // 请求结束（成功或失败）就回到可以操作的状态（工单 #1355）：
      // 候选由服务端在后台取，页面不再因为这件事停住
      setConnecting(false);
    }
    if (!outcome.ok) {
      setConnectStatus((current2) => ({
        ...current2,
        [editing ?? "new"]: { kind: "error", message: commandProblemText(outcome.problem) },
      }));
      return;
    }
    // 连接成功以后结果写在连接卡片旁（被操作的对象），表单收起、Key 清空
    const refs = outcome.accepted.refs as { provider_id?: string } | undefined;
    const providerId = refs?.provider_id ?? editing ?? "new";
    setApiKey("");
    setAddress("");
    setTarget(null);
    setConnectStatus((current2) => {
      const next = { ...current2 };
      delete next[providerId];
      return next;
    });
    // 重新获取模型列表以后候选回到第一页（工单 #1585）
    setPage((current2) => candidatePageAfter(current2, "refetch"));
    // 记下这次获取：结果回来后连接卡片上写「已获取 N 个模型」或失败原因，说明也就随之消失
    const previous = before.get(providerId);
    setPendingFetch({
      provider_id: providerId,
      fetched_at: previous?.fetched_at ?? null,
      status: previous?.status ?? null,
    });
  }, [address, apiKey, resultBefore, submit, target]);

  const refreshCandidates = useCallback(async (providerId: string) => {
    const before = resultBefore();
    setConnecting(true);
    let outcome: CommandOutcome;
    try {
      outcome = await submit("catalog.candidates.collect", { provider_id: providerId });
    } finally {
      setConnecting(false);
    }
    if (!outcome.ok) {
      setConnectStatus((current) => ({
        ...current,
        [providerId]: { kind: "error", message: commandProblemText(outcome.problem) },
      }));
      return;
    }
    // 重新获取模型列表以后候选回到第一页（工单 #1585）
    setPage((current) => candidatePageAfter(current, "refetch"));
    const previous = before.get(providerId);
    setPendingFetch({
      provider_id: providerId,
      fetched_at: previous?.fetched_at ?? null,
      status: previous?.status ?? null,
    });
  }, [resultBefore, submit]);

  const removeConnection = useCallback(async (providerId: string) => {
    const outcome = await submit("catalog.connection.delete", { provider_id: providerId });
    setConnectStatus((current) => ({
      ...current,
      [providerId]: outcome.ok
        ? { kind: "ok", message: "已删除这份连接。" }
        : { kind: "error", message: commandProblemText(outcome.problem) },
    }));
  }, [submit]);

  // —— 选用与取消选用 ——

  const selectModel = useCallback(async (providerId: string, upstreamModel: string, key: string): Promise<boolean> => {
    const outcome = await submit("catalog.model.select", {
      provider_id: providerId,
      model: upstreamModel,
    });
    if (!outcome.ok) {
      setCandidateStatus((current) => ({
        ...current,
        [key]: { kind: "error", message: commandProblemText(outcome.problem) },
      }));
      return false;
    }
    setCandidateStatus((current) => {
      const next = { ...current };
      delete next[key];
      return next;
    });
    return true;
  }, [submit]);

  const removeModel = useCallback(async (providerId: string, modelId: string, key: string): Promise<boolean> => {
    const outcome = await submit("catalog.model.remove", {
      provider_id: providerId,
      model_id: modelId,
    });
    if (!outcome.ok) {
      setSelectionStatus((current) => ({
        ...current,
        [key]: { kind: "error", message: removalRejectionText(commandProblemText(outcome.problem), departmentLabels) },
      }));
      return false;
    }
    setSelectionStatus((current) => {
      const next = { ...current };
      delete next[key];
      return next;
    });
    return true;
  }, [submit]);

  // 取消选用：从候选的勾选框与从「已选模型」面板走的是同一条路，
  // 成功以后两处都取消（候选那边按本地这份勾选显示）
  const cancelSelection = useCallback(async (providerId: string, modelId: string, key: string) => {
    const removed = await removeModel(providerId, modelId, key);
    if (removed) {
      setPicked((current) => ({ ...current, [key]: false }));
    }
    return removed;
  }, [removeModel]);

  const toggleCandidate = useCallback(async (row: CandidateRow) => {
    const key = candidateKey(row.provider_id, row.candidate.id);
    const model = catalogRef.current?.models.find(
      (item) => item.provider_id === row.provider_id && item.model === row.candidate.id,
    );
    if (model) {
      // 取消选用：先撤下勾选，服务端拒绝（被引用）时再放回去
      setPicked((current) => ({ ...current, [key]: false }));
      const removed = await cancelSelection(row.provider_id, model.id, key);
      if (!removed) {
        setPicked((current) => ({ ...current, [key]: true }));
      }
      return;
    }
    setPicked((current) => ({ ...current, [key]: true }));
    const selected = await selectModel(row.provider_id, row.candidate.id, key);
    if (!selected) {
      setPicked((current) => ({ ...current, [key]: false }));
    }
  }, [cancelSelection, selectModel]);

  // 容量未知：填完窗口与输出上限以后继续（同一条选用命令带上这两个值）
  const continueWithCapacity = useCallback(async (providerId: string, upstreamModel: string, key: string) => {
    const draft = capacity[key] ?? { context_window: "", max_output_tokens: "" };
    const window = intFromInput(draft.context_window);
    const output = intFromInput(draft.max_output_tokens);
    const issue = capacityInputIssue(window, output);
    if (issue !== "") {
      setSelectionStatus((current) => ({ ...current, [key]: { kind: "error", message: issue } }));
      return;
    }
    const outcome = await submit("catalog.model.select", {
      provider_id: providerId,
      model: upstreamModel,
      context_window: window,
      max_output_tokens: output,
    });
    if (!outcome.ok) {
      setSelectionStatus((current) => ({
        ...current,
        [key]: { kind: "error", message: commandProblemText(outcome.problem) },
      }));
    }
  }, [capacity, submit]);

  const submitManual = useCallback(async () => {
    const providerId = manualProvider !== ""
      ? manualProvider
      : catalogRef.current?.providers[0]?.id ?? "";
    if (providerId === "") {
      setCandidateStatus((current) => ({
        ...current,
        manual: { kind: "error", message: "先连接一个服务，再手动添加模型。" },
      }));
      return;
    }
    const upstream = manualModel.trim();
    const key = candidateKey(providerId, upstream);
    const outcome = await submit("catalog.model.select", { provider_id: providerId, model: upstream });
    if (!outcome.ok) {
      setCandidateStatus((current) => ({
        ...current,
        [key]: { kind: "error", message: commandProblemText(outcome.problem) },
      }));
      return;
    }
    setManualOpen(false);
    setManualModel("");
  }, [manualModel, manualProvider, submit]);

  // —— 部门使用 ——

  const saveBindings = useCallback(async (bindings: Record<string, BindingInput>, department: string,
    message: string) => {
    const outcome = await submit("catalog.department_defaults.save", { bindings });
    setDepartmentStatus((current) => ({
      ...current,
      [department]: outcome.ok
        ? { kind: "ok", message }
        : { kind: "error", message: commandProblemText(outcome.problem) },
    }));
  }, [submit]);

  const chooseDepartmentModel = useCallback(async (department: string, modelId: string) => {
    const current = catalogRef.current;
    if (current === null) {
      return;
    }
    await saveBindings(departmentBindings(current, department, modelId, departments), department,
      modelId === "" ? "已取消这个部门的模型，从下一次模型请求起生效。"
        : "已保存部门默认，从各部门下一次模型请求起生效。");
  }, [departments, saveBindings]);

  const chooseDepartmentTier = useCallback(async (department: string, tier: string) => {
    const current = catalogRef.current;
    if (current === null || current.bindings[department] === undefined) {
      return;
    }
    await saveBindings(departmentTierBindings(current, department, tier, departments), department,
      "已保存请求档位，从下一次模型请求起生效。");
  }, [departments, saveBindings]);

  // —— 高级 ——

  const reload = useCallback(async () => {
    const outcome = await submit("catalog.reload", {});
    setPageNotice(outcome.ok
      ? { kind: "ok", message: "已重新读取目录文件。" }
      : { kind: "error", message: commandProblemText(outcome.problem) });
  }, [submit]);

  const saveDocument = useCallback(async (next: EditableDocument): Promise<{ ok: boolean; message: string }> => {
    const outcome = await submit("catalog.document.save", { document: next });
    return outcome.ok
      ? { ok: true, message: "已保存目录文档。" }
      : { ok: false, message: commandProblemText(outcome.problem) };
  }, [submit]);

  // 连接与定义的参数保存：一次写这份连接与它下面的全部定义（catalog.connection.save）
  const saveConnection = useCallback(async (providerId: string, draft: ConnectionDraft) => {
    const current = catalogRef.current;
    const provider = current?.providers.find((item) => item.id === providerId);
    if (!current || !provider) {
      return;
    }
    const timeout = intFromInput(draft.timeout_sec);
    const outcome = await submit("catalog.connection.save", {
      provider: {
        id: provider.id,
        name: draft.name,
        base_url: provider.base_url,
        credential_ref: draft.credential_ref,
        ...(timeout === null ? {} : { timeout_sec: timeout }),
        preset_id: provider.preset_id,
        models_url: draft.models_url,
      },
      models: provider.models.map(modelInputOf),
    });
    setPageNotice(outcome.ok
      ? { kind: "ok", message: "已保存这份连接。" }
      : { kind: "error", message: commandProblemText(outcome.problem) });
  }, [submit]);

  const saveModel = useCallback(async (providerId: string, modelId: string, draft: ModelDraft) => {
    const current = catalogRef.current;
    const provider = current?.providers.find((item) => item.id === providerId);
    if (!current || !provider) {
      return;
    }
    const models = provider.models.map((model) => (model.id === modelId
      ? {
        ...modelInputOf(model),
        protocol: draft.protocol,
        reasoning_levels: draft.reasoning_levels,
        default_reasoning_level: draft.reasoning_levels.includes(draft.default_reasoning_level)
          ? draft.default_reasoning_level
          : null,
        reasoning_mode: draft.reasoning_mode,
        input_modalities: draft.input_image ? ["text", "image"] : ["text"],
        accepts_required_tool_call: draft.accepts_required_tool_call,
      }
      : modelInputOf(model)));
    const outcome = await submit("catalog.connection.save", {
      provider: {
        id: provider.id,
        name: provider.name,
        base_url: provider.base_url,
        credential_ref: provider.credential_ref,
        timeout_sec: provider.timeout_sec,
        preset_id: provider.preset_id,
        models_url: provider.models_url,
      },
      models,
    });
    setPageNotice(outcome.ok
      ? { kind: "ok", message: "已保存这个模型。" }
      : { kind: "error", message: commandProblemText(outcome.problem) });
  }, [submit]);

  if (catalog === null) {
    // 目录读不出来：写一句失败提示与服务端给的原文，不停在「正在读取目录…」（工单 #776）
    return (
      <div className="y10-block card">
        <h1>模型管理</h1>
        {catalogError !== null ? (
          <p className="y10-note note" role="status">{readFailureText(catalogError)}</p>
        ) : (
          <p className="y10-muted note">正在读取目录…</p>
        )}
      </div>
    );
  }

  return (
    <div className="y10-content y10-sys-models mm-page">
      <PageHead
        title="模型管理"
        actions={
          <div className="y10-row mm-actions">
            <button type="button" className="y10-btn" onClick={props.onBack}>
              返回原界面
            </button>
          </div>
        }
      />
      {pageNotice ? (
        <p className={pageNotice.kind === "ok" ? "y10-note mm-ok" : "y10-note is-warn mm-warn"}
           role="status" data-testid="page-notice">
          {pageNotice.message}
        </p>
      ) : null}

      <Block
        title="连接服务"
        subtitle="填服务地址与 API Key，点「获取模型」：连接、Key 与候选一步完成"
      >
        <ConnectCard
          providers={catalog.providers}
          target={target}
          address={address}
          apiKey={apiKey}
          busy={busy || connecting}
          fetching={collecting}
          status={connectStatus}
          onTarget={(next) => {
            setTarget(next);
            setConnectStatus({});
            if (next?.mode === "edit") {
              const provider = catalog.providers.find((item) => item.id === next.provider_id);
              setAddress(provider?.base_url ?? "");
            } else {
              setAddress("");
            }
            setApiKey("");
          }}
          onAddress={setAddress}
          onApiKey={setApiKey}
          onConnect={() => void connect()}
          onRefresh={(providerId) => void refreshCandidates(providerId)}
          onRemove={(providerId) => void removeConnection(providerId)}
        />
      </Block>

      <Block
        title="部门使用"
        subtitle="首个启用的模型自动供三个部门使用；在这里按部门更换"
      >
        <DepartmentUsage
          departments={departments}
          labels={departmentLabels}
          groups={departmentGroups}
          bindings={catalog.bindings}
          models={catalog.models}
          reminders={catalog.department_reminders}
          status={departmentStatus}
          busy={busy}
          onSelect={(department, modelId) => void chooseDepartmentModel(department, modelId)}
          onTier={(department, tier) => void chooseDepartmentTier(department, tier)}
        />
      </Block>

      <Block
        title="选择模型"
        subtitle="勾选后自动补全参数并验证，通过的模型启用"
      >
        <div className="mm-model-layout">
          <div className="mm-model-results">
            <CandidateList
              rows={pageView.rows}
              total={candidateRows.length}
              search={search}
              filter={filter}
              selected={selectedKeys}
              page={pageView.page}
              pages={pageView.pages}
              status={candidateStatus}
              manualOpen={manualOpen}
              manualModel={manualModel}
              manualProvider={manualProvider}
              providers={catalog.providers.map((item) => ({ id: item.id, base_url: item.base_url }))}
              disabled={locked}
              fetchNote={fetchNoteText({ connecting, collecting: collecting !== null })}
              onSearch={(value) => {
                setSearch(value);
                setPage((current) => candidatePageAfter(current, "search"));
              }}
              onFilter={(value) => {
                setFilter(value);
                setPage((current) => candidatePageAfter(current, "filter"));
              }}
              onPrevious={() => setPage(candidatePageAfter(pageView.page, "previous", pageView.pages))}
              onNext={() => setPage(candidatePageAfter(pageView.page, "next", pageView.pages))}
              onToggle={(row) => void toggleCandidate(row)}
              onManualOpen={() => {
                setManualOpen(true);
                setManualProvider(catalog.providers[0]?.id ?? "");
              }}
              onManualClose={() => setManualOpen(false)}
              onManualModel={setManualModel}
              onManualProvider={setManualProvider}
              onManualSubmit={() => void submitManual()}
            />
          </div>
          <SelectionPanel
            rows={selectedRows}
            capacity={capacity}
            status={selectionStatus}
            tests={tests}
            busy={busy}
            onCapacity={(key, field, value) => setCapacity((current) => ({
              ...current,
              [key]: { ...(current[key] ?? { context_window: "", max_output_tokens: "" }), [field]: value },
            }))}
            onContinue={(row) => void continueWithCapacity(row.provider_id, row.upstream_model, row.key)}
            onRetry={(row) => void selectModel(row.provider_id, row.upstream_model, row.key)}
            onRemove={(row) => void cancelSelection(row.provider_id, row.model_id, row.key)}
          />
        </div>
      </Block>

      <Advanced
        catalog={catalog}
        busy={busy}
        onReload={() => void reload()}
        onEditDocument={() => setJsonOpen(true)}
        onSaveConnection={(providerId, draft) => void saveConnection(providerId, draft)}
        onSaveModel={(providerId, modelId, draft) => void saveModel(providerId, modelId, draft)}
      />

      {jsonOpen ? (
        <JsonDialog
          document={document === null ? null : (document as unknown as EditableDocument)}
          error={documentError}
          onSave={saveDocument}
          onClose={() => setJsonOpen(false)}
        />
      ) : null}
    </div>
  );
}
