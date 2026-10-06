// 概览页（原型 v8 设计说明第 5.1 节，工单 #80）：项目摘要、循环画面的位置（#82 填入）、
// 当前事项（输入记录与处理进度、「追加需求」、「取消事项」；没有进行中的事项时提供「记录原文」
// 与「作为新事项开始」）、事项看板与流转记录（点击打开原始事件）。
// 页面上方不放决定区块：决定请求在大厅的板与文字列表里（v9 第 9 节，#175）。
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
import type { Route } from "../../shell/routing";
import { CommandFeedback, Empty, EventDetail, KeyValue, Loading, Section, SubmitButton, Table, TextArea,
  TextInput, hasCommand, optionalText, pageKey, show, useDraft } from "./common";
import { FloorScreen } from "./floor-screen";
import { Timeline } from "../timeline/timeline";
import { ticksOf } from "../timeline/logic";
import { INPUT_KIND, PHASE_LABELS, STOP_REASON, WORK_ITEM_STATUS, departmentName, formatTime, label } from "./labels";
import { RestartOnboarding } from "./restart-onboarding";
import { BOARD_TITLES, boardColumns } from "./board";
import { type CommandState, rejectionLinks, useCommand, useSnapshot } from "./use-snapshot";

export function OverviewPage(props: { app: ClientApp; route: Route }) {
  const projectId = props.route.projectId ?? "";
  const workItem = props.route.workItemId;
  // 回放位置（全局位置）：为 null 时是实时画面（设计说明第 5.5 节）
  const [at, setAt] = useState<number | null>(null);
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
      {data ? (
        <>
          <Summary data={data} />
          <Section title="循环画面" note="项目楼层与管道；下方时间轴回放本项目的关键事实">
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
                onPosition={setAt}
                onSelect={() => undefined}
                highlight={[]}
                liveNote={`实时画面 · ${ticksOf(report.data.facts, projectId).length} 条关键事实`}
              />
            ) : null}
          </Section>
          <CurrentItem app={props.app} projectId={projectId} item={current} command={command} />
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

function Summary(props: { data: ProjectOverviewResult }) {
  const adoption = props.data.current_adoption;
  return (
    <Section title="项目摘要" note={`当前读取的是项目版本 ${props.data.version}`}>
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
          ["事项统计", `共 ${props.data.stats.total}：进行中 ${props.data.stats.in_progress}、排队中 ${props.data.stats.not_started}、已采纳 ${props.data.stats.adopted}、已放行 ${props.data.stats.released_unsettled}、已停止 ${props.data.stats.stopped}`],
        ]}
      />
      {/* 起点只在项目还没有采纳成果时写明：project.overview 在有采纳成果时不返回起点说明 */}
      {props.data.start_point ? <p className="note">{props.data.start_point}</p> : null}
    </Section>
  );
}

// 当前事项：所选事项优先，否则进行中的一项；都找不到时不显示（界面不猜）
function pickCurrent(items: WorkItemCard[], selected: string | null): WorkItemCard | null {
  if (selected) {
    return items.find((item) => item.work_item_id === selected) ?? null;
  }
  return items.find((item) => item.status === "in_progress") ?? null;
}

function CurrentItem(props: {
  app: ClientApp;
  projectId: string;
  item: WorkItemCard | null;
  command: CommandState;
}) {
  const item = props.item;
  const inputs = useSnapshot<WorkItemInputsResult>(props.app, "page.inputs", "work_item.inputs", {
    project_id: props.projectId,
    work_item: item?.work_item_id ?? "",
  }, item === null);
  const [appendText, setAppendText] = useDraft(`input/${props.projectId}/${item?.work_item_id ?? "none"}/append`);
  const [recordText, setRecordText] = useDraft(`input/${props.projectId}/${item?.work_item_id ?? "none"}/record`);
  const [newTitle, setNewTitle] = useState("");

  if (item === null) {
    return (
      <Section title="当前事项" note="项目没有进行中的事项，顶栏也没有选中事项">
        <div className="composer">
          <TextArea label="记录原文（保存为本项目的材料）" value={recordText} onInput={setRecordText} />
          {hasCommand(props.app, "material.record") ? (
            <SubmitButton
              label="记录原文"
              busy={props.command.busy}
              disabled={recordText.trim() === ""}
              onClick={() => {
                void props.command.submit("material.record", { project_id: props.projectId, text: recordText.trim() })
                  .then((ok) => { if (ok) setRecordText(""); });
              }}
            />
          ) : <p className="note">这台主机没有提供记录原文的操作</p>}
        </div>
        <div className="composer">
          <TextArea label="新的要求" value={recordText} onInput={setRecordText} />
          <TextInput label="事项标题（可以留空）" value={newTitle} onInput={setNewTitle} />
          {hasCommand(props.app, "work_item.create") ? (
            <SubmitButton
              label="作为新事项开始"
              busy={props.command.busy}
              disabled={recordText.trim() === ""}
              onClick={() => {
                const body: Record<string, unknown> = { project_id: props.projectId, text: recordText.trim() };
                if (newTitle.trim() !== "") {
                  body.title = newTitle.trim();
                }
                void props.command.submit("work_item.create", body).then((ok) => { if (ok) { setRecordText(""); setNewTitle(""); } });
              }}
            />
          ) : <p className="note">这台主机没有提供新建事项的操作</p>}
          <p className="note">要把已有代码目录作为起点，先在设置页登记源目录。</p>
          <CommandFeedback submitted={props.command.submitted} rejection={props.command.rejection} />
          {(() => {
            const links = rejectionLinks(props.command.rejection, props.projectId);
            return links.length > 0 ? (
              <div className="row-actions">
                {links.map((link) => (
                  <button key={link.hash} type="button" className="link" onClick={() => { window.location.hash = link.hash; }}>
                    {link.label}
                  </button>
                ))}
              </div>
            ) : null;
          })()}
        </div>
      </Section>
    );
  }

  const data = inputs.data;
  const processing = data === null
    ? (inputs.loading ? "正在读取" : "没有输入记录")
    : `已接收第 ${data.input_version} 版输入，已由有效需求接纳到第 ${data.processed_input_version} 版`
      + `${data.input_version > data.processed_input_version ? "（还有输入没有接纳）" : ""}`;
  // 停止的事项没有在处理的部门，这一项不写进去
  const department = departmentName(item.department);
  const note = `${item.title}（事项标识 ${item.work_item_id}，第 ${item.round} 轮${department === "" ? "" : `，部门 ${department}`}）`;
  return (
    <Section title="当前事项" note={note}>
      <KeyValue
        items={[
          ["状态", `${label(WORK_ITEM_STATUS, item.status)}${item.phase ? ` · ${label(PHASE_LABELS, item.phase)}` : ""}`],
          ["待决问题", show(item.pending_question, "没有")],
          ["停止原因", item.stop_reason === null || item.stop_reason === "" ? "没有" : label(STOP_REASON, item.stop_reason)],
          ["未能开始", show(item.start_error, "没有")],
          ["处理进度", processing],
        ]}
      />
      <InputRecords app={props.app} inputs={data === null ? [] : data.inputs} loading={inputs.loading} />
      {item.status === "in_progress" && hasCommand(props.app, "work_item.append_input") ? (
        <div className="composer">
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
          <CommandFeedback submitted={props.command.submitted} rejection={props.command.rejection} />
        </div>
      ) : null}
      {item.status === "in_progress" && hasCommand(props.app, "work_item.cancel") ? (
        <div className="composer">
          <SubmitButton
            label="取消事项"
            busy={props.command.busy}
            onClick={() => {
              void props.command.submit("work_item.cancel", { work_item_id: item.work_item_id, base_version: item.version });
            }}
          />
          <CommandFeedback submitted={props.command.submitted} rejection={props.command.rejection} />
        </div>
      ) : null}
    </Section>
  );
}

// 输入记录：版本、字节范围与原文；点击打开接收这条输入的原始事件
function InputRecords(props: { app: ClientApp; inputs: WorkItemInputsResult["inputs"]; loading: boolean }) {
  const [openEvent, setOpenEvent] = useState<string | null>(null);
  const detail = useSnapshot<EventDetailResult>(
    props.app,
    openEvent ? `page.overview.inputs.event.${openEvent}` : "page.overview.inputs.event.none",
    "event.detail",
    { event_id: openEvent ?? "" },
    openEvent === null,
  );

  if (props.inputs.length === 0) {
    return props.loading ? <p className="note">正在读取输入记录</p> : <Empty text="这个事项没有输入记录" />;
  }

  return (
    <>
      <ul className="input-list">
        {props.inputs.map((input) => (
          <li key={input.input_id}>
            <div className="input-head">
              <strong>第 {input.version} 版</strong>
              <span className="byte-range">字节 {input.byte_start}–{input.byte_end}</span>
              <span className="byte-range">{label(INPUT_KIND, input.kind)}</span>
              <button type="button" className="link" onClick={() => setOpenEvent(input.created_event_id)}>查看原始事件</button>
            </div>
            <p className="raw-text">{input.text}</p>
            <p className="byte-range">来自事件 {input.created_event_id}，git 版本 {optionalText(input.git_version?.commit) ?? "未上报"}</p>
          </li>
        ))}
      </ul>
      {openEvent ? <EventDetail eventId={openEvent} onClose={() => setOpenEvent(null)} snapshot={detail} /> : null}
    </>
  );
}

function Board(props: { items: WorkItemCard[] }) {
  const columns = boardColumns(props.items);

  return (
    <Section title="事项看板" note="排队中一列的顺序就是执行顺序">
      {props.items.length === 0 ? <Empty text="项目还没有事项" /> : (
        <div className="board">
          {BOARD_TITLES.map(([key, title]) => (
            <div key={key} className="board-col">
              <h3>{title}（{columns[key].length}）</h3>
              {columns[key].map((item) => (
                <article key={item.work_item_id} className="board-card">
                  <strong>{item.title}</strong>
                  <div className="card-meta">
                    <span>{label(WORK_ITEM_STATUS, item.status)}</span>
                    {departmentName(item.department) === "" ? null : <span>{departmentName(item.department)}</span>}
                    <span>第 {item.round} 轮</span>
                  </div>
                  {item.pending_question ? <p className="card-note">待决问题：{item.pending_question}</p> : null}
                  {item.stop_reason ? <p className="card-note">停止原因：{label(STOP_REASON, item.stop_reason)}</p> : null}
                  {item.start_error ? <p className="card-note">未能开始：{item.start_error}</p> : null}
                </article>
              ))}
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}

// 流转记录：时间、方向、类型、内容与状态；返工行用醒目颜色，点击打开原始事件
function FlowTable(props: { app: ClientApp; flow: { data: ProjectFlowResult | null; loading: boolean } }) {
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
      <Section title="流转记录">
        <p className="note">正在读取流转记录</p>
      </Section>
    );
  }

  return (
    <Section title="流转记录" note="点击时间打开原始事件">
      {records.length === 0 ? <Empty text="项目还没有流转记录" /> : (
        <Table
          head={["时间", "方向", "类型", "内容", "状态"]}
          rows={records.map((record) => [
            <button type="button" className="link" key={record.flow_id} onClick={() => setOpenEvent(record.event_id)}>
              {formatTime(record.created_at)}
            </button>,
            `${departmentName(record.direction_from) || "没有"} → ${departmentName(record.direction_to) || "没有"}`,
            record.kind,
            record.content,
            <span key={`${record.flow_id}-status`} className={record.kind === "返工" || record.status === "已退回" ? "rework" : undefined}>
              {record.status}
            </span>,
          ])}
        />
      )}
      {openEvent ? <EventDetail eventId={openEvent} onClose={() => setOpenEvent(null)} snapshot={detail} /> : null}
    </Section>
  );
}
