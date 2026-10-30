// 部门使用（工单 #1297；模型管理设计说明第 9.1 节「部门使用」行、第 5.1、5.6 节）。
// 产品、工程、质检各一个下拉框，选项是已启用的模型（按连接分组）与「未设置」；
// 选中以后立即保存（catalog.department_defaults.save），说明为「从各部门下一次模型请求起生效……」。
// 每个部门的「更多」里是请求档位；选项来自所选模型的声明，没有声明时禁用并写明原因。
// 建议能力提醒沿用（设计说明第 5.6 节）：保存时带回的提醒一直显示在该项旁。

import type { CatalogBinding, CatalogModel } from "../../api/generated/types.gen";
import { DEPARTMENT_LABELS, DEPARTMENTS, tierOptions, type AdmissionGroup } from "./model-logic";

export type DepartmentStatus = { kind: "ok" | "error"; message: string };

export type DepartmentUsageProps = {
  /** 已启用的模型，按连接分组 */
  groups: AdmissionGroup[];
  /** 当前的部门默认 */
  bindings: Record<string, CatalogBinding>;
  /** 目录里的访问定义：请求档位的选项来自所选模型的声明 */
  models: CatalogModel[];
  /** 各部门当前绑定的模型的建议能力提醒 */
  reminders: Record<string, string[]>;
  /** 每个部门旁的结果（保存成功或被拒绝） */
  status: Record<string, DepartmentStatus>;
  busy: boolean;
  onSelect: (department: string, modelId: string) => void;
  onTier: (department: string, tier: string) => void;
};

export function DepartmentUsage(props: DepartmentUsageProps) {
  const enabled = props.groups.flatMap((group) => group.options);
  return (
    <div className="mm-usage" data-testid="department-usage">
      {enabled.length === 0 ? (
        <div className="y10-empty mm-empty" data-testid="department-empty">
          <strong>选好模型，部门就能开始工作</strong>
          <p>首个通过验证的模型会自动供三个部门使用。</p>
        </div>
      ) : null}
      {DEPARTMENTS.map((department) => {
        const binding = props.bindings[department];
        const current = binding?.model_id ?? "";
        const model = props.models.find((item) => item.id === current) ?? null;
        // 当前绑定的定义不在已启用的选项里（准入作废、目录里没有或是测试用的假模型）：
        // 照样列出这一项，用户看得到当前的真实状态，也能改回「未设置」
        const listed = enabled.some((option) => option.id === current);
        const tiers = tierOptions(model?.reasoning_levels ?? [], binding?.requested_tier ?? null);
        const reminders = props.reminders[department] ?? [];
        const status = props.status[department];
        return (
          <div className="mm-usage-row" key={department}
               data-testid={`department-${department}`}>
            <label className="y10-field" htmlFor={`department-model-${department}`}>
              <span>{DEPARTMENT_LABELS[department]}</span>
              <select id={`department-model-${department}`} className="y10-select"
                      value={current} disabled={props.busy}
                      data-testid={`department-model-${department}`}
                      onChange={(event) => props.onSelect(department, event.target.value)}>
                <option value="">未设置</option>
                {listed || current === "" ? null : (
                  <option value={current}>{model?.model ?? current}（当前绑定，未启用）</option>
                )}
                {props.groups.map((group) => (
                  <optgroup key={group.provider_id} label={group.provider_name}>
                    {group.options.map((option) => (
                      <option key={option.id} value={option.id}>{option.model}</option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </label>
            <details className="y10-details mm-usage-more">
              <summary>更多</summary>
              <label className="y10-field" htmlFor={`department-tier-${department}`}>
                <span>请求档位</span>
                <select id={`department-tier-${department}`} className="y10-select"
                        value={binding?.requested_tier ?? ""}
                        disabled={props.busy || tiers.length === 0}
                        data-testid={`department-tier-${department}`}
                        onChange={(event) => props.onTier(department, event.target.value)}>
                  <option value="">不指定</option>
                  {tiers.map((tier) => (
                    <option key={tier.value} value={tier.value}>{tier.label}</option>
                  ))}
                </select>
                {tiers.length === 0 ? (
                  <small className="y10-muted" data-testid={`department-tier-hint-${department}`}>
                    该模型未声明推理档位，请求不带推理参数
                  </small>
                ) : null}
              </label>
            </details>
            {reminders.map((reminder) => (
              <p className="y10-small y10-warn-text mm-warn" key={reminder}
                 data-testid={`department-reminder-${department}`}>
                {reminder}
              </p>
            ))}
            {status ? (
              <p className={status.kind === "ok" ? "y10-small mm-ok" : "y10-warn-text mm-warn"}
                 role="status" data-testid={`department-status-${department}`}>
                {status.message}
              </p>
            ) : null}
          </div>
        );
      })}
      <p className="y10-small y10-muted mm-meta">
        从各部门下一次模型请求起生效，没有另选模型的项目同样生效，包括进行中的事项。
      </p>
    </div>
  );
}
