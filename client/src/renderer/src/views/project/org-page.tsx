// 「组织」一级标签页（工单 #1650）：展示当前形态与四问、组织蓝图与成果流向、
// 只读职能表、待采用候选与采用历史（支持预览差异并直接「改回这一份」）。

import { useEffect, useState } from "react";
import type {
  Catalog,
  OrganizationDraftResult,
  ProjectLoopResult,
  ProjectOrganizationResult,
  ProjectSettingsResult,
} from "../../api/generated/types.gen";
import type { ClientApp } from "../../contract/client-app";
import { readFailureText } from "../../contract/read-failure";
import { Block, PageHead } from "../../shell/kit";
import { paths, type Route } from "../../shell/routing";
import {
  Empty,
  Loading,
  Modal,
  SubmitButton,
  Tag,
  TextInput,
  hasCommand,
  pageKey,
} from "./common";
import { FormCards } from "./form-cards";
import {
  ORGANIZATION_CHANGE_HINT,
  ORGANIZATION_NOT_READ,
  adoptPayload,
  discardedLines,
  needsRefresh,
  switchNeedsConfirm,
} from "./form-section-logic";
import { LoopGraphView } from "./loop-graph";
import {
  departmentRows,
  departmentTableColumnTitle,
  formatOrgCommandProblem,
  oldOrgItems,
  orgBlueprint,
  orgFormSummary,
  orgHistoryRows,
  orgQuestions,
  pendingCandidates,
  previousItemDiffView,
  revertAdoptPayload,
  revertConfirmView,
  revertDraftParams,
  type OrgHistoryRow,
  type ProjectOrganizationSnapshot,
} from "./org-page-model";
import type { DepartmentView } from "./organization";
import { useCommand, useSnapshot } from "./use-snapshot";

function hasQuery(app: ClientApp | null, name: string): boolean {
  return (app?.currentCapabilities?.queries ?? []).some((query) => query.name === name);
}

function originTagTone(kind: "release" | "changed" | "added" | "running_item"): "muted" | "warn" | "ok" | "danger" {
  if (kind === "added") return "ok";
  if (kind === "changed") return "warn";
  if (kind === "running_item") return "danger";
  return "muted";
}

export function OrganizationPage(props: {
  app: ClientApp;
  route: Route;
  organization: ProjectOrganizationResult | null;
  departments: DepartmentView[];
  onNavigate: (hash: string) => void;
}) {
  const projectId = props.route.projectId ?? "";
  const orgData = props.organization as ProjectOrganizationSnapshot | null;
  const synth = orgData?.organization ?? null;
  const conversationHash = paths.conversation(projectId, { workItem: props.route.workItemId });
  const editable = hasCommand(props.app, "organization.adopt");

  const loopSnap = useSnapshot<ProjectLoopResult>(
    props.app,
    "page.org.loop",
    "project.loop",
    { project_id: projectId },
    !projectId || !hasQuery(props.app, "project.loop"),
  );
  const settingsSnap = useSnapshot<ProjectSettingsResult>(
    props.app,
    "page.org.settings",
    "project.settings",
    { project_id: projectId },
    !projectId || !hasQuery(props.app, "project.settings"),
  );
  const catalogSnap = useSnapshot<Catalog>(
    props.app,
    "page.org.catalog",
    "catalog",
    {},
    !hasQuery(props.app, "catalog"),
  );

  // 「换形态」折叠状态与目标形态预检
  const [switchOpen, setSwitchOpen] = useState(false);
  const [switchPicked, setSwitchPicked] = useState("");
  const [oldItemsExpanded, setOldItemsExpanded] = useState(false);

  const switchDraft = useSnapshot<OrganizationDraftResult>(
    props.app,
    "page.org.switch.draft",
    "organization.draft",
    { project_id: projectId, form: switchPicked, changes: "{}" },
    !projectId || switchPicked === "",
  );

  const switchCmd = useCommand(
    props.app,
    pageKey(["org-switch", orgData?.form, orgData?.version, orgData?.history.length]),
  );

  // 「改回这一份」弹窗状态、预检与命令状态
  const [revertRow, setRevertRow] = useState<OrgHistoryRow | null>(null);
  const [revertReason, setRevertReason] = useState("");
  const revertDraftParamsObj =
    revertRow && projectId
      ? revertDraftParams(projectId, revertRow)
      : { project_id: projectId, form: "", changes: "{}" };

  const revertDraft = useSnapshot<OrganizationDraftResult>(
    props.app,
    "page.org.revert.draft",
    "organization.draft",
    revertDraftParamsObj,
    !projectId || revertRow === null,
  );

  const revertCmd = useCommand(
    props.app,
    pageKey(["org-revert", revertRow?.eventId, orgData?.version]),
  );

  useEffect(() => {
    if (needsRefresh(switchCmd.problem) || needsRefresh(revertCmd.problem)) {
      void props.app.viewSync?.refresh("shell.organization");
    }
  }, [switchCmd.problem, revertCmd.problem, props.app]);

  const navigateToDepartment = (deptId: string): void => {
    if (!projectId) return;
    props.onNavigate(
      paths.departmentDetail(projectId, deptId, { workItem: props.route.workItemId, from: "org" }),
    );
  };

  const closeSwitchPanel = (): void => {
    setSwitchOpen(false);
    setSwitchPicked("");
  };

  const submitFormSwitch = (formId: string): void => {
    if (!orgData) return;
    void switchCmd
      .submit(
        "organization.adopt",
        adoptPayload({
          projectId: orgData.project_id,
          form: formId,
          reason: "",
          baseVersion: orgData.version,
        }),
      )
      .then((ok) => {
        if (ok) {
          closeSwitchPanel();
          void props.app.viewSync?.refresh("shell.organization");
        }
      });
  };

  const handlePickForm = (formId: string): void => {
    if (!orgData) return;
    if (formId === orgData.form && !switchNeedsConfirm(orgData)) {
      return;
    }
    if (switchNeedsConfirm(orgData)) {
      setSwitchPicked(formId);
      return;
    }
    submitFormSwitch(formId);
  };

  const openRevertModal = (row: OrgHistoryRow): void => {
    setRevertRow(row);
    setRevertReason(`从历史版本 ${row.version}（${row.formLabel}）改回`);
  };

  const closeRevertModal = (): void => {
    setRevertRow(null);
    setRevertReason("");
  };

  const submitRevert = (): void => {
    if (!orgData || !revertRow) return;
    const payload = revertAdoptPayload({
      projectId: orgData.project_id,
      row: revertRow,
      baseVersion: orgData.version,
      reason: revertReason,
    });
    void revertCmd.submit("organization.adopt", payload).then((ok) => {
      if (ok) {
        closeRevertModal();
        void props.app.viewSync?.refresh("shell.organization");
      }
    });
  };

  const pageActions = (
    <a
      className="y10-btn is-small small"
      href={conversationHash}
      onClick={(event) => {
        event.preventDefault();
        props.onNavigate(conversationHash);
      }}
    >
      回到对话
    </a>
  );

  if (!orgData) {
    return (
      <div className="page v21-org-page" data-testid="org-page">
        <PageHead
          eyebrow="组织"
          title="组织"
          subtitle="展示项目当前的组织形态、四问蓝图、职能详情与采用历史。"
          actions={pageActions}
        />
        <Block title="项目组织">
          <Empty text={ORGANIZATION_NOT_READ} />
        </Block>
      </div>
    );
  }

  const summary = orgFormSummary(orgData);
  const questions = synth ? orgQuestions(synth) : null;
  const blueprint = synth ? orgBlueprint(synth) : null;
  const runningOldItems = oldOrgItems(loopSnap.data, orgData, projectId);
  const prevItemDiff = previousItemDiffView(orgData.previous_item, orgData.forms);
  const deptRows = departmentRows({
    organization: orgData,
    settings: settingsSnap.data,
    catalog: catalogSnap.data,
  });
  const relationColTitle = departmentTableColumnTitle(synth);
  const candidates = pendingCandidates(orgData);
  const historyRows = orgHistoryRows(orgData);
  const switchDiscarded = discardedLines(switchDraft.data?.discarded ?? []);
  const switchProblemInfo = switchCmd.problem ? formatOrgCommandProblem(switchCmd.problem) : null;
  const revertProblemInfo = revertCmd.problem ? formatOrgCommandProblem(revertCmd.problem) : null;
  const revertPreview =
    revertRow !== null
      ? revertConfirmView({
          row: revertRow,
          currentOrganization: synth,
          draft: revertDraft.data,
        })
      : null;

  return (
    <div className="page v21-org-page" data-testid="org-page">
      <PageHead
        eyebrow="组织"
        title="组织"
        subtitle="由当前合成组织直接给出分工规则、成果流向、职能列表与历史记录。"
        actions={pageActions}
      />

      {!summary.inRelease ? (
        <div className="v21-org-alert is-warn" role="alert" data-testid="org-out-of-release">
          当前形态「{summary.formLabel}」已不在这版发布里，可选用「换形态」切到发布里的组织，或从下方采用历史改回。
        </div>
      ) : null}

      {(orgData.rejections ?? []).length > 0 ? (
        <div className="v21-org-alert is-danger" role="alert" data-testid="org-rejections">
          当前组织声明存在冲突：
          {(orgData.rejections ?? []).map((item) => item.message || item.item).join("；")}
        </div>
      ) : null}

      <Block
        title="当前组织"
        subtitle="运行参数（写回与目录、本机授权、跑在哪里、MCP）仍在设置页对应栏目配置。"
        dataTestId="org-summary-block"
      >
        <div className="v21-org-summary-bar">
          <div className="v21-org-badges">
            <span className="v21-org-form-name" data-testid="org-form-label">
              {summary.formLabel}
            </span>
            <Tag tone="muted">{summary.routingText}</Tag>
            <Tag tone={summary.isOpenLoop ? "warn" : "ok"}>{summary.endingText}</Tag>
            <Tag tone="muted">
              {summary.changeCount > 0 ? `项目已改 ${summary.changeCount} 处` : "跟随发布默认"}
            </Tag>
            <Tag tone="muted">版本 {summary.version}</Tag>
          </div>
          {editable ? (
            <button
              type="button"
              className="y10-btn small"
              data-testid="org-switch-btn"
              onClick={() => {
                if (switchOpen) {
                  closeSwitchPanel();
                } else {
                  setSwitchOpen(true);
                }
              }}
            >
              {switchOpen ? "收起换形态" : "换形态"}
            </button>
          ) : null}
        </div>

        <div className="v21-org-hint-row" data-testid="org-change-hint">
          <span>{ORGANIZATION_CHANGE_HINT}</span>
          {runningOldItems.length > 0 ? (
            <button
              type="button"
              className="y10-btn is-small small"
              data-testid="org-old-items-toggle"
              onClick={() => setOldItemsExpanded((prev) => !prev)}
            >
              还有 {runningOldItems.length} 个未结束事项按旧组织运行（
              {oldItemsExpanded ? "收起" : "展开查看"}）
            </button>
          ) : null}
        </div>

        {oldItemsExpanded && runningOldItems.length > 0 ? (
          <div className="v21-org-old-items" data-testid="org-old-items-list">
            <ul className="v21-org-old-list">
              {runningOldItems.map((item) => (
                <li key={item.workItemId} className="v21-org-old-item">
                  <a
                    href={item.href}
                    onClick={(event) => {
                      event.preventDefault();
                      props.onNavigate(item.href);
                    }}
                  >
                    {item.workItemId}
                  </a>
                  <Tag tone="muted">{item.statusText}</Tag>
                  <span>
                    冻结组织：{item.formLabel}（{item.version}）
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {prevItemDiff !== null ? (
          <div className="v21-org-prev-diff" data-testid="org-previous-item-diff">
            <strong>
              上一条事项「{prevItemDiff.title}」（{prevItemDiff.formLabel} · {prevItemDiff.version}）与当前组织有以下差异：
            </strong>
            <ul>
              {prevItemDiff.differences.map((diff, idx) => (
                <li key={`${diff.item}-${idx}`}>
                  {diff.item}：{diff.before || "空"} → {diff.after || "空"}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {switchProblemInfo !== null ? (
          <div className="v21-org-alert is-danger" role="status" data-testid="org-switch-problem">
            {switchProblemInfo.message}
          </div>
        ) : null}

        {switchCmd.submitted && switchProblemInfo === null ? (
          <p className="hint" role="status">
            已提交组织切换，等待更新完成
          </p>
        ) : null}

        {switchOpen ? (
          <div className="v21-org-switch-panel" data-testid="org-switch-panel">
            <FormCards app={props.app} onPick={handlePickForm} hint={null} />
            {switchPicked !== "" ? (
              <div className="v21-org-switch-confirm" data-testid="org-switch-confirm">
                <p>换成这一份以后，以下本项目自定义改动会丢弃（历史里保留，改回即可找回）：</p>
                <Loading state={switchDraft} />
                {switchDraft.error !== null ? (
                  <p className="error">{readFailureText(switchDraft.error)}</p>
                ) : null}
                {switchDraft.data !== null && switchDiscarded.length === 0 ? (
                  <p className="y10-note note">没有需要丢弃的自定义项。</p>
                ) : null}
                {switchDiscarded.length > 0 ? (
                  <ul className="v21-org-card-list" data-testid="org-switch-discarded">
                    {switchDiscarded.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                ) : null}
                <div className="y10-row">
                  <SubmitButton
                    label="确认换成这一份"
                    busy={switchCmd.busy}
                    disabled={switchDraft.loading && switchDraft.data === null}
                    onClick={() => submitFormSwitch(switchPicked)}
                  />
                  <button
                    type="button"
                    className="y10-btn small"
                    onClick={() => setSwitchPicked("")}
                  >
                    换一张卡
                  </button>
                </div>
              </div>
            ) : null}
          </div>
        ) : null}
      </Block>

      {questions !== null ? (
        <Block title="四问概览" subtitle="以下四条完全按当前合成组织推出" dataTestId="org-questions-block">
          <div className="v21-org-questions" data-testid="org-questions">
            <div className="v21-org-qcard">
              <p className="v21-org-qtitle">事项从哪来</p>
              <p className="v21-org-qbody" data-testid="org-q-from">
                {questions.fromWhere}
              </p>
            </div>
            <div className="v21-org-qcard">
              <p className="v21-org-qtitle">谁做</p>
              <p className="v21-org-qbody" data-testid="org-q-who">
                {questions.whoDoes}
              </p>
            </div>
            <div className="v21-org-qcard">
              <p className="v21-org-qtitle">谁核验</p>
              <p className="v21-org-qbody" data-testid="org-q-verify">
                {questions.whoVerifies}
              </p>
            </div>
            <div className="v21-org-qcard">
              <p className="v21-org-qtitle">怎么结束</p>
              <p className="v21-org-qbody" data-testid="org-q-end">
                {questions.howEnds}
              </p>
            </div>
          </div>
        </Block>
      ) : null}

      {blueprint !== null ? (
        <Block
          title="组织蓝图"
          subtitle={`轮转方式：${blueprint.routingLabel} · 结束方式：${blueprint.endingText}`}
          dataTestId="org-blueprint-block"
        >
          <div className="v21-org-blueprint-wrap">
            <LoopGraphView
              graph={blueprint.loopGraph}
              pick={null}
              onPickNode={(deptId) => navigateToDepartment(deptId)}
              onPickArrow={() => {}}
              onPickAsk={() => {}}
            />

            <div className="v21-org-stages">
              <div className="v21-org-stage">
                <span className="v21-org-stage-head">入口</span>
                {blueprint.sources.length === 0 ? (
                  <p className="y10-note note">未声明入口</p>
                ) : (
                  blueprint.sources.map((node) => (
                    <div key={node.id} className="v21-org-stage-node">
                      <div className="v21-org-stage-title">{node.title}</div>
                      <div className="v21-org-stage-detail">{node.detail}</div>
                    </div>
                  ))
                )}
              </div>

              <div className="v21-org-stage">
                <span className="v21-org-stage-head">执行与交接</span>
                {blueprint.executors.map((node) => (
                  <div key={node.id} className="v21-org-stage-node">
                    <div className="v21-org-stage-title">{node.title}</div>
                    <div className="v21-org-stage-detail">{node.detail}</div>
                  </div>
                ))}
              </div>

              {blueprint.verifiers.length > 0 ? (
                <div className="v21-org-stage">
                  <span className="v21-org-stage-head">独立核验</span>
                  {blueprint.verifiers.map((node) => (
                    <div key={node.id} className="v21-org-stage-node is-verifier">
                      <div className="v21-org-stage-title">{node.title}</div>
                      <div className="v21-org-stage-detail">{node.detail}</div>
                    </div>
                  ))}
                </div>
              ) : null}

              <div className="v21-org-stage">
                <span className="v21-org-stage-head">怎么结束</span>
                <div className="v21-org-stage-node is-ending">
                  <div className="v21-org-stage-title">{blueprint.endingNode.title}</div>
                  <div className="v21-org-stage-detail">{blueprint.endingNode.detail}</div>
                </div>
              </div>
            </div>

            <div className="v21-org-flow" data-testid="org-flow-steps">
              <h3 className="v21-org-flow-title">成果怎么走</h3>
              <ol className="v21-org-flow-list">
                {blueprint.flowSteps.map((step, idx) => (
                  <li key={`${idx}-${step}`}>{step}</li>
                ))}
              </ol>
            </div>
          </div>
        </Block>
      ) : null}

      <Block
        title="职能列表（只读）"
        subtitle={
          props.departments.length > 0
            ? `共 ${deptRows.length} 个职能 · 点击任意一行查看该职能详情；新增、移除或调整职能定义请让运维助手通过命令行处理`
            : "点击任意一行查看该职能详情；新增、移除或调整职能定义请让运维助手通过命令行处理"
        }
        dataTestId="org-departments-block"
      >
        {deptRows.length === 0 ? (
          <Empty text="当前组织还没有职能" />
        ) : (
          <div className="y10-table-wrap table-scroll v21-org-dept-table">
            <table className="y10-table">
              <thead>
                <tr>
                  <th scope="col">职能</th>
                  <th scope="col">负责什么（target）</th>
                  <th scope="col">什么时候开工</th>
                  <th scope="col">交出什么</th>
                  <th scope="col">{relationColTitle}</th>
                  <th scope="col">当前生效模型</th>
                  <th scope="col">来源</th>
                </tr>
              </thead>
              <tbody>
                {deptRows.map((row) => {
                  const deptHref = paths.departmentDetail(projectId, row.id, {
                    workItem: props.route.workItemId,
                    from: "org",
                  });
                  return (
                    <tr
                      key={row.id}
                      className={row.clickable ? "is-clickable" : undefined}
                      data-testid={`org-dept-row-${row.id}`}
                      onClick={row.clickable ? () => navigateToDepartment(row.id) : undefined}
                    >
                      <td data-label="职能">
                        <div className="v21-org-dept-name">
                          {row.clickable ? (
                            <a
                              href={deptHref}
                              onClick={(event) => {
                                event.preventDefault();
                                event.stopPropagation();
                                navigateToDepartment(row.id);
                              }}
                            >
                              {row.label}
                            </a>
                          ) : (
                            <span>{row.label}</span>
                          )}
                          {row.verifier ? <Tag tone="ok">核验角色</Tag> : null}
                        </div>
                      </td>
                      <td data-label="负责什么（target）">{row.target}</td>
                      <td data-label="什么时候开工">{row.whenToStart}</td>
                      <td data-label="交出什么">{row.outputs}</td>
                      <td data-label={relationColTitle}>{row.relationText}</td>
                      <td data-label="当前生效模型">
                        <div className="v21-org-model-main">{row.modelText}</div>
                        <div className="v21-org-model-src">{row.modelSourceText}</div>
                      </td>
                      <td data-label="来源">
                        <Tag tone={originTagTone(row.originKind)}>{row.originLabel}</Tag>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Block>

      {candidates.length > 0 ? (
        <Block
          title="待采用的候选"
          subtitle="来自项目运行过程中的改进建议；审阅差异与依据后可决定是否采纳"
          dataTestId="org-candidates-block"
        >
          <div className="v21-org-candidates">
            {candidates.map((cand) => (
              <div key={cand.key} className="v21-org-card" data-testid={`org-candidate-${cand.key}`}>
                <div className="v21-org-card-head">
                  <strong>{cand.title}</strong>
                  {cand.summary ? <span className="y10-note note">{cand.summary}</span> : null}
                </div>
                {cand.diffLines.length > 0 ? (
                  <div>
                    <strong>差异：</strong>
                    <ul className="v21-org-card-list">
                      {cand.diffLines.map((line, i) => (
                        <li key={i}>{line}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {cand.evidenceLines.length > 0 ? (
                  <div>
                    <strong>依据：</strong>
                    <ul className="v21-org-card-list">
                      {cand.evidenceLines.map((line, i) => (
                        <li key={i}>{line}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </Block>
      ) : null}

      <Block title="采用历史" subtitle="按时间倒序排列；需要退回某一次记录时点「改回这一份」先看差异再确认" dataTestId="org-history-block">
        {historyRows.length === 0 ? (
          <Empty text="还没有组织调整历史" />
        ) : (
          <div className="v21-org-history">
            {historyRows.map((row) => (
              <div
                key={row.eventId}
                className={`v21-org-card${row.isCurrent ? " is-current" : ""}`}
                data-testid={`org-history-row-${row.eventId}`}
              >
                <div className="v21-org-card-head">
                  <div className="v21-org-card-meta">
                    <span className="v21-org-card-time">{row.atText}</span>
                    <span>{row.actorLabel}</span>
                    <strong>
                      {row.previousFormLabel}（{row.previousVersion}）→ {row.formLabel}（{row.version}）
                    </strong>
                    {row.isCurrent ? <Tag tone="ok">现在</Tag> : null}
                  </div>
                  {row.canRevert && editable ? (
                    <button
                      type="button"
                      className="y10-btn is-small small"
                      data-testid={`org-revert-btn-${row.eventId}`}
                      onClick={() => openRevertModal(row)}
                    >
                      改回这一份
                    </button>
                  ) : null}
                </div>
                <div className="y10-note note">原因：{row.reason}</div>
                {row.diffLines.length > 0 ? (
                  <ul className="v21-org-card-list">
                    {row.diffLines.map((line, idx) => (
                      <li key={idx}>{line}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </Block>

      {revertRow !== null ? (
        <Modal title="改回这一份组织" onClose={closeRevertModal}>
          <div data-testid="org-revert-modal">
            <div className="v21-org-modal-section">
              <h3>目标份</h3>
              <p>
                {revertRow.formLabel}（版本 {revertRow.version} · 原采用时间 {revertRow.atText}）
              </p>
            </div>

            <Loading state={revertDraft} />

            {revertDraft.error !== null ? (
              <div className="v21-org-alert is-danger">{readFailureText(revertDraft.error)}</div>
            ) : null}

            {revertPreview !== null && revertDraft.data !== null ? (
              <>
                <div className="v21-org-modal-section">
                  <h3>改回后的结束条件</h3>
                  <p>
                    <Tag tone={revertPreview.isOpenLoop ? "warn" : "ok"}>
                      {revertPreview.isOpenLoop ? "开环完成" : "核验放行"}
                    </Tag>{" "}
                    {revertPreview.finishesText}
                  </p>
                </div>

                <div className="v21-org-modal-section">
                  <h3>与当前组织的差异</h3>
                  <ul className="v21-org-card-list" data-testid="org-revert-diffs">
                    {revertPreview.diffLines.map((line, idx) => (
                      <li key={idx}>{line}</li>
                    ))}
                  </ul>
                </div>

                {revertPreview.discarded.length > 0 ? (
                  <div className="v21-org-modal-section">
                    <h3>将丢弃的项目覆盖</h3>
                    <ul className="v21-org-card-list">
                      {revertPreview.discarded.map((line, idx) => (
                        <li key={idx}>{line}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                {revertPreview.reminders.length > 0 ? (
                  <div className="v21-org-alert is-warn">
                    {revertPreview.reminders.join("；")}
                  </div>
                ) : null}

                {revertPreview.rejections.length > 0 ? (
                  <div className="v21-org-alert is-danger">
                    无法直接改回：{revertPreview.rejections.join("；")}
                  </div>
                ) : null}
              </>
            ) : null}

            <div className="v21-org-modal-section">
              <TextInput
                label="改回原因（记入采用历史）"
                value={revertReason}
                placeholder="填写改回原因"
                disabled={revertCmd.busy}
                onInput={setRevertReason}
              />
            </div>

            {revertProblemInfo !== null ? (
              <div className="v21-org-alert is-danger" role="status" data-testid="org-revert-problem">
                {revertProblemInfo.message}
              </div>
            ) : null}

            <div className="v21-org-modal-actions">
              <button type="button" className="y10-btn small" onClick={closeRevertModal}>
                取消
              </button>
              <SubmitButton
                label="确认改回这一份"
                busy={revertCmd.busy}
                disabled={
                  revertDraft.loading ||
                  revertDraft.data === null ||
                  revertPreview === null ||
                  revertPreview.blocked ||
                  revertReason.trim() === ""
                }
                onClick={submitRevert}
              />
            </div>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}
