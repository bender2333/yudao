// 资料页（原型 v8 设计说明第 7.3 节，工单 #80）：只读，按事项查看。
// intend 原文（版本与字节范围）、PRD（各版本与状态）、PLAN（各版本与目标）、交付（版本、文件清单与摘要，
// 文件内容由 delivery.file 取回）、质检（结论、理由、检查与缺陷）、项目材料（material.record 保存的原文）。
// 范围跟随顶栏的 ?w=；没有选中事项时取进行中的一项，并在页面上写明所选事项。
// Git 差异、截图与启动方式属于 3.2D/3.8，在对应查询登记以后加入。

import { useState } from "react";
import type { ClientApp } from "../../contract/client-app";
import type { DeliveryFileResult, ProjectOverviewResult, WorkItemMaterialsResult } from "../../api/generated/types.gen";
import type { Route } from "../../shell/routing";
import { Empty, KeyValue, Loading, Section, Table, list, show, text } from "./common";
import { departmentName, formatTime } from "./labels";
import { useSnapshot } from "./use-snapshot";

export function MaterialsPage(props: { app: ClientApp; route: Route }) {
  const projectId = props.route.projectId ?? "";
  const overview = useSnapshot<ProjectOverviewResult>(props.app, "page.materials.pick", "project.overview", {
    project_id: projectId,
  });
  const items = overview.data?.work_items ?? [];
  const requested = props.route.workItemId;
  const chosen = requested ?? (items.find((item) => item.status === "in_progress")?.work_item_id ?? items[0]?.work_item_id ?? null);
  const materials = useSnapshot<WorkItemMaterialsResult>(props.app, "page.materials", "work_item.materials", {
    project_id: projectId,
    work_item: chosen ?? "",
  }, chosen === null);
  const data = materials.data;

  return (
    <div className="page">
      <Section
        title="资料"
        note={`只读，按事项查看；本页的事项 ${chosen ?? "无"}${requested === null && chosen !== null ? "（未选中事项，取当前事项）" : requested === null ? "" : "（顶栏选中）"}`}
      >
        <Loading state={overview} />
        {overview.data !== null && chosen === null ? <Empty text="项目还没有事项，没有资料可看" /> : null}
        <Loading state={materials} />
        {data ? (
          <>
            <IntendTable rows={data.inputs} />
            <VersionTable title="PRD（有效合同）" rows={data.contracts} />
            <VersionTable title="PLAN（工程方案）" rows={data.plans} />
            <DeliveryTable app={props.app} rows={data.deliveries} />
            <ReviewTable rows={data.reviews} />
            <MaterialTable rows={data.materials} />
          </>
        ) : null}
      </Section>
    </div>
  );
}

// intend 原文：首次与逐次输入，版本、字节范围与内容
function IntendTable(props: { rows: WorkItemMaterialsResult["inputs"] }) {
  if (props.rows.length === 0) {
    return <p className="y9-note note">intend 原文：这个事项没有输入记录</p>;
  }
  return (
    <Table
      head={["版本", "种类", "字节范围", "内容"]}
      rows={props.rows.map((input) => [
        `第 ${input.version} 版`,
        input.kind,
        `${input.byte_start}–${input.byte_end}`,
        <p className="y9-pre raw-text" key={input.input_id}>{input.text}</p>,
      ])}
      caption="intend 原文：首次与逐次输入"
    />
  );
}

// PRD 与 PLAN：各版本、状态与目标（摘要）
function VersionTable(props: { title: string; rows: WorkItemMaterialsResult["contracts"] }) {
  if (props.rows.length === 0) {
    return <p className="y9-note note">{props.title}：还没有版本</p>;
  }
  return (
    <Table
      head={["版本", "状态", "内容摘要", "内容指纹"]}
      rows={props.rows.map((entry) => [
        entry.revision === null ? "未编号" : `第 ${entry.revision} 版`,
        entry.status,
        show(entry.summary, "没有摘要"),
        show(entry.content_hash, "未上报"),
      ])}
      caption={props.title}
    />
  );
}

// 交付：各版本、文件清单与摘要；点开文件用 delivery.file 取内容
function DeliveryTable(props: { app: ClientApp; rows: WorkItemMaterialsResult["deliveries"] }) {
  const [open, setOpen] = useState<{ eventId: string; path: string } | null>(null);
  const file = useSnapshot<DeliveryFileResult>(
    props.app,
    open ? `page.delivery.${open.eventId}.${open.path}` : "page.delivery.none",
    "delivery.file",
    { event_id: open?.eventId ?? "", path: open?.path ?? "" },
    open === null,
  );

  if (props.rows.length === 0) {
    return <p className="y9-note note">交付：还没有版本</p>;
  }

  return (
    <>
      {props.rows.map((entry) => (
        <div key={entry.event_id} className="y9-mt-doc delivery-block">
          <h3 className="y9-h3 sub">
            交付 {entry.revision === null ? "（未编号）" : `第 ${entry.revision} 版`} · {entry.status} · {show(entry.summary, "没有摘要")}
          </h3>
          {entry.files.length === 0 ? <p className="y9-note note">这条交付没有文件清单</p> : (
            <ul className="y9-mt-files file-list">
              {entry.files.map((path) => (
                <li key={path}>
                  <span className="y9-code file-path">{path}</span>
                  <button type="button" className="y9-link link" onClick={() => setOpen({ eventId: entry.event_id, path })}>查看内容</button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
      {open ? (
        <div className="y9-block card">
          <div className="y9-block-head section-head">
            <h2>交付文件 {open.path}</h2>
            <button type="button" onClick={() => setOpen(null)}>收起</button>
          </div>
          {file.loading && file.data === null ? <p className="y9-note note">正在读取文件</p> : null}
          {file.data ? <FileContent data={file.data} /> : null}
        </div>
      ) : null}
    </>
  );
}

// 文本内容直接显示；二进制给出 base64 的下载链接，界面不伪造文本
function FileContent(props: { data: DeliveryFileResult }) {
  if (props.data.content !== null && props.data.content !== undefined) {
    return <pre className="y9-pre raw">{props.data.content}</pre>;
  }
  const base64 = props.data.base64;
  if (base64 !== null && base64 !== undefined) {
    return (
      <>
        <p className="y9-note note">二进制内容（{base64.length} 个 base64 字符，指纹 {show(props.data.content_hash)}）</p>
        <a
          className="y9-btn primary"
          href={`data:application/octet-stream;base64,${base64}`}
          download={props.data.path.split("/").pop() ?? "file"}
        >
          下载文件
        </a>
      </>
    );
  }
  return <p className="y9-note note">这个文件没有返回内容</p>;
}

// 质检：结论、理由、检查回执与缺陷
function ReviewTable(props: { rows: WorkItemMaterialsResult["reviews"] }) {
  if (props.rows.length === 0) {
    return <p className="y9-note note">质检：还没有结论</p>;
  }
  return (
    <>
      <h3 className="y9-h3 sub">质检</h3>
      {props.rows.map((review) => (
        <div key={review.event_id} className="y9-mt-doc review-block">
          <KeyValue
            items={[
              ["结论", review.verdict],
              ["理由", show(review.rationale, "没有写明")],
              ["检查回执", review.checks.length === 0 ? "无" : list(review.checks).map(checkRow).join("；")],
              ["缺陷", review.defects.length === 0 ? "无" : list(review.defects).map(checkRow).join("；")],
            ]}
          />
        </div>
      ))}
    </>
  );
}

function checkRow(value: Record<string, unknown>): string {
  const name = text(value.name) || text(value.id) || text(value.check_id);
  const result = text(value.result) || text(value.status) || text(value.verdict);
  const detail = text(value.summary) || text(value.message) || text(value.reason);
  return [name || "未命名", result, detail].filter((part) => part !== "").join(" · ");
}

// 项目材料：material.record 保存下来的原文
function MaterialTable(props: { rows: WorkItemMaterialsResult["materials"] }) {
  if (props.rows.length === 0) {
    return <p className="y9-note note">项目材料：没有记录</p>;
  }
  return (
    <Table
      head={["时间", "交给的部门", "内容"]}
      rows={props.rows.map((material) => [
        formatTime(material.recorded_at),
        departmentName(material.department),
        <p className="y9-pre raw-text" key={material.material_id}>{material.text}</p>,
      ])}
      caption="项目材料"
    />
  );
}
