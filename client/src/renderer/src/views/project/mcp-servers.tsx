// 项目设置页的「MCP 服务器」一节（工单 #237；网络与 MCP docs/design/network-and-mcp.md「服务器设置」、「读取工具清单（探测）」、「项目设置的「MCP 服务器」一节」）。
// 数据来自 project.settings 的 mcp_servers：保存的非秘密设置、版本，与设置里各凭据名称的状态。
// 保存走 mcp_servers.save（带基准版本，过期时拒绝并提示重新读取）；探测走 tool_server.probe，
// 命令接受以后作为任务进行，结果以项目流事件 tool_server_probe_finished 出现，到达之前显示「测试中」。
// 凭据只写名称与状态：值不显示、不回填，写入用 credential.set（与模型管理页的来源相同）。
// 页面上的说法都在 mcp-servers-logic.ts 里，这里只按它们渲染。

import { useCallback, useEffect, useRef, useState } from "react";
import type { ClientApp } from "../../contract/client-app";
import type {
  EventObject, McpProbeResultView, McpServerSettingView, ProjectSettingsResult,
} from "../../api/generated/types.gen";
import { CredentialField } from "../models/credential-field";
import {
  Empty, Section, SubmitButton, Table, TextArea, TextInput, pageKey,
} from "./common";
import {
  MCP_TRANSPORTS, type McpServerDraft, type McpToolRow, type McpVariableDraft,
  credentialNamesOfSettings, credentialState, credentialVersion, departmentsText, draftIssue, draftOfServer,
  emptyDraft, mcpDocumentPayload, mcpServerPayload, probeFailureText, probeOf, probeStateLabel, probeTools,
  saveNotice, sectionNote, serverInfoText, snapshotTools, toolCountText, transportLabel,
} from "./mcp-servers-logic";
import { departmentLabel, departmentLabels, type DepartmentView } from "./organization";
import { useCommand } from "./use-snapshot";
import { commandProblemText } from "../../contract/command-problem.ts";

// 这一节打开的视图就是设置页那一个（重新读取时按它让服务重新查询）
const SETTINGS_VIEW = "page.settings";

type Editing = { mode: "new" } | { mode: "edit"; name: string };

// 探测结果事件 → 页面上用的结果：只取这件工单用得到的字段
export function probeViewOf(event: EventObject): McpProbeResultView | null {
  if (event.type !== "tool_server_probe_finished") {
    return null;
  }
  const payload = (event.payload ?? {}) as Record<string, unknown>;
  const serverName = String(payload.server_name ?? "");
  if (serverName === "") {
    return null;
  }
  return {
    server_name: serverName,
    status: String(payload.status ?? ""),
    config_digest: String(payload.config_digest ?? ""),
    server_info: (payload.server_info ?? null) as McpProbeResultView["server_info"],
    tools: Array.isArray(payload.tools) ? (payload.tools as McpProbeResultView["tools"]) : [],
    error: String(payload.error ?? ""),
  };
}

export function McpServersSection(props: { app: ClientApp; data: ProjectSettingsResult;
  departments: DepartmentView[] }) {
  const servers = props.data.mcp_servers.servers ?? {};
  const statuses = props.data.mcp_servers.credentials ?? {};
  const lastProbe = props.data.last_probe ?? null;
  // 可以使用的部门取自项目现在的组织（工单 #1457）；组织还没有数据时用设置里已有的部门兜底
  const labels = departmentLabels(props.departments);
  const departmentOptions = props.departments.length > 0
    ? props.departments.map((department) => department.id)
    : Object.keys(props.data.departments ?? {});

  const [editing, setEditing] = useState<Editing | null>(null);
  const [draft, setDraft] = useState<McpServerDraft>(() => emptyDraft(departmentOptions));
  // 表单的基准版本：打开表单那一刻读到的版本。期间别人改过设置时保存会被拒绝，页面提示重新读取
  // （docs/design/network-and-mcp.md「版本与固定」：命令带基准版本，版本过期时拒绝）
  const [baseVersion, setBaseVersion] = useState(0);
  const [issue, setIssue] = useState("");
  const [probing, setProbing] = useState(false);
  const [localProbes, setLocalProbes] = useState<Record<string, McpProbeResultView>>({});
  const [credentialValues, setCredentialValues] = useState<Record<string, string>>({});
  const [credentialBusy, setCredentialBusy] = useState("");
  const [credentialProblem, setCredentialProblem] = useState("");
  // 「重新读取」按过以后把上一次的拒绝提示收起来：基准版本已经换到最新的那一个
  const [noticeDismissed, setNoticeDismissed] = useState(false);
  // 自己那次探测成功时后端把快照写回设置，设置因此多一个版本：等新版本到达时把表单的基准版本换成它
  const writeBackFrom = useRef<number | null>(null);
  // 保存被接受时服务端带回新的版本（refs.version）：页面还没读到新快照时，下一次打开表单用它，
  // 不拿着已经过期的版本再去提交一次
  const acceptedVersion = useRef(0);
  const probingName = useRef("");

  const save = useCommand(props.app, pageKey(["mcp-save", props.data.mcp_servers.version, baseVersion]));
  const probe = useCommand(props.app, pageKey(["mcp-probe", editing === null ? "" : JSON.stringify(draft)]));
  const credential = useCommand(props.app, pageKey(["mcp-credential", props.data.mcp_servers.version]));

  // 探测结果以事件到达：结果写进这一节，探测的「测试中」随之结束
  const app = props.app;
  const subscribe = useCallback((listener: (event: EventObject) => void) => app.subscribeEvents(listener), [app]);
  const finishProbe = useRef<(event: EventObject) => void>(() => undefined);
  finishProbe.current = (event: EventObject) => {
    const result = probeViewOf(event);
    if (result === null) {
      return;
    }
    setLocalProbes((current) => ({ ...current, [result.server_name]: result }));
    if (result.server_name === probingName.current) {
      setProbing(false);
      // 探测成功时后端把工具清单快照写回设置，设置因此多了一个版本（docs/design/network-and-mcp.md「读取工具清单（探测）」）：
      // 这是页面自己那次探测写回的，等新版本到达以后把表单的基准版本换成它，
      // 不让用户保存时白撞一次「已过期」
      if (result.status === "ok") {
        writeBackFrom.current = props.data.mcp_servers.version;
      }
    }
  };
  useEffect(() => subscribe((event) => finishProbe.current(event)), [subscribe]);

  // 自己那次探测写回带来的新版本：表单的基准版本跟着换成它
  useEffect(() => {
    const version = props.data.mcp_servers.version;
    if (writeBackFrom.current === null || version === writeBackFrom.current) {
      return;
    }
    writeBackFrom.current = null;
    setBaseVersion(version);
  }, [props.data.mcp_servers.version]);

  // 保存被接受以后服务端带回的版本：比页面读到的那份新时记下来（重新打开表单按它取基准版本）
  useEffect(() => {
    const refs = (save.accepted?.refs ?? null) as { version?: unknown } | null;
    if (refs !== null && typeof refs.version === "number" && refs.version > acceptedVersion.current) {
      acceptedVersion.current = refs.version;
    }
  }, [save.accepted]);

  // 页面此刻能确定的设置版本：读到的那一份与保存回执里带回的，取更新的一个
  const currentVersion = () => Math.max(props.data.mcp_servers.version, acceptedVersion.current);

  const openForm = (next: Editing | null) => {
    setIssue("");
    setProbing(false);
    setCredentialProblem("");
    setNoticeDismissed(false);
    writeBackFrom.current = null;
    setEditing(next);
    if (next === null) {
      return;
    }
    setBaseVersion(currentVersion());
    setDraft(next.mode === "edit" && servers[next.name] !== undefined
      ? draftOfServer(servers[next.name])
      : emptyDraft(departmentOptions));
  };

  const submitSave = async () => {
    const problem = draftIssue(draft);
    setIssue(problem);
    setNoticeDismissed(false);
    if (problem !== "") {
      return;
    }
    const previousName = editing?.mode === "edit" ? editing.name : null;
    const document = mcpDocumentPayload(servers, draft, { previous_name: previousName });
    const ok = await save.submit("mcp_servers.save", {
      project_id: props.data.project_id, base_version: baseVersion, servers: document.servers,
    });
    if (ok) {
      openForm(null);
    }
  };

  const remove = async (name: string) => {
    const document = mcpDocumentPayload(servers, null, { previous_name: name });
    const ok = await save.submit("mcp_servers.save", {
      project_id: props.data.project_id, base_version: currentVersion(), servers: document.servers,
    });
    if (ok && editing !== null && editing.mode === "edit" && editing.name === name) {
      openForm(null);
    }
  };

  const startProbe = async () => {
    const problem = draftIssue(draft);
    setIssue(problem);
    if (problem !== "") {
      return;
    }
    probingName.current = draft.name.trim();
    setProbing(true);
    const ok = await probe.submit("tool_server.probe", {
      project_id: props.data.project_id, name: draft.name.trim(), server: mcpServerPayload(draft),
    });
    if (!ok) {
      setProbing(false);
    }
  };

  const setCredentialValue = async (ref: string) => {
    const secret = (credentialValues[ref] ?? "").trim();
    if (secret === "") {
      return;
    }
    setCredentialBusy(ref);
    setCredentialProblem("");
    const ok = await credential.submit("credential.set", {
      base_version: credentialVersion(statuses, ref), ref, secret, persist: true,
    });
    setCredentialBusy("");
    if (ok) {
      // 值不回填：写进去以后输入框空着，状态由后端的设置给出
      setCredentialValues((current) => ({ ...current, [ref]: "" }));
    } else if (credential.problem !== null) {
      setCredentialProblem(commandProblemText(credential.problem));
    }
  };

  const reload = () => {
    // 重新读取：基准版本换成页面上读到的那一个（页面按事件流一直在重新读，这里再让服务查一次）
    setBaseVersion(currentVersion());
    setNoticeDismissed(true);
    void props.app.viewSync?.refresh(SETTINGS_VIEW);
  };

  // 表单里出现的凭据名称：已保存的设置与这一份草稿中的都在（写入区按名称各给一行）
  const credentialNames = credentialNamesOfSettings(servers, editing === null ? null : draft);
  const formProbe = editing === null ? null : probeOf(draft.name.trim(), lastProbe, localProbes);
  const saveProblem = save.problem === null || noticeDismissed ? "" : saveNotice(save.problem);

  return (
    <Section id="mcp-servers" title="MCP 服务器" note={sectionNote(servers)}>
      {Object.keys(servers).length === 0 ? (
        <Empty text="还没有服务器。点「添加服务器」写一台：命令或地址、可以使用的部门，需要时写凭据名称。" />
      ) : (
        <Table
          head={["名称", "传输", "可以使用的部门", "工具", "最近一次连接结果", ""]}
          rows={Object.entries(servers).map(([name, server]) => [
            name,
            transportLabel(server.transport),
            departmentsText(server.departments, labels),
            toolCountText(server),
            probeStateLabel(probeOf(name, lastProbe, localProbes)),
            <span className="y10-row" key={`${name}-actions`}>
              <button type="button" className="y10-btn small" data-testid={`mcp-edit-${name}`}
                      onClick={() => openForm({ mode: "edit", name })}>
                编辑
              </button>
              <button type="button" className="y10-btn small danger" data-testid={`mcp-delete-${name}`}
                      disabled={save.busy} onClick={() => void remove(name)}>
                删除
              </button>
            </span>,
          ])}
        />
      )}
      <div className="y10-row row-actions">
        <button type="button" className="y10-btn" data-testid="mcp-add"
                onClick={() => openForm({ mode: "new" })}>
          添加服务器
        </button>
      </div>
      {/* 列表上的拒绝（删除时基准版本过期等）写在这里，说明写在被操作的那一节旁边 */}
      {save.problem !== null && editing === null ? (
        <p className="y10-note is-warn warn" role="status" data-testid="mcp-list-notice">{saveProblem}</p>
      ) : null}
      {editing !== null ? (
        <div className="y10-form form mcp-server-form" data-testid="mcp-server-form">
          <h3 className="y10-h3">{editing.mode === "new" ? "添加服务器" : `修改服务器「${editing.name}」`}</h3>
          <TextInput label="名称" value={draft.name} onInput={(value) => setDraft({ ...draft, name: value })} />
          <p className="y10-note note">名称用小写字母、数字与连字符；它同时是这台服务器的工具名的前缀。</p>
          <label className="y10-field field">
            <span>传输</span>
            <select className="y10-input" value={draft.transport} data-testid="mcp-transport"
                    onChange={(event) => setDraft({ ...draft, transport: event.target.value as McpServerDraft["transport"] })}>
              {MCP_TRANSPORTS.map((transport) => (
                <option key={transport} value={transport}>{transportLabel(transport)}</option>
              ))}
            </select>
          </label>
          {draft.transport === "stdio" ? (
            <>
              <TextInput label="命令" value={draft.command}
                         onInput={(value) => setDraft({ ...draft, command: value })} />
              <TextArea label="参数（一行一个）" value={draft.args} rows={3}
                        onInput={(value) => setDraft({ ...draft, args: value })} />
              <VariablesEditor
                title="环境变量" testId="mcp-env" rows={draft.env}
                onChange={(rows) => setDraft({ ...draft, env: rows })} />
            </>
          ) : (
            <>
              <TextInput label="地址" value={draft.url}
                         onInput={(value) => setDraft({ ...draft, url: value })} />
              <VariablesEditor
                title="请求头" testId="mcp-headers" rows={draft.headers}
                onChange={(rows) => setDraft({ ...draft, headers: rows })} />
            </>
          )}
          <fieldset className="y10-field field mcp-departments">
            <legend>可以使用的部门</legend>
            {departmentOptions.map((department) => (
              <label className="y10-check checkbox" key={department}>
                <input type="checkbox" checked={draft.departments.includes(department)}
                       data-testid={`mcp-department-${department}`}
                       onChange={(event) => setDraft({
                         ...draft,
                         departments: event.target.checked
                           ? [...draft.departments, department]
                           : draft.departments.filter((item) => item !== department),
                       })} />
                <span>{departmentLabel(department, labels)}</span>
              </label>
            ))}
          </fieldset>
          <details className="y10-details">
            <summary>时限与输出上限（默认值：启动 60 秒、调用 120 秒、输出 20000 个字符）</summary>
            <TextInput label="启动时限（秒）" value={draft.startup_timeout_sec}
                       onInput={(value) => setDraft({ ...draft, startup_timeout_sec: value })} />
            <TextInput label="调用时限（秒）" value={draft.call_timeout_sec}
                       onInput={(value) => setDraft({ ...draft, call_timeout_sec: value })} />
            <TextInput label="输出上限（字符）" value={draft.output_limit}
                       onInput={(value) => setDraft({ ...draft, output_limit: value })} />
          </details>
          {credentialNames.length > 0 ? (
            <div className="mcp-credentials" data-testid="mcp-credentials">
              <h4 className="y10-h4">凭据值</h4>
              <p className="y10-note note">
                设置里只写凭据名称；这里写入值，或者把名称写成进程环境里的变量名由环境提供。
                输入框始终为空，值不回显。
              </p>
              {credentialNames.map((ref) => (
                <CredentialField
                  key={ref}
                  id={`mcp-credential-${ref}`}
                  label={ref}
                  testId={`mcp-credential-${ref}`}
                  inputTestId={`mcp-credential-${ref}-input`}
                  value={credentialValues[ref] ?? ""}
                  onValue={(value) => setCredentialValues((current) => ({ ...current, [ref]: value }))}
                  status={credentialState(statuses, ref)}
                  unknownText="还没有读到状态"
                  placeholder="输入值以设置这个凭据"
                  hint="写入以后状态由后端给出；输入框始终为空，值不回显。"
                  submit={{ label: "设置值", busy: credentialBusy === ref, onClick: () => void setCredentialValue(ref) }}
                />
              ))}
              {credentialProblem !== "" ? (
                <p className="y10-note is-warn warn" role="status" data-testid="mcp-credential-notice">
                  {credentialProblem}
                </p>
              ) : null}
            </div>
          ) : null}
          <div className="y10-row row-actions">
            <SubmitButton label={editing.mode === "new" ? "保存服务器" : "保存修改"} busy={save.busy}
                          disabled={draftIssue(draft) !== ""} onClick={() => void submitSave()} />
            <SubmitButton label={probing ? "正在读取工具清单…" : "连接并读取工具清单"}
                          busy={probe.busy || probing} disabled={draftIssue(draft) !== ""}
                          onClick={() => void startProbe()} />
            <button type="button" className="y10-btn" data-testid="mcp-cancel" onClick={() => openForm(null)}>
              取消
            </button>
          </div>
          {issue !== "" ? (
            <p className="y10-note note" role="status" data-testid="mcp-issue">{issue}</p>
          ) : null}
          {saveProblem !== "" ? (
            <p className="y10-note is-warn warn" role="status" data-testid="mcp-save-notice">
              {saveProblem}
              {save.problem !== null && save.problem.kind === "rejected" && save.problem.rejection.reason === "stale_base" ? (
                <button type="button" className="y10-btn small" data-testid="mcp-reload" onClick={reload}>
                  重新读取
                </button>
              ) : null}
            </p>
          ) : null}
          {save.submitted ? <p className="y10-note note" role="status">已提交，等待写入结果</p> : null}
          {probing ? (
            <p className="y10-note note" role="status" data-testid="mcp-probing">测试中：正在连接这台服务器并读取工具清单…</p>
          ) : null}
          {probe.problem !== null ? (
            <p className="y10-note is-warn warn" role="status" data-testid="mcp-probe-notice">
              {commandProblemText(probe.problem)}
            </p>
          ) : null}
          {formProbe !== null && !probing ? (
            <ProbeResult result={formProbe} server={editing.mode === "edit" ? servers[editing.name] ?? null : null} />
          ) : null}
        </div>
      ) : null}
      {editing === null && Object.keys(servers).length > 0 ? (
        <SavedTools servers={servers} />
      ) : null}
    </Section>
  );
}


// 变量与请求头的几行：名字、取值方式与值（凭据只写名称，值在下面的「凭据值」里写）
function VariablesEditor(props: {
  title: string;
  testId: string;
  rows: McpVariableDraft[];
  onChange: (rows: McpVariableDraft[]) => void;
}) {
  const patch = (index: number, next: Partial<McpVariableDraft>) => {
    props.onChange(props.rows.map((row, position) => (position === index ? { ...row, ...next } : row)));
  };
  return (
    <div className="mcp-variables" data-testid={props.testId}>
      <h4 className="y10-h4">{props.title}</h4>
      {props.rows.map((row, index) => (
        <div className="y10-row mcp-variable" key={`${index}`}>
          <TextInput label="名称" value={row.key} onInput={(value) => patch(index, { key: value })} />
          <label className="y10-field field">
            <span>取值方式</span>
            <select className="y10-input" value={row.kind} data-testid={`${props.testId}-kind-${index}`}
                    onChange={(event) => patch(index, { kind: event.target.value === "credential" ? "credential" : "text" })}>
              <option value="text">固定文本</option>
              <option value="credential">凭据名称</option>
            </select>
          </label>
          {row.kind === "credential" ? (
            <TextInput label="凭据名称" value={row.credential_ref}
                       onInput={(value) => patch(index, { credential_ref: value })} />
          ) : (
            <TextInput label="值" value={row.value} onInput={(value) => patch(index, { value })} />
          )}
          <button type="button" className="y10-btn small" data-testid={`${props.testId}-remove-${index}`}
                  onClick={() => props.onChange(props.rows.filter((_row, position) => position !== index))}>
            删除这一行
          </button>
        </div>
      ))}
      <button type="button" className="y10-btn small" data-testid={`${props.testId}-add`}
              onClick={() => props.onChange([...props.rows, { key: "", kind: "text", value: "", credential_ref: "" }])}>
        添加一行
      </button>
    </div>
  );
}

// 探测结果：成功时列出服务器信息与工具清单（工具、说明、服务器自己的提示），失败时写原因
function ProbeResult(props: { result: McpProbeResultView; server: McpServerSettingView | null }) {
  if (props.result.status !== "ok") {
    return (
      <p className="y10-note is-warn warn" role="status" data-testid="mcp-probe-failure">
        连接失败：{probeFailureText(props.result)}
      </p>
    );
  }
  const rows: McpToolRow[] = probeTools(props.result);
  return (
    <div className="mcp-probe-result" data-testid="mcp-probe-result">
      <p className="y10-note note">
        读取到 {serverInfoText(props.result)}，{rows.length} 个工具。
      </p>
      <Table head={["工具", "说明", "服务器自己的提示"]}
             rows={rows.map((row) => [row.name, row.description, toolHintText(row)])} />
    </div>
  );
}

// 保存下来的工具清单：这一节在不开表单时也看得到每台服务器的工具
function SavedTools(props: { servers: Record<string, McpServerSettingView> }) {  const entries = Object.entries(props.servers).filter(([, server]) => snapshotTools(server).length > 0);
  if (entries.length === 0) {
    return null;
  }
  return (
    <details className="y10-details" data-testid="mcp-saved-tools">
      <summary>各服务器读到的工具清单</summary>
      {entries.map(([name, server]) => (
        <div key={name}>
          <h4 className="y10-h4">{name}</h4>
          <Table head={["工具", "说明", "服务器自己的提示"]}
                 rows={snapshotTools(server).map((row) => [row.name, row.description, toolHintText(row)])} />
        </div>
      ))}
    </details>
  );
}

// 一台服务器的工具行（提示只供参考，没有标注时写「—」）
export function toolHintText(row: McpToolRow): string {
  return row.hints === "" ? "—" : row.hints;
}
