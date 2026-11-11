// 设置页（原型 v8 设计说明第 7.5 节，工单 #80）：基本信息、组织、登记的源目录与底部几节。
// 数据全部来自 project.settings；每项修改提交对应的命令，基准版本取快照里的 version，
// 过期时拒绝并提示重新读取（工单验收第 3 条）。
// 机器授权（3.2C）的命令尚未登记，入口按能力清单不出现。
// 「组织」一节由 #1403 加入、#1649 改成一行组织与两个按钮（加或去掉独立核验、换形态）：数据来自 project.organization；
// 改回与历史在「高级」（#1650）。
// 「职能设置」一节由 #1713 搬到职能详情页（模型、推理档位与职能 Prompt 在那里改）。

import { useEffect, useState } from "react";
import type { ClientApp } from "../../contract/client-app";
import type { ProjectSettingsResult } from "../../api/generated/types.gen";
import type { Route } from "../../shell/routing";
import {
  CommandFeedback, Empty, KeyValue, Loading, Section, SubmitButton, Table, TextArea, TextInput,
  hasCommand, pageKey, useDraft,
} from "./common";
import { FormSection } from "./form-section";
import { McpServersSection } from "./mcp-servers";
import type { DepartmentView } from "./organization";
import { RequestsSection } from "./requests-section";
import { WritebackSection } from "./writeback";
import {
  CHECK_COMMANDS_LABEL, CHECK_COMMANDS_NOTE, checkCommandsText, sourceDirectoryPayload, sourceWritebackText,
} from "./writeback-text";
import { PageHead } from "../../shell/kit";
import { type CommandState, useCommand, useSnapshot } from "./use-snapshot";
import { readFailureText } from "../../contract/read-failure";

export function SettingsPage(props: { app: ClientApp; route: Route; departments: DepartmentView[] }) {
  const projectId = props.route.projectId ?? "";
  const settings = useSnapshot<ProjectSettingsResult>(props.app, "page.settings", "project.settings", {
    project_id: projectId,
  });
  const data = settings.data;
  // 提交提示跟随快照：事件到达、快照出现新内容以后由数据本身显示最终状态
  const command = useCommand(props.app, pageKey([data?.version, data?.name, data?.goal, data?.pinned, data?.archived]));
  // 决定卡片上的「前往本项目的部门设置」落在部门设置那一节，不停在设置页的顶部（工单 #1161）：
  // 路径参数 ?section= 给出节名，内容画出来以后滚到那里；认不出的节名不动，停在页首
  const section = props.route.settingsSection;
  const loaded = data !== null;
  useEffect(() => {
    if (!loaded || section === null) {
      return;
    }
    document.getElementById(section)?.scrollIntoView({ block: "start" });
  }, [loaded, section, projectId]);

  return (
    <div className="page y10-set">
      <PageHead
        eyebrow="项目设置"
        title={data ? data.name : "项目设置"}
        subtitle="基本信息、组织、源目录、MCP 服务器、机器授权、执行位置与角色设置。"
      />
      <Loading state={settings} />
      {settings.error !== null ? (
        // 项目设置读不出来：这一页本来有内容（工单 #775），不留一片空白
        <p className="y10-note note" role="status">{readFailureText(settings.error)}</p>
      ) : null}
      {data ? (
        <>
          <Basics app={props.app} data={data} command={command} />
          <FormSection app={props.app} projectId={projectId} />
          <SourceDirectories app={props.app} data={data} />
          <McpServersSection app={props.app} data={data} departments={props.departments} />
          <WritebackSection app={props.app} projectId={projectId} />
          <MachineAuthorization />
          <ExecutionPlacement />
          <Operations />
          <RoleSettings />
          {/* 模型请求与用量（工单 #1710）：设置页底部的一节，平时收着；
              展开状态与筛选条件写在地址里，内容与观测页是同一份部件 */}
          <RequestsSection app={props.app} route={props.route} departments={props.departments} />
        </>
      ) : null}
    </div>
  );
}

// 机器授权（3.2C）、执行位置、运维与本项目各角色设置：
// 命令与查询还在所属工作包，登记以后这里改成对应的表单；在此之前如实写明等待登记，不造表
function PendingBlock(props: { title: string; note: string; text: string }) {
  return (
    <Section title={props.title} note={props.note} className="y10-set-pending">
      <Empty text={props.text} />
    </Section>
  );
}

function MachineAuthorization() {
  return <PendingBlock
    title="机器授权"
    note="本项目可以使用的机器"
    text="机器授权的命令还没有登记，等 3.2C 工作包登记以后在这里选择机器并写明登记的目录"
  />;
}

function ExecutionPlacement() {
  return <PendingBlock
    title="执行位置"
    note="运行工作区与各检查的位置"
    text="执行位置的命令还没有登记，等 3.2C 工作包登记以后在这里选择运行工作区与三个职能的检查位置"
  />;
}

function Operations() {
  return <PendingBlock
    title="运维"
    note="观察窗口与连续修复失败的次数上限"
    text="运维配置由运维工作的工单登记，登记以后这里只读显示观察窗口与次数上限"
  />;
}

function RoleSettings() {
  return <PendingBlock
    title="本项目各角色设置"
    note="项目角色设置优先于角色默认与职能设置"
    text="各角色设置的命令还没有登记，等 Stage 5 工作包登记以后在这里设置每个角色使用的模型、推理档位与角色 Prompt"
  />;
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
      <div className="y10-row row-actions">
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
        <div className="y10-form form">
          <TextInput label="名称" value={name} onInput={setName} />
          <TextArea label="长期目标" value={goal} rows={3} onInput={setGoal} />
          <p className="y10-note note">长期目标修改以后，之后开始的事项使用新目标；进行中的事项按开始时的目标做完。</p>
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
      <CommandFeedback submitted={command.submitted} problem={command.problem} />
    </Section>
  );
}

// 部门设置（7.5 节第 2 项）已搬到职能详情页（工单 #1713）：设置页不再有「职能设置」一节，
// 模型、推理档位与职能 Prompt 在那一页改，内容与保存命令不变。

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
          head={["名称", "路径", "版本", "写回", ""]}
          rows={entries.map(([key, setting]) => [
            setting.name,
            setting.path,
            `第 ${setting.version} 版`,
            sourceWritebackText(setting),
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
  // 写回的三项设置（是否打开、远端、目标分支）与写回检查的命令：界面上填写，随源目录一起保存（工单 #709、#815）
  const [writebackEnabled, setWritebackEnabled] = useState(existing?.writeback_enabled ?? false);
  const [targetBranch, setTargetBranch] = useDraft(
    `settings/${data.project_id}/source/${props.name}/target_branch`, existing?.target_branch ?? "");
  const [remote, setRemote] = useDraft(
    `settings/${data.project_id}/source/${props.name}/remote`, existing?.remote ?? "");
  // 写回检查的命令从已登记的清单读出初值，一行一条；只改名称、路径与写回的三项设置时它保持不变
  const [checkCommands, setCheckCommands] = useDraft(
    `settings/${data.project_id}/source/${props.name}/check_commands`,
    checkCommandsText(existing?.check_commands ?? []));
  const command = useCommand(
    props.app,
    pageKey([existing?.version, name, path, writebackEnabled, targetBranch, remote, checkCommands]));

  if (!open) {
    return (
      <button type="button" className="y10-link link" onClick={() => setOpen(true)}>修改</button>
    );
  }

  return (
    <span className="y10-set-inline inline-form">
      <TextInput label="名称" value={name} onInput={setName} />
      <TextInput label="路径" value={path} onInput={setPath} />
      <label className="y10-check checkbox">
        <input
          type="checkbox"
          checked={writebackEnabled}
          onChange={(event) => setWritebackEnabled(event.target.checked)}
        />
        <span>打开写回</span>
      </label>
      <TextInput label="目标分支" value={targetBranch} onInput={setTargetBranch} />
      <TextInput label="远端仓库（留空表示源目录本身）" value={remote} onInput={setRemote} />
      <TextArea label={CHECK_COMMANDS_LABEL} value={checkCommands} rows={3} onInput={setCheckCommands} />
      <span className="y10-note note">{CHECK_COMMANDS_NOTE}</span>
      <SubmitButton
        label="保存源目录"
        busy={command.busy}
        disabled={name.trim() === "" || path.trim() === ""}
        onClick={() => void command.submit("source_directory.save", sourceDirectoryPayload({
          projectId: data.project_id,
          existing: existing ?? null,
          name,
          path,
          writebackEnabled,
          targetBranch,
          remote,
          checkCommands,
        })).then((ok) => { if (ok) { setOpen(false); } })}
      />
      <button type="button" onClick={() => setOpen(false)}>取消</button>
      <CommandFeedback submitted={command.submitted} problem={command.problem} />
    </span>
  );
}
