// 项目设置页的「形态」一节（工单 #1403，形态与核验角色设计说明「形态随事项冻结」；
// 项目的组织设计说明「采用与历史」「模板一键选用」；总图第一节「界面」：只读事实，命令从这里发）。
//
// 这一节回答四件事，判断都在 form-section-logic.ts 的纯函数里，这里只摆位置：
//   1. 现在用哪一份形态、它的组织版本，以及发布带的几份各叫什么、一句说明（没有核验角色的那一份
//      写明以开环完成结束、不经过放行）；
//   2. 换成另一份：选一份、写理由、确认；提交时带上页面看到的当前值，被拒绝时原样显示拒绝说明；
//   3. 历史：每一次改动的原值、新值、理由、时间与谁改的，每一条都能「改回这一份」（用原值再改一次）；
//   4. 一句提示：改动只对之后新建的事项生效，正在跑的事项按原来的形态跑完。
//
// 命令与查询用 #1402 登记的那两个：organization.adopt 与 project.organization。查询没有登记时这一节不出现，
// 命令没有登记时只读显示、不给按钮（与源目录一节同一做法）。

import { useState } from "react";
import type { ClientApp } from "../../contract/client-app";
import type { ProjectOrganizationResult } from "../../api/generated/types.gen";
import { readFailureText } from "../../contract/read-failure";
import {
  CommandFeedback, Empty, KeyValue, Loading, Section, SubmitButton, Table, Tag, TextArea, hasCommand, pageKey,
  useDraft,
} from "./common";
import {
  FORM_CHANGE_HINT, type FormHistoryRow, adoptPayload, canAdopt, changeBackPayload, currentFormText, formChoices,
  historyRows, otherChoices,
} from "./form-section-logic";
import { formatTime } from "./labels";
import { useCommand, useSnapshot } from "./use-snapshot";

// 能力清单里有没有登记这条查询：没有登记时这一节整节不出现（页面按能力清单决定显示哪些内容）
function hasQuery(app: ClientApp | null, name: string): boolean {
  return (app?.currentCapabilities?.queries ?? []).some((query) => query.name === name);
}

export function FormSection(props: { app: ClientApp; projectId: string }) {
  const organization = useSnapshot<ProjectOrganizationResult>(
    props.app, "page.settings.form", "project.organization", { project_id: props.projectId });
  const data = organization.data;
  // 选中的那一份与理由都存在草稿里：刷新、后退以后还在
  const [picked, setPicked] = useState("");
  const [reason, setReason] = useDraft(`settings/${props.projectId}/form-reason`, "");
  // 提交提示跟随快照：形态、版本或历史变了以后，由数据本身显示最终状态
  const command = useCommand(props.app, pageKey([data?.form, data?.version, data?.history.length]));
  const editable = hasCommand(props.app, "organization.adopt");

  if (!hasQuery(props.app, "project.organization")) {
    return null;
  }

  const submitChange = (form: string, text: string): void => {
    if (data === null) {
      return;
    }
    void command.submit("organization.adopt", adoptPayload({
      projectId: data.project_id, form, reason: text, baseVersion: data.version,
    })).then((ok) => {
      if (ok) {
        // 换过以后清掉选中的那一份与理由：表单回到「请选择」，理由不留在下一次的提交里
        setPicked("");
        setReason("");
      }
    });
  };

  // 历史每一行的「改回这一份」（工单验收：每一条都有）：等于用原值再改一次。
  // 原值已经是现在用的那一份时，点了等于没改，因此这一条禁用并在提示里说明原因
  const changeBackCell = (row: FormHistoryRow): React.ReactNode => {
    if (!editable || data === null) {
      return null;
    }
    return (
      <button
        key="back"
        type="button"
        data-testid={`form-change-back-${row.eventId}`}
        disabled={command.busy || !row.canChangeBack}
        title={row.canChangeBack ? undefined : "现在用的就是这一份"}
        onClick={() => {
          void command.submit("organization.adopt", changeBackPayload({
            projectId: data.project_id, previousForm: row.previous, baseVersion: data.version,
          }));
        }}
      >
        改回这一份
      </button>
    );
  };

  return (
    <Section id="form" title="形态" note="本项目现在用哪一份形态，可以换成发布带里的哪一份">
      <Loading state={organization} />
      {organization.error !== null ? (
        <p className="y10-note note" role="status">{readFailureText(organization.error)}</p>
      ) : null}
      {data === null ? null : (
        <>
          <KeyValue
            items={[
              ["现在用的形态", <span key="current" data-testid="form-current">{currentFormText(data)}</span>],
              ["改过几次", data.history.length === 0 ? "还没有改过" : `${data.history.length} 次`],
            ]}
          />
          <p className="y10-note note" data-testid="form-hint">{FORM_CHANGE_HINT}</p>

          <div data-testid="form-choices">
            <Table
              caption="发布带里的几份形态"
              head={["形态", "一句说明"]}
              rows={formChoices(data).map((choice) => [
                <span key="name" data-testid={`form-choice-${choice.form}`}>
                  {choice.form}
                  {choice.isCurrent ? <Tag tone="ok">现在用这一份</Tag> : null}
                </span>,
                <div key="description">
                  {choice.description}
                  {choice.openLoop === "" ? null : (
                    <p className="y10-note note is-warn" data-testid={`form-open-loop-${choice.form}`}>
                      {choice.openLoop}
                    </p>
                  )}
                </div>,
              ])}
            />
          </div>

          {editable ? (
            <div className="y10-form form" data-testid="form-change">
              <label className="y10-field field">
                <span>换成</span>
                <select
                  className="y10-select"
                  data-testid="form-select"
                  value={picked}
                  onChange={(event) => setPicked(event.target.value)}
                >
                  <option value="">选择一份形态</option>
                  {otherChoices(data).map((choice) => (
                    <option key={choice.form} value={choice.form}>{choice.form}</option>
                  ))}
                </select>
              </label>
              <TextArea
                label="理由（会记进历史，可以不写）"
                value={reason}
                rows={3}
                onInput={setReason}
              />
              <SubmitButton
                label="换成这一份"
                busy={command.busy}
                disabled={!canAdopt({ form: picked, currentForm: data.form })}
                onClick={() => submitChange(picked, reason)}
              />
            </div>
          ) : null}

          <h3 className="y10-block-title">改动历史</h3>
          <div data-testid="form-history">
            {data.history.length === 0 ? <Empty text="还没有改过形态" /> : (
              <Table
                head={["改动", "理由", "时间", "谁改的", ""]}
                rows={historyRows(data).map((row) => [
                  <span key="change" data-testid={`form-history-${row.eventId}`}>{row.text}</span>,
                  row.reason,
                  formatTime(row.at),
                  row.actor,
                  changeBackCell(row),
                ])}
              />
            )}
          </div>
          <CommandFeedback submitted={command.submitted} problem={command.problem} />
        </>
      )}
    </Section>
  );
}
