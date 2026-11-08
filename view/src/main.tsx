// 画面的入口（画面与播放 docs/design/visualization.md「搬出：画面成为单独的应用」；工单 #1418、#1573）。
//
// 入口是壳：连上画面自己的来源（Yudao 服务，同一来源），在楼、楼层、房间三个场景之间切换；
// 画布以外的文字（连接状态、接口版本、缺口清单、面包屑）由壳写在画布上方，不属于画面合同。
// 图鉴留作开发构建里的一个页面：开发服务器上打开 #/gallery 就是它，构建产物里没有这个页面。
//
// 页面的文字列表、决定卡片与实时模型输出留在页面上，不在这里；这里只画画面自己的三个场景。

import { useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { Shell, type ShellState } from "./shell.ts";
import { BuildingScene } from "./scenes/building.tsx";
import { FloorScene } from "./scenes/floor.tsx";
import { RoomScene } from "./scenes/room.tsx";

/** 订阅壳的状态：连接状态、场景、缺口清单与面包屑变了就重画画布以外的部分。 */
function useShellState(shell: Shell): ShellState {
  const [state, setState] = useState<ShellState>(() => shell.state);
  useEffect(() => shell.subscribe(setState), [shell]);
  return state;
}

/** 画布以外的文字（壳的一部分，实时显示）。 */
function ShellBar(props: { state: ShellState; onScene: (scene: ShellState["crumbs"][number]["scene"]) => void }): React.JSX.Element {
  const { state } = props;
  const status = state.status;
  const statusText = status.kind === "connecting" ? "连接中…"
    : status.kind === "failed" ? "没有连上 Yudao 服务"
    : status.kind === "unauthorized" ? "需要访问令牌"
    : status.stream === "interrupted" ? "连接中断，数据可能过时" : "已连接";
  return (
    <header style={{ padding: "8px 12px", color: "#e8e8f0", font: "14px/1.5 sans-serif" }}>
      <div style={{ display: "flex", gap: 12, alignItems: "baseline", flexWrap: "wrap" }}>
        <nav aria-label="场景" style={{ display: "flex", gap: 4 }}>
          {state.crumbs.map((crumb, index) => (
            <button
              key={`${crumb.label}-${index}`}
              type="button"
              onClick={() => props.onScene(crumb.scene)}
              style={{
                background: index === state.crumbs.length - 1 ? "#3b3f55" : "transparent",
                color: "#e8e8f0", border: "1px solid #555a77", borderRadius: 4, padding: "2px 8px",
              }}
            >
              {crumb.label}
            </button>
          ))}
        </nav>
        <span aria-label="连接状态">连接状态：{statusText}</span>
        {state.versionNote !== null ? <span>{state.versionNote}</span> : null}
      </div>
      {state.note !== null ? <p style={{ margin: "4px 0 0", color: "#ffd479" }}>{state.note}</p> : null}
      {state.gap.length > 0 ? (
        <details style={{ marginTop: 4 }}>
          <summary>缺口清单（{state.gap.length}）</summary>
          <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
            {state.gap.map((line) => <li key={line}>{line}</li>)}
          </ul>
        </details>
      ) : null}
    </header>
  );
}

function TokenGate(props: { onSubmit: (token: string) => void }): React.JSX.Element {
  const [value, setValue] = useState("");
  return (
    <div style={{ padding: 24, color: "#e8e8f0", font: "14px/1.6 sans-serif" }}>
      <h1>填写访问令牌</h1>
      <p>Yudao 服务以局域网访问方式运行，接口需要访问令牌。在控制主机上用 token create 建立令牌并复制它。</p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          const token = value.trim();
          if (token !== "") props.onSubmit(token);
        }}
      >
        <input
          type="password"
          autoComplete="off"
          aria-label="访问令牌"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          style={{ padding: "4px 8px", marginRight: 8 }}
        />
        <button type="submit">连接</button>
      </form>
    </div>
  );
}

/** 壳的整页：画布以外的一段文字与当前的场景。 */
function App(props: { shell: Shell }): React.JSX.Element {
  const state = useShellState(props.shell);
  const [token, setToken] = useState("");
  const [attempt, setAttempt] = useState(0);
  // 连接画面自己的来源：地址就是画面自己的来源（服务在同一来源下提供画面）
  useEffect(() => {
    void props.shell.open(window.location.origin, token);
  }, [props.shell, token, attempt]);
  const onScene = useCallback((scene: ShellState["crumbs"][number]["scene"]) => {
    if (scene.kind === "building") props.shell.goBuilding();
    else if (scene.kind === "floor") props.shell.goFloor(scene.projectId, scene.workItemId);
    else props.shell.goRoom(scene.department);
  }, [props.shell]);

  if (state.status.kind === "connecting") {
    return <div style={{ padding: 24, color: "#e8e8f0", font: "14px sans-serif" }}>连接中…</div>;
  }
  if (state.status.kind === "unauthorized") {
    return <TokenGate onSubmit={(value) => { setToken(value); setAttempt((count) => count + 1); }} />;
  }
  if (state.status.kind === "failed") {
    return (
      <div style={{ padding: 24, color: "#e8e8f0", font: "14px sans-serif" }}>
        <h1>没有连上 Yudao 服务</h1>
        <p>连接失败：{state.status.message}</p>
        <button type="button" onClick={() => setAttempt((count) => count + 1)}>重新连接</button>
      </div>
    );
  }

  const scene = state.scene;
  return (
    <div className="view-app" style={{ minHeight: "100vh", background: "#14151c" }}>
      <ShellBar state={state} onScene={onScene} />
      {scene.kind === "building" ? <BuildingScene shell={props.shell} /> : null}
      {scene.kind === "floor" ? (
        <FloorScene key={`${scene.projectId}\u0000${scene.workItemId ?? ""}`} shell={props.shell}
          projectId={scene.projectId} workItemId={scene.workItemId} />
      ) : null}
      {scene.kind === "room" ? (
        <RoomScene key={`${scene.projectId}\u0000${scene.department}`} shell={props.shell}
          projectId={scene.projectId} department={scene.department} />
      ) : null}
    </div>
  );
}

const container = document.getElementById("root");
if (container === null) {
  throw new Error("找不到根元素 #root");
}
const root = createRoot(container);

// 图鉴：只在开发构建里、地址写着 #/gallery 时打开（构建产物里没有这个页面）
if (import.meta.env.DEV && window.location.hash === "#/gallery") {
  const { GalleryPage } = await import("./gallery.tsx");
  root.render(<GalleryPage />);
} else {
  const shell = new Shell();
  root.render(<App shell={shell} />);
}
