// 首页的楼（原型 v13 设计说明第 3 至 5 节、原型 js/ui/scenes.js 的 mountBuilding，工单 #178、#955）：
// 每个项目一层，画成缩小的项目楼层。
//
// 页面只做连接（画面与播放设计说明第 3 节）：
//   - projects.list 与每个项目的 project.loop 交给翻译层（translate/building.ts），翻成画面合同的楼的状态；
//   - 事件流不按项目筛选，每条事件先经翻译层翻成楼的动作，再交给画面播放；
//   - 打开画面、重新同步、标签页从后台切回都用 jump：直接显示最新状态，不补播；
//   - 画面的回调（点击楼层）变成跳转。
// 文字列表不属于画面，照旧按查询结果写。

import { useEffect, useMemo, useRef, useState } from "react";
import type { ProjectList, ProjectLoopResult } from "../../api/generated/types.gen";
import type { ClientApp } from "../../contract/client-app";
import { createRafClock } from "../../pixel/clock";
import { buildingTestHooks, createBuildingView, type BuildingModel, type BuildingTestHooks, type BuildingView } from "../../pixel/building/view";
import { BUILDING_STATUS } from "../../pixel/building/status-text";
import { buildingActions, buildingState, toBuildingEvent } from "../../translate/building";
import { Section } from "../project/common";
import { emptyOrFailureText } from "../../contract/read-failure";

export interface BuildingSectionProps {
  app: ClientApp;
  projects: ProjectList | null;
  /** 项目列表读取失败时的原因：有它时不说「还没有项目」，说「读不出来」（工单 #728）。 */
  error: string | null;
  /** 回放位置（全局位置）：不为 null 时每个项目的 project.loop 按位置带 at 读取。 */
  at?: number | null;
  onNavigate: (hash: string) => void;
}

/** 首页的楼：画布、按项目打开的事项查询与事件流接线。 */
export function BuildingSection(props: BuildingSectionProps): React.JSX.Element {
  const at = props.at ?? null;
  const loops = useProjectLoops(props.app, props.projects, at);
  // 状态只由查询结果翻出来：projects.list 的行与各项目的 project.loop
  const model = useMemo(() => buildingState({
    position: loops.position,
    projects: props.projects?.projects ?? [],
    loops: loops.byProject,
  }), [props.projects, loops]);

  return (
    <Section className="y10-home-building" title="全部项目与机器" note={at !== null ? "回放中：每个项目一层，按所选位置的快照显示" : "每个项目一层；点击楼层进入项目概览"}>
      <div className="y10-building-wrap">
        <div className="y10-building-scroll">
          <BuildingCanvas app={props.app} model={model} onNavigate={props.onNavigate} live={at === null} />
        </div>
      </div>
      {model.floors.length === 0 ? (
        <p className="y10-note note">{emptyOrFailureText(props.error, "还没有项目")}</p>
      ) : (
        <ul className="building-list">
          {model.floors.map((floor) => (
            <li key={floor.project_id}>
              <button type="button" className="link" onClick={() => props.onNavigate(`#/p/${floor.project_id}/overview`)}>
                {floor.name}
              </button>
              <span>{BUILDING_STATUS[floor.status]?.text ?? floor.status}</span>
              <span className="y10-note note">{litText(floor.lit)}</span>
              {floor.decisions > 0 ? <span className="count">待你决定 {floor.decisions}</span> : null}
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

/** 楼层亮灯的部门：按产品、工程、质检、运维的顺序列出中文名，都没有时写「没有部门在工作」。 */
function litText(lit: Record<string, boolean>): string {
  const names = ([
    ["product", "产品"], ["engineering", "工程"], ["quality", "质检"], ["operations", "运维"],
  ] as const).filter(([key]) => lit[key]).map(([, label]) => label);
  return names.length ? `${names.join("、")}在工作` : "没有部门在工作";
}

// ---------------------------------------------------------------------------
// 每个项目的事项：为每行项目打开一次 project.loop，连同查询快照的位置一起记下。
// 项目集合变化时重新打开；查询随事件刷新。位置只增不减：跳到最新以后晚回来的旧结果不再上画面。

interface ProjectLoops {
  byProject: Record<string, ProjectLoopResult>;
  /** 这些查询里最新的位置（画面合同的状态要带位置）。 */
  position: number;
}

function useProjectLoops(app: ClientApp, projects: ProjectList | null, at: number | null): ProjectLoops {
  const ids = useMemo(
    () => [...new Set((projects?.projects ?? []).map((p) => p.project_id))].sort(),
    [projects],
  );
  const key = ids.join(",");
  const [loops, setLoops] = useState<ProjectLoops>({ byProject: {}, position: 0 });
  useEffect(() => {
    const views = app.viewSync;
    if (!views || key === "") {
      // 没有项目：楼层清空，位置保留（时间线按位置决定状态上不上画面，位置回到 0 会让空状态上不去）
      setLoops((current) => ({ byProject: {}, position: current.position }));
      return;
    }
    const open = key.split(",");
    for (const projectId of open) {
      const params: Record<string, unknown> = { project_id: projectId };
      if (at !== null) params.at = at;
      void views.open<ProjectLoopResult>(`home.building.${projectId}`, {
        query: "project.loop",
        params,
      }, (data, position) => {
        setLoops((current) => ({
          byProject: { ...current.byProject, [projectId]: data },
          position: Math.max(current.position, position),
        }));
      });
    }
    return () => {
      for (const projectId of open) {
        views.close(`home.building.${projectId}`);
      }
    };
  }, [app, key, at]);
  return loops;
}

// ---------------------------------------------------------------------------
// 楼的画布：PixiJS 挂在宿主元素上，订阅事件流与重新同步

function BuildingCanvas(props: { app: ClientApp; model: BuildingModel; onNavigate: (hash: string) => void; live: boolean }): React.JSX.Element {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const viewRef = useRef<BuildingView | null>(null);
  const clockRef = useRef<ReturnType<typeof createRafClock> | null>(null);
  const navigateRef = useRef(props.onNavigate);
  const liveRef = useRef(props.live);
  const modelRef = useRef(props.model);
  const [error, setError] = useState<string | null>(null);
  navigateRef.current = props.onNavigate;
  liveRef.current = props.live;
  modelRef.current = props.model;

  // 建立画面：PixiJS 的 Application 挂在宿主元素上，时钟与事件流分别订阅
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let cancelled = false;
    const clock = createRafClock(
      (cb: (t: number) => void) => requestAnimationFrame(cb),
      () => performance.now(),
      (h: number) => cancelAnimationFrame(h),
    );
    clockRef.current = clock;
    void (async () => {
      try {
        const view = await createBuildingView({
          host,
          clock,
          onFloorClick: (projectId) => navigateRef.current(`#/p/${projectId}/overview`),
        });
        if (cancelled) {
          view.destroy();
          return;
        }
        viewRef.current = view;
        // 打开画面：直接显示最新的状态，不补播（查询可能早于画面就绪）
        view.jump(modelRef.current);
        // 端到端测试经这个入口读取楼的当前状态（只读的检查入口，与楼层画面的入口同一个做法）
        (window as unknown as { __buildingViewForTest?: BuildingTestHooks }).__buildingViewForTest = buildingTestHooks(view);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
      viewRef.current?.destroy();
      viewRef.current = null;
      clock.destroy();
      clockRef.current = null;
    };
  }, []);

  // 每次查询结果到达：直播交给播放时间线（状态等它之前的动作演完再上画面），回放直接显示那个位置的状态
  useEffect(() => {
    if (!props.live) viewRef.current?.jump(props.model);
    else viewRef.current?.setState(props.model);
  }, [props.model, props.live]);

  // 事件只决定动作的起点：事件经翻译层翻成楼的动作（楼的远层动作不按项目筛选，事件本身带项目标识）。
  // 回放期间不按事件流更新画面（设计说明第 4.1 节：客户端不按事件流更新回放的视图）
  useEffect(() => {
    const off = props.app.subscribeEvents((event) => {
      if (!liveRef.current) return;
      for (const action of buildingActions(toBuildingEvent(event))) viewRef.current?.play(action);
    });
    return off;
  }, [props.app]);

  // 重新同步与标签页从后台切回：清空时间线，直接显示最新状态，不补播（设计说明第 5.2 节）
  useEffect(() => {
    const jumpLatest = (): void => {
      if (modelRef.current) viewRef.current?.jump(modelRef.current);
    };
    const off = props.app.subscribeResync(jumpLatest);
    const onVisible = (): void => {
      if (document.visibilityState === "visible") jumpLatest();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      off();
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [props.app]);

  return (
    <>
      <div className="building-canvas" ref={hostRef} />
      {error !== null ? <p className="pixel-canvas-error">楼的画面加载失败：{error}</p> : null}
    </>
  );
}

