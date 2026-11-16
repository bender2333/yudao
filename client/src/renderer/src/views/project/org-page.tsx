// 「组织」一级标签页挂载入口（工单 #1809，具体视图内容由下游工单 #1650 实现）

import type { ClientApp } from "../../contract/client-app";
import type { ProjectOrganizationResult } from "../../api/generated/types.gen";
import { Block, PageHead } from "../../shell/kit";
import { paths, type Route } from "../../shell/routing";
import { Empty } from "./common";
import type { DepartmentView } from "./organization";

export function OrganizationPage(props: {
  app: ClientApp;
  route: Route;
  organization: ProjectOrganizationResult | null;
  departments: DepartmentView[];
  onNavigate: (hash: string) => void;
}) {
  const projectId = props.route.projectId ?? "";
  const conversationHash = paths.conversation(projectId, { workItem: props.route.workItemId });

  return (
    <div className="page v21-org-page" data-testid="org-page-placeholder">
      <PageHead
        eyebrow="组织"
        title="组织"
        subtitle="展示项目当前的组织形态、各职能卡片与近期调整动态。"
        actions={
          <a
            className="y10-btn is-small small"
            href={conversationHash}
            onClick={(event) => {
              event.preventDefault();
              props.onNavigate(conversationHash);
            }}
          >
            回到对话
          </a>
        }
      />
      <Block title="项目组织" subtitle="组织视图将在后续工单中完善">
        <Empty text="组织视图内容尚未迁入这一页，可先在设置与对话节点中查看。" />
      </Block>
    </div>
  );
}
