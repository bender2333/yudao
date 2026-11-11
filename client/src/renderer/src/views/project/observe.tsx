// 观测页（原型 v8 设计说明第 7.4 节，工单 #80，需求 D21）：请求记录、用量统计与循环区块。
// 请求记录与用量统计是设置页底部「模型请求与用量」的同一份部件（requests-section.tsx，工单 #1710）：
// 两处内容相同，筛选条件也同一组。请求详情在 attempt-detail.tsx。
// 「循环」区块留在这里（工单 #400）：它按事项列出循环树的层、已用边界与收敛状态，
// 设置页那一节里没有循环。
// 页面只读已登记的查询，不用假数据补位。

import type { ClientApp } from "../../contract/client-app";
import type { ProjectOverviewResult } from "../../api/generated/types.gen";
import { paths, type Route } from "../../shell/routing";
import { PageHead } from "../../shell/kit";
import { attemptsSummary } from "./attempts-summary";
import { seedFilters } from "./observe-filter";
import type { DepartmentView } from "./organization";
import { RequestsPanel } from "./requests-section";
import { useSnapshot } from "./use-snapshot";
import { LoopsBlock, loopItems } from "./loops-block";

// 观测页（工单 #80、#400、#801、#1710）：页头说明范围与请求数，下面是请求记录与用量统计，
// 之后是「循环」区块。职能这一格筛选条件由地址给出（?dept=，工单 #801）：
// 职能工作间的「本职能的模型请求」带它进来，观测页自己换条件时地址跟着改。
export function ObservePage(props: { app: ClientApp; route: Route; departments: DepartmentView[] }) {
  const projectId = props.route.projectId ?? "";
  const workItem = props.route.workItemId;
  // 循环区块要的事项清单来自 project.overview（工单 #400）
  const scope = useSnapshot<ProjectOverviewResult>(props.app, "page.observe.loops", "project.overview", {
    project_id: projectId,
  });

  // 职能这一格写回地址（工单 #801）：地址里写的与页面上生效的始终是同一件事，
  // 刷新、后退与分享链接都对得上。地址没有变化时不写，地址栏里不多一条历史
  const writeDepartment = (department: string): void => {
    const target = paths.observe(projectId, { workItem, department: department || null });
    if (window.location.hash !== target) {
      window.location.hash = target;
    }
  };

  return (
    <div className="page y10-obs">
      <RequestsPanel
        app={props.app}
        projectId={projectId}
        workItem={workItem}
        departments={props.departments}
        addressFilters={seedFilters(props.route.departmentFilter)}
        onFiltersChange={(filters) => writeDepartment(filters.department)}
        onScopeChange={(next, filters) => {
          const target = paths.observe(projectId, { workItem: next, department: filters.department || null });
          if (window.location.hash !== target) {
            window.location.hash = target;
          }
        }}
        attemptHash={(item, filters) => paths.observeDetail(projectId, item.attempt_id, {
          workItem,
          runId: item.run_id,
          department: filters.department || null,
        })}
        head={(summary) => (
          <PageHead
            eyebrow={`观测 · ${workItem === null ? "整个项目" : "事项范围"}`}
            title="模型请求"
            subtitle={attemptsSummary(summary)}
          />
        )}
        title="请求记录与用量"
        note="按职能、状态与模型筛选；两个页签使用同一组筛选；点一行看请求详情。"
        sectionId="obs-requests"
        className="y10-obs"
      />
      {/* 「循环」区块（工单 #400）：请求记录与用量之后，按事项列出循环树的层、已用边界与收敛状态 */}
      <LoopsBlock app={props.app} items={loopItems(scope.data, workItem)} />
    </div>
  );
}
