/**
 * 图上画哪一件事项（工单 #1708，docs/design/project-organization.md 4.14「事项面板与全部事项」）。
 *
 * 这一行在对话上方、循环图的正上方，从 conversation.tsx 搬出来：
 *   - 只有一件事项时也照样有这一行，选中那件的标题可以点，点开它的事项面板；
 *   - 有几件事项时点一件切到那一件（图与时序图跟着换），选中那件的标题可以点，点开它的事项面板；
 *   - 停了的在状态旁写一句停止原因，以开环完成结束的写「开环完成：没有人核验」（item-panel-model.ts）；
 *   - 有中断待恢复的事项时，这一行下面多一行提示，点进那个事项的恢复详情。
 * 页面不在这里判状态与原因：话由 pickStatusText 给，中断的事项由 floor-text 的 interruptionFactRows 给。
 */

import type { InterruptionFactView } from "./floor-text";
import { pickStatusText } from "./item-panel-model";
import type { LoopItemView } from "./loop-graph-model";

export function ItemPicker(props: {
  items: LoopItemView[];
  titles: Record<string, string>;
  /** 图上画的是哪一件 */
  selected: string;
  /** 中断或者待恢复的事项，一行一个 */
  interruptions: InterruptionFactView[];
  /** 切到另一件事项 */
  onPick: (workItem: string) => void;
  /** 打开选中那件事项的面板 */
  onOpen: () => void;
  /** 点进某件事项的恢复详情 */
  onOpenRecovery: (workItem: string) => void;
}) {
  // 标题取项目概览给的那一份；概览还没到时先写事项编号（与线程里的事项细线同一个口径）
  const title = (item: LoopItemView): string => props.titles[item.work_item_id] ?? item.work_item_id;
  const status = (item: LoopItemView): string => pickStatusText(item);
  const only = props.items[0];
  if (only === undefined) {
    return null;
  }
  return (
    <>
      {props.items.length < 2 ? (
        <p className="y10-cv-only" data-testid="item-picker">
          图上画「
          <button type="button" className="y10-link link v20-items-title" data-testid="item-picker-open" onClick={props.onOpen}>
            {title(only)}
          </button>
          」
          <span className="y10-muted" data-testid="item-picker-status"> · {status(only)}</span>
          {only.round === 0 ? null : <span className="y10-muted"> · 第 {only.round} 轮</span>}
        </p>
      ) : (
        <div className="y10-cv-pick" role="tablist" aria-label="选事项" data-testid="item-picker">
          <span className="y10-muted">图上画</span>
          {props.items.map((item) => (
            item.work_item_id === props.selected ? (
              <span key={item.work_item_id} className="y10-cv-pick-btn is-on" role="tab" aria-selected>
                <button
                  type="button"
                  className="y10-link link v20-items-title"
                  data-testid="item-picker-open"
                  onClick={props.onOpen}
                >
                  {title(item)}
                </button>
                <small> {status(item)}</small>
              </span>
            ) : (
              <button
                key={item.work_item_id}
                type="button"
                role="tab"
                aria-selected={false}
                className="y10-cv-pick-btn"
                onClick={() => props.onPick(item.work_item_id)}
              >
                {title(item)}
                <small> {status(item)}</small>
              </button>
            )
          ))}
        </div>
      )}
      {props.interruptions.map((row) => (
        <p key={row.itemId} className="v20-items-interrupted" data-testid="item-interrupted">
          <span>「{row.itemTitle}」{row.state}</span>
          {row.department === "" ? null : <span className="y10-muted"> · {row.department}</span>}
          <span className="y10-muted"> · 已用 {row.elapsed}</span>
          <button
            type="button"
            className="y10-link link"
            data-testid="item-interrupted-open"
            onClick={() => props.onOpenRecovery(row.itemId)}
          >
            看恢复详情
          </button>
        </p>
      ))}
    </>
  );
}
