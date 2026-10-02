// 连接设置页（原型 v8 设计说明第 3.4 节）。连接「本机」时服务已经运行就直接连接；
// 服务没有运行时的启动由 #207 实现。更新页在 views/update.tsx（工单 #208）。

import { useEffect, useState } from "react";
import type { ConnectionSettings } from "../contract/settings";
import { DEFAULT_LOCAL_ADDRESS, normalizeAddress } from "../contract/settings";

export type ConnectPageProps = {
  settings: ConnectionSettings;
  onChange: (settings: ConnectionSettings) => void;
  onConnect: () => void;
  connecting: boolean;
  error: string | null;
};

export function ConnectPage(props: ConnectPageProps) {
  const [kind, setKind] = useState(props.settings.kind);
  const [address, setAddress] = useState(props.settings.address);
  const [token, setToken] = useState(props.settings.token);
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    setKind(props.settings.kind);
    setAddress(props.settings.address);
    setToken(props.settings.token);
  }, [props.settings]);

  const submit = () => {
    try {
      const next: ConnectionSettings = {
        kind,
        address: kind === "local" ? DEFAULT_LOCAL_ADDRESS : normalizeAddress(address),
        token,
        // 连接页不改动「允许局域网访问」，沿用已保存的值
        allowLan: props.settings.allowLan,
      };
      setLocalError(null);
      props.onChange(next);
      props.onConnect();
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : String(error));
    }
  };

  return (
    <div className="gate">
      <form
        className="card"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <h1>连接 Yudao 服务</h1>
        <div className="field">
          <label htmlFor="kind">访问方式</label>
          <select id="kind" value={kind} onChange={(event) => setKind(event.target.value as ConnectionSettings["kind"])}>
            <option value="local">本机（127.0.0.1）</option>
            <option value="lan">局域网内的控制主机</option>
          </select>
        </div>
        {kind === "lan" && (
          <div className="field">
            <label htmlFor="address">控制主机地址</label>
            <input
              id="address"
              value={address}
              onChange={(event) => setAddress(event.target.value)}
              placeholder="http://192.168.1.10:8765"
            />
          </div>
        )}
        <div className="field">
          <label htmlFor="token">访问令牌</label>
          <input id="token" value={token} disabled placeholder="局域网内使用期间不需要" />
          <span className="note">令牌与 TLS 保留位置，当前不发送（设计说明第 6.3 节 TODO）。</span>
        </div>
        {(localError ?? props.error) && <p className="error">{localError ?? props.error}</p>}
        <button className="primary" type="submit" disabled={props.connecting}>
          {props.connecting ? "连接中…" : "连接"}
        </button>
      </form>
    </div>
  );
}
