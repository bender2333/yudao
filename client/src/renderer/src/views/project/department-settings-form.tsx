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
export type DepartmentSettingsDraft = {
  model: string;
  tier: string;
  text: string;
};

function draftFromSetting(setting: DepartmentSetting | null): DepartmentSettingsDraft {
  return {
    model: selectionValue(setting?.provider_id, setting?.model_id),
    tier: setting?.requested_tier ?? "",
    text: setting?.text ?? "",
  };
}

// 草稿按项目部门设置的版本重置：设置随事件流更新（别人改了、自己保存成功）以后，草稿回到当前值，
// 未提交的修改不跨越版本（第 9.2 节的基准版本语义）
export function useDepartmentDraft(setting: DepartmentSetting | null): [
  DepartmentSettingsDraft,
  (draft: DepartmentSettingsDraft) => void,
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
  return [draft, setDraft];
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
        <p className="y9-note is-warn warn" role="status" key={item} data-testid={props.testId}>
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
    <div className="y9-form form">
      <label className="y9-field field">
        <span>模型</span>
        <select
          className="y9-select"
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
        <p className="y9-note is-warn warn" role="status">所选模型不在已准入的定义中，保存会被拒绝，请重新读取目录。</p>
      ) : null}
      <label className="y9-field field">
        <span>推理档位</span>
        <select
          className="y9-select"
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
        <p className="y9-note note">该模型未声明推理档位，请求不带推理参数。</p>
      ) : null}
      <TextArea
        label="部门 Prompt"
        value={props.draft.text}
        rows={10}
        onInput={(value) => props.onDraft({ ...props.draft, text: value })}
      />
      <ReminderList items={props.reminders} testId={`department-reminder-${props.department}`} />
    </div>
  );
}

// 保存：提交项目部门设置的三项；模型选择「跟随部门默认」时不给连接与定义，
// 档位选择「跟随」时不给请求档位。基准版本取设置自身的版本，
// 版本冲突时服务端按 stale_base 拒绝，由调用处的反馈提示重新读取
export function DepartmentSettingsSave(props: {
  projectId: string;
  department: string;
  setting: DepartmentSetting | null;
  draft: DepartmentSettingsDraft;
  command: CommandState;
  onSaved: () => void;
}) {
  const selection = selectionPair(props.draft.model);
  return (
    <div className="y9-form composer">
      <SubmitButton
        label="保存部门设置"
        busy={props.command.busy}
        onClick={() => {
          void props.command.submit("department_settings.save", {
            project_id: props.projectId,
            department: props.department,
            base_version: props.setting?.version ?? 0,
            provider_id: selection.provider_id,
            model_id: selection.model_id,
            requested_tier: props.draft.tier === "" ? null : props.draft.tier,
            department_prompt: props.draft.text,
          }).then((ok) => { if (ok) { props.onSaved(); } });
        }}
      />
      <p className="y9-note note">{DEPARTMENT_SAVE_NOTICE}</p>
    </div>
  );
}
