// 职能详情（工单 #1713）：项目的组织设计说明 4.9「职能详情」里「发布带的那一版」。
//
// 从节点面板的「职能详情」进，自己加的职能同样能进。三组：
// 职责只读（取自项目现在的组织 project.organization，要改走「高级」）、
// 权限里的写入范围只读、模型与 Prompt 可改（写入本项目的职能设置 project.settings，
// 下一次模型请求生效；每项写明跟随发布还是本项目写入，能恢复）。
// 由谁做只写「自有角色」，不给选项：外部 agent 与小组有了以后再出现。
// 工具许可、可见范围与位置这一版不显示：组织的查询还没有给出它们。
// 设置页不再有「职能设置」一节，原来那一节的表单从这里引用（工单 #1713）。

import type {
  Catalog, ProjectOrganizationResult, ProjectSettingsResult,
} from "../../api/generated/types.gen";
import type { ClientApp } from "../../contract/client-app";
import { readFailureText } from "../../contract/read-failure";
import { PageHead, Block } from "../../shell/kit";
import { paths, type Route } from "../../shell/routing";
import { CommandFeedback, Empty, KeyValue, Loading, list, pageKey, text } from "./common";
import {
  dutyRows, NOT_SHOWN_NOTE, requestsPath, scopeRows, settingSourceRows, sourceText,
} from "./department-detail-model.ts";
import {
  DepartmentSettingsFields, DepartmentSettingsSave, ReminderList, useDepartmentDraft,
} from "./department-settings-form";
import { departmentLabel, type DepartmentView } from "./organization";
import { useCommand, useSnapshot } from "./use-snapshot";
import { mergedModelId, modelById } from "../models/model-logic";

export function DepartmentDetailPage(props: {
  app: ClientApp;
  route: Route;
  organization: ProjectOrganizationResult | null;
  departments: DepartmentView[];
}) {
  const projectId = props.route.projectId ?? "";
  const department = props.route.department ?? "";
  const workItemId = props.route.workItemId;
  const labels: Record<string, string> = {};
  for (const item of props.departments) {
    labels[item.id] = item.label;
  }
  const name = departmentLabel(department, labels);
  const settings = useSnapshot<ProjectSettingsResult>(props.app, "page.dept.detail.settings", "project.settings", {
    project_id: projectId,
  }, projectId === "");
  const setting = settings.data?.departments[department] ?? null;
  // 刚才保存过的那一版带上它自己的提醒：建议能力的提醒照旧（设计说明 9.2）
  const command = useCommand(props.app, pageKey([setting?.version]));

  return (
    <div className="page y10-dept-detail">
      <PageHead
        eyebrow="职能详情"
        title={name === "" ? "职能详情" : name}
        subtitle="职责与权限只读；由谁做、模型与 Prompt 在这里改，保存后从下一次模型请求起生效。"
        actions={<a className="y10-btn is-small small" href={paths.conversation(projectId, { workItem: workItemId })}>关闭</a>}
      />
      <Loading state={settings} />
      {settings.error !== null ? <p className="y10-note note" role="status">{readFailureText(settings.error)}</p> : null}
      {props.organization === null ? (
        <Empty text="项目现在的组织还没有读出来：职责与权限要等它" />
      ) : null}
      <Block title="职责" subtitle="之后新建的事项 · 只读，要改走「高级」" dataTestId="dept-detail-duty">
        <KeyValue items={dutyRows(props.organization?.organization ?? null, department).map((row) => [row.label, row.value])} />
        <p className="y10-note note">{NOT_SHOWN_NOTE}</p>
      </Block>
      <Block title="由谁做" subtitle="之后新建的事项 · 只读" dataTestId="dept-detail-solver">
        <p className="y10-note note">自有角色</p>
      </Block>
      <Block title="权限" subtitle="之后新建的事项 · 只读" dataTestId="dept-detail-scope">
        <KeyValue items={scopeRows(props.organization?.organization ?? null, department).map((row) => [row.label, row.value])} />
      </Block>
      <Block title="模型与 Prompt" subtitle="下一次模型请求，包括进行中的事项" dataTestId="dept-detail-model">
        {setting === null && !settings.loading ? (
          <Empty text="这个职能没有本项目的职能设置" />
        ) : (
          <ModelSection
            app={props.app}
            projectId={projectId}
            department={department}
            setting={setting}
            reminders={settings.data?.department_reminders[department] ?? []}
            command={command}
          />
        )}
        <p className="y10-note note">
          <a href={requestsPath(projectId, workItemId, department)}>本职能的模型请求</a>
        </p>
      </Block>
    </div>
  );
}

// 模型、推理档位与职能 Prompt（设计说明 9.2）：复用的表单与设置页原来是同一份。
// 每项写明来源：本项目的职能设置写了这一项就是「本项目写入」，没写就跟随发布
function ModelSection(props: {
  app: ClientApp;
  projectId: string;
  department: string;
  setting: ProjectSettingsResult["departments"][string] | null;
  reminders: string[];
  command: ReturnType<typeof useCommand>;
}) {
  const [draft, setDraft, saved] = useDepartmentDraft(props.setting);
  const catalog = useSnapshot<Catalog>(props.app, `page.dept.detail.catalog.${props.projectId}`, "catalog", {});
  const bindings = catalog.data?.bindings ?? {};
  const models = catalog.data?.models ?? [];
  const effectiveId = mergedModelId(props.setting?.model_id, props.department, bindings);
  const effectiveModel = modelById(models, effectiveId);
  const followName = effectiveModel?.model ?? (effectiveId === "" ? "" : effectiveId);
  const savedReminders = list(props.command.accepted?.reminders).map((item) => text(item)).filter((item) => item !== "");

  return (
    <div className="y10-dept-detail-model form">
      <p className="y10-note note" data-testid="dept-detail-current">
        当前生效的模型及来源：{followName === "" ? "未设置" : followName} · {sourceText(Boolean(props.setting?.model_id))}
        {props.setting === null ? "" : ` · 第 ${props.setting.version} 版`}
      </p>
      <KeyValue className="y10-kv kv" items={settingSourceRows(props.setting).map((row) => [row.label, row.value])} />
      <DepartmentSettingsFields
        app={props.app}
        projectId={props.projectId}
        department={props.department}
        draft={draft}
        onDraft={setDraft}
        effective={{ state: effectiveId === "" ? "unset" : "effective", model: followName }}
        reminders={[...props.reminders, ...savedReminders]}
        saved={saved}
      />
      <ReminderList items={props.reminders} testId={`dept-detail-reminder-${props.department}`} />
      <DepartmentSettingsSave
        projectId={props.projectId}
        department={props.department}
        setting={props.setting}
        draft={draft}
        command={props.command}
        onSaved={() => undefined}
      />
      <CommandFeedback submitted={props.command.submitted} problem={props.command.problem} />
    </div>
  );
}
