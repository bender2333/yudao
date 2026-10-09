// 重新开始建档（3.8，设计第 3.1 节）：项目由接入已有项目建立、建档停下而还没有基线采纳时，
// 从登记的源目录重新采集快照并开始新的建档事项。可用条件取自 projects.list 的 onboarding_status
// （接入已有项目建立、还没有基线采纳、没有进行中的建档事项时为 awaiting_onboarding），
// 源目录的登记名取自 project.settings；服务端负责最后的判定与拒绝原因。

import { useMemo, useState } from "react";
import type { ProjectList, ProjectSettingsResult } from "../../api/generated/types.gen";
import type { ClientApp } from "../../contract/client-app";
import { CommandFeedback, Section, hasCommand } from "./common";
import { useCommand, useSnapshot } from "./use-snapshot";

export function RestartOnboarding(props: { app: ClientApp; projectId: string }) {
  const projects = useSnapshot<ProjectList>(props.app, "page.onboarding.projects", "projects.list", {});
  const settings = useSnapshot<ProjectSettingsResult>(props.app, "page.onboarding.settings", "project.settings", {
    project_id: props.projectId,
  });
  const row = projects.data?.projects.find((project) => project.project_id === props.projectId);
  const sources = useMemo(
    () => Object.values(settings.data?.source_directories ?? {}),
    [settings.data],
  );
  const [picked, setPicked] = useState<string | null>(null);
  const chosen = picked !== null && sources.some((source) => source.name === picked)
    ? picked
    : sources[0]?.name ?? null;
  const command = useCommand(props.app, JSON.stringify([chosen, row?.onboarding_status]));

  if (!hasCommand(props.app, "onboarding.restart") || row?.onboarding_status !== "awaiting_onboarding") {
    return null;
  }

  return (
    <Section
      title="重新开始建档"
      note="建档已经停下，还没有基线采纳。从登记的源目录重新采集代码快照，开始新的建档事项"
    >
      {sources.length === 0 ? (
        <p className="y9-note note">这个项目还没有登记源目录，先在项目设置里登记。</p>
      ) : (
        <div className="y9-row row-actions">
          {sources.length > 1 ? (
            <label className="y9-field field">
              <span>源目录</span>
              <select className="y9-select" value={chosen ?? ""} onChange={(event) => setPicked(event.target.value)}>
                {sources.map((source) => (
                  <option key={source.name} value={source.name}>{source.name}（{source.path}）</option>
                ))}
              </select>
            </label>
          ) : (
            <span className="y9-note note">源目录：{sources[0].name}（{sources[0].path}）</span>
          )}
          <button
            type="button"
            className="y9-btn primary"
            disabled={command.busy || chosen === null}
            onClick={() => chosen !== null
              && void command.submit("onboarding.restart", { project_id: props.projectId, source_name: chosen })}
          >
            {command.busy ? "正在提交" : "重新开始建档"}
          </button>
          <CommandFeedback submitted={command.submitted} rejection={command.rejection} />
        </div>
      )}
    </Section>
  );
}
