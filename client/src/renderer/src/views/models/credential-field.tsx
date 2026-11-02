// 凭据写入区（工单 #237）：模型管理页与项目设置的「MCP 服务器」一节共用一块。
// 抽出之前是模型管理页连接表单里的 API Key 那一行（views/models/connect-card.tsx）与那一页提交
// 凭据的做法（views/models/page.tsx）。两处写的是同一件事，所以只写一遍：
// 输入框始终为空、不回填，也不把值放回输入框；页面只显示后端给出的状态（已设置或缺失、来源）。
// 两种写入方式：随外层表单一起提交（模型管理页的「获取模型」一次做完连接与 Key），
// 或者由这一行自己的「设置值」按钮提交（MCP 服务器设置，写凭据用 credential.set）。
// 界面不出现凭据值：输入框是密码框，值只在提交那一刻交给命令。

import { credentialStatusLabel } from "./model-logic";

// 凭据此刻的状态：后端给出的两项（configured、source），两个页面用的是同一种说法
export type CredentialState = { configured: boolean; source: string };

export type CredentialFieldProps = {
  id: string;
  label: string;
  value: string;
  onValue: (value: string) => void;
  placeholder?: string;
  /** 输入框下面的一句话：写这次写入会落到哪里 */
  hint?: string;
  /** 输入框的 data-testid（模型管理页的 connect-key 由它保持） */
  inputTestId?: string;
  /** 后端给出的状态：不传就不显示状态这一行（模型管理页的状态写在连接卡片上） */
  status?: CredentialState | null;
  /** 状态读不到时写的话 */
  unknownText?: string;
  /** 这一行自己的「设置值」按钮：给出时值由它提交，不给时随外层表单提交 */
  submit?: { label: string; busy: boolean; onClick: () => void } | null;
  /** 状态与按钮各自的 data-testid 前缀：给出时分别是 -status 与 -submit */
  testId?: string;
};

// 状态那一行的话：后端给出什么就写什么，读不到时如实写读不到（不猜「已设置」）
export function credentialStateText(status: CredentialState | null | undefined, unknownText = "还没有读到状态"): string {
  return status === null || status === undefined ? unknownText : credentialStatusLabel(status);
}

export function CredentialField(props: CredentialFieldProps) {
  const empty = props.value.trim() === "";
  return (
    <div className="y10-field field credential-field">
      {/* 与别的字段一样：第一层是标签，下面是输入框那一行。这里的标签不包住输入框（旁边还有按钮） */}
      <span className="credential-field-label">{props.label}</span>
      <span className="y10-row credential-field-row">
        <input
          id={props.id}
          className="y10-input"
          type="password"
          autoComplete="off"
          spellCheck={false}
          aria-label={props.label}
          placeholder={props.placeholder}
          value={props.value}
          data-testid={props.inputTestId}
          onChange={(event) => props.onValue(event.target.value)}
        />
        {props.submit ? (
          <button
            type="button"
            className="y10-btn small"
            data-testid={props.testId === undefined ? undefined : `${props.testId}-submit`}
            disabled={props.submit.busy || empty}
            onClick={props.submit.onClick}
          >
            {props.submit.busy ? "正在设置…" : props.submit.label}
          </button>
        ) : null}
      </span>
      {props.status === undefined ? null : (
        <small className="y10-note note" data-testid={props.testId === undefined ? undefined : `${props.testId}-status`}>
          状态：{credentialStateText(props.status, props.unknownText)}
        </small>
      )}
      {props.hint ? <small className="y10-note note">{props.hint}</small> : null}
    </div>
  );
}
