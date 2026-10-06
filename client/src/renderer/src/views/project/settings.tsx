// 设置页（原型 v8 设计说明第 7.5 节，工单 #80）：基本信息、部门设置、登记命令与登记的源目录。
// 数据全部来自 project.settings；每项修改提交对应的命令，基准版本取快照里的 version，
// 过期时拒绝并提示重新读取（工单验收第 3 条）。部门设置里的模型与档位由 #95 加入，
// 工具授权（3.2B）与机器授权（3.2C）的命令尚未登记，入口按能力清单不出现。

import { useState } from "react";
import type { ClientApp } from "../../contract/client-app";
import type { Catalog, ProjectSettingsResult } from "../../api/generated/types.gen";
import type { Route } from "../../shell/routing";
import {
  Checkbox, CommandFeedback, Empty, KeyValue, Loading, Modal, Section, SubmitButton, Table, TextArea, TextInput,
  formatNumberOr, hasCommand, list, pageKey, text, useDraft,
} from "./common";
import { DepartmentSettingsFields, DepartmentSettingsSave, ReminderList, useDepartmentDraft } from "./department-settings-form";
import { SETTING_SOURCE, departmentName, label } from "./labels";
import { type CommandState, useCommand, useSnapshot } from "./use-snapshot";
import { followDepartmentLabel, mergedModelId, modelById } from "../models/model-logic";

export function SettingsPage(props: { app: ClientApp; route: Route }) {
  const projectId = props.route.projectId ?? "";
  const settings = useSnapshot<ProjectSettingsResult>(props.app, "page.settings", "project.settings", {
    project_id: projectId,
  });
  const data = settings.data;
  // 提交提示跟随快照：事件到达、快照出现新内容以后由数据本身显示最终状态
  const command = useCommand(props.app, pageKey([data?.version, data?.name, data?.goal, data?.pinned, data?.archived]));

  return (
    <div className="page">
      <Loading state={settings} />
      {data ? (
        <>
          <Basics app={props.app} data={data} command={command} />
          <Departments app={props.app} data={data} />
          <CommandRegistry app={props.app} data={data} />
          <SourceDirectories app={props.app} data={data} />
        </>
      ) : null}
    </div>
  );
}

// 基本信息（7.5 节第 1 项）：名称、长期目标、置顶、归档与恢复。
// 名称、长期目标、置顶、归档共用项目的基准版本；其中一项被拒绝以后重新读取即可看到当前值
function Basics(props: { app: ClientApp; data: ProjectSettingsResult; command: CommandState }) {
  const { data, command } = props;
  const [name, setName] = useDraft(`settings/${data.project_id}/name`, data.name);
  const [goal, setGoal] = useDraft(`settings/${data.project_id}/goal`, data.goal);
  const [editing, setEditing] = useState(false);
  const base = { project_id: data.project_id, base_version: data.version };

  return (
    <Section title="基本信息" note={`当前项目版本 ${data.version}`}>
      <KeyValue
        items={[
          ["项目", data.project_id],
          ["当前名称", data.name],
          ["长期目标", data.goal || "没有填写"],
          ["置顶", data.pinned ? "是" : "否"],
          ["状态", data.archived ? "已归档" : "进行中"],
        ]}
      />
      <div className="row-actions">
        <button type="button" onClick={() => setEditing(!editing)}>
          {editing ? "收起" : "修改名称与长期目标"}
        </button>
        {hasCommand(props.app, "project.pin") ? (
          <SubmitButton
            label={data.pinned ? "取消置顶" : "置顶"}
            busy={command.busy}
            onClick={() => void command.submit("project.pin", { ...base, pinned: !data.pinned })}
          />
        ) : null}
        {data.archived ? (
          hasCommand(props.app, "project.restore") ? (
            <SubmitButton
              label="恢复项目"
              busy={command.busy}
              onClick={() => void command.submit("project.restore", base)}
            />
          ) : null
        ) : hasCommand(props.app, "project.archive") ? (
          <SubmitButton
            label="归档项目"
            busy={command.busy}
            onClick={() => void command.submit("project.archive", base)}
          />
        ) : null}
      </div>
      {editing ? (
        <div className="form">
          <TextInput label="名称" value={name} onInput={setName} />
          <TextArea label="长期目标" value={goal} rows={3} onInput={setGoal} />
          <p className="note">长期目标修改以后，之后开始的事项使用新目标；进行中的事项按开始时的目标做完。</p>
          <SubmitButton
            label="保存名称"
            busy={command.busy}
            disabled={name.trim() === "" || name === data.name}
            onClick={() => void command.submit("project.rename", { ...base, name: name.trim() })}
          />
          <SubmitButton
            label="保存长期目标"
            busy={command.busy}
            disabled={goal === data.goal}
            onClick={() => void command.submit("project.set_goal", { ...base, goal })}
          />
        </div>
      ) : null}
      <CommandFeedback submitted={command.submitted} rejection={command.rejection} />
    </Section>
  );
}

// 部门设置（7.5 节第 2 项）：各部门的项目部门设置，内容同部门设置弹窗（第 9.2 节）。
// 模型、推理档位与部门 Prompt 三项一起保存；模型与档位由 #95 加入，
// 读取与保存的版本由 project.settings 给出，部门默认来自 catalog 的 bindings，
// 生效模型的跟随说明与建议能力提醒按第 5.3、5.6 节计算
function Departments(props: { app: ClientApp; data: ProjectSettingsResult }) {
  const { data } = props;
  const entries = Object.entries(data.departments);
  const [editing, setEditing] = useState<string | null>(null);
  const catalog = useSnapshot<Catalog>(props.app, "page.settings.catalog", "catalog", {});
  // 生效模型的说明与档位声明：项目设置写入了模型就用它，否则用部门默认（catalog 的 bindings）
  const bindings = catalog.data?.bindings ?? {};
  const models = catalog.data?.models ?? [];

  return (
    <Section title="部门设置" note="本项目各部门的项目部门设置：模型、推理档位与部门 Prompt（第 9.2 节）">
      {entries.length === 0 ? <Empty text="没有登记部门设置" /> : null}
      {entries.map(([key, setting]) => {
        const effectiveId = mergedModelId(setting.model_id, key, bindings);
        const model = modelById(models, effectiveId);
        const followText = followDepartmentLabel(model?.model ?? (effectiveId ? effectiveId : ""));
        const reminders = data.department_reminders[key] ?? [];
        return (
          <div className="sub-card" key={key}>
            <div className="section-head">
              <h3>
                {departmentName(key)}（{key}）
              </h3>
              <p className="note">
                {setting.version} 版；来源 {label(SETTING_SOURCE, setting.source)}
              </p>
            </div>
            <p className="note">
              模型与档位：{setting.model_id
                ? `${model?.model ?? setting.model_id}${setting.requested_tier ? `，档位 ${setting.requested_tier}` : ""}`
                : `${followText}${setting.requested_tier ? `，档位 ${setting.requested_tier}` : ""}`}
            </p>
            <ReminderList items={reminders} testId={`settings-reminder-${key}`} />
            <pre className="raw department-setting-text">{setting.text || "（没有部门 Prompt 文字）"}</pre>
            {editing === key ? (
              <DepartmentSettingsForm app={props.app} data={data} department={key} onClose={() => setEditing(null)} />
            ) : (
              <button type="button" onClick={() => setEditing(key)}>
                修改部门设置
              </button>
            )}
          </div>
        );
      })}
    </Section>
  );
}

function DepartmentSettingsForm(props: {
  app: ClientApp;
  data: ProjectSettingsResult;
  department: string;
  onClose: () => void;
}) {
  const { data } = props;
  const setting = data.departments[props.department];
  const [draft, setDraft] = useDepartmentDraft(setting ?? null);
  const command = useCommand(props.app, pageKey([setting?.version, draft.model, draft.tier, draft.text]));
  const catalog = useSnapshot<Catalog>(props.app, `page.settings.catalog.${props.department}`, "catalog", {});
  const bindings = catalog.data?.bindings ?? {};
  const models = catalog.data?.models ?? [];
  const reminders = data.department_reminders[props.department] ?? [];
  const savedReminders = list(command.accepted?.reminders).map((item) => text(item)).filter((item) => item !== "");

  if (setting === undefined) {
    return <Empty text={`没有 ${departmentName(props.department)} 的部门设置`} />;
  }

  // 生效模型的说明：项目设置写入了模型就用它，否则用部门默认（跟随部门默认的当前值）
  const effectiveId = mergedModelId(setting.model_id, props.department, bindings);
  const effectiveModel = modelById(models, effectiveId);
  const followName = effectiveModel?.model ?? (effectiveId ? effectiveId : "");

  return (
    <div className="form">
      <DepartmentSettingsFields
        app={props.app}
        projectId={data.project_id}
        department={props.department}
        draft={draft}
        onDraft={setDraft}
        effective={{
          state: effectiveId ? "effective" : "unset",
          model: followName,
        }}
        reminders={[...reminders, ...savedReminders]}
      />
      <div className="row-actions">
        <button type="button" onClick={() => setDraft({ ...draft, text: setting.text })}>恢复默认</button>
      </div>
      <DepartmentSettingsSave
        projectId={data.project_id}
        department={props.department}
        setting={setting}
        draft={draft}
        command={command}
        onSaved={props.onClose}
      />
      <button type="button" onClick={props.onClose}>取消</button>
      <CommandFeedback submitted={command.submitted} rejection={command.rejection} />
    </div>
  );
}

// 登记命令（7.5 节第 3 项，3.2A）：登记名、固定参数、允许的额外参数、时限、输出上限、版本。
// 每条登记命令的基准版本是它自己的 version；版本冲突时服务端以 stale_base 拒绝，页面提示重新读取
function CommandRegistry(props: { app: ClientApp; data: ProjectSettingsResult }) {
  const { data } = props;
  const entries = Object.entries(data.commands);
  const [editing, setEditing] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  if (!hasCommand(props.app, "command_registration.save")) {
    return (
      <Section title="登记命令">
        <Empty text="这台主机没有提供登记命令的操作" />
      </Section>
    );
  }

  return (
    <Section title="登记命令" note="部门可以在房间里调用这些命令；固定参数与允许的额外参数由这里决定">
      {entries.length === 0 ? <Empty text="还没有登记命令" /> : (
        <Table
          head={["登记名", "固定参数", "允许的额外参数", "时限", "输出上限", "可以重新执行", "版本", ""]}
          rows={entries.map(([key, setting]) => [
            setting.name,
            setting.argv.length > 0 ? setting.argv.join(" ") : "（无）",
            setting.args.length > 0 ? setting.args.join(" ") : "（不允许）",
            formatNumberOr(setting.timeout_sec, " 秒"),
            formatNumberOr(setting.output_limit, " 字节"),
            setting.repeatable ? "是" : "否",
            `第 ${setting.version} 版`,
            <button
              type="button"
              className="link"
              key={key}
              onClick={() => { setEditing(setting.name); setCreating(false); }}
            >
              修改
            </button>,
          ])}
        />
      )}
      {creating ? (
        <CommandForm app={props.app} data={data} name="" onClose={() => setCreating(false)} />
      ) : null}
      {editing !== null ? (
        <CommandForm app={props.app} data={data} name={editing} onClose={() => setEditing(null)} />
      ) : null}
      {creating || editing !== null ? null : (
        <button type="button" onClick={() => setCreating(true)}>登记新命令</button>
      )}
    </Section>
  );
}

function CommandForm(props: {
  app: ClientApp;
  data: ProjectSettingsResult;
  name: string;
  onClose: () => void;
}) {
  const { data } = props;
  const existing = data.commands[props.name];
  const scope = `settings/${data.project_id}/command/${props.name || "new"}`;
  const [name, setName] = useDraft(`${scope}/name`, existing?.name ?? "");
  const [argv, setArgv] = useDraft(`${scope}/argv`, existing?.argv.join(" ") ?? "");
  const [args, setArgs] = useDraft(`${scope}/args`, existing?.args.join(" ") ?? "");
  const [timeoutText, setTimeoutText] = useDraft(
    `${scope}/timeout`,
    existing === undefined ? "" : String(existing.timeout_sec),
  );
  const [outputText, setOutputText] = useDraft(
    `${scope}/output`,
    existing === undefined ? "" : String(existing.output_limit),
  );
  // 可以重新执行（工单 #242）：新登记默认关闭；修改时取当前登记的声明
  const [repeatableText, setRepeatableText] = useDraft(
    `${scope}/repeatable`,
    existing?.repeatable === true ? "yes" : "no",
  );
  const command = useCommand(props.app,
    pageKey([existing?.version, name, argv, args, timeoutText, outputText, repeatableText]));

  // 时限与输出上限：留空表示不写入（服务端保留默认值），填写时需要是非负整数
  const timeout = timeoutText === "" ? null : Number(timeoutText);
  const output = outputText === "" ? null : Number(outputText);
  const numbersInvalid =
    (timeout !== null && (!Number.isInteger(timeout) || timeout < 0))
    || (output !== null && (!Number.isInteger(output) || output < 0));
  const canSave = name.trim() !== "" && !numbersInvalid;

  return (
    <Modal title={props.name === "" ? "登记新命令" : `修改登记命令 ${props.name}`} onClose={props.onClose}>
      <div className="form">
        <TextInput label="登记名" value={name} disabled={props.name !== ""} onInput={setName} />
        <TextInput label="固定参数" value={argv} placeholder="含程序名，按空格拆分，例如 python -c print(1)" onInput={setArgv} />
        <TextInput label="允许的额外参数" value={args} placeholder="留空表示不允许；多个用空格分开" onInput={setArgs} />
        <TextInput label="时限（秒）" value={timeoutText} placeholder="留空表示使用默认值" onInput={setTimeoutText} />
        <TextInput label="输出上限（字节）" value={outputText} placeholder="留空表示使用默认值" onInput={setOutputText} />
        <Checkbox
          label="可以重新执行"
          checked={repeatableText === "yes"}
          onChange={(checked) => setRepeatableText(checked ? "yes" : "no")}
        />
        <p className="note">登记时声明这个命令可以重新执行：动作结果未知时，核实请求按这个声明给出「重新执行一次」的选项。</p>
        {numbersInvalid ? <p className="error">时限与输出上限需要是非负整数</p> : null}
        <SubmitButton
          label="保存"
          busy={command.busy}
          disabled={!canSave}
          onClick={() => void command.submit("command_registration.save", {
            project_id: data.project_id,
            name: name.trim(),
            base_version: existing?.version ?? 0,
            argv: argv === "" ? [] : argv.split(" ").filter((part) => part !== ""),
            args: args === "" ? [] : args.split(" ").filter((part) => part !== ""),
            timeout_sec: timeout,
            output_limit: output,
            repeatable: repeatableText === "yes",
          }).then((ok) => { if (ok) { props.onClose(); } })}
        />
        <button type="button" onClick={props.onClose}>取消</button>
        <CommandFeedback submitted={command.submitted} rejection={command.rejection} />
      </div>
    </Modal>
  );
}

// 登记的源目录（7.5 节第 1 项，3.2A）：接入已有项目时填写的源目录在这里查看与修改。
// 工单 #74 登记了 source_directory.save；没有登记时不显示这一节
function SourceDirectories(props: { app: ClientApp; data: ProjectSettingsResult }) {
  const { data } = props;
  const entries = Object.entries(data.source_directories);
  if (!hasCommand(props.app, "source_directory.save") && entries.length === 0) {
    return null;
  }

  return (
    <Section title="源目录" note="接入已有项目时登记的源目录；已有的代码只从这里进入 Yudao">
      {entries.length === 0 ? <Empty text="没有登记源目录" /> : (
        <Table
          head={["名称", "路径", "版本", ""]}
          rows={entries.map(([key, setting]) => [
            setting.name,
            setting.path,
            `第 ${setting.version} 版`,
            <SourceDirectoryForm key={key} app={props.app} data={data} name={setting.name} />,
          ])}
        />
      )}
    </Section>
  );
}

function SourceDirectoryForm(props: { app: ClientApp; data: ProjectSettingsResult; name: string }) {
  const { data } = props;
  const existing = data.source_directories[props.name];
  const [open, setOpen] = useState(false);
  const [name, setName] = useDraft(`settings/${data.project_id}/source/${props.name}/name`, props.name);
  const [path, setPath] = useDraft(`settings/${data.project_id}/source/${props.name}/path`, existing?.path ?? "");
  const command = useCommand(props.app, pageKey([existing?.version, name, path]));

  if (!open) {
    return (
      <button type="button" className="link" onClick={() => setOpen(true)}>修改</button>
    );
  }

  return (
    <span className="inline-form">
      <TextInput label="名称" value={name} onInput={setName} />
      <TextInput label="路径" value={path} onInput={setPath} />
      <SubmitButton
        label="保存源目录"
        busy={command.busy}
        disabled={name.trim() === "" || path.trim() === ""}
        onClick={() => void command.submit("source_directory.save", {
          project_id: data.project_id,
          name: name.trim(),
          path: path.trim(),
          base_version: existing?.version ?? 0,
        }).then((ok) => { if (ok) { setOpen(false); } })}
      />
      <button type="button" onClick={() => setOpen(false)}>取消</button>
      <CommandFeedback submitted={command.submitted} rejection={command.rejection} />
    </span>
  );
}
