// 顶栏与项目标签（原型 v8 设计说明第 3.2 节）：路径、状态项、连接状态、项目标签。
// 状态项取自 system.status 与 decisions.list 的等待数量，与托盘图标共用同一份数据（第 4.1 节）。
// 本工单建立状态项结构并实现「待你决定」；结果未知的动作、离线的机器由所属工作包的界面工单加入。

export type TopbarProps = {
  path: string;
  pending: number;
  streamConnected: boolean;
  onPendingClick: () => void;
  onToggleDrawer: () => void;
};

export function Topbar(props: TopbarProps) {
  return (
    <header className="topbar">
      <button className="nav-item drawer-toggle" onClick={props.onToggleDrawer} aria-label="打开左侧栏">
        菜单
      </button>
      <span className="path">{props.path}</span>
      <div className="spacer" />
      <button
        className={`status-item${props.pending > 0 ? " lit" : ""}`}
        onClick={props.onPendingClick}
        title="跨项目等待回答的决定请求"
      >
        待你决定：{props.pending > 0 ? props.pending : "无"}
      </button>
      <span className={`connection${props.streamConnected ? "" : " interrupted"}`} role="status">
        {props.streamConnected ? "已连接" : "连接中断，数据可能过时"}
      </span>
    </header>
  );
}

export type Tab = { label: string; hash: string };

export function Tabbar(props: { tabs: Tab[]; activeHash: string; onNavigate: (hash: string) => void }) {
  if (props.tabs.length === 0) {
    return null;
  }
  return (
    <nav className="tabbar" aria-label="项目页面">
      {props.tabs.map((tab) => (
        <button
          key={tab.hash}
          className="tab"
          aria-current={tab.hash === props.activeHash ? "page" : undefined}
          onClick={() => props.onNavigate(tab.hash)}
        >
          {tab.label}
        </button>
      ))}
    </nav>
  );
}
