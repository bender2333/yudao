// 资料页（原型 v10 设计说明第 7.3 节，工单 #380）：只读，先按事项索引，再按 intend、PRD、
// 交付、质检、项目材料的顺序查看。数据仍来自 project.overview 与 work_item.materials 两个已登记的查询。
// 范围跟随顶栏的 ?w=；没有选中事项时取进行中的一项，并在索引卡上写明当前查看的是哪一项。
// 接入已有项目的建档各轮（工单 #138，设计第 3.3、4.3 节）按轮列出初始 PRD、结构说明、基线核验
// 与确认记录；旧版本的执行（原型里的 mt-oldruns）在所属工作包登记查询以后加入。

import { useEffect, useState, type CSSProperties } from "react";
import type { ClientApp } from "../../contract/client-app";
import type { DeliveryFileResult, EventDetailResult, ProjectOverviewResult, WorkItemMaterialsResult,
  WorkItemCard } from "../../api/generated/types.gen";
import { paths, type Route } from "../../shell/routing";
import { StatusMark } from "../../shell/kit";
import { ITEM_COLORS } from "../../pixel/registry";
import { Empty, KeyValue, Loading, Section, Tag, dict, list, show, text } from "./common";
import { departmentName, formatTime, label, WORK_ITEM_STATUS, WORK_ITEM_STATUS_KIND } from "./labels";
import { fileDownload } from "./materials-download";
import { originalView, readView } from "./materials-read";
import { useSnapshot } from "./use-snapshot";
import { readFailureText } from "../../contract/read-failure";
import { scopeName } from "./scope-name";

const COUNT_KINDS = [
  ["intend", "intend"],
  ["prd", "PRD"],
  ["delivery", "交付"],
  ["qa", "质检"],
  ["note", "材料"],
  ["onboarding", "建档"],
] as const;

export function MaterialsPage(props: { app: ClientApp; route: Route; onNavigate: (hash: string) => void }) {
  const projectId = props.route.projectId ?? "";
  const overview = useSnapshot<ProjectOverviewResult>(props.app, "page.materials.pick", "project.overview", {
    project_id: projectId,
  });
  const items = overview.data?.work_items ?? [];
  const requested = props.route.workItemId;
  const chosen = requested ?? (items.find((item) => item.status === "in_progress")?.work_item_id
    ?? items[0]?.work_item_id ?? null);
  const materials = useSnapshot<WorkItemMaterialsResult>(props.app, "page.materials", "work_item.materials", {
    project_id: projectId,
    work_item: chosen ?? "",
  }, chosen === null);
  const data = materials.data;
  const targetRound = props.route.round;
  useEffect(() => {
    if (targetRound === null || !data) {
      return;
    }
    const scrollToTarget = () => {
      const el = document.getElementById(`onboarding-round-${targetRound}`);
      if (el) {
        el.scrollIntoView({ block: "start" });
      }
    };
    scrollToTarget();
    const timer = setTimeout(scrollToTarget, 50);
    return () => clearTimeout(timer);
  }, [targetRound, data, chosen]);
  return (
    <div className="page y10-pp y10-mt">
      <header className="y10-pp-head">
        <h1>{requested === null ? "资料" : `资料 · ${items.find((item) => item.work_item_id === requested)?.title ?? ""}`}</h1>
        <p className="y10-block-sub note">
          {overview.data === null ? "" : requested === null
            ? `${overview.data.name} · 在顶栏选择事项以后查看这个事项的完整资料`
            : `${overview.data.name} · 按事项查看的资料全部只读`}
        </p>
      </header>
      <Loading state={overview} />
      {overview.error !== null ? (
        <p className="y10-note note" role="status">{readFailureText(overview.error)}</p>
      ) : null}
      {overview.data !== null ? (
        <IndexBlock
          items={items}
          chosen={chosen}
          requested={requested}
          counts={data === null ? null : countsOf(data)}
          onNavigate={props.onNavigate}
          projectId={projectId}
        />
      ) : null}
      {materials.error !== null ? (
        <p className="y10-note note" role="status">{readFailureText(materials.error)}</p>
      ) : null}
      {data ? (
        <>
          <IntendBlock rows={data.inputs} />
          <VersionBlock app={props.app} id="mt-prd" title="PRD" note="产品部门提交并被接纳的各版本；接入已有项目的初始 PRD 标明确认记录" rows={data.contracts} empty="产品部门还没有提交 PRD" />
          <OnboardingBlock rounds={data.onboarding_rounds} />
          <DeliveryBlock app={props.app} rows={data.deliveries} />
          <ReviewBlock rows={data.reviews} />
          <NotesBlock rows={data.materials} scoped={requested !== null} />
        </>
      ) : null}
    </div>
  );
}

// 当前查看事项各资料的条数；其余事项没有读取，索引卡上按未查看显示
function countsOf(data: WorkItemMaterialsResult): Record<string, number> {
  return {
    intend: data.inputs.length,
    prd: data.contracts.length,
    delivery: data.deliveries.length,
    qa: data.reviews.length,
    note: data.materials.length,
    onboarding: data.onboarding_rounds.length,
  };
}

// 按事项查看（原型 mt-index）：点击卡上的标题换到那个事项
function IndexBlock(props: {
  items: WorkItemCard[];
  chosen: string;
  requested: string | null;
  counts: Record<string, number> | null;
  projectId: string;
  onNavigate: (hash: string) => void;
}) {
  // 本页的事项用名字说明，不显示事项标识这类内部标识（工单 #746）
  const chosenTitle = scopeName(props.items, props.chosen);
  return (
    <Section
      id="mt-index"
      title="按事项查看"
      note={`资料按事项保存；点击事项查看它的 intend、PRD、交付、质检与项目材料；本页的事项${chosenTitle === "" ? "" : ` ${chosenTitle}`}${props.requested === null ? "（未选中事项，取当前事项）" : ""}`}
      className="y10-mt"
    >
      {props.items.length === 0 ? <Empty text="项目还没有事项，没有资料可看" /> : (
        <div className="y10-mt-index">
          {props.items.map((item, index) => {
            const current = item.work_item_id === props.chosen;
            return (
              <article
                key={item.work_item_id}
                className={`y10-mt-index-card${current ? " is-current" : ""}`}
                style={{ "--item": ITEM_COLORS[(index + 1) % ITEM_COLORS.length] } as CSSProperties}
              >
                <button
                  type="button"
                  className="y10-pp-title"
                  onClick={() => props.onNavigate(paths.materials(props.projectId, { workItem: item.work_item_id }))}
                >
                  {item.title}
                </button>
                <StatusMark kind={WORK_ITEM_STATUS_KIND[item.status] ?? "idle"} text={label(WORK_ITEM_STATUS, item.status)} />
                <div className="y10-mt-counts">
                  {current && props.counts !== null ? (
                    COUNT_KINDS.map(([kind, name]) => (
                      <span key={kind} className={props.counts?.[kind] ? "" : "is-zero"}>{name} {props.counts?.[kind] ?? 0}</span>
                    ))
                  ) : <span className="is-zero">未查看</span>}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </Section>
  );
}

// intend 原文（原型 mt-intend）：首次与逐次输入，按接收顺序保存
function IntendBlock(props: { rows: WorkItemMaterialsResult["inputs"] }) {
  return (
    <Section id="mt-intend" title="intend 原文" note="按接收顺序保存的用户原文" className="y10-mt">
      {props.rows.length === 0 ? <Empty text="这个事项还没有 intend 原文" /> : (
        <ol className="y10-mt-list">
          {props.rows.map((input) => (
            <li className="y10-mt-doc" key={input.input_id}>
              <header className="y10-mt-doc-head">
                <strong>intend 原文 第 {input.version} 版</strong>
                <Tag>{input.version === 1 ? "首次输入" : `第 ${input.version} 次输入`}</Tag>
                <span className="y10-muted">{input.byte_start}–{input.byte_end} 字节</span>
                <span className="y10-muted">{input.kind}</span>
              </header>
              <p className="y10-clamp">{input.text}</p>
            </li>
          ))}
        </ol>
      )}
    </Section>
  );
}

// 建档各轮（工单 #138，设计第 3.3、4.3 节）：接入已有项目的每一轮候选，逐轮列出初始 PRD 与
// 结构说明的原文、上一轮的修改意见、基线核验的各条结论与检查、这一轮的确认记录
function OnboardingBlock(props: { rounds: WorkItemMaterialsResult["onboarding_rounds"] }) {
  return (
    <Section
      id="mt-onboarding"
      title="建档各轮"
      note="接入已有项目的每一轮初始 PRD：原文、基线核验与这一轮的确认记录"
      className="y10-mt"
    >
      {props.rounds.length === 0 ? <Empty text="这个事项不是接入已有项目的建档" /> : (
        <ol className="y10-mt-list">
          {props.rounds.map((round) => (
            <li className="y10-mt-doc" key={round.candidate_event_id} id={`onboarding-round-${round.round}`}>
              <header className="y10-mt-doc-head">
                <strong>第 {round.round} 轮</strong>
                <Tag>建档</Tag>
                <span className="y10-muted">run {round.run_id}</span>
                <span className="y10-muted">提出于 {formatTime(round.proposed_at)}</span>
              </header>
              {round.revision_note === null || round.revision_note.trim() === "" ? null : (
                <blockquote className="y10-mt-quote">
                  <strong>上一轮的修改意见：</strong>{round.revision_note}
                </blockquote>
              )}
              <h3 className="y10-mt-sub">初始 PRD</h3>
              <pre className="y10-pre raw">{round.prd}</pre>
              <h3 className="y10-mt-sub">现有结构说明</h3>
              <pre className="y10-pre raw">{round.structure}</pre>
              <BaselineReviewBlock review={round.baseline_review} />
              <DecisionRecords rows={round.decisions} />
            </li>
          ))}
        </ol>
      )}
    </Section>
  );
}

// 某一轮基线核验的结论（工单 #138，设计第 3.2 节）：逐条结论、遗漏的能力、检查回执与其他失败
function BaselineReviewBlock(props: { review: WorkItemMaterialsResult["onboarding_rounds"][number]["baseline_review"] }) {
  const review = props.review;
  return (
    <>
      <h3 className="y10-mt-sub">基线核验</h3>
      <KeyValue
        items={[
          ["核实结果", review.conclusions.length === 0
            ? "没有逐条结论"
            : review.conclusions.map(conclusionRow).join("；")],
          ["遗漏的能力", review.omissions.length === 0 ? "无" : review.omissions.map(omissionRow).join("；")],
          ["基线检查", review.checks.length === 0 ? "无" : review.checks.map(baselineCheckRow).join("；")],
          ["其他失败", review.other_failures.length === 0 ? "无" : review.other_failures.map(failureRow).join("；")],
          ["指纹", show(review.content_hash, "未上报")],
        ]}
      />
    </>
  );
}

// 某一轮的确认记录（工单 #138，设计第 4.7 节）：回答与撤销各自一条
function DecisionRecords(props: { rows: WorkItemMaterialsResult["onboarding_rounds"][number]["decisions"] }) {
  return (
    <>
      <h3 className="y10-mt-sub">确认记录</h3>
      {props.rows.length === 0 ? <Empty text="这一轮还没有确认记录" /> : (
        <ul className="y10-mt-notes">
          {props.rows.map((record) => (
            <li key={record.event_id}>
              <header className="y10-mt-doc-head">
                <strong>{record.outcome === "answered" ? `回答：${decisionOptionLabel(record.option)}` : "撤销"}</strong>
                <span className="y10-muted">{formatTime(record.decided_at)}</span>
              </header>
              {record.note === null || record.note === "" ? null : <blockquote className="y10-mt-quote">{record.note}</blockquote>}
              {record.reason === null || record.reason === "" ? null : <p className="y10-note note">原因：{record.reason}</p>}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}


const ONBOARDING_DECISION_OPTIONS: Record<string, string> = {
  confirm: "确认",
  revise: "提出修改",
};

function decisionOptionLabel(option: string | null): string {
  if (option === null) {
    return "未记录选项";
  }
  return ONBOARDING_DECISION_OPTIONS[option] ?? option;
}

function baselineCheckRow(value: { name?: string; command?: string; exit_code?: number; summary?: string }): string {
  const name = text(value.name) || "未命名检查";
  const cmd = text(value.command);
  const exit = typeof value.exit_code === "number" ? `退出状态 ${value.exit_code}` : "";
  const summary = text(value.summary);
  return [name, cmd, exit, summary].filter((part) => part !== "").join(" · ");
}
// 逐条结论按 要求 / 状态 / 依据 一行一条（设计第 3.2 节的「各要求核实结果」）
function conclusionRow(value: { requirement?: string; status?: string; evidence?: string }): string {
  return [text(value.requirement) || "未写明要求", conclusionName(text(value.status)), text(value.evidence)]
    .filter((part) => part !== "").join(" · ");
}

const CONCLUSION_NAMES: Record<string, string> = {
  verified: "已核实",
  read_only: "只读",
  existing_defect: "现有缺陷",
  unsupported: "不支持",
};

function conclusionName(status: string): string {
  return CONCLUSION_NAMES[status] ?? status;
}

function omissionRow(value: { capability?: string; location?: string }): string {
  return [text(value.capability) || "未写明能力", text(value.location)]
    .filter((part) => part !== "").join(" · ");
}

function failureRow(value: { check?: string; reason?: string }): string {
  return [text(value.check) || "未命名检查", text(value.reason)].filter((part) => part !== "").join(" · ");
}

// PRD（原型 mt-prd）：各版本、状态与目标（摘要）；点「查看原文」用 event.detail 取合同原文
function VersionBlock(props: {
  app: ClientApp;
  id: string;
  title: string;
  note: string;
  rows: WorkItemMaterialsResult["contracts"];
  empty: string;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const detail = useSnapshot<EventDetailResult>(
    props.app,
    open === null ? "page.materials.prd.none" : `page.materials.prd.${open}`,
    "event.detail",
    { event_id: open ?? "" },
    open === null,
  );
  // 读不出来与「这一版没有留下原文」是两句不同的话（工单 #714）
  const original = originalView(detail, (data) => text(dict(data.artifacts).prd));

  return (
    <Section id={props.id} title={props.title} note={props.note} className="y10-mt">
      {props.rows.length === 0 ? <Empty text={props.empty} /> : (
        <ol className="y10-mt-list">
          {props.rows.map((entry, index) => (
            <li className={`y10-mt-doc${index === props.rows.length - 1 ? " is-current" : " is-old"}`} key={entry.event_id}>
              <header className="y10-mt-doc-head">
                <strong>{props.title} {entry.revision === null ? "未编号" : `第 ${entry.revision} 版`}</strong>
                <Tag>{entry.status}</Tag>
                <span className="y10-muted">指纹 {show(entry.content_hash, "未上报")}</span>
                <button type="button" className="y10-link link" onClick={() => setOpen(entry.event_id)}>查看原文</button>
              </header>
              <p className="y10-clamp">{show(entry.summary, "（这一版没有摘要，点「查看原文」看合同）")}</p>
            </li>
          ))}
        </ol>
      )}
      {open === null ? null : (
        <div className="y10-block card">
          <div className="y10-block-head section-head">
            <h2>合同原文</h2>
            <button type="button" onClick={() => setOpen(null)}>收起</button>
          </div>
          {original.kind === "loading" ? <p className="y10-note note">正在读取原文</p> : null}
          {original.kind === "failed" ? (
            <p className="y10-note note" role="status">{readFailureText(original.reason)}</p>
          ) : null}
          {original.kind === "empty" ? <p className="y10-note note">这一版没有留下原文</p> : null}
          {original.kind === "content" ? <pre className="y10-pre raw">{original.text}</pre> : null}
        </div>
      )}
    </Section>
  );
}

// 交付（原型 mt-delivery）：各版本的封存快照，文件清单与摘要；点开文件用 delivery.file 取内容
function DeliveryBlock(props: { app: ClientApp; rows: WorkItemMaterialsResult["deliveries"] }) {
  const [open, setOpen] = useState<{ eventId: string; path: string } | null>(null);
  const file = useSnapshot<DeliveryFileResult>(
    props.app,
    open ? `page.delivery.${open.eventId}.${open.path}` : "page.delivery.none",
    "delivery.file",
    { event_id: open?.eventId ?? "", path: open?.path ?? "" },
    open === null,
  );
  // 读不出来与「没有内容」是两句不同的话（工单 #714）
  const view = readView(file);

  return (
    <Section id="mt-delivery" title="交付" note="各版本的封存快照：文件清单、摘要与文件下载" className="y10-mt">
      {props.rows.length === 0 ? <Empty text="工程部门还没有封存交付" /> : (
        <ol className="y10-mt-list">
          {props.rows.map((entry, index) => (
            <li className={`y10-mt-doc delivery-block${index === props.rows.length - 1 ? " is-current" : " is-old"}`} key={entry.event_id}>
              <header className="y10-mt-doc-head">
                <strong>交付 {entry.revision === null ? "（未编号）" : `第 ${entry.revision} 版`}</strong>
                <Tag>{entry.status}</Tag>
                <span className="y10-muted">{show(entry.summary, "没有摘要")}</span>
              </header>
              {entry.files.length === 0 ? <p className="y10-note note">这条交付没有文件清单</p> : (
                <ul className="y10-mt-files file-list">
                  {entry.files.map((path) => (
                    <li key={path}>
                      <code className="y10-code file-path">{path}</code>
                      <button type="button" className="y10-link link" onClick={() => setOpen({ eventId: entry.event_id, path })}>查看内容</button>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ol>
      )}
      {open ? (
        <div className="y10-block card">
          <div className="y10-block-head section-head">
            <h2>交付文件 {open.path}</h2>
            <button type="button" onClick={() => setOpen(null)}>收起</button>
          </div>
          {view.kind === "loading" ? <p className="y10-note note">正在读取文件</p> : null}
          {view.kind === "failed" ? (
            <p className="y10-note note" role="status">{readFailureText(view.reason)}</p>
          ) : null}
          {view.kind === "ready" && view.data !== null ? <FileContent data={view.data} /> : null}
        </div>
      ) : null}
    </Section>
  );
}

// 文本内容直接显示，也给下载；二进制给出 base64 的下载链接，界面不伪造文本（工单 #748）
function FileContent(props: { data: DeliveryFileResult }) {
  const download = fileDownload(props.data);
  const link = download === null ? null : (
    <a className="y10-btn primary" href={download.href} download={download.name}>下载文件</a>
  );
  if (props.data.content !== null && props.data.content !== undefined) {
    return (
      <>
        {link}
        <pre className="y10-pre raw">{props.data.content}</pre>
      </>
    );
  }
  const base64 = props.data.base64;
  if (base64 !== null && base64 !== undefined) {
    return (
      <>
        <p className="y10-note note">二进制内容（{base64.length} 个 base64 字符，指纹 {show(props.data.content_hash)}）</p>
        {link}
      </>
    );
  }
  return <p className="y10-note note">这个文件没有返回内容</p>;
}

// 质检（原型 mt-qa）：结论、理由、检查回执与缺陷
function ReviewBlock(props: { rows: WorkItemMaterialsResult["reviews"] }) {
  return (
    <Section id="mt-qa" title="质检" note="结论、理由、检查回执；截图绑定到交付快照" className="y10-mt">
      {props.rows.length === 0 ? <Empty text="质检部门还没有给出结论" /> : (
        <ol className="y10-mt-list">
          {props.rows.map((review) => (
            <li className={`y10-mt-doc ${verdictClass(review.verdict)}`} key={review.event_id}>
              <header className="y10-mt-doc-head">
                <strong>质检结论</strong>
                <Tag tone={review.verdict === "release" ? "ok" : "danger"}>{verdictName(review.verdict)}</Tag>
              </header>
              <KeyValue
                items={[
                  ["理由", show(review.rationale, "没有写明")],
                  ["检查回执", review.checks.length === 0 ? "无" : list(review.checks).map(checkRow).join("；")],
                  ["缺陷", review.defects.length === 0 ? "无" : list(review.defects).map(checkRow).join("；")],
                ]}
              />
            </li>
          ))}
        </ol>
      )}
    </Section>
  );
}

function verdictName(verdict: string): string {
  return VERDICT_LABELS[verdict] ?? verdict;
}

function verdictClass(verdict: string): string {
  return verdict === "release" ? "is-release" : "is-rework";
}

const VERDICT_LABELS: Record<string, string> = {
  release: "放行",
  rework_engineering: "退回工程",
};

function checkRow(value: Record<string, unknown>): string {
  const name = text(value.name) || text(value.id) || text(value.check_id);
  const result = text(value.result) || text(value.status) || text(value.verdict);
  const detail = text(value.summary) || text(value.message) || text(value.reason);
  return [name || "未命名", result, detail].filter((part) => part !== "").join(" · ");
}

// 项目材料（原型 mt-notes）：「记录原文」保存下来的材料
function NotesBlock(props: { rows: WorkItemMaterialsResult["materials"]; scoped: boolean }) {
  return (
    <Section id="mt-notes" title="项目材料" note="「记录原文」保存的材料；项目材料只记录原文，不注入后续事项" className="y10-mt">
      {props.rows.length === 0 ? <Empty text={props.scoped ? "这个范围还没有项目材料" : "项目还没有记录原文"} /> : (
        <ul className="y10-mt-notes">
          {props.rows.map((material) => (
            <li key={material.material_id}>
              <header className="y10-mt-doc-head">
                <strong>{material.department === null ? "项目材料" : `${departmentName(material.department)}部门记录`}</strong>
                <span className="y10-muted">{formatTime(material.recorded_at)} 记录</span>
              </header>
              <blockquote className="y10-mt-quote">{material.text}</blockquote>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}
