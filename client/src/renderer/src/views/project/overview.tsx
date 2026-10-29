// 概览页（原型 v8 设计说明第 5.1 节，工单 #80）：项目摘要、循环画面的位置（#82 填入）、
// 当前事项（输入记录与处理进度、「追加需求」、「取消事项」；没有进行中的事项时提供「记录原文」
// 与「作为新事项开始」）、事项看板与流转记录（点击打开原始事件）。
// 页面上方不放决定区块：决定请求在大厅的板与文字列表里（v10 第 9 节，#175）。
// 数据只来自 project.overview、work_item.inputs、project.flow 与 event.detail 这几个已登记的查询。

import { useEffect, useMemo, useRef, useState } from "react";
import type { ClientApp } from "../../contract/client-app";
import type {
  AwayReport,
  EventDetailResult,
  ProjectFlowResult,
  ProjectOverviewResult,
  RunAsksResult,
  WorkItemCard,
  WorkItemInputsResult,
  WorkItemStats,
} from "../../api/generated/types.gen";
import { paths } from "../../shell/routing";
import { StatusMark } from "../../shell/kit";
import type { Route } from "../../shell/routing";
import { emptyOrFailureText, readFailureText } from "../../contract/read-failure";
import { CommandFeedback, Empty, EventDetail, KeyValue, Loading, Section, StopNote, SubmitButton, Table, TextArea,
  TextInput, hasCommand, optionalText, pageKey, show, useDraft } from "./common";
import { FloorScreen } from "./floor-screen";
import { Timeline } from "../timeline/timeline";
import { scopeAtTick, ticksOf } from "../timeline/logic";
import { INPUT_KIND, STOP_REASON, WORK_ITEM_STATUS, departmentName, departmentLine, formatTime, label,
  progressLabel, workingDepartmentsText } from "./labels";
import { askIndent, askLine } from "./asks-text";
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
  // 刻度带着各自所属的事项（ticksOf 从关键事实带过来），点刻度时按它决定范围（工单 #1217）
  const ticks = useMemo(
    () => (report.data === null ? [] : ticksOf(report.data.facts, projectId)),
    [report.data, projectId],
  );

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
                // 换范围与换位置在同一次导航里完成（工单 #1217）：刻度的位置属于时间轴，事项范围
                // 取刻度自己的事项；两者一起写进地址，页面不先按当前范围发出一次读不到的请求再纠正
                onPosition={(next) => props.onNavigate(paths.overviewAt(projectId, next, { workItem: scopeAtTick(ticks, workItem, next) }))}
                onSelect={() => undefined}
                highlight={[]}
                liveNote={`实时画面 · ${ticks.length} 条关键事实`}
              />
            ) : null}
          </Section>
          <CurrentItem
            app={props.app}
            projectId={projectId}
            item={current}
            command={command}
            startPoint={data.start_point ?? null}
            onNavigate={props.onNavigate}
          />
          <Asks app={props.app} item={current} />
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
          ["事项统计", statsText(props.data.stats)],
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

// 事项统计那一行（工单 #1160）：每一项只写这一种状态，不写累计。
// released_unsettled 是「放行了、还没采纳」这一个状态，所以写「放行待采纳」，不写「已放行」；
// held（成果挂起）也要有一项，否则各项加起来不等于「共 N」。看板的列名另有一套，不跟这一行。
// 服务端的统计没有 awaiting_initial_prd（要改接口快照才能加，本工单不加）：等待确认初始 PRD 的事项
// 因此只计入「共 N」，这一行不单列它，界面不猜它的数量。
export function statsText(stats: WorkItemStats): string {
  return `共 ${stats.total}：进行中 ${stats.in_progress}、排队中 ${stats.not_started}、已采纳 ${stats.adopted}`
    + `、放行待采纳 ${stats.released_unsettled}、成果挂起 ${stats.held}、已停止 ${stats.stopped}`;
}

// 命令受理回执里的标识：project.create 带 project_id、work_item.create 带 work_item_id（都在 refs 里），
// 没有这一项时返回空串（工单 #1160 用它转到刚建好的项目与事项）
function receiptId(accepted: Record<string, unknown> | null, key: string): string {
  const refs = accepted?.["refs"];
  if (refs === null || refs === undefined || typeof refs !== "object") {
    return "";
  }
  const value = (refs as Record<string, unknown>)[key];
  return typeof value === "string" ? value : "";
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
  onNavigate: (hash: string) => void;
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
          onNavigate={props.onNavigate}
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
  // 事项的进度：从成果推算（工单 #556）；部门状态按三个部门各自写（工单 #904，下面那一行）
  const progress = progressLabel(item.progress);
  const note = `${item.title}（事项标识 ${item.work_item_id}，第 ${item.round} 轮）`;
  return (
    <Section id="ov-current" title="当前事项" note={note}>
      <KeyValue
        items={[
          ["状态", <span key="status" className="y10-row">{itemStatus(item.status)}{progress === null ? null : <span className="y10-muted"> · {progress}</span>}</span>],
          ["待决问题", show(item.pending_question, "没有")],
          ["停止原因", item.stop_reason === null || item.stop_reason === "" ? "没有" : label(STOP_REASON, item.stop_reason)],
          // 停止说明（工单 #1162）：让事项停下的那条错误的原文，写在停止原因下面
          ["停止说明", <StopNote key="stop-note" note={item.stop_note} empty="没有" />],
          ["未能开始", show(item.start_error, "没有")],
          ["处理进度", processing],
        ]}
      />
      {/* 三个部门各自的状态与原因（三部门的循环结构第 2.1 节，工单 #904）：没有 departments 时照旧写所在部门 */}
      <p className="y10-note note department-line">{departmentLine(item.departments, item.department)}</p>
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

// 询问（三部门的循环结构第 4.7 节、原型 v12 第 3.3 节，工单 #904）：这个事项里的询问，一次一行，
// 写状态、询问链、回问标记、时间与问题，有回答时写回答（附带 PRD 时标版本），没能回答写原因；回问按深度缩进。
// 没有询问时这一节不出现。
function Asks(props: { app: ClientApp; item: WorkItemCard | null }) {
  const runId = props.item?.run_id ?? "";
  const asks = useSnapshot<RunAsksResult>(props.app, "page.overview.asks", "run.asks", { run_id: runId }, props.item === null);
  const rows = asks.data?.asks ?? [];
  if (asks.error !== null) {
    return (
      <Section id="ov-asks" title="询问">
        <p className="y10-note note" role="status">{readFailureText(asks.error)}</p>
      </Section>
    );
  }
  if (rows.length === 0) {
    return null;
  }
  return (
    <Section id="ov-asks" title="询问" note="这个事项里的询问：状态、询问链、时间与问题；有回答时写回答，没能回答写原因">
      <ul className="y10-ov-asks ask-list">
        {rows.map((ask) => (
          <li key={ask.id} data-depth={ask.depth} style={{ marginLeft: askIndent(ask) }}>{askLine(ask)}</li>
        ))}
      </ul>
    </Section>
  );
}

// 没有进行中的事项时的输入（原型 v13 的 composerHtml，工单 #1160）：一个框「新的想法或材料」加一个
// 「事项标题（可选）」，一句说明写清两个按钮各做什么，两个按钮读同一个框。框为空时两个按钮都不可用
// （不说原因，原型的做法就是不填不能点）。草稿按项目保存，换项目以后各是各的。
// 「作为新事项开始」成功以后转到这个事项（地址带 ?w=，原型 v13 的 ov.create）。
export function NewItemComposer(props: {
  projectId: string;
  command: CommandState;
  canRecord: boolean;
  canCreate: boolean;
  /** 项目的起点说明（project.overview 的 start_point，以「起点：」开头）；没有时新建事项处不写这句话 */
  startPoint?: string | null;
  onNavigate: (hash: string) => void;
}) {
  const [text, setText] = useDraft(`input/${props.projectId}/none/new`);
  const [title, setTitle] = useDraft(`input/${props.projectId}/none/title`);
  const empty = text.trim() === "";
  // 转事项看的是受理回执里的 work_item_id：提交之前先立一个标记，回执换成新的一份时转一次，
  // 不因为页面上还留着上一次的回执而自己跳走
  const creating = useRef(false);
  const usedReceipt = useRef<Record<string, unknown> | null>(null);
  const accepted = props.command.accepted;
  useEffect(() => {
    if (!creating.current || accepted === null || accepted === usedReceipt.current) {
      return;
    }
    const workItemId = receiptId(accepted, "work_item_id");
    if (workItemId === "") {
      return;
    }
    creating.current = false;
    usedReceipt.current = accepted;
    props.onNavigate(paths.overview(props.projectId, { workItem: workItemId }));
  }, [accepted]);

  return (
    <div className="y10-ov-composer composer">
      <TextArea label="新的想法或材料" value={text} onInput={setText} />
      <TextInput label="事项标题（可选）" value={title} onInput={setTitle} placeholder="留空时取原文第一行" />
      {/* 新事项从项目的起点开始（工单 #907）：起点说明取自概览已有的 start_point，去掉前面的「起点：」 */}
      {startPointText(props.startPoint) === "" ? null : (
        <p className="y10-note note">新事项从{startPointText(props.startPoint)}开始</p>
      )}
      <p className="y10-note note">「记录原文」只保存材料，不调用模型；「作为新事项开始」进入产品部门</p>
      <div className="y10-row row-actions">
        {props.canRecord ? (
          <SubmitButton
            label="记录原文"
            busy={props.command.busy}
            disabled={empty}
            onClick={() => {
              void props.command.submit("material.record", { project_id: props.projectId, text: text.trim() })
                .then((ok) => { if (ok) setText(""); });
            }}
          />
        ) : <p className="y10-note note">这台主机没有提供记录原文的操作</p>}
        {props.canCreate ? (
          <SubmitButton
            label="作为新事项开始"
            busy={props.command.busy}
            disabled={empty}
            onClick={() => {
              const body: Record<string, unknown> = { project_id: props.projectId, text: text.trim() };
              if (title.trim() !== "") {
                body.title = title.trim();
              }
              creating.current = true;
              void props.command.submit("work_item.create", body)
                .then((ok) => {
                  // 被拒绝时不转（回执没有换成新的一份，转不上去）；框里的文字留着，改完可以再提交
                  if (!ok) {
                    creating.current = false;
                    return;
                  }
                  setText("");
                  setTitle("");
                });
            }}
          />
        ) : <p className="y10-note note">这台主机没有提供新建事项的操作</p>}
      </div>
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
    <Section id="ov-board" title="事项看板" note="卡片显示标题、状态、正在工作的部门与轮次；排队中的顺序就是执行顺序">
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
                    {/* 正在工作的部门（工单 #904）：一轮工作中或询问中的部门；没有时不写这一格（工单 #842 的旧数据显示所在部门） */}
                    {workingDepartmentsText(item) === "" ? null : <span>{workingDepartmentsText(item)}</span>}
                    <span>第 {item.round} 轮</span>
                  </div>
                  {item.pending_question ? <p className="y10-muted card-note">待决问题：{item.pending_question}</p> : null}
                  {item.stop_reason ? <p className="y10-muted card-note">停止原因：{label(STOP_REASON, item.stop_reason)}</p> : null}
                  {/* 停止说明（工单 #1162）：停在停止原因下面，长的折起来可以展开 */}
                  <StopNote note={item.stop_note} block />
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
