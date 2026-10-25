// 工具与扩展页（原型 v10 的 ui/views/sys-tools.js，原型 v8 设计说明第 9.4 节，工单 #378）：
// 网络取回、MCP 工具、浏览器工具、computer use 与只读观察者五个区块。
// 这一页只读汇总各项目的登记，依据见网络取回与 MCP 工具设计说明第 11 节。
// 明细由 tools.registry 给出，后端还没有这一条查询，各区块因此只写它的内容与所属阶段。

import type { Capabilities } from "../../api/generated/types.gen";
import { Block } from "../../shell/kit";

// 五个部分（第 9.4 节）
const SECTIONS: { title: string; subtitle: string }[] = [
  { title: "网络取回", subtitle: "最近的取回记录" },
  { title: "MCP 工具", subtitle: "各项目的服务器、连接方式、可以使用的部门、最近一次状态与其中的工具" },
  { title: "浏览器工具", subtitle: "浏览器工具的动作" },
  { title: "computer use", subtitle: "虚拟屏幕上的动作" },
  { title: "只读观察者", subtitle: "已登记的观察者与它们的订阅范围" },
];

export function ToolsPage(props: { capabilities: Capabilities }) {
  const listed = props.capabilities.queries.some((query) => query.name === "tools.registry");
  return (
    <div className="y10-sys-tools">
      {listed ? null : (
        <p className="y10-note note">控制主机的能力清单中没有工具登记这一条查询，各部分的明细暂时不能列出。</p>
      )}
      {SECTIONS.map((section) => (
        <Block key={section.title} title={section.title} subtitle={section.subtitle}>
          <p className="y10-note note">等待所属工作包加入工具登记的查询。</p>
        </Block>
      ))}
    </div>
  );
}
