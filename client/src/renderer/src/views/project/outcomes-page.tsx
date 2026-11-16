// 「成果库」一级标签页挂载入口（工单 #1809，具体视图内容由下游工单 #1810 实现）

import type { ClientApp } from "../../contract/client-app";
import type { ProjectOrganizationResult } from "../../api/generated/types.gen";
import { Block, PageHead } from "../../shell/kit";
import { paths, type Route } from "../../shell/routing";
import { Empty } from "./common";
import type { DepartmentView } from "./organization";

export function OutcomesPage(props: {
  app: ClientApp;
  route: Route;
  organization: ProjectOrganizationResult | null;
  departments: DepartmentView[];
  onNavigate: (hash: string) => void;
}) {
  const projectId = props.route.projectId ?? "";
  const conversationHash = paths.conversation(projectId, { workItem: props.route.workItemId });

  return (
    <div className="page v21-outcomes-page" data-testid="outcomes-page-placeholder">
      <PageHead
        eyebrow="成果库"
        title="成果库"
        subtitle="汇集项目最近放行、开环交付与核心文档资料索引。"
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
      <Block title="项目成果" subtitle="成果库视图将在后续工单中完善">
        <Empty text="成果库内容尚未迁入这一页，可先在对话页查看各事项产出。" />
      </Block>
    </div>
  );
}
