// 项目设置页的「组织」一节（工单 #1649，项目的组织设计说明「形态一键选用」行 337 与 4.15
// 「加独立核验」；总图第一节「界面」：只读事实，命令从这里发）。
//
// 这一节回答四件事，判断都在 form-section-logic.ts 的纯函数里，这里只摆位置：
//   1. 组织一行：现在这份合成的组织有几个职能、谁核验谁、轮转是什么（由合成结果写出，页面不另写）；
//   2. 加独立核验与去掉独立核验：同一条命令，一次点击生效，理由不写，改动用查询给的那一份；
//   3. 换形态：打开与新建项目同一组卡；本项目没有改动时点卡一步生效，有改动时先确认一次，
//      列出会丢掉哪些（历史里还在，改回能找回）；
//   4. 一句提示：改动只对之后新建的事项生效，正在跑的事项按原来的组织做完。
//
// 命令与查询用 #1402 登记的那两个：organization.adopt 与 project.organization；
// 确认清单取 organization.draft 的 discarded（由后端逐项比较给出，页面不自己重算）。
// 查询没有登记时这一节不出现，命令没有登记时只读显示、不给按钮（与源目录一节同一做法）。

import { useEffect, useState } from "react";
import type { ClientApp } from "../../contract/client-app";
import type { OrganizationDraftResult, ProjectOrganizationResult } from "../../api/generated/types.gen";
import { readFailureText } from "../../contract/read-failure";
import {
  CommandFeedback, Loading, Section, SubmitButton, hasCommand, pageKey,
} from "./common";
import { FormCards } from "./form-cards";
import {
  ORGANIZATION_CHANGE_HINT, adoptPayload, canAddVerifier, canRemoveVerifier, discardedLines, needsRefresh,
  organizationLine, switchNeedsConfirm, verifierPayload,
} from "./form-section-logic";
import { useCommand, useSnapshot } from "./use-snapshot";

// 能力清单里有没有登记这条查询：没有登记时这一节整节不出现（页面按能力清单决定显示哪些内容）
function hasQuery(app: ClientApp | null, name: string): boolean {
  return (app?.currentCapabilities?.queries ?? []).some((query) => query.name === name);
}

export function FormSection(props: { app: ClientApp; projectId: string }) {
  const organization = useSnapshot<ProjectOrganizationResult>(
    props.app, "page.settings.form", "project.organization", { project_id: props.projectId });
  const data = organization.data;
  // 「换形态」打开卡以后选了哪一张：等着确认时非空；卡关掉时清空
  const [picked, setPicked] = useState("");
  const [cards, setCards] = useState(false);
  // 确认清单：后端比较「现在这份」与「换成这张卡」以后会丢掉哪些改动
  const draft = useSnapshot<OrganizationDraftResult>(
    props.app, "page.settings.form.draft", "organization.draft",
    { project_id: props.projectId, form: picked, changes: "{}" }, picked === "");
  // 提交提示跟随快照：形态、版本或历史变了以后，由数据本身显示最终状态
  const command = useCommand(props.app, pageKey([data?.form, data?.version, data?.history.length]));
  const editable = hasCommand(props.app, "organization.adopt");

  // 版本对不上：服务端拒绝了这一条，页面重新读取以后照实显示，不悄悄覆盖别处刚改过的组织
  useEffect(() => {
    if (needsRefresh(command.problem)) {
      void props.app.viewSync?.refresh("page.settings.form");
    }
  }, [command.problem, props.app]);

  if (!hasQuery(props.app, "project.organization")) {
    return null;
  }

  const closeCards = (): void => {
    setCards(false);
    setPicked("");
  };

  // 换形态：带上页面看到的组织版本提交，理由不写（历史里仍记一条）
  const submitAdopt = (form: string): void => {
    if (data === null) {
      return;
    }
    void command.submit("organization.adopt", adoptPayload({
      projectId: data.project_id, form, reason: "", baseVersion: data.version,
    })).then((ok) => {
      if (ok) {
        closeCards();
      }
    });
  };

  // 加独立核验 / 去掉独立核验：改动用查询给的那一份，不在页面里拼部门定义
  const submitVerifier = (changes: Record<string, unknown>): void => {
    if (data === null) {
      return;
    }
    void command.submit("organization.adopt", verifierPayload({
      projectId: data.project_id, form: data.form, changes, baseVersion: data.version,
    }));
  };

  // 点了一张卡：本项目有改动时先确认一次，没有改动时一步生效
  const pickForm = (form: string): void => {
    if (data === null) {
      return;
    }
    if (form === data.form) {
      return;
    }
    if (switchNeedsConfirm(data)) {
      setPicked(form);
      return;
    }
    submitAdopt(form);
  };

  const discarded = discardedLines(draft.data?.discarded ?? []);

  return (
    <Section id="form" title="组织" note="本项目现在用哪一份组织；可以加独立核验，也可以换成发布带里的另一份">
      <Loading state={organization} />
      {organization.error !== null ? (
        <p className="y10-note note" role="status">{readFailureText(organization.error)}</p>
      ) : null}
      {data === null ? null : (
        <>
          <div data-testid="organization-row">
            <p className="y10-org-line" data-testid="organization-line">{organizationLine(data)}</p>
            {editable ? (
              <div className="y10-row">
                {canAddVerifier(data) ? (
                  <button
                    type="button"
                    data-testid="organization-add-verifier"
                    disabled={command.busy}
                    onClick={() => submitVerifier(data.add_verifier ?? {})}
                  >
                    加独立核验
                  </button>
                ) : null}
                {canRemoveVerifier(data) ? (
                  <button
                    type="button"
                    data-testid="organization-remove-verifier"
                    disabled={command.busy}
                    onClick={() => submitVerifier(data.remove_verifier ?? {})}
                  >
                    去掉独立核验
                  </button>
                ) : null}
                <button type="button" data-testid="organization-switch" onClick={() => setCards(!cards)}>
                  换形态
                </button>
              </div>
            ) : null}
          </div>
          <p className="y10-note note" data-testid="organization-hint">{ORGANIZATION_CHANGE_HINT}</p>

          {cards ? (
            <div className="y10-form form" data-testid="organization-cards">
              <FormCards app={props.app} onPick={pickForm} hint={null} />
              {picked === "" ? null : (
                <div className="y10-confirm" data-testid="organization-confirm">
                  <p className="y10-note note">
                    换成这一份以后，本项目的这些改动会丢掉（历史里还在，改回能找回）：
                  </p>
                  <Loading state={draft} />
                  {draft.data === null || discarded.length === 0 ? (
                    <p className="y10-note note">没有会丢掉的改动。</p>
                  ) : (
                    <ul className="y10-list" data-testid="organization-discarded">
                      {discarded.map((line) => <li key={line}>{line}</li>)}
                    </ul>
                  )}
                  <div className="y10-row">
                    <SubmitButton
                      label="确认换成这一份"
                      busy={command.busy}
                      onClick={() => submitAdopt(picked)}
                    />
                    <button type="button" data-testid="organization-confirm-cancel" onClick={() => setPicked("")}>
                      换一张卡
                    </button>
                  </div>
                </div>
              )}
            </div>
          ) : null}
          <CommandFeedback submitted={command.submitted} problem={command.problem} />
        </>
      )}
    </Section>
  );
}
