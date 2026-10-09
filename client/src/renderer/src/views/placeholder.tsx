// 页面占位：外壳与路由已建立，某个路径还没有对应的页面内容。
// 这里显示当前路径与已读取的外壳数据，不假装已经实现页面内容。

import type { SystemStatus } from "../api/generated/types.gen";
import type { Route } from "../shell/routing";

export type PlaceholderPageProps = {
  route: Route;
  systemStatus: SystemStatus | null;
};

export function PlaceholderPage(props: PlaceholderPageProps) {
  const { route } = props;
  const version = props.systemStatus?.log_id ?? null;
  return (
    <div className="y9-block card">
      <h1>{titleOf(route)}</h1>
      <p className="y9-note note">这个页面还没有内容。</p>
      <dl>
        <dt>路径</dt>
        <dd>{window.location.hash || "#/home"}</dd>
        {route.projectId && (
          <>
            <dt>项目</dt>
            <dd>{route.projectId}</dd>
          </>
        )}
        {version && (
          <>
            <dt>日志身份</dt>
            <dd>{version}</dd>
          </>
        )}
      </dl>
    </div>
  );
}

function titleOf(route: Route): string {
  switch (route.name) {
    case "home":
      return "首页";
    case "not-found":
      return "找不到这个页面";
    default:
      return route.name.startsWith("sys-") ? `系统页：${route.systemPage ?? ""}` : route.name;
  }
}
