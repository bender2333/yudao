// 独立新建与接入已有项目页（工单 #1806，docs/design/project-organization.md「新建的入口」）：
// 从左侧栏只留跳转入口，这里在右侧主工作区以全宽舒展展示名称、源目录、起始文件夹与所有形态卡；
// 点卡之前由 cardPickProblem 核对必填字段，点卡即发起 project.create 或 project.onboard，
// 写入完成以后转到新项目的对话页（#/p/{project_id}/conversation）。

import { useEffect, useMemo, useState } from "react";
import type { Capabilities, ProjectRow } from "../../api/generated/types.gen";
import type { ClientApp } from "../../contract/client-app";
import { Block, PageHead } from "../../shell/kit";
import { newProjectPageMeta, type NewProjectMode } from "../../shell/new-project-text";
import { paths } from "../../shell/routing";
import { FormCards } from "../project/form-cards";
import { cardPickProblem, projectEntryBody } from "../project/form-cards-model";
import { onboardingProblemText, sourceInvalidLines } from "../project/onboarding";
import { useCommand } from "../project/use-snapshot";

export type NewProjectPageProps = {
  app: ClientApp | null;
  mode: NewProjectMode;
  capabilities: Capabilities;
  projects: ProjectRow[];
  onCancel: () => void;
  onNavigate: (hash: string) => void;
};

// 命令受理回执里的标识：project.create 与 project.onboard 都带 refs.project_id，
// 新建成功以后用它转到新项目的对话（工单 #1160）；没有这一项时返回空串
function receiptId(accepted: Record<string, unknown> | null, key: string): string {
  const refs = accepted?.["refs"];
  if (refs === null || refs === undefined || typeof refs !== "object") {
    return "";
  }
  const value = (refs as Record<string, unknown>)[key];
  return typeof value === "string" ? value : "";
}

export function NewProjectPage(props: NewProjectPageProps) {
  const meta = newProjectPageMeta(props.mode);
  const canUseEntry = props.capabilities.commands.some((item) => item.name === meta.requiredCapability);
  const dataKey = useMemo(
    () => JSON.stringify(props.projects.map((row) => [row.project_id, row.onboarding_status])),
    [props.projects],
  );
  const command = useCommand(props.app, dataKey);

  const [name, setName] = useState("");
  const [sourceName, setSourceName] = useState("");
  const [sourcePath, setSourcePath] = useState("");
  const [initialDirectory, setInitialDirectory] = useState("");
  const [hint, setHint] = useState<string | null>(null);
  const [waitingWrite, setWaitingWrite] = useState(false);

  // 本次提交被接受以后等事件到达：项目列表由事件到达时重新查询，列表出现新内容以后「已提交」消失，
  // 或新项目已经出现在项目列表里时转到新项目的对话页；被拒绝时 submit 返回假，保留已填字段并显示原因
  useEffect(() => {
    if (!waitingWrite) {
      return;
    }
    const projectId = receiptId(command.accepted, "project_id");
    const listed = projectId !== "" && props.projects.some((row) => row.project_id === projectId);
    if (!command.submitted || listed) {
      if (projectId !== "") {
        props.onNavigate(paths.conversation(projectId));
      } else {
        props.onCancel();
      }
    }
  }, [waitingWrite, command.submitted, command.accepted, props.projects, props.onNavigate, props.onCancel]);

  // 点卡：名字空着、或接入时缺源目录都不发命令，把那句话写在卡片上方
  const pickForm = (form: string): void => {
    if (command.busy || !canUseEntry) {
      return;
    }
    const input = { mode: props.mode, name, sourceName, sourcePath };
    const problem = cardPickProblem(input);
    if (problem !== null) {
      setHint(problem);
      return;
    }
    const body = projectEntryBody({ ...input, form, initialDirectory });
    if (body === null) {
      return;
    }
    setHint(null);
    void command.submit(meta.commandName, body).then((ok) => setWaitingWrite(ok));
  };

  return (
    <div className="y10-page v20-np-page" data-testid="new-project-page" data-mode={props.mode}>
      <PageHead
        title={meta.title}
        subtitle={meta.subtitle}
        actions={
          <button
            type="button"
            className="y10-btn"
            data-testid="new-project-cancel"
            onClick={props.onCancel}
          >
            取消
          </button>
        }
      />
      {!canUseEntry ? (
        <Block className="v20-np-block">
          <p className="y10-note note">{meta.missingCapabilityText}</p>
        </Block>
      ) : (
        <Block className="v20-np-block">
          <form
            className="y10-form v20-np-form"
            onSubmit={(event) => {
              // 提交靠点卡：回车只核对字段，不发命令
              event.preventDefault();
              setHint(cardPickProblem({ mode: props.mode, name, sourceName, sourcePath }));
            }}
          >
            <div className="v20-np-fields">
              <label className="y10-field field">
                <span>项目名称</span>
                <input
                  className="y10-input"
                  type="text"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  required
                />
              </label>
              {meta.showSourceDirectory ? (
                <>
                  <label className="y10-field field">
                    <span>源目录名称</span>
                    <input
                      className="y10-input"
                      type="text"
                      value={sourceName}
                      onChange={(event) => setSourceName(event.target.value)}
                      required
                    />
                  </label>
                  <label className="y10-field field v20-np-field-wide">
                    <span>源目录路径</span>
                    <input
                      className="y10-input"
                      type="text"
                      value={sourcePath}
                      onChange={(event) => setSourcePath(event.target.value)}
                      required
                    />
                  </label>
                </>
              ) : null}
            </div>
            {meta.showSourceDirectory ? (
              <p className="y10-note note">接入以后会登记源目录、采集代码快照并开始建档事项（3.8）。</p>
            ) : null}
            <div className="v20-np-cards">
              <div className="v20-np-cards-head">
                <h2>{meta.cardsHeading}</h2>
                <p className="y10-muted">{meta.cardsHint}</p>
              </div>
              {/* 形态卡：一份形态一张卡，点卡就建好（发不发命令由名字与源目录决定） */}
              <FormCards app={props.app} hint={hint} onPick={pickForm} />
            </div>
            {meta.showInitialDirectory ? (
              // 起始文件夹是可选的一份快照，收在小入口里（原型 v13 的说明，工单 #1160）
              <details className="y10-details v20-new-project-dir">
                <summary>选起始文件夹（可选）</summary>
                <label className="y10-field field">
                  <span>起始文件夹</span>
                  <input
                    className="y10-input"
                    type="text"
                    value={initialDirectory}
                    placeholder="控制主机上的文件夹路径，留空则从空项目开始"
                    onChange={(event) => setInitialDirectory(event.target.value)}
                  />
                  <small className="y10-muted">填写时，新建项目取这个文件夹的一份快照，作为项目的起点；以后对这个文件夹的修改不影响项目。不填时从空目录开始。</small>
                </label>
              </details>
            ) : null}
            {meta.formNote ? <p className="y10-note note">{meta.formNote}</p> : null}
            {command.problem ? (
              <div className="rejection y10-rejection" role="status">
                <p className="error">{onboardingProblemText(command.problem)}</p>
                <ul className="rejection-paths y10-list">
                  {sourceInvalidLines(command.problem).map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {command.busy ? <p className="y10-muted hint" role="status">正在提交</p> : null}
            {command.submitted ? <p className="y10-muted hint" role="status">已提交，等待写入结果</p> : null}
          </form>
        </Block>
      )}
    </div>
  );
}
