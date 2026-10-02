// 部门工作间（原型 v8 设计说明第 7.1 节，工单 #80）：标题区（部门名、职责、当前生效的模型及来源、
// 最近一次请求实际使用的模型、协议与发送的档位、部门状态、「部门设置」）；部门房间的位置由 #177 填入；
// 检查区页签：动作与回执（run.actions）、Context（清单与压缩记录）、部门 Prompt；
// 部门消息与指导（guidance.send）；部门设置弹窗只改部门 Prompt，模型与档位由 #95 加入。

import { useState } from "react";
import type { ClientApp } from "../../contract/client-app";
import type {
  DepartmentWorkspaceResult,
  EventDetailResult,
  ProjectOverviewResult,
  RunActionsResult,
} from "../../api/generated/types.gen";
import type { Route } from "../../shell/routing";
import { CommandFeedback, Empty, EventDetail, KeyValue, Loading, Modal, Section, SubmitButton, Table, TextArea,
  dict, formatNumberOr, hasCommand, list, numberValue, optionalText, pageKey, show, text, useDraft } from "./common";
import { ACTION_STATUS, DEPARTMENTS, GUIDANCE_STATUS, PHASE_LABELS, departmentName, formatTime, label } from "./labels";
import { RoomScreen } from "./room-screen";
import { type CommandState, useCommand, useSnapshot } from "./use-snapshot";

export function DepartmentPage(props: { app: ClientApp; route: Route }) {
  const projectId = props.route.projectId ?? "";
  const department = props.route.department ?? "product";
  // 顶栏没有选中事项时取进行中的那一项，其次取最近一项；与资料页的取法相同，
  // 部门工作间的状态、消息与检查区都需要一个事项才有内容可显示
  const picked = useSnapshot<ProjectOverviewResult>(props.app, "page.dept.pick", "project.overview", {
    project_id: projectId,
  });
  const requested = props.route.workItemId;
  const items = picked.data?.work_items ?? [];
  const workItem = requested
    ?? (items.find((item) => item.status === "in_progress")?.work_item_id
      ?? items[items.length - 1]?.work_item_id
      ?? null);
  const workspace = useSnapshot<DepartmentWorkspaceResult>(props.app, "page.dept", "department.workspace", {
    project_id: projectId,
    department,
    work_item: workItem,
  }, workItem === null);
  const data = workspace.data;
  const command = useCommand(props.app, pageKey([data?.work_item_id, data?.prompt.configured_version, data?.phase]));
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <div className="page">
      <Loading state={picked} />
      <Loading state={workspace} />
      <Section title="部门房间" note="小人的姿势来自部门状态，动作由事件驱动；头顶的话说明自己现在做什么">
        <RoomScreen app={props.app} data={data} />
      </Section>
      {data ? (
        <>
          <TitleArea
            data={data}
            scopeNote={requested !== null
              ? "（顶栏选中）"
              : workItem !== null ? "（未选中事项，取当前事项）" : "（项目还没有事项）"}
            onOpenSettings={() => setSettingsOpen(true)}
          />
          <InspectArea app={props.app} data={data} />
          <MessagesAndGuidance app={props.app} data={data} command={command} />
          {settingsOpen ? <SettingsDialog app={props.app} data={data} onClose={() => setSettingsOpen(false)} /> : null}
        </>
      ) : null}
    </div>
  );
}

// 当前生效模型的来源：取自调用目标的 selection_source；后端目前只登记部门默认这一种
function selectionSourceLabel(value: string | null): string {
  if (value === "department_default") {
    return "部门默认";
  }
  return show(value, "未上报");
}

function departmentStatus(data: DepartmentWorkspaceResult): string {
  if (data.run_id === null) {
    return "空闲（这个范围里没有运行）";
  }
  if (data.active) {
    return `正在工作 · ${label(PHASE_LABELS, data.phase)}`;
  }
  return `这次运行不在本部门 · ${label(PHASE_LABELS, data.phase)}`;
}

function TitleArea(props: { data: DepartmentWorkspaceResult; scopeNote: string; onOpenSettings: () => void }) {
  const data = props.data;
  const provider = data.provider === null ? null : dict(data.provider);
  const lastCall = data.last_call === null ? null : dict(data.last_call);
  const info = DEPARTMENTS[data.department];

  return (
    <Section title={`${departmentName(data.department)}工作间`} note={info ? info.role : "部门职责未登记"}>
      <KeyValue
        items={[
          ["部门状态", departmentStatus(data)],
          ["当前生效的模型及来源", provider === null
            ? "还没有请求，未上报"
            : `${show(optionalText(provider.requested_model))}（来源 ${selectionSourceLabel(optionalText(provider.selection_source))}）`],
          ["最近一次请求实际使用的模型", lastCall === null ? "未上报" : show(optionalText(lastCall.actual_model))],
          ["协议", lastCall === null && provider === null
            ? "未上报"
            : show(optionalText(lastCall?.requested_protocol) ?? optionalText(provider?.protocol))],
          ["发送的档位", provider === null
            ? "未上报"
            : `请求 ${show(optionalText(provider.requested_tier))}，实际发送 ${show(optionalText(provider.sent_tier))}`],
          ["提醒", data.reminders.length === 0 ? "没有" : data.reminders.join("；")],
        ]}
      />
      <p className="note">
        {data.work_item_id === null
          ? "这个范围没有事项"
          : `所选事项 ${data.work_item_id}，运行 ${show(data.run_id, "未创建")}`}
        {props.scopeNote}
      </p>
      <div className="composer">
        <SubmitButton label="部门设置" busy={false} onClick={props.onOpenSettings} />
      </div>
    </Section>
  );
}

const INSPECT_TABS = [
  { id: "actions", label: "动作与回执" },
  { id: "context", label: "Context" },
  { id: "prompt", label: "部门 Prompt" },
];

// 检查区：页签切换动作与回执、Context 与部门 Prompt
function InspectArea(props: { app: ClientApp; data: DepartmentWorkspaceResult }) {
  const [tab, setTab] = useState("actions");
  const data = props.data;

  return (
    <section className="card">
      <div className="tabs" role="tablist">
        {INSPECT_TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            className={tab === item.id ? "active" : ""}
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>
      {tab === "actions" ? <Actions app={props.app} runId={data.run_id} /> : null}
      {tab === "context" ? <ContextPanel data={data} /> : null}
      {tab === "prompt" ? <PromptState data={data} /> : null}
    </section>
  );
}

// 动作与回执：这次运行的动作列表；执行机器（3.2C）在 machines.list 登记以后加入
function Actions(props: { app: ClientApp; runId: string | null }) {
  const [openEvent, setOpenEvent] = useState<string | null>(null);
  const actions = useSnapshot<RunActionsResult>(
    props.app, "page.dept.actions", "run.actions", { run_id: props.runId ?? "" }, props.runId === null,
  );
  const detail = useSnapshot<EventDetailResult>(
    props.app,
    openEvent ? `page.dept.actions.event.${openEvent}` : "page.dept.actions.event.none",
    "event.detail",
    { event_id: openEvent ?? "" },
    openEvent === null,
  );

  if (props.runId === null) {
    return <Empty text="这个范围没有运行，动作列表为空" />;
  }
  if (actions.loading && actions.data === null) {
    return <p className="note">正在读取动作列表</p>;
  }
  const rows = actions.data?.actions ?? [];

  return (
    <>
      {rows.length === 0 ? <Empty text="这次运行没有记录动作" /> : (
        <Table
          head={["工具", "部门", "状态", "登记名", "结果", "输出引用", "时间"]}
          rows={rows.map((action) => {
            const receipt = action.receipt;
            const eventId = receipt === null ? null : receipt.event_id;
            return [
              action.tool,
              departmentName(action.department),
              label(ACTION_STATUS, action.status),
              show(receipt === null ? null : receipt.registered_name, "没有回执"),
              receipt === null
                ? "没有回执"
                : (receipt.ok ? "成功" : show(receipt.error, "失败")),
              receipt?.output_ref ? "有（见原始事件）" : "无",
              <button
                type="button"
                className="link"
                key={action.action_id}
                disabled={eventId === null || eventId === ""}
                onClick={() => setOpenEvent(eventId)}
              >
                {formatTime(action.created_at)}
              </button>,
            ];
          })}
        />
      )}
      {openEvent ? <EventDetail eventId={openEvent} onClose={() => setOpenEvent(null)} snapshot={detail} /> : null}
    </>
  );
}

// Context：上下文清单与压缩记录（取自 department.workspace 查询的 context 字段）
function ContextPanel(props: { data: DepartmentWorkspaceResult }) {
  const context = dict(props.data.context);
  const manifests = list(context.manifests);
  const compactions = list(context.compactions);

  if (manifests.length === 0 && compactions.length === 0) {
    return <Empty text="这次运行没有上下文清单与压缩记录" />;
  }

  return (
    <>
      <h3 className="sub">上下文清单（{manifests.length} 条）</h3>
      {manifests.length === 0 ? <Empty text="没有清单" /> : (
        <Table
          head={["第几步", "激活", "估算用量", "工作上限", "截断", "放入的来源"]}
          rows={manifests.map((manifest, index) => [
            show(optionalText(manifest.step_id), String(index + 1)),
            show(optionalText(manifest.activation_id)),
            formatNumberOr(numberValue(manifest.token_estimate), " token"),
            formatNumberOr(numberValue(manifest.budget), " token"),
            manifest.truncated ? "是" : "否",
            list(manifest.injected).map((entry) => `${text(entry.source)}（${formatNumberOr(numberValue(entry.tokens), " token")}）`).join("、") || "没有记录",
          ])}
        />
      )}
      <h3 className="sub">压缩记录（{compactions.length} 条）</h3>
      {compactions.length === 0 ? <Empty text="没有压缩记录" /> : (
        <Table
          head={["来源事件", "部门", "第几步", "激活", "摘要上限"]}
          rows={compactions.map((entry) => [
            show(optionalText(entry.source_event_id)),
            departmentName(optionalText(entry.department)),
            show(optionalText(entry.step_id)),
            show(optionalText(entry.activation_id)),
            formatNumberOr(numberValue(entry.summary_token_limit), " token"),
          ])}
        />
      )}
    </>
  );
}

// 部门 Prompt：项目当前配置与所选请求实际使用的版本
function PromptState(props: { data: DepartmentWorkspaceResult }) {
  const prompt = props.data.prompt;
  return (
    <>
      <KeyValue
        items={[
          ["项目当前配置", `第 ${prompt.configured_version} 版（来源 ${show(prompt.source, "未写明")}）`],
          ["所选请求实际使用的版本", prompt.used_version === null
            ? "这次运行还没有用到部门 Prompt"
            : `第 ${prompt.used_version} 版（事件 ${show(prompt.used_event_id)}）`],
        ]}
      />
      <h3 className="sub">配置的内容</h3>
      <pre className="raw">{prompt.configured_text === "" ? "（空）" : prompt.configured_text}</pre>
    </>
  );
}

// 部门消息与指导：消息日志每条可打开原始事件；指导记录列出状态与回应
function MessagesAndGuidance(props: { app: ClientApp; data: DepartmentWorkspaceResult; command: CommandState }) {
  const [openEvent, setOpenEvent] = useState<string | null>(null);
  const data = props.data;
  const [draft, setDraft] = useDraft(`guidance/${data.project_id}/${data.work_item_id ?? "none"}/${data.department}`);
  const detail = useSnapshot<EventDetailResult>(
    props.app,
    openEvent ? `page.dept.messages.event.${openEvent}` : "page.dept.messages.event.none",
    "event.detail",
    { event_id: openEvent ?? "" },
    openEvent === null,
  );
  const messages = list(data.messages);

  return (
    <>
      <Section title="部门消息" note="按日志位置取最近的一批；点击时间打开原始事件">
        {messages.length === 0 ? <Empty text="这个部门还没有消息" /> : (
          <ul className="message-list">
            {messages.map((message) => (
              <li key={text(message.event_id)}>
                <div className="input-head">
                  <button type="button" className="link" onClick={() => setOpenEvent(text(message.event_id))}>
                    {formatTime(optionalText(message.created_at))}
                  </button>
                  <span className="msg-type">{text(message.type)}</span>
                </div>
                <p className="msg-text">{show(text(message.text), "（这条事件没有文字摘要）")}</p>
              </li>
            ))}
          </ul>
        )}
      </Section>
      <Section title="部门指导" note="已接收的指导在下一次安全激活进入模型输入">
        {data.guidance.length === 0 ? <Empty text="这个部门还没有指导记录" /> : (
          <ul className="guidance-list">
            {data.guidance.map((record) => (
              <li key={record.guidance_id}>
                <div className="input-head">
                  <strong>{label(GUIDANCE_STATUS, record.status)}</strong>
                  <span className="byte-range">第 {record.version} 版</span>
                  {record.applied_activation_id ? <span className="byte-range">已用于激活 {record.applied_activation_id}</span> : null}
                  <button type="button" className="link" onClick={() => setOpenEvent(record.created_event_id)}>查看原始事件</button>
                </div>
                <p className="msg-text">{record.text}</p>
                {record.response_status ? <p className="card-note">部门的回应：{show(record.response_text, record.response_status)}</p> : null}
              </li>
            ))}
          </ul>
        )}
        {data.work_item_id && hasCommand(props.app, "guidance.send") ? (
          <div className="composer">
            <TextArea label={`向${departmentName(data.department)}下达指导`} value={draft} onInput={setDraft} />
            <SubmitButton
              label="发送指导"
              busy={props.command.busy}
              disabled={draft.trim() === ""}
              onClick={() => {
                void props.command.submit("guidance.send", {
                  work_item_id: data.work_item_id,
                  department: data.department,
                  text: draft.trim(),
                }).then((ok) => { if (ok) setDraft(""); });
              }}
            />
            <CommandFeedback submitted={props.command.submitted} rejection={props.command.rejection} />
          </div>
        ) : (
          <p className="note">
            {data.work_item_id === null ? "这个范围没有事项，不能发送指导" : "能力清单没有登记 guidance.send，不能发送指导"}
          </p>
        )}
      </Section>
      {openEvent ? <EventDetail eventId={openEvent} onClose={() => setOpenEvent(null)} snapshot={detail} /> : null}
    </>
  );
}

// 部门设置弹窗：部门 Prompt 文本；模型与推理档位由 #95 加入
function SettingsDialog(props: { app: ClientApp; data: DepartmentWorkspaceResult; onClose: () => void }) {
  const prompt = props.data.prompt;
  const [textValue, setTextValue] = useDraft(`dept-settings/${props.data.project_id}/${props.data.department}`, prompt.configured_text);
  const command = useCommand(props.app, pageKey([prompt.configured_version]));
  const canSave = hasCommand(props.app, "department_settings.save");

  return (
    <Modal title={`${departmentName(props.data.department)}设置`} onClose={props.onClose}>
      <p className="note">
        基准版本：第 {prompt.configured_version} 版。模型与推理档位属于部门默认与项目部门设置（#95），这里留出位置。
      </p>
      <TextArea label="部门 Prompt" value={textValue} rows={10} onInput={setTextValue} />
      <div className="composer">
        <SubmitButton
          label="保存部门设置"
          busy={command.busy}
          disabled={!canSave || textValue === prompt.configured_text}
          onClick={() => {
            void command.submit("department_settings.save", {
              project_id: props.data.project_id,
              department: props.data.department,
              base_version: prompt.configured_version,
              department_prompt: textValue,
            }).then((ok) => { if (ok) props.onClose(); });
          }}
        />
        {!canSave ? <p className="note">能力清单没有登记 department_settings.save</p> : null}
        <CommandFeedback submitted={command.submitted} rejection={command.rejection} />
      </div>
    </Modal>
  );
}
