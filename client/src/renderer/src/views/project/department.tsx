// 部门工作间（原型 v8 设计说明第 7.1 节，工单 #80）：标题区（部门名、职责、本部门的状态与原因、三个部门各自的状态、
// 当前生效的模型及来源、最近一次请求实际使用的模型、协议与发送的档位、「部门设置」）；部门房间的位置由 #177 填入，
// 房间信息写传信管上等待本部门回答的询问数；检查区页签：动作与回执（run.actions）、Context（清单与压缩记录）、部门 Prompt；
// 询问、部门消息与指导（run.asks 的询问、department.workspace 的消息与 guidance.send 的指导）；
// 部门设置弹窗只改部门 Prompt，模型与档位由 #95 加入。标题区与询问的写法按原型 v12 第 3.1、3.3 节（工单 #905）。

import { Fragment, useState } from "react";
import type { ReactNode } from "react";
import type { ClientApp } from "../../contract/client-app";
import type {
  BackgroundCommandView,
  DepartmentWorkspaceResult,
  EventDetailResult,
  GuidanceRecord,
  ProjectOverviewResult,
  RunActionsResult,
  RunAsksResult,
} from "../../api/generated/types.gen";
import { paths, type Route } from "../../shell/routing";
import { CommandFeedback, Empty, EventDetail, KeyValue, Loading, Modal, Section, SubmitButton, Table, TextArea,
  dict, formatNumberOr, hasCommand, list, numberValue, optionalText, pageKey, show, text, useDraft } from "./common";
import { DepartmentSettingsFields, DepartmentSettingsSave, promptWritten, useDepartmentDraft } from "./department-settings-form";
import { DEPARTMENTS, GUIDANCE_STATUS, departmentName, departmentStatusView, departmentsLineParts, formatTime,
  itemSource, label, lettersWaitingText, type DepartmentStateView } from "./labels";
import { askIndent, askLine } from "./asks-text";
import { ACTION_TABLE_HEAD, actionCells } from "./action-table";
import { RoomScreen } from "./room-screen";
import { type CommandState, useCommand, useSnapshot } from "./use-snapshot";
import { ReadExisting } from "./read-existing";
import { scopeName } from "./scope-name";
import { emptyOrFailureText, readFailureText } from "../../contract/read-failure";

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
  // 事项标识取不到时 department.workspace 不被打开：那一处没有读取动作，页面显示空态，
  // 不显示「正在读取数据」（工单 #295 第 3 项）
  const noWorkItem = picked.data !== null && workItem === null;
  const command = useCommand(props.app, pageKey([data?.work_item_id, data?.department_setting.configured_version, data?.run_status]));
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <div className="y10-ws page" data-dept={department}>
      <Loading state={picked} />
      <Loading state={workspace} />
      {picked.error !== null ? (
        // 项目概览读不出来：连当前事项都取不到，不留一片空白（工单 #775）
        <p className="y10-note note" role="status">{readFailureText(picked.error)}</p>
      ) : null}
      {workspace.error !== null ? (
        // 部门工作间读不出来：这一处本来有内容（工单 #775）
        <p className="y10-note note" role="status">{readFailureText(workspace.error)}</p>
      ) : null}
      {noWorkItem ? <Empty text="项目还没有事项，部门工作间没有内容可显示" /> : null}
      {data ? (
        <TitleArea
          data={data}
          // 所选事项用名字说明，不显示事项标识这类内部标识（工单 #746）
          workItemTitle={scopeName(items, data.work_item_id)}
          scopeWorkItem={requested}
          scopeNote={requested !== null
            ? "（顶栏选中）"
            : workItem !== null ? "（未选中事项，取当前事项）" : "（项目还没有事项）"}
          onOpenSettings={() => setSettingsOpen(true)}
        />
      ) : null}
      <RoomSection app={props.app} department={department} data={data} />

      {data ? (
        <>
          <InspectArea app={props.app} data={data} />
          <MessagesAndGuidance app={props.app} data={data} command={command} />
          {/* 「阅读已有项目」不是原型 v10 的区块；原型最后一个区块是部门消息与指导，放在它之后 */}
          <ReadExisting
            app={props.app}
            runId={data.run_id}
            item={items.find((item) => item.work_item_id === workItem) ?? null}
          />
          {settingsOpen ? <SettingsDialog app={props.app} data={data} onClose={() => setSettingsOpen(false)} /> : null}
        </>
      ) : null}
    </div>
  );
}

export function RoomSection(props: { app: ClientApp; department: string; data: DepartmentWorkspaceResult | null }) {
  return (
    <Section title="部门房间" note="小人的姿势来自部门状态，动作由事件驱动；头顶的话说明自己现在做什么">
      <div className="y10-ws-stage stage">
        <RoomScreen app={props.app} department={props.department} data={props.data} />
      </div>
      {props.data ? (
        <div className="y10-ws-room-info room-info" data-ws-info>
          <RoomInfoArea data={props.data} />
        </div>
      ) : null}
    </Section>
  );
}

function RoomInfoArea(props: { data: DepartmentWorkspaceResult }) {
  const { data } = props;
  const room = data.room;
  // 传信管：等待本部门回答的询问数（原型 v12 第 3.3 节，工单 #905）；为 0 时不写这一行
  const letters = lettersWaitingText(room.pipes?.letters_waiting);
  return (
    <>
      <KeyValue
        className="is-inline y10-ws-facts facts"
        items={[
          ["第几轮", data.room.crt.cycle === null || data.room.crt.cycle === undefined
            ? "—"
            : `第 ${data.room.crt.cycle} 轮`],
          // 已用时间与上限：department.workspace 不带这两项（project.loop 里有），没有数据显示「—」
          ["已用时间 / 上限", "—"],
          ["执行机器", room.machine ? room.machine : "—"],
          ["信箱", `${room.mailbox} 封未读指导`],
        ]}
      />
      {letters === null ? null : <p className="y10-note note ws-tube" data-ws-tube>{letters}</p>}
      {room.roles && room.roles.length > 0 ? (
        <div className="y10-ws-roles roles">
          <span className="y10-ws-k">房间里的角色</span>
          <ul>
            {room.roles.map((role) => (
              <li key={role.id}>
                <strong>{role.name}</strong>
                <span className="y10-status">{role.task || role.status}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {room.door ? (
        <p className="y10-ws-event event">
          <code>{room.door}</code>
          <span>{room.hold_card || "门口立起了牌子"}</span>
        </p>
      ) : null}
    </>
  );
}

// 当前生效模型的来源：取自生效模型的 selection_source
function selectionSourceLabel(value: string | null): string {
  if (value === "department_default") {
    return "部门默认";
  }
  if (value === "project_department_setting") {
    return "项目设置";
  }
  return show(value, "未上报");
}

// 三个部门各自的状态（原型 v12 第 3.1 节、三部门的循环结构第 2.1 节，工单 #905）：
// 标题区另起一行列出三个部门，本部门加粗；没有部门状态（事项没有进行中）时这一行不出现。
export function DepartmentsLine(props: {
  departments?: Record<string, DepartmentStateView> | null;
  department: string;
}) {
  const parts = departmentsLineParts(props.departments, props.department);
  if (parts === null) {
    return null;
  }
  return (
    <p className="y10-ws-item y10-ws-states department-line">
      <span className="y10-muted">三个部门</span>
      {parts.map((part, index) => (
        <Fragment key={part.text}>
          {index === 0 ? "　" : " · "}
          {part.current ? <strong>{part.text}</strong> : <span>{part.text}</span>}
        </Fragment>
      ))}
    </p>
  );
}

function TitleArea(props: { data: DepartmentWorkspaceResult; workItemTitle: string; scopeWorkItem: string | null; scopeNote: string; onOpenSettings: () => void }) {
  const data = props.data;
  const effective = data.effective;
  const lastCall = data.last_call === null ? null : dict(data.last_call);
  const info = DEPARTMENTS[data.department];
  // 去观测页时带着当前的范围（工单 #746）与本部门的筛选条件（工单 #801）：
  // 范围是项目级的一份，换页面不丢掉；部门是筛选条件，观测页按它只显示这个部门的请求
  const observeLink = paths.observe(data.project_id, { workItem: props.scopeWorkItem, department: data.department });
  // 部门状态：事项进行中时用查询给的这个部门的状态与原因；没有部门状态时按事项的结束方式写（工单 #905）
  const status = departmentStatusView(data);

  return (
    <section className="y10-block card y10-ws-head-block" id="ws-head-block">
      <div className="y10-ws-head section-head">
        <div className="y10-ws-titles">
          <p className="y10-eyebrow">部门工作间</p>
          <div className="y10-ws-title-row">
            <h1 className="y10-h1 title" style={{ margin: 0, fontSize: "20px", fontWeight: 700 }}>
              {departmentName(data.department)}部门
            </h1>
            <span className={`y10-status is-${status.kind}`}>{status.text}</span>
            {status.note === "" ? null : <small className="y10-muted">{status.note}</small>}
          </div>
          <p className="y10-ws-duty note">{info ? info.role : "部门职责未登记"}</p>
          <p className="y10-ws-item item">
            <span className="y10-muted">事项</span>
            <strong>{data.work_item_id === null
              ? "本项目没有进行中的事项"
              : `所选事项${props.workItemTitle === "" ? "" : ` ${props.workItemTitle}`}`}</strong>
            {props.scopeNote ? <span className="y10-muted">{props.scopeNote}</span> : null}
          </p>
          <DepartmentsLine departments={data.departments} department={data.department} />
          <div className="y10-ws-inline">
            <span className="y10-ws-k">当前生效模型</span>
            <strong>
              {effective.state === "unset"
                ? "未设置"
                : effective.state === "unusable"
                  ? `无法使用：${show(effective.message)}`
                  : show(optionalText(effective.model))}
            </strong>
            <span className="y10-tag tag">来源 {selectionSourceLabel(optionalText(effective.selection_source))}</span>
          </div>
        </div>
        <div className="y10-ws-head-actions">
          <button type="button" className="y10-btn is-small small" onClick={props.onOpenSettings}>
            部门设置
          </button>
          <a href={observeLink} className="y10-btn is-small small">
            本部门的模型请求
          </a>
        </div>
      </div>
      <KeyValue
        className="is-inline y10-ws-model kv"
        items={[
          // 部门状态与原因：与标题区同一个状态（工单 #905）
          ["部门状态", status.note === "" ? status.text : `${status.text}（${status.note}）`],
          ["当前生效的模型及来源", effective.state === "unset"
            ? "未设置"
            : effective.state === "unusable"
              ? `无法使用：${show(effective.message)}`
              : `${show(optionalText(effective.model))}（来源 ${selectionSourceLabel(optionalText(effective.selection_source))}）`],
          // 最近一次请求实际使用的模型：取自请求事件的调用目标（解析出的模型就是这次请求使用的模型），
          // 上游回报的实际模型只作为对照；这里显示调用目标的模型（设计说明第 9.3 节）
          ["最近一次请求实际使用的模型", lastCall === null
            ? "未上报"
            : show(optionalText(lastCall.requested_model) ?? optionalText(lastCall.actual_model))],
          ["协议", lastCall === null ? "未上报" : show(optionalText(lastCall.requested_protocol))],
          ["发送的档位", lastCall === null
            ? "未上报"
            : `请求 ${show(optionalText(lastCall.requested_tier))}，实际发送 ${show(optionalText(lastCall.sent_tier))}`],
        ]}
      />
      {/* 当前生效模型不具备本部门建议能力的角色，提醒显示在该角色的当前模型旁（第 5.6 节） */}
      {data.reminders.length > 0 ? (
        <p className="y10-note is-warn warn" role="status" data-testid={`workshop-reminder-${data.department}`}>
          {data.reminders.join("；")}
        </p>
      ) : null}
      <p className="y10-note note">
        工位：{departmentName(data.department)} Agent
      </p>
    </section>
  );
}

const INSPECT_TABS = [
  { id: "actions", label: "动作与回执" },
  { id: "context", label: "上下文" },
  { id: "department-setting", label: "部门设置" },
];

// 检查区：页签切换动作与回执、上下文清单与压缩记录、部门设置
function InspectArea(props: { app: ClientApp; data: DepartmentWorkspaceResult }) {
  const [tab, setTab] = useState("actions");
  const data = props.data;

  return (
    <Section title="检查区" note="房间下方按页签切换；每个页签的内容来自能力清单中登记的查询。">
      <div className="y10-tabs tabs" role="tablist">
        {INSPECT_TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            className={`y10-tab${tab === item.id ? " is-active active" : ""}`}
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>
      {tab === "actions" ? <Actions app={props.app} runId={data.run_id} /> : null}
      {tab === "context" ? <ContextPanel data={data} /> : null}
      {tab === "department-setting" ? <DepartmentSettingState data={data} /> : null}
    </Section>
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
    return <p className="y10-note note">正在读取动作列表</p>;
  }
  const rows = actions.data?.actions ?? [];
  const backgroundCommands = actions.data?.background_commands ?? [];

  return (
    <>
      <RunningBackgroundCommands commands={backgroundCommands} />
      {rows.length === 0 ? <Empty text={emptyOrFailureText(actions.error, "这次运行没有记录动作")} /> : (
        <Table
          head={ACTION_TABLE_HEAD}
          rows={rows.map((action) => {
            const eventId = action.receipt === null ? null : action.receipt.event_id;
            return [
              ...actionCells(action),
              <button
                type="button"
                className="y10-link link"
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

export function RunningBackgroundCommands(props: { commands: BackgroundCommandView[] }) {
  const running = props.commands.filter((cmd) => cmd.status === "running");
  if (running.length === 0) {
    return null;
  }
  return (
    <>
      <h3 className="y10-h3 sub">正在运行的后台命令（{running.length} 条）</h3>
      <Table
        head={["命令原文", "开始时间", "状态"]}
        rows={running.map((cmd) => [
          cmd.command,
          formatTime(cmd.started_at),
          "运行中",
        ])}
      />
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
      <h3 className="y10-h3 sub">上下文清单（{manifests.length} 条）</h3>
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
      <h3 className="y10-h3 sub">压缩记录（{compactions.length} 条）</h3>
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

// 部门设置：项目当前配置与所选请求实际使用的版本。
// 来源按这一段部门 Prompt 说：本项目写入还是内置默认（工单 #741）
function DepartmentSettingState(props: { data: DepartmentWorkspaceResult }) {
  const setting = props.data.department_setting;
  const written = promptWritten(setting.department_setting_configured, setting.configured_text);
  return (
    <>
      <KeyValue
        items={[
          ["项目当前配置", `第 ${setting.configured_version} 版`],
          ["部门 Prompt 来源", itemSource(written, "内置默认")],
          ["所选请求实际使用的版本", setting.used_version === null
            ? "这次运行还没有用到部门设置"
            : `第 ${setting.used_version} 版（事件 ${show(setting.used_event_id)}）`],
        ]}
      />
      <h3 className="y10-h3 sub">部门 Prompt 的内容</h3>
      <pre className="y10-pre raw">{setting.configured_text === "" ? "（空）" : setting.configured_text}</pre>
    </>
  );
}

// 部门消息与指导：询问一节列出本部门发出与收到的询问；消息日志每条可打开原始事件；
// 指导记录列出状态与原文，状态只有三种（已接收、已进入模型输入、已回答，工单 #906）
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
  // 本部门发出与收到的询问（原型 v12 第 3.3 节、三部门的循环结构第 4.7 节，工单 #905）：
  // 用 run.asks，写法与概览的询问一行相同（共用的 asks-text）
  const asks = useSnapshot<RunAsksResult>(
    props.app, "page.dept.asks", "run.asks", { run_id: data.run_id ?? "" }, data.run_id === null);
  const ownAsks = (asks.data?.asks ?? []).filter(
    (ask) => ask.requester === data.department || ask.recipient === data.department);
  const messages = list(data.messages);

  return (
    <>
      <div className="y10-ws-comms-grid">
        <div className="y10-ws-col">
          <Section title="询问" note="本部门发出与收到的询问：状态、询问链、时间与问题；有回答时写回答，没能回答写原因">
            {asks.error !== null ? (
              <p className="y10-note note" role="status">{readFailureText(asks.error)}</p>
            ) : ownAsks.length === 0 ? (
              <Empty text="这个事项里本部门还没有发出或收到询问" />
            ) : (
              <ul className="y10-ws-guidance ask-list ws-asks">
                {ownAsks.map((ask) => (
                  <li key={ask.id} data-depth={ask.depth} style={{ marginLeft: askIndent(ask) }}>{askLine(ask)}</li>
                ))}
              </ul>
            )}
          </Section>
          <Section title="部门消息" note="按日志位置取最近的一批；点击时间打开原始事件">
            {messages.length === 0 ? <Empty text="这个部门还没有消息" /> : (
              <ul className="y10-ws-log message-list">
                {messages.map((message) => {
                  const msgType = text(message.type);
                  const isUser = msgType.includes("user") || msgType.includes("guidance");
                  const isOther = msgType.includes("other") || msgType.includes("peer");
                  const cls = isUser ? "is-user" : isOther ? "is-other" : "is-self";
                  return (
                    <li key={text(message.event_id)} className={cls}>
                      <div className="y10-ws-log-meta input-head">
                        <button type="button" className="y10-link link" onClick={() => setOpenEvent(text(message.event_id))}>
                          {formatTime(optionalText(message.created_at))}
                        </button>
                        <span className="y10-ws-src msg-type">{msgType}</span>
                      </div>
                      <p className="y10-ws-log p msg-text">{show(text(message.text), "（这条消息没有正文，点上面的时间看原始事件）")}</p>
                    </li>
                  );
                })}
              </ul>
            )}
          </Section>
        </div>
        <div className="y10-ws-col">
          <GuidanceSection guidance={data.guidance} onOpenEvent={setOpenEvent}>
            {data.work_item_id && hasCommand(props.app, "guidance.send") ? (
              <div className="y10-ws-composer composer">
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
                <CommandFeedback submitted={props.command.submitted} problem={props.command.problem} />
              </div>
            ) : (
              <p className="y10-note note">
                {data.work_item_id === null ? "这个范围没有事项，不能发送指导" : "这台主机没有提供发送指导的操作"}
              </p>
            )}
          </GuidanceSection>
        </div>
      </div>
      {openEvent ? <EventDetail eventId={openEvent} onClose={() => setOpenEvent(null)} snapshot={detail} /> : null}
    </>
  );
}

// 指导一节（原型 v12 设计说明第 3.4 节、工单 #906）：说明写「部门正在工作时，指导在它的下一步作为通知加入；
// 部门在等待工作时，以这段指导开始一轮工作」。记录只写状态与原文，没有单独一行写部门的回答：
// 第三种状态「已回答」就是部门的回答，由主机在收到它的那一轮正常结束时写（#1039）。
// 发送框由调用处作为 children 传进来；这一节自己只认指导记录，单元测试按接口夹具直接渲染它。
export function GuidanceSection(props: {
  guidance: GuidanceRecord[];
  onOpenEvent: (eventId: string) => void;
  children?: ReactNode;
}) {
  return (
    <Section
      title="部门指导"
      note="部门正在工作时，指导在它的下一步作为通知加入；部门在等待工作时，以这段指导开始一轮工作"
    >
      {props.children}
      {props.guidance.length === 0 ? <Empty text="这个部门还没有指导记录" /> : (
        <ul className="y10-ws-guidance guidance-list">
          {props.guidance.map((record) => (
            <li key={record.guidance_id}>
              <div className="y10-ws-log-meta input-head">
                <strong>{label(GUIDANCE_STATUS, record.status)}</strong>
                <span className="y10-code byte-range">第 {record.version} 版</span>
                {record.applied_activation_id ? <span className="y10-code byte-range">已用于激活 {record.applied_activation_id}</span> : null}
                <button type="button" className="y10-link link" onClick={() => props.onOpenEvent(record.created_event_id)}>查看原始事件</button>
              </div>
              <p className="y10-ws-guidance p msg-text">{record.text}</p>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

// 部门设置弹窗（第 9.2 节）：标题为「本项目 · 某部门设置」，写入本项目该部门的项目部门设置。
// 模型、推理档位与部门 Prompt 三项一起保存；模型第一项为「跟随部门默认（当前：…）」，
// 档位第一项为「跟随」；保存以后提示「从本部门下一次模型请求起生效」；
// 版本冲突时服务端按 stale_base 拒绝，反馈提示重新读取（useCommand 的 rejection）。
function SettingsDialog(props: { app: ClientApp; data: DepartmentWorkspaceResult; onClose: () => void }) {
  const { data } = props;
  const [draft, setDraft, saved] = useDepartmentDraft(data.setting);
  const command = useCommand(props.app, pageKey([data.setting.version, draft.model, draft.tier, draft.text]));
  const canSave = hasCommand(props.app, "department_settings.save");
  // 保存结果带回的提醒（第 5.6 节「保存时」）：照常保存，提醒在设置旁显示
  const savedReminders = list(command.accepted?.reminders).map((item) => text(item)).filter((item) => item !== "");
  const reminders = [...data.reminders, ...savedReminders];

  return (
    <Modal title={`本项目 · ${departmentName(data.department)}设置`} onClose={props.onClose}>
      <p className="y10-note note">基准版本：第 {data.setting.version} 版；写入本项目的项目部门设置，不修改部门默认。</p>
      <DepartmentSettingsFields
        app={props.app}
        projectId={data.project_id}
        department={data.department}
        draft={draft}
        onDraft={setDraft}
        effective={data.effective}
        reminders={reminders}
        saved={saved}
      />
      {canSave ? (
        <DepartmentSettingsSave
          projectId={data.project_id}
          department={data.department}
          setting={data.setting}
          draft={draft}
          command={command}
          onSaved={props.onClose}
        />
      ) : (
        <p className="y10-note note">这台主机没有提供保存部门设置的操作</p>
      )}
      <CommandFeedback submitted={command.submitted} problem={command.problem} />
    </Modal>
  );
}
