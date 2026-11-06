// 资料页质检一项的逐条结论表与交付一项的启动方式（工单 #154；浏览器与 computer use 设计说明
// 第 7.3、8.3、8.4 节；验证的独立性设计说明第 7、7.1 节）。
//
// 表头写检验覆盖比例、模型阅读与开环的条数，取自 acceptance.coverage 里的放行记录，页面不重算；
// 每条验收条件一行：验收条件、检验方式（中文）、结果（中文）与证据；证据里列检查名称、试用用例与
// 截图缩略图。截图按工件引用经 evidence.screenshot 取内容，取不出来的那一张写「截图读不出来」。
// 无法核验的条目与原因在表下另列一条，原因取自逐条结论的 note（#1179）。
// 数字与文字的判断都在 materials-read.ts 里，这里只按它给出的结果画。

import type { CSSProperties } from "react";
import type { ClientApp } from "../../contract/client-app";
import type { AcceptanceCoverageResult, LaunchMethodView, ReviewEntry,
  ScreenshotEvidenceResult } from "../../api/generated/types.gen";
import { StatusMark } from "../../shell/kit";
import { Table, Tag } from "./common";
import { COVERAGE_UNREADABLE, SCREENSHOT_READING, SCREENSHOT_UNREADABLE } from "./labels";
import {
  coverageSummary,
  criterionRows,
  launchViews,
  unverifiedViews,
  type CriterionRowView,
  type ScreenshotRefView,
} from "./materials-read";
import { useSnapshot } from "./use-snapshot";

// 缩略图的尺寸（浏览器截图 1280×800，界面等比缩小；点开原尺寸留给试用记录页签）
const SHOT_STYLE: CSSProperties = {
  maxHeight: 64,
  maxWidth: 96,
  border: "1px solid var(--line, #d0d0d0)",
  borderRadius: 4,
  background: "var(--surface, #fff)",
};

// 一份 QAReview 的逐条结论表：表头是放行记录里的数，表下是无法核验的条目与原因
export function CriteriaTable(props: { app: ClientApp; review: ReviewEntry; coverage: AcceptanceCoverageResult | null }) {
  // 放行记录只与它对应的那一份结论放在一起；旧的缺陷记录没有自己的覆盖数，不借用最近一份的数
  const coverage = props.coverage !== null && props.coverage.review_event_id === props.review.event_id
    ? props.coverage : null;
  const rows = criterionRows(props.review, coverage);
  const unverified = unverifiedViews(props.review);
  if (rows.length === 0) {
    return <p className="y10-note note">这份结论没有逐条结论</p>;
  }
  return (
    <>
      {coverage === null ? null : (
        <p className="y10-note note y10-mt-coverage">{coverageSummary(coverage.numbers)}</p>
      )}
      <Table
        head={["验收条件", "检验方式", "结果", "证据与截图"]}
        rows={rows.map((row, index) => [
          <span className="y10-mt-criterion">
            <strong>{row.criterion}</strong>
            {row.open ? <> <Tag tone="warn">开环</Tag></> : null}
          </span>,
          <span className="y10-mt-method">{row.methodName}</span>,
          <StatusMark kind={row.resultKind} text={row.resultName} />,
          <EvidenceCell app={props.app} anchorEventId={props.review.event_id} row={row} rowIndex={index} />,
        ])}
      />
      {unverified.length === 0 ? null : (
        <div className="y10-mt-unverified">
          <h3 className="y10-mt-sub">无法核验的条目与原因</h3>
          <ul className="y10-mt-notes">
            {unverified.map((item) => (
              <li key={item.criterion}>
                <strong>{item.criterion}</strong>
                <span> · {item.methodName} · {item.note}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}

// 一行的证据：检查名称、试用用例与结论、截图缩略图；未核验的原因也写在这一格
function EvidenceCell(props: { app: ClientApp; anchorEventId: string; row: CriterionRowView; rowIndex: number }) {
  const row = props.row;
  const reason = row.resultName === "未核验" && row.note !== "" ? row.note : "";
  const empty = row.checks.length === 0 && row.cases.length === 0 && reason === "";
  return (
    <div className="y10-mt-evidence">
      {row.checks.map((name) => (
        <p key={`check-${name}`} className="y10-mt-evidence-line">检查 <code className="y10-code">{name}</code></p>
      ))}
      {row.cases.map((item, index) => (
        <p key={`case-${index}`} className="y10-mt-evidence-line">
          试用用例「{item.title}」{item.resultName === "" ? "" : `：${item.resultName}`}
        </p>
      ))}
      {reason === "" ? null : <p className="y10-mt-evidence-line">无法核验：{reason}</p>}
      {row.screenshots.length === 0 ? null : (
        <div className="y10-mt-shots">
          {row.screenshots.map((shot, index) => (
            <ScreenshotThumb
              key={`${shot.contentHash}-${index}`}
              app={props.app}
              anchorEventId={props.anchorEventId}
              viewId={`page.materials.shot.${props.anchorEventId}.${props.rowIndex}.${index}`}
              shot={shot}
              label={`验收条件 ${row.criterion} 的截图 ${index + 1}`}
            />
          ))}
        </div>
      )}
      {row.hiddenScreenshots === 0 ? null : (
        <p className="y10-muted">另有 {row.hiddenScreenshots} 张截图</p>
      )}
      {empty ? <span className="y10-muted">没有证据</span> : null}
    </div>
  );
}

// 一张截图：按工件引用读内容，读到了画等比缩小的缩略图；读不出来时写下这一句，不画一个空框
function ScreenshotThumb(props: {
  app: ClientApp;
  anchorEventId: string;
  viewId: string;
  shot: ScreenshotRefView;
  label: string;
}) {
  const state = useSnapshot<ScreenshotEvidenceResult>(props.app, props.viewId, "evidence.screenshot", {
    event_id: props.anchorEventId,
    kind: props.shot.kind,
    content_hash: props.shot.contentHash,
    path: props.shot.path,
    media_type: props.shot.mediaType,
  });
  if (state.error !== null) {
    return <span className="y10-muted">{SCREENSHOT_UNREADABLE}</span>;
  }
  const data = state.data;
  if (data === null) {
    return <span className="y10-muted">{SCREENSHOT_READING}</span>;
  }
  if (!data.media_type.startsWith("image/") || data.base64 === "") {
    return <span className="y10-muted">{SCREENSHOT_UNREADABLE}</span>;
  }
  return (
    <img
      className="y10-mt-shot"
      style={SHOT_STYLE}
      src={`data:${data.media_type};base64,${data.base64}`}
      alt={props.label}
    />
  );
}

// 交付一项的启动方式：名称、种类、每个系统的命令、就绪地址与时限；旧交付没有这一项时写明
export function LaunchMethods(props: { launch: readonly LaunchMethodView[] | undefined }) {
  const rows = launchViews(props.launch);
  return (
    <div className="y10-mt-launch">
      <h3 className="y10-mt-sub">启动方式</h3>
      {rows.length === 0 ? <p className="y10-note note">这份交付没有写启动方式</p> : (
        <ul className="y10-mt-notes">
          {rows.map((row) => (
            <li key={row.key}>
              <header className="y10-mt-doc-head">
                <strong>{row.name}</strong>
                <Tag>{row.kindName}</Tag>
                {row.readyTimeoutSec === null ? null : (
                  <span className="y10-muted">就绪时限 {row.readyTimeoutSec} 秒</span>
                )}
              </header>
              {row.readyUrl === null ? null : (
                <p className="y10-note note">就绪地址 <code className="y10-code">{row.readyUrl}</code></p>
              )}
              {row.commands.length === 0 ? null : (
                <ul className="y10-mt-files">
                  {row.commands.map((command) => (
                    <li key={command.system}>
                      <span>{command.system}</span>
                      <code className="y10-code">{command.argv.join(" ")}</code>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// 读不出检验覆盖数与真的没有覆盖数是两句话；调用处只在有质检结论时读，读不出来时写这一句
export function CoverageUnreadable() {
  return <p className="y10-note note" role="status">{COVERAGE_UNREADABLE}</p>;
}
