// 预留入口页（原型 v9 的 ui/views/sys-reserved.js，原型 v8 设计说明第 9.5 节，工单 #378）：
// 元观察、演化、经验各有一页，只写所属阶段与产品结果（取自路线图第 1 节），
// 并写明进入该阶段时设计。这三个入口没有查询来源，内容写在客户端。

import { Block } from "../../shell/kit";
import { KeyValue } from "../project/common";

type Reserved = { title: string; stage: string; outcome: string };

const RESERVED: Record<string, Reserved> = {
  meta: {
    title: "元观察",
    stage: "Stage 6",
    outcome: "根据运行证据提出组织或规则变更，独立验证、限定采用并可撤销；部门之间的流转有独立的流程审查",
  },
  evolution: {
    title: "演化",
    stage: "Stage 6",
    outcome: "根据运行证据提出组织或规则变更，独立验证、限定采用并可撤销；部门之间的流转有独立的流程审查",
  },
  lessons: {
    title: "经验",
    stage: "持续改进工作线",
    outcome: "从重复问题形成经过验证、可停用的跨任务经验，并证明收益",
  },
};

export function ReservedPage(props: { which: string | null }) {
  const info = props.which === null ? null : RESERVED[props.which] ?? null;
  if (info === null) {
    return (
      <div className="y9-sys-reserved">
        <Block className="y9-reserved" title="预留入口">
          <p className="y9-note note">没有这个预留入口。</p>
        </Block>
      </div>
    );
  }
  return (
    <div className="y9-sys-reserved">
      <Block className="y9-reserved" title={info.title}>
        <KeyValue
          items={[
            ["所属阶段", info.stage],
            ["产品结果", info.outcome],
          ]}
        />
        <p className="y9-note note">进入该阶段时设计。</p>
      </Block>
    </div>
  );
}
