// 写回的界面（工单 #709）：发起写回的入口与写回结果的显示。
// 数据来自 project.writeback 查询（写回记录）；命令是 writeback.execute。
// 写回设置在项目设置页的源目录一节里填写（那里已经是源目录的地方）。

import type { ClientApp } from "../../contract/client-app";
import type { ProjectWritebackResult } from "../../api/generated/types.gen";
import { paths } from "../../shell/routing";
import {
  CommandFeedback, Empty, Section, SubmitButton, Table, hasCommand, pageKey,
} from "./common";
import { formatTime } from "./labels";
import { WRITEBACK_STATUS, writebackText } from "./writeback-text";
import { useCommand, useSnapshot } from "./use-snapshot";

// 查询与命令都在能力清单里才有这一节：服务没有提供时不显示，也不去查没有的查询
function available(app: ClientApp): boolean {
  const capabilities = app.currentCapabilities;
  if (capabilities === null) {
    return false;
  }
  return capabilities.queries.some((query) => query.name === "project.writeback")
    && hasCommand(app, "writeback.execute");
}

// 项目设置页的「成果写回」一节：发起写回，并列出写回的记录
export function WritebackSection(props: { app: ClientApp; projectId: string }) {
  const ready = available(props.app);
  const records = useSnapshot<ProjectWritebackResult>(
    props.app, "page.settings.writeback", "project.writeback", { project_id: props.projectId }, !ready);
  const command = useCommand(props.app, pageKey([records.data?.records.length]));
  const rows = records.data?.records ?? [];

  if (!ready) {
    return null;
  }

  return (
    <Section
      id="set-writeback"
      title="成果写回"
      note="把采纳的成果写回登记的源目录：三方合并、核验最终树、推送分支并创建合并请求"
    >
      <div className="y10-row row-actions">
        <SubmitButton
          label="写回成果"
          busy={command.busy}
          onClick={() => void command.submit("writeback.execute", { project_id: props.projectId })}
        />
      </div>
      <CommandFeedback submitted={command.submitted} problem={command.problem} />
      {rows.length === 0 ? <Empty text="还没有写回记录" /> : (
        <Table
          head={["时间", "结果", "说明"]}
          rows={rows.map((record) => [
            formatTime(record.created_at),
            WRITEBACK_STATUS[record.status] ?? record.status,
            writebackText(record),
          ])}
        />
      )}
    </Section>
  );
}

// 概览页「当前成果」里的写回状态：这一次采纳还没有写回时写明，并给出到设置页的入口
export function WritebackState(props: {
  app: ClientApp;
  projectId: string;
  adoptionId: string | null;
  onboardingBaseline: boolean;
}) {
  const ready = available(props.app);
  const records = useSnapshot<ProjectWritebackResult>(
    props.app, "page.overview.writeback", "project.writeback", { project_id: props.projectId }, !ready);
  const record = props.adoptionId === null
    ? null
    : (records.data?.records ?? []).find((row) => row.adoption_id === props.adoptionId) ?? null;

  if (!ready) {
    return null;
  }
  // 建档基线就是接入时的代码快照，按设计不写回
  if (props.onboardingBaseline) {
    return <span>建档基线是接入时的代码快照，按设计不写回</span>;
  }
  if (record === null) {
    return (
      <span>
        还没有写回
        <button
          type="button"
          className="y10-link link"
          onClick={() => { window.location.hash = paths.settings(props.projectId); }}
        >
          去项目设置页写回
        </button>
      </span>
    );
  }
  return <span>{writebackText(record)}</span>;
}
