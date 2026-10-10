// 机器页（原型 v9 的 ui/views/sys-machines.js，原型 v8 设计说明第 9.2 节，工单 #378）：
// 上方是机房的画面，下方是机器列表。列表的每一行与登记表单由 machines.list 与 machine.save 提供，
// 后端还没有这两项，页面因此只画出这两个区块，并写明等待所属工作包登记（3.2C）。

import type { Capabilities } from "../../api/generated/types.gen";
import { Block } from "../../shell/kit";

export function MachinesPage(props: { capabilities: Capabilities }) {
  const listed = props.capabilities.queries.some((query) => query.name === "machines.list");
  return (
    <div className="y9-sys-machines">
      <Block title="机房" subtitle="与首页地下室相同的放大画面；点击设备打开修改表单">
        <p className="y9-note note">机房的放大画面由像素画面的工单填入。</p>
      </Block>
      <Block id="sys-machine-list" title="机器" subtitle="登记以后由执行代理报到；心跳超时的机器上，动作结果未知">
        <p className="y9-note note">
          {listed
            ? "还没有登记的机器。"
            : "控制主机的能力清单中没有机器列表这一条查询，机器暂时不能列出。"}
        </p>
      </Block>
    </div>
  );
}
