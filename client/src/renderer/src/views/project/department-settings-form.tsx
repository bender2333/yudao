// 项目部门设置的共用表单（模型管理设计说明第 9.2、9.1 节，工单 #95）：模型、推理档位与部门 Prompt。
// 部门设置弹窗与设置页的部门设置都用这一份：两者写入同一处项目部门设置，字段与校验完全一致。
// 模型下拉第一项是「跟随部门默认（当前：…）」，选择它即清除项目的模型选择；档位第一项是「跟随」。
// 已保存的档位不在当前生效模型的支持档位内时额外保留这一项并标明按模型限制（保存只核对档位属于档位全集）。

import { useEffect, useMemo, useRef, useState } from "react";
import type { ClientApp } from "../../contract/client-app";
import type { Catalog, DepartmentSetting, EffectiveModel } from "../../api/generated/types.gen";
import { SubmitButton, TextArea } from "./common";
import { type CommandState, useSnapshot } from "./use-snapshot";
import {
  DEPARTMENT_SAVE_NOTICE,
  admittedModels,
  currentEffectiveLabel,
  followDepartmentLabel,
  groupAdmittedModels,
  selectionPair,
  selectionValue,
  tierOptions,
} from "../models/model-logic";

// 表单的草稿：取项目部门设置里已写入的三项；未写入的项为空（跟随部门默认、跟随档位）
// 部门 Prompt 分两件事记：文本框里的文字（这一段由本项目写入时的内容）与
// 「这一段是不是由本项目写入」。没有写入时文本框是空的，保存时不发这一项，
// 服务端按「没有写入」处理，部门用内置默认 Prompt（工单 #741）
export type DepartmentSettingsDraft = {
  model: string;
  tier: string;
  text: string;
  writePrompt: boolean;
};

// 这一段部门 Prompt 是不是由本项目写入：服务端用 department_setting_configured 分清
// （有设置记录但没写这一段时，这一段仍然是内置默认）。
// 没有这个字段的旧服务端按已写入处理，不因为缺一个字段就把用户写的那一段丢掉
export function promptWritten(configured: boolean | undefined, text: string): boolean {
  if (configured === false) {
    return false;
  }
  return Boolean(text);
}

// 草稿从已保存的设置来：模型与档位按写入了没有取；部门 Prompt 的两件事按上面那条规则分清
export function draftFromSetting(setting: DepartmentSetting | null): DepartmentSettingsDraft {
  const written = promptWritten(setting?.department_setting_configured, setting?.text ?? "");
  return {
    model: selectionValue(setting?.provider_id, setting?.model_id),
    tier: setting?.requested_tier ?? "",
    text: written ? setting?.text ?? "" : "",
    writePrompt: written,
  };
}

// 文本框里改动以后草稿怎么变：清空以后这一段没有内容了，按「不写入」处理，
// 保存时不发这一项，不再是一个会被 422 挡下的空串（工单 #741）
export function promptDraftOnInput(draft: DepartmentSettingsDraft, value: string): DepartmentSettingsDraft {
  const blank = value.trim() === "";
  return { ...draft, text: blank ? "" : value, writePrompt: !blank };
}

// 撤销本次修改：还原成已保存的那一份（不是恢复默认，那件事有单独的入口）
export function promptDraftRevert(
  draft: DepartmentSettingsDraft,
  saved: DepartmentSettingsDraft,
): DepartmentSettingsDraft {
  return { ...draft, text: saved.text, writePrompt: saved.writePrompt };
}

// 使用内置默认 Prompt：这一段不再由本项目写入，保存以后部门用内置默认
export function promptDraftUseDefault(draft: DepartmentSettingsDraft): DepartmentSettingsDraft {
  return { ...draft, text: "", writePrompt: false };
}

// 草稿按项目部门设置的版本重置：设置随事件流更新（别人改了、自己保存成功）以后，草稿回到当前值，
// 未提交的修改不跨越版本（第 9.2 节的基准版本语义）
// 第三项是已保存的那一份：撤销本次修改时还原成它
export function useDepartmentDraft(setting: DepartmentSetting | null): [
  DepartmentSettingsDraft,
  (draft: DepartmentSettingsDraft) => void,
  DepartmentSettingsDraft,
] {
  const version = setting?.version ?? -1;
  const [draft, setDraft] = useState<DepartmentSettingsDraft>(() => draftFromSetting(setting));
  const lastVersion = useRef(version);
  useEffect(() => {
    if (lastVersion.current !== version) {
      lastVersion.current = version;
      setDraft(draftFromSetting(setting));
    }
  }, [version, setting]);
  return [draft, setDraft, draftFromSetting(setting)];
}

// 建议能力提醒（第 5.6 节）：保存结果带回的提醒，以及当前生效模型（含跟随）已有的提醒。
// 弹窗打开期间一直显示，直到换成具备该能力的模型
export function ReminderList(props: { items: string[]; testId?: string }) {
  if (props.items.length === 0) {
    return null;
  }
  return (
    <>
      {props.items.map((item) => (
        <p className="y10-note is-warn warn" role="status" key={item} data-testid={props.testId}>
          {item}
        </p>
      ))}
    </>
  );
}

export function DepartmentSettingsFields(props: {
  app: ClientApp | null;
  projectId: string;
  department: string;
  draft: DepartmentSettingsDraft;
  onDraft: (draft: DepartmentSettingsDraft) => void;
  effective: EffectiveModel | null;
  reminders: string[];
  // 已保存的那一份：撤销本次修改时还原成它
  saved: DepartmentSettingsDraft;
}) {
  // 已准入定义按连接分组：模型选项来自 catalog 查询（部门设置弹窗与设置页都能读取它）
  const catalog = useSnapshot<Catalog>(props.app, `page.dept.settings.catalog.${props.projectId}`, "catalog", {});
  const choices = useMemo(
    () => (catalog.data ? admittedModels(catalog.data.models, catalog.data.providers, catalog.data.admissions) : []),
    [catalog.data],
  );
  const groups = useMemo(
    () => groupAdmittedModels(choices, catalog.data?.providers ?? []),
    [choices, catalog.data],
  );
  // 当前生效模型的说明：跟随部门默认时写明部门默认的模型与来源（第 9.2 节）
  const followText = followDepartmentLabel(currentEffectiveLabel(props.effective));
  // 档位选项来自当前生效模型声明的支持档位；随选择变化（选新模型以后按新模型声明取档位）
  const pickedModelId = selectionPair(props.draft.model).model_id;
  const model = catalog.data?.models.find((item) => item.id === pickedModelId) ?? null;
  const tiers = tierOptions(model?.reasoning_levels ?? [], props.draft.tier);

  return (
    <div className="y10-form form">
      <label className="y10-field field">
        <span>模型</span>
        <select
          className="y10-select"
          value={props.draft.model}
          data-testid={`department-model-${props.department}`}
          onChange={(event) => props.onDraft({ ...props.draft, model: event.target.value, tier: "" })}
        >
          <option value="">{followText}</option>
          {groups.map((group) => (
            <optgroup key={group.provider_id} label={group.provider_name}>
              {group.options.map((item) => (
                <option key={item.id} value={`${item.provider_id}/${item.id}`}>{item.model}</option>
              ))}
            </optgroup>
          ))}
        </select>
      </label>
      {props.draft.model !== "" && model === null ? (
        <p className="y10-note is-warn warn" role="status">所选模型不在已准入的定义中，保存会被拒绝，请重新读取目录。</p>
      ) : null}
      <label className="y10-field field">
        <span>推理档位</span>
        <select
          className="y10-select"
          value={props.draft.tier}
          data-testid={`department-tier-${props.department}`}
          disabled={props.draft.model === "" && props.draft.tier === ""}
          onChange={(event) => props.onDraft({ ...props.draft, tier: event.target.value })}
        >
          <option value="">跟随</option>
          {tiers.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select>
      </label>
      {model !== null && model.reasoning_levels.length === 0 && props.draft.tier === "" ? (
        <p className="y10-note note">该模型未声明推理档位，请求不带推理参数。</p>
      ) : null}
      <TextArea
        label="部门 Prompt"
        value={props.draft.text}
        rows={10}
        onInput={(value) => props.onDraft(promptDraftOnInput(props.draft, value))}
      />
      {/* 这一段写不写由这一行说清：页面上不出现内部字段名与英文标识（工单 #741） */}
      <p className="y10-note note" data-testid={`department-prompt-source-${props.department}`}>
        {props.draft.writePrompt
          ? "这一段由本项目写入，保存以后按这里的内容生效。"
          : "这一段不写入本项目，部门使用内置默认 Prompt。"}
      </p>
      <div className="y10-row row-actions">
        <button
          type="button"
          onClick={() => props.onDraft(promptDraftRevert(props.draft, props.saved))}
        >
          撤销本次修改
        </button>
        <button
          type="button"
          disabled={!props.draft.writePrompt}
          onClick={() => props.onDraft(promptDraftUseDefault(props.draft))}
        >
          使用内置默认 Prompt
        </button>
      </div>
      <ReminderList items={props.reminders} testId={`department-reminder-${props.department}`} />
    </div>
  );
}

// 保存时提交的内容：三项一起提交。这一段不写入时 department_prompt 给 null，
// 服务端按「没有写入」处理（部门用内置默认 Prompt），不再是一个会被 422 挡下的空串
export function departmentSettingsPayload(props: {
  projectId: string;
  department: string;
  setting: DepartmentSetting | null;
  draft: DepartmentSettingsDraft;
}): Record<string, unknown> {
  const selection = selectionPair(props.draft.model);
  return {
    project_id: props.projectId,
    department: props.department,
    base_version: props.setting?.version ?? 0,
    provider_id: selection.provider_id,
    model_id: selection.model_id,
    requested_tier: props.draft.tier === "" ? null : props.draft.tier,
    department_prompt: props.draft.writePrompt ? props.draft.text : null,
  };
}

// 保存：提交项目部门设置的三项；模型选择「跟随部门默认」时不给连接与定义，
// 档位选择「跟随」时不给请求档位。基准版本取设置自身的版本，
// 版本冲突时服务端按 stale_base 拒绝，由调用处的反馈提示重新读取。
// 部门 Prompt 这一段不写入时给 null：服务端按「没有写入」处理，部门用内置默认 Prompt
export function DepartmentSettingsSave(props: {
  projectId: string;
  department: string;
  setting: DepartmentSetting | null;
  draft: DepartmentSettingsDraft;
  command: CommandState;
  onSaved: () => void;
}) {
  return (
    <div className="y10-form composer">
      <SubmitButton
        label="保存部门设置"
        busy={props.command.busy}
        onClick={() => {
          void props.command.submit("department_settings.save", departmentSettingsPayload({
            projectId: props.projectId,
            department: props.department,
            setting: props.setting,
            draft: props.draft,
          })).then((ok) => { if (ok) { props.onSaved(); } });
        }}
      />
      <p className="y10-note note">{DEPARTMENT_SAVE_NOTICE}</p>
    </div>
  );
}
