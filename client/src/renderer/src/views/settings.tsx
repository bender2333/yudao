// 设置页（设计说明第 4.3、4.5 节，工单 #207）：连接设置（访问方式、地址）、本机服务的
// 停止，以及「登录时启动客户端」。连接「本机」时由 app.tsx 的 connectTo 启动服务；
// 没有找到 yudao 命令时显示安装命令，命令找到了但服务没有起来时显示原因与服务日志的位置
// （工单 #296）。

import { useEffect, useState } from "react";
import type { ConnectionSettings } from "../contract/settings";
import { DEFAULT_LOCAL_ADDRESS, normalizeAddress } from "../contract/settings";

export type SettingsPageProps = {
  settings: ConnectionSettings;
  loginAtStartup: boolean;
  // 本机服务没有可用的两种情况：no-command 时 reason 是安装命令，failed 时 reason 是失败原因，
  // logPath 是服务日志的位置（设计说明第 4.3 节、工单 #296）
  localIssue: { kind: "no-command" | "failed"; reason: string; logPath: string } | null;
  localConnected: boolean;
  // 服务正在运行且访问方式与「允许局域网访问」开关不同：显示「重新启动服务后生效」（设计说明第 4.3 节）
  lanRestartNeeded: boolean;
  onChange: (settings: ConnectionSettings) => void;
  onConnect: (settings: ConnectionSettings) => void;
  onStopLocal: () => void;
  onRestartLocal: () => void;
  onAllowLan: (allowLan: boolean) => void;
  onLoginAtStartup: (enabled: boolean) => void;
  connecting: boolean;
  error: string | null;
};

export function SettingsPage(props: SettingsPageProps) {
  const [kind, setKind] = useState(props.settings.kind);
  const [address, setAddress] = useState(props.settings.address);
  const [token, setToken] = useState(props.settings.token);
  const [loginAtStartup, setLoginAtStartup] = useState(props.loginAtStartup);
  const [addressError, setAddressError] = useState<string | null>(null);

  useEffect(() => {
    setKind(props.settings.kind);
    setAddress(props.settings.address);
    setToken(props.settings.token);
  }, [props.settings]);

  useEffect(() => {
    setLoginAtStartup(props.loginAtStartup);
  }, [props.loginAtStartup]);

  // 连接：地址不合法时就地显示原因，不保存也不发起连接
  const submit = () => {
    let next: ConnectionSettings;
    try {
      next = {
        kind,
        address: kind === "local" ? DEFAULT_LOCAL_ADDRESS : normalizeAddress(address),
        token,
        // 「允许局域网访问」由开关单独保存，这里沿用当前值
        allowLan: props.settings.allowLan,
      };
    } catch (error) {
      setAddressError(error instanceof Error ? error.message : String(error));
      return;
    }
    setAddressError(null);
    props.onChange(next);
    props.onConnect(next);
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
        <h1>设置</h1>
        <fieldset className="field">
          <legend>连接</legend>
          <label className="choice">
            <input
              type="radio"
              name="kind"
              value="local"
              checked={kind === "local"}
              onChange={() => setKind("local")}
            />
            本机（{DEFAULT_LOCAL_ADDRESS}）
          </label>
          <label className="choice">
            <input
              type="radio"
              name="kind"
              value="lan"
              checked={kind === "lan"}
              onChange={() => setKind("lan")}
            />
            局域网内的控制主机
          </label>
          {kind === "lan" && (
            <input
              id="lan-address"
              value={address}
              onChange={(event) => setAddress(event.target.value)}
              placeholder="http://192.168.1.10:8765"
            />
          )}
          <input id="token" value={token} disabled placeholder="访问令牌（保留位置，当前不发送）" />
          {(addressError ?? props.error) && <p className="error">{addressError ?? props.error}</p>}
          <button className="primary" type="submit" disabled={props.connecting}>
            {props.connecting ? "连接中…" : "连接"}
          </button>
        </fieldset>

        {kind === "local" && (
          <fieldset className="field">
            <legend>本机的 Yudao 服务</legend>
            {props.localIssue ? (
              <>
                <p className="note">{props.localIssue.reason}</p>
                {props.localIssue.kind === "no-command" ? (
                  <code className="install">uv tool install --python 3.12 &lt;wheel&gt;</code>
                ) : (
                  <code className="install">服务日志：{props.localIssue.logPath}</code>
                )}
                <button type="button" onClick={submit}>
                  重新检测
                </button>
              </>
            ) : (
              <>
                <p className="note">
                  {props.localConnected
                    ? "本机的 Yudao 服务正在运行。退出客户端不会停止它。"
                    : "本机没有运行 Yudao 服务，连接时客户端会启动它（最多等待 30 秒）。"}
                </p>
                {props.localConnected && (
                  <button type="button" onClick={props.onStopLocal}>
                    停止 Yudao
                  </button>
                )}
              </>
            )}

            <label className="choice">
              <input
                type="checkbox"
                checked={props.settings.allowLan}
                onChange={(event) => props.onAllowLan(event.target.checked)}
              />
              允许局域网访问
            </label>
            <span className="note">
              其他电脑与开发板可以访问这台电脑上的 Yudao，局域网内不校验身份。第一次开启时 Windows
              防火墙会询问是否允许 Python 访问网络，需要管理员确认；电脑所在网络是「公用」类型时勾选
              「公用网络」，或者在 Windows 设置中把这个网络改为「专用」。客户端不修改防火墙。
            </span>
            {props.lanRestartNeeded && (
              <>
                <p className="note">重新启动服务后生效</p>
                <button type="button" onClick={props.onRestartLocal}>
                  重新启动
                </button>
              </>
            )}
          </fieldset>
        )}

        <fieldset className="field">
          <legend>客户端</legend>
          <label className="choice">
            <input
              type="checkbox"
              checked={loginAtStartup}
              onChange={(event) => {
                setLoginAtStartup(event.target.checked);
                props.onLoginAtStartup(event.target.checked);
              }}
            />
            登录时启动客户端
          </label>
          <span className="note">写入当前用户的启动项，不需要管理员权限。</span>
        </fieldset>
      </form>
    </div>
  );
}
