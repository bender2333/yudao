/**
 * 全部事项（工单 #1709，docs/design/project-organization.md「事项面板与全部事项」）。
 *
 * 从选事项一行末尾的「全部事项」打开，与节点面板、箭头面板、事项面板同一个位置，一次只开一个：
 * 这是这个项目全部事项的分组列表，每组写件数；点一件，循环图切到它并打开它的事项面板。
 * 不在跑的事项也在这里选。
 *
 * 分组、顺序与件数用看板的同一份口径（board.ts 的 boardGroups，依据
 * docs/design/app-and-interface.md「事项看板在页面上的显示」），这里只按列表画出来：
 * 排队中的顺序就是执行顺序，一件同时在几个部门手里时在每个部门的组里各出现一次。
 * 事项的卡片与统计读 project.overview，本页已有的那一份查询，不另发起。
 */

import type { ProjectOverviewResult } from "../../api/generated/types.gen";
import { readFailureText } from "../../contract/read-failure";
import { allItemsList } from "./board";
import type { SnapshotState } from "./use-snapshot";

/** 面板打开的是全部事项的列表：与节点、箭头、事项面板一起放在同一个开关里，一次只开一个。 */
export const ALL_ITEMS_PICK = "all-items";
export type AllItemsPick = typeof ALL_ITEMS_PICK;

export function AllItems(props: {
  /** project.overview：全部事项的卡片与统计 */
  state: SnapshotState<ProjectOverviewResult>;
  /** 图上现在画的那件事项，在列表里标出来 */
  selected: string;
  onPick: (workItem: string) => void;
  onClose: () => void;
}) {
  const list = allItemsList(props.state.data?.work_items ?? []);
  return (
    <section className="y10-cv-panel v20-all-items" aria-label="全部事项" data-testid="all-items">
      <button
        type="button" className="y10-icon-btn y10-cv-close" aria-label="收起" data-testid="all-items-close"
        onClick={props.onClose}
      >
        ×
      </button>
      <h3>全部事项<small> {list.total} 件</small></h3>
      {props.state.data !== null ? null : (
        <p className={props.state.error === null ? "y10-note note" : "error"} role="status">
          {props.state.error === null ? "正在读取全部事项" : readFailureText(props.state.error)}
        </p>
      )}
      {props.state.data === null ? null : props.state.data.work_items.length === 0 ? (
        <p className="y10-cv-note">这个项目还没有事项。</p>
      ) : (
        <>
          <p className="y10-cv-note">
            分组与看板一致：排队中的顺序就是执行顺序；一件同时在几个部门手里时，会出现在每个部门的组里。
          </p>
          {list.groups.map((group) => (
            <div className="v20-all-items-group" key={group.key} data-testid={`all-items-group-${group.key}`}>
              <h4 className="v20-all-items-head">
                {group.title}
                <span className="v20-all-items-count"> {group.count} 件</span>
              </h4>
              <ul className="v20-all-items-list">
                {group.cards.map((card) => (
                  <li
                    key={`${group.key}:${card.workItemId}`}
                    className={`v20-all-items-row${card.workItemId === props.selected ? " is-on" : ""}`}
                  >
                    <button
                      type="button" className="y10-link link v20-all-items-item"
                      data-testid={`all-items-item-${card.workItemId}`}
                      aria-current={card.workItemId === props.selected ? "true" : undefined}
                      onClick={() => props.onPick(card.workItemId)}
                    >
                      {card.title}
                    </button>
                    <span className="v20-all-items-meta">{card.statusText}</span>
                    {card.workingText === "" ? null : <span className="v20-all-items-meta">{card.workingText}</span>}
                    {card.roundText === "" ? null : <span className="v20-all-items-meta">{card.roundText}</span>}
                    {card.stopText === "" ? null : <span className="v20-all-items-stop">停止原因：{card.stopText}</span>}
                    {card.identity === "" ? null : <span className="v20-all-items-identity">{card.identity}</span>}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </>
      )}
    </section>
  );
}
