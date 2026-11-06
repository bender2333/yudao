// 连接服务（工单 #1297；模型管理 docs/design/model-management.md「模型管理页」「连接服务」行、docs/design/model-management.md「模型访问定义与准入」「获取模型列表」）。
// 服务地址与 API Key 两个输入，一个「获取模型」按钮：连接、Key 与候选一步做完（catalog.connect）。
// Key 输入框始终不回填：结果回来之前保持原样，成功以后清空。
// 已有连接按连接显示卡片：地址、Key 状态、最近一次获取的结果与时间；
// 操作有「修改地址或 Key」「刷新模型列表」「删除」。
// 进度、成功与失败原因都写在这张卡片里（工单第 5 条：反馈写在被操作的对象旁边）。

import type { CatalogProvider } from "../../api/generated/types.gen";
import { CredentialField } from "./credential-field";
import {
  CONNECTION_FETCHING_TEXT,
  connectIssue,
  credentialStatusLabel,
  fetchSummaryOf,
} from "./model-logic";

export type ConnectStatus = { kind: "ok" | "error"; message: string };

// 正在填写的连接：新建一份，或修改某一份的地址与 Key
export type ConnectTarget = { mode: "new" } | { mode: "edit"; provider_id: string };

export type ConnectCardProps = {
  providers: CatalogProvider[];
  /** 表单收着时是 null；「添加服务」展开同一个表单 */
  target: ConnectTarget | null;
  address: string;
  apiKey: string;
  /** 命令在途 */
  busy: boolean;
  /** 正在后台取候选的那一份连接（工单 #1355）：说明写在卡片里，不禁用任何操作 */
  fetching: string | null;
  /** 被操作对象旁的结果：键是连接的 id，新建时用 "new" */
  status: Record<string, ConnectStatus>;
  onTarget: (target: ConnectTarget | null) => void;
  onAddress: (value: string) => void;
  onApiKey: (value: string) => void;
  onConnect: () => void;
  onRefresh: (providerId: string) => void;
  onRemove: (providerId: string) => void;
};

export function ConnectCard(props: ConnectCardProps) {
  const editing = props.target?.mode === "edit" ? props.target.provider_id : null;
  const editingProvider = editing === null ? null : props.providers.find((item) => item.id === editing) ?? null;
  // 已有凭据的连接不用再填 Key；新连接必须填
  const credentialSaved = editingProvider?.credential?.configured === true;
  const issue = connectIssue({ address: props.address, api_key: props.apiKey, credential_saved: credentialSaved });
  const formStatus = props.status[editing ?? "new"];

  return (
    <div className="mm-connect">
      {props.target === null ? (
        <div className="y10-row mm-actions">
          <button type="button" className="y10-btn small" data-testid="connection-add"
                  onClick={() => props.onTarget({ mode: "new" })}>
            添加服务
          </button>
        </div>
      ) : (
        <form className="y10-form mm-connect-form" data-testid="connect-form"
              onSubmit={(event) => {
                event.preventDefault();
                props.onConnect();
              }}>
          <h3 className="y10-h3">{editing === null ? "连接服务" : "修改地址或 Key"}</h3>
          <label className="y10-field" htmlFor="connect-address">
            <span>服务地址</span>
            <input id="connect-address" className="y10-input" type="text" autoComplete="off" spellCheck={false}
                   placeholder="https://api.example.com/v1" value={props.address}
                   data-testid="connect-address"
                   onChange={(event) => props.onAddress(event.target.value)} />
            <small>填写服务提供的 API 地址。</small>
          </label>
          {/* Key 那一行与「设置值」的写法在凭据写入区里（工单 #237）：MCP 服务器一节用的是同一块 */}
          <CredentialField
            id="connect-key"
            label="API Key"
            inputTestId="connect-key"
            value={props.apiKey}
            onValue={props.onApiKey}
            placeholder={credentialSaved ? "已保存 · 输入以更换 Key" : "输入 API Key"}
            hint="连接、凭据与模型配置随这次获取一起保存。"
          />
          <div className="y10-row mm-actions">
            <button type="submit" className="y10-btn primary" data-testid="connect-submit"
                    disabled={props.busy || issue !== ""}>
              {props.busy ? "正在获取…" : "获取模型"}
            </button>
            <button type="button" className="y10-btn" data-testid="connect-cancel"
                    onClick={() => props.onTarget(null)}>
              取消
            </button>
            {/* 按钮不可用时旁边写明还缺哪一项；请求在途时写明在做什么（工单验收第 1 条、#1355） */}
            <span className="y10-small y10-muted mm-hint" data-testid="connect-issue">
              {props.busy ? "正在连接并获取模型列表…" : issue === "" ? "已填写完整，可以获取模型。" : issue}
            </span>
          </div>
          {formStatus ? (
            <p className={formStatus.kind === "ok" ? "y10-note mm-ok" : "y10-note is-warn mm-warn"}
               role="status" data-testid="connect-status">
              {formStatus.message}
            </p>
          ) : null}
        </form>
      )}
      {props.providers.map((provider) => {
        const summary = fetchSummaryOf(provider);
        const status = props.status[provider.id];
        return (
          <section className="y10-conn-card mm-card" key={provider.id} data-testid="connection-card"
                   data-provider={provider.id}>
            <div className="y10-conn-summary mm-summary" aria-label={`连接 ${provider.base_url}`}>
              <span className="y10-conn-name mm-name">
                <strong>{provider.base_url || "（没有地址）"}</strong>
                <small>{credentialStatusLabel(provider.credential)}</small>
              </span>
              <span className="y10-conn-count mm-count">
                {summary.kind === "ok" ? summary.text : summary.kind === "error" ? "获取失败" : "未获取"}
              </span>
            </div>
            <div className="y10-conn-body mm-body">
              {/* 正在取候选：说明写在这张卡片里，不禁止操作（工单 #1355） */}
              {props.fetching === provider.id ? (
                <p className="y10-note mm-ok" role="status" data-testid="connection-fetching">
                  {CONNECTION_FETCHING_TEXT}
                </p>
              ) : null}
              {summary.kind !== "none" ? (
                <p className={summary.kind === "error" ? "y10-warn-text mm-warn" : "y10-small y10-muted mm-meta"}
                   data-testid="connection-fetch">
                  {summary.text}
                </p>
              ) : null}
              {status ? (
                <p className={status.kind === "ok" ? "y10-note mm-ok" : "y10-note is-warn mm-warn"}
                   role="status" data-testid="connection-status">
                  {status.message}
                </p>
              ) : null}
              <div className="y10-conn-actions mm-actions">
                <button type="button" className="y10-btn small"
                        data-testid="connection-edit"
                        onClick={() => props.onTarget({ mode: "edit", provider_id: provider.id })}>
                  修改地址或 Key
                </button>
                <button type="button" className="y10-btn small"
                        data-testid="connection-refresh"
                        disabled={props.busy}
                        onClick={() => props.onRefresh(provider.id)}>
                  刷新模型列表
                </button>
                <button type="button" className="y10-btn small danger"
                        data-testid="connection-delete"
                        disabled={props.busy}
                        onClick={() => props.onRemove(provider.id)}>
                  删除
                </button>
              </div>
            </div>
          </section>
        );
      })}
    </div>
  );
}
