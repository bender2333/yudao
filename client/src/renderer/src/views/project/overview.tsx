// 概览页（原型 v8 设计说明第 5.1 节，工单 #80）：项目摘要、循环画面的位置（#82 填入）、
// 当前事项（输入记录与处理进度、「追加需求」、「取消事项」；没有进行中的事项时提供「记录原文」
// 与「作为新事项开始」）、事项看板与流转记录（点击打开原始事件）。
// 页面上方不放决定区块：决定请求在大厅的板与文字列表里（v10 第 9 节，#175）。
// 数据只来自 project.overview、work_item.inputs、project.flow 与 event.detail 这几个已登记的查询。

import { useState } from "react";
import type { ClientApp } from "../../contract/client-app";
import type {
  AwayReport,
  EventDetailResult,
  ProjectFlowResult,
  ProjectOverviewResult,
  WorkItemCard,
  WorkItemInputsResult,
} from "../../api/generated/types.gen";
import { paths } from "../../shell/routing";
import { StatusMark } from "../../shell/kit";
import type { Route } from "../../shell/routing";
import { emptyOrFailureText, readFailureText } from "../../contract/read-failure";
import { CommandFeedback, Empty, EventDetail, KeyValue, Loading, Section, SubmitButton, Table, TextArea,
  TextInput, hasCommand, optionalText, pageKey, show, useDraft } from "./common";
import { FloorScreen } from "./floor-screen";
import { Timeline } from "../timeline/timeline";
import { ticksOf } from "../timeline/logic";
import { INPUT_KIND, STOP_REASON, WORK_ITEM_STATUS, departmentName, formatTime, label, progressLabel } from "./labels";
import { RestartOnboarding } from "./restart-onboarding";
import { WritebackState } from "./writeback";
import { BOARD_TITLES, boardColumns } from "./board";
import { type CommandState, rejectionLinks, useCommand, useSnapshot } from "./use-snapshot";

// 事项状态对应的原型标记（原型 v10 handlers/project.js 的 displayOf）：
// held 与 stopped 在原型图标里没有对应（held 无图标），这两项保留纯文字，界面不猜
const ITEM_STATUS_KIND: Record<string, string> = {
  not_started: "idle",
  in_progress: "running",
  adopted: "adopted",
  released_unsettled: "released",
  awaiting_initial_prd: "asking",
};

// 状态文字能用原型标记显示的才用标记；没有对应的（排队中、已停止）保留纯文字
function itemStatus(status: string): React.ReactNode {
  const kind = ITEM_STATUS_KIND[status];
  const text = label(WORK_ITEM_STATUS, status);
  return kind === undefined ? text : <StatusMark kind={kind} text={text} />;
}

export function OverviewPage(props: { app: ClientApp; route: Route; onNavigate: (hash: string) => void }) {
  const projectId = props.route.projectId ?? "";
  const workItem = props.route.workItemId;
  // 回放位置（全局位置）写在路径的 ?at= 中（设计说明第 3.3 节）；为 null 时是实时画面
  const at = props.route.at;
  const overview = useSnapshot<ProjectOverviewResult>(props.app, "page.overview", "project.overview", {
    project_id: projectId,
    work_item: workItem,
  });
  const flow = useSnapshot<ProjectFlowResult>(props.app, "page.flow", "project.flow", {
    project_id: projectId,
    work_item: workItem,
  });

  // 时间轴的刻度：本项目范围内的关键事实（home.away_report 按项目筛选）
  const report = useSnapshot<AwayReport>(props.app, "page.overview.timeline", "home.away_report", {
    range: "7d", project: projectId,
  });

  const data = overview.data;
  const items = data === null ? [] : data.work_items;
  const current = pickCurrent(items, workItem);
  const command = useCommand(props.app, pageKey([data?.version, data?.stats.total, workItem]));

  return (
    <div className={`page${at !== null ? " is-replay" : ""}`}>
      <Loading state={overview} />
      {overview.error !== null ? (
        // 读不出来就说读不出来：这一页本来有内容（工单 #775），不写空态，也不留一片空白
        <p className="y10-note note" role="status">{readFailureText(overview.error)}</p>
      ) : data ? (
        <>
          <Summary app={props.app} projectId={projectId} data={data} />
          <Section
            id="ov-loop"
            title="循环画面"
            note="三部门循环、包裹与管道；等待回答的决定贴在大厅的板上，点开就在画面里回答；右上角切换覆盖层，下方时间轴回放本项目的关键事实"
          >
            {at !== null ? (
              <p className="replay-banner" role="status">
                回放中 · {formatTime(atTimeOf(report.data, at))}
              </p>
            ) : null}
            <FloorScreen app={props.app} projectId={projectId} workItemId={workItem} at={at} />
            {report.data !== null ? (
              <Timeline
                facts={report.data.facts}
                fromPosition={report.data.range.from_position}
                fromAt={report.data.range.from_at}
                project={projectId}
                at={at}
                onPosition={(next) => props.onNavigate(paths.overviewAt(projectId, next, { workItem }))}
                onSelect={() => undefined}
                highlight={[]}
                liveNote={`实时画面 · ${ticksOf(report.data.facts, projectId).length} 条关键事实`}
              />
            ) : null}
          </Section>
          <CurrentItem app={props.app} projectId={projectId} item={current} command={command} startPoint={data.start_point ?? null} />
          <RestartOnboarding app={props.app} projectId={projectId} />
          <Board items={items} />
          <FlowTable app={props.app} flow={flow} />
        </>
      ) : null}
    </div>
  );
}

// 回放位置对应的时刻：范围内关键事实里位置相同的那条；没有时取范围的起点
function atTimeOf(report: AwayReport | null, at: number): string | null {
  if (report === null) return null;
  return report.facts.find((fact) => fact.position === at)?.at ?? report.range.from_at;
}

function Summary(props: { app: ClientApp; projectId: string; data: ProjectOverviewResult }) {
  const adoption = props.data.current_adoption;
  const baseline = adoption !== null && adoption.onboarding_baseline;
  return (
    <Section id="ov-summary" className="y10-ov-summary" title="项目摘要" note={`当前读取的是项目版本 ${props.data.version}`}>
      <KeyValue
        items={[
          ["名称", props.data.name],
          ["长期目标", show(props.data.goal, "没有填写")],
          ["当前成果", adoption === null ? "尚未采纳" : (
            <span>
              {show(adoption.summary, "没有摘要")}（采纳于 {formatTime(adoption.adopted_at)}，
              文件 {adoption.files.length} 项，检查 {adoption.check_names.length} 项，已知风险 {adoption.known_risks.length} 项）
            </span>
          )],
          // 写回状态（工单 #709）：采纳以后成果有没有回到仓库，没有写回时给出到设置页的入口
          ["写回", adoption === null ? "尚未采纳，没有需要写回的成果" : (
            <WritebackState
              app={props.app}
              projectId={props.projectId}
              adoptionId={adoption.adoption_id}
              onboardingBaseline={baseline}
            />
          )],
          // 接入已有项目时的建档基线（工单 #138，设计第 3.4 节）：快照来源与现有缺陷数
          ...(baseline ? [
            ["建档基线", "当前成果来自接入的代码快照：下面的来源与缺陷数按快照采集时的原样显示"],
            ["快照来源", show(adoption.snapshot_source, "未上报")],
            ["快照提交", provenanceText(adoption.snapshot_provenance)],
            ["现有缺陷", `现有缺陷 ${adoption.existing_defect_count} 项`],
          ] as [string, string][] : []),
          ["事项统计", `共 ${props.data.stats.total}：进行中 ${props.data.stats.in_progress}、排队中 ${props.data.stats.not_started}、已采纳 ${props.data.stats.adopted}、已放行 ${props.data.stats.released_unsettled}、已停止 ${props.data.stats.stopped}`],
        ]}
      />
      {/* 起点只在项目还没有采纳成果时写明：project.overview 在有采纳成果时不返回起点说明 */}
      {props.data.start_point ? <p className="y10-note note">{props.data.start_point}</p> : null}
    </Section>
  );
}

// 起点说明去掉前面的「起点：」：概览的摘要行原样写它，新建事项处把它接在「新事项从」后面（工单 #907）
function startPointText(value: string | null | undefined): string {
  const text = value ?? "";
  return text.startsWith("起点：") ? text.slice("起点：".length) : text;
}

// 快照的 git 来源（与决定卡片同一份文案）：没有仓库时写明采集时的目录内容
function provenanceText(value: { [key: string]: unknown } | null): string {
  const commit = value !== null && typeof value.commit === "string" ? value.commit : "";
  if (commit === "") {
    return "没有 git 仓库，快照采集时的目录内容";
  }
  const branch = value !== null && typeof value.branch === "string" && value.branch !== "" ? value.branch : "未知";
  return `git 提交 ${commit}（分支 ${branch}，${value?.dirty ? "有未提交的修改" : "没有未提交的修改"}）`;
}

// 当前事项：所选事项优先，否则进行中或等待确认初始 PRD 的一项；都找不到时不显示（界面不猜）。
// 建档事项等用户确认时没有在执行，但用户要在这一处放弃它并重新开始建档（工单 #136）
function pickCurrent(items: WorkItemCard[], selected: string | null): WorkItemCard | null {
  if (selected) {
    return items.find((item) => item.work_item_id === selected) ?? null;
  }
  return items.find((item) => item.status === "in_progress" || item.status === "awaiting_initial_prd") ?? null;
}

function CurrentItem(props: {
  app: ClientApp;
  projectId: string;
  item: WorkItemCard | null;
  command: CommandState;
  startPoint: string | null;
}) {
  const item = props.item;
  const inputs = useSnapshot<WorkItemInputsResult>(props.app, "page.inputs", "work_item.inputs", {
    project_id: props.projectId,
    work_item: item?.work_item_id ?? "",
  }, item === null);
  const [appendText, setAppendText] = useDraft(`input/${props.projectId}/${item?.work_item_id ?? "none"}/append`);

  if (item === null) {
    return (
      <Section title="当前事项" note="项目没有进行中的事项，顶栏也没有选中事项">
        <NewItemComposer
          projectId={props.projectId}
          command={props.command}
          canRecord={hasCommand(props.app, "material.record")}
          canCreate={hasCommand(props.app, "work_item.create")}
          startPoint={props.startPoint}
        />
      </Section>
    );
  }

  const data = inputs.data;
  // 读不出来与本来就没有输入记录是两句话（工单 #775）：失败说失败，空态说空态
  const processing = inputs.error !== null
    ? readFailureText(inputs.error)
    : data === null
      ? (inputs.loading ? "正在读取" : "没有输入记录")
      : `已接收第 ${data.input_version} 版输入，已由有效需求接纳到第 ${data.processed_input_version} 版`
        + `${data.input_version > data.processed_input_version ? "（还有输入没有接纳）" : ""}`;
  // 停止的事项没有在处理的部门，这一项不写进去
  const department = departmentName(item.department);
  const note = `${item.title}（事项标识 ${item.work_item_id}，第 ${item.round} 轮${department === "" ? "" : `，部门 ${department}`}）`;
  // 事项的进度：从成果推算（工单 #556）
  const progress = progressLabel(item.progress);
  return (
    <Section id="ov-current" title="当前事项" note={note}>
      <KeyValue
        items={[
          ["状态", <span key="status" className="y10-row">{itemStatus(item.status)}{progress === null ? null : <span className="y10-muted"> · {progress}</span>}</span>],
          ["待决问题", show(item.pending_question, "没有")],
          ["停止原因", item.stop_reason === null || item.stop_reason === "" ? "没有" : label(STOP_REASON, item.stop_reason)],
          ["未能开始", show(item.start_error, "没有")],
          ["处理进度", processing],
        ]}
      />
      <InputRecords app={props.app} inputs={data === null ? [] : data.inputs} loading={inputs.loading} error={inputs.error} />
      {item.status === "in_progress" && hasCommand(props.app, "work_item.append_input") ? (
        <div className="y10-ov-composer composer">
          <TextArea label="追加需求" value={appendText} onInput={setAppendText} />
          <SubmitButton
            label="追加需求"
            busy={props.command.busy}
            disabled={appendText.trim() === ""}
            onClick={() => {
              void props.command.submit("work_item.append_input", { work_item_id: item.work_item_id, text: appendText.trim() })
                .then((ok) => { if (ok) setAppendText(""); });
            }}
          />
          <CommandFeedback submitted={props.command.submitted} problem={props.command.problem} />
        </div>
      ) : null}
      {/* 建档事项等用户确认初始 PRD 时事项本身没有在执行，取消撤销那条决定请求（工单 #136），
          用户因此能回到「等待建档」并重新开始建档（设计第 3.1 节） */}
      {(item.status === "in_progress" || item.status === "awaiting_initial_prd")
        && hasCommand(props.app, "work_item.cancel") ? (
        <div className="y10-ov-composer composer">
          <SubmitButton
            label={item.status === "awaiting_initial_prd" ? "放弃本次建档" : "取消事项"}
            busy={props.command.busy}
            onClick={() => {
              void props.command.submit("work_item.cancel", { work_item_id: item.work_item_id, base_version: item.version });
            }}
          />
          <CommandFeedback submitted={props.command.submitted} problem={props.command.problem} />
        </div>
      ) : null}
    </Section>
  );
}

// 没有进行中的事项时的两个输入框：「记录原文」把文字存成本项目的材料，
// 「新的要求」用它开始一个新事项。两个框各有各的草稿与各自的状态：
// 写在一个框里的文字不会出现在另一个框里，提交一个框只清空那个框（工单 #652）。
export function NewItemComposer(props: {
  projectId: string;
  command: CommandState;
  canRecord: boolean;
  canCreate: boolean;
  /** 项目的起点说明（project.overview 的 start_point，以「起点：」开头）；没有时新建事项处不写这句话 */
  startPoint?: string | null;
}) {
  const [recordText, setRecordText] = useDraft(`input/${props.projectId}/none/record`);
  const [requirementText, setRequirementText] = useDraft(`input/${props.projectId}/none/requirement`);
  const [newTitle, setNewTitle] = useState("");

  return (
    <>
      <div className="y10-ov-composer composer">
        <TextArea label="记录原文（保存为本项目的材料）" value={recordText} onInput={setRecordText} />
        {props.canRecord ? (
          <SubmitButton
            label="记录原文"
            busy={props.command.busy}
            disabled={recordText.trim() === ""}
            onClick={() => {
              void props.command.submit("material.record", { project_id: props.projectId, text: recordText.trim() })
                .then((ok) => { if (ok) setRecordText(""); });
            }}
          />
        ) : <p className="y10-note note">这台主机没有提供记录原文的操作</p>}
      </div>
      <div className="y10-ov-composer composer">
        <TextArea label="新的要求" value={requirementText} onInput={setRequirementText} />
        <TextInput label="事项标题（可以留空）" value={newTitle} onInput={setNewTitle} />
        {props.canCreate ? (
          <SubmitButton
            label="作为新事项开始"
            busy={props.command.busy}
            disabled={requirementText.trim() === ""}
            onClick={() => {
              const body: Record<string, unknown> = { project_id: props.projectId, text: requirementText.trim() };
              if (newTitle.trim() !== "") {
                body.title = newTitle.trim();
              }
              void props.command.submit("work_item.create", body).then((ok) => { if (ok) { setRequirementText(""); setNewTitle(""); } });
            }}
          />
        ) : <p className="y10-note note">这台主机没有提供新建事项的操作</p>}
        {/* 新事项从项目的起点开始（工单 #907）：起点说明取自概览已有的 start_point，去掉前面的「起点：」 */}
        {startPointText(props.startPoint) === "" ? null : (
          <p className="y10-note note">新事项从{startPointText(props.startPoint)}开始</p>
        )}
        <CommandFeedback submitted={props.command.submitted} problem={props.command.problem} />
        {(() => {
          const links = rejectionLinks(props.command.problem, props.projectId);
          return links.length > 0 ? (
            <div className="y10-row row-actions">
              {links.map((link) => (
                <button key={link.hash} type="button" className="y10-link link" onClick={() => { window.location.hash = link.hash; }}>
                  {link.label}
                </button>
              ))}
            </div>
          ) : null;
        })()}
      </div>
    </>
  );
}

// 输入记录：版本、字节范围与原文；点击打开接收这条输入的原始事件
function InputRecords(props: {
  app: ClientApp;
  inputs: WorkItemInputsResult["inputs"];
  loading: boolean;
  /** 读取失败时的原因；有它时不说「没有输入记录」（工单 #775） */
  error: string | null;
}) {
  const [openEvent, setOpenEvent] = useState<string | null>(null);
  const detail = useSnapshot<EventDetailResult>(
    props.app,
    openEvent ? `page.overview.inputs.event.${openEvent}` : "page.overview.inputs.event.none",
    "event.detail",
    { event_id: openEvent ?? "" },
    openEvent === null,
  );

  if (props.inputs.length === 0) {
    return props.loading
      ? <p className="y10-note note">正在读取输入记录</p>
      : <Empty text={emptyOrFailureText(props.error, "这个事项没有输入记录")} />;
  }

  return (
    <>
      <ul className="y10-ov-inputs input-list">
        {props.inputs.map((input) => (
          <li key={input.input_id}>
            <div className="y10-ov-input-head input-head">
              <strong>第 {input.version} 版</strong>
              <span className="y10-code byte-range">字节 {input.byte_start}–{input.byte_end}</span>
              <span className="y10-code byte-range">{label(INPUT_KIND, input.kind)}</span>
              <button type="button" className="y10-link link" onClick={() => setOpenEvent(input.created_event_id)}>查看原始事件</button>
            </div>
            <p className="y10-ov-input-text raw-text">{input.text}</p>
            <p className="y10-muted byte-range">来自事件 {input.created_event_id}，git 版本 {optionalText(input.git_version?.commit) ?? "未上报"}</p>
          </li>
        ))}
      </ul>
      {openEvent ? <EventDetail eventId={openEvent} onClose={() => setOpenEvent(null)} snapshot={detail} /> : null}
    </>
  );
}

export function Board(props: { items: WorkItemCard[] }) {
  const columns = boardColumns(props.items);

  return (
    <Section id="ov-board" title="事项看板" note="卡片显示标题、状态、所在部门与轮次；排队中的顺序就是执行顺序">
      {props.items.length === 0 ? <Empty text="项目还没有事项" /> : (
        <div className="y10-ov-board board">
          {BOARD_TITLES.map(([key, title]) => (
            <div key={key} className="y10-ov-board-col board-col">
              <h3>{title}（{columns[key].length}）</h3>
              {columns[key].map((item) => (
                <article key={item.work_item_id} className="y10-ov-card board-card">
                  <strong>{item.title}</strong>
                  <div className="y10-ov-card-meta card-meta">
                    <span>{itemStatus(item.status)}</span>
                    {departmentName(item.department) === "" ? null : <span>{departmentName(item.department)}</span>}
                    <span>第 {item.round} 轮</span>
                  </div>
                  {item.pending_question ? <p className="y10-muted card-note">待决问题：{item.pending_question}</p> : null}
                  {item.stop_reason ? <p className="y10-muted card-note">停止原因：{label(STOP_REASON, item.stop_reason)}</p> : null}
                  {item.start_error ? <p className="y10-muted card-note">未能开始：{item.start_error}</p> : null}
                </article>
              ))}
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}

// 流转记录：时间、方向、类型、内容与状态；缺陷记录行用醒目颜色，点击打开原始事件
function FlowTable(props: { app: ClientApp; flow: { data: ProjectFlowResult | null; loading: boolean; error: string | null } }) {
  const [openEvent, setOpenEvent] = useState<string | null>(null);
  const detail = useSnapshot<EventDetailResult>(
    props.app,
    openEvent ? `page.overview.flow.event.${openEvent}` : "page.overview.flow.event.none",
    "event.detail",
    { event_id: openEvent ?? "" },
    openEvent === null,
  );
  const records = props.flow.data?.records ?? [];

  if (props.flow.loading && props.flow.data === null) {
    return (
      <Section id="ov-flow" title="流转记录">
        <p className="y10-note note">正在读取流转记录</p>
      </Section>
    );
  }

  return (
    <Section id="ov-flow" title="流转记录" note="点击时间打开原始事件；缺陷记录行用醒目的颜色标出">
      {records.length === 0 ? <Empty text={emptyOrFailureText(props.flow.error, "项目还没有流转记录")} /> : (
        <Table
          head={["时间", "方向", "类型", "内容", "状态"]}
          rows={records.map((record) => [
            <button type="button" className="y10-link link" key={record.flow_id} onClick={() => setOpenEvent(record.event_id)}>
              {formatTime(record.created_at)}
            </button>,
            `${departmentName(record.direction_from) || "没有"} → ${departmentName(record.direction_to) || "没有"}`,
            record.kind,
            record.content,
            <span key={`${record.flow_id}-status`} className={record.status === "已退回" ? "rework" : undefined}>
              {record.status}
            </span>,
          ])}
        />
      )}
      {openEvent ? <EventDetail eventId={openEvent} onClose={() => setOpenEvent(null)} snapshot={detail} /> : null}
    </Section>
  );
}
