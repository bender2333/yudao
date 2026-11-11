// 形态卡与小循环图（工单 #1648，docs/design/project-organization.md「形态一键选用」「新建的入口」）。
//
// 一份形态一张卡：形态名、轮转与结束两个标记、一句话、一张小循环图，全部读 forms.list（页面不内置形态清单，
// 也不内置职能清单）。发布带里没有的那一份（产品 · 工程 · 质检 · 运维）由页面写灰卡，写「发布带还没有」。
// 小图不另写画法：卡上直接画 form-cards-model 用冻结组织的形状交给 loop-graph-model 得到的那张图。
//
// 点卡选中这份形态（连图里的节点与箭头一起），发不发命令由入口决定：名字空着、接入时缺源目录都不发，
// 提示写在卡片上方。卡上不另写提交按钮，点卡就是提交。

import type { FormCatalogResult } from "../../api/generated/types.gen";
import type { ClientApp } from "../../contract/client-app";
import { readFailureText } from "../../contract/read-failure";
import { formCards, type FormCardView } from "./form-cards-model";
import { LoopGraphView } from "./loop-graph";
import { useSnapshot } from "./use-snapshot";

/** 卡上小图的回调：点图里的节点、箭头、询问都算点这一张卡。 */
function graphPick(form: string, onPick: (form: string) => void): () => void {
  return () => onPick(form);
}

function Card(props: { card: FormCardView; onPick: (form: string) => void }): React.JSX.Element {
  const { card } = props;
  if (!card.available) {
    // 灰着点不了：发布带里没有这份形态，由页面写这一张，不画小图
    return (
      <div className="v20-form-card is-missing" aria-disabled="true" data-testid="form-card-missing">
        <p className="v20-form-card-name">{card.label}</p>
        <p className="v20-form-card-note">{card.note}</p>
      </div>
    );
  }
  const pick = graphPick(card.form, props.onPick);
  return (
    <div
      className={`v20-form-card${card.defaultCard ? " is-default" : ""}`}
      data-testid={`form-card-${card.form}`}
      onClick={() => props.onPick(card.form)}
    >
      <div className="v20-form-card-head">
        <button
          type="button"
          className="v20-form-card-pick"
          onClick={(event) => {
            event.stopPropagation();
            props.onPick(card.form);
          }}
        >
          {card.label}
        </button>
        {card.note === "" ? null : <span className="v20-form-card-default">{card.note}</span>}
      </div>
      <p className="v20-form-card-markers">
        {card.markers.map((marker) => (
          <span className="v20-form-card-marker" key={marker}>
            {marker}
          </span>
        ))}
      </p>
      <p className="v20-form-card-line">{card.cardLine}</p>
      {card.graph === null ? null : (
        <div className="v20-form-card-graph">
          <LoopGraphView graph={card.graph} pick={null} onPickNode={pick} onPickArrow={pick} onPickAsk={pick} />
        </div>
      )}
    </div>
  );
}

export function FormCards(props: {
  app: ClientApp | null;
  /** 点一张卡：入口拿到形态标识，自己看名字与源目录齐不齐，再决定发不发命令 */
  onPick: (form: string) => void;
  /** 入口写的那一句（名字空着、缺源目录），画在卡片上方 */
  hint: string | null;
}): React.JSX.Element {
  // 不带项目的形态清单：请求为 None（工单 #1647）
  const forms = useSnapshot<FormCatalogResult>(props.app, "shell.new-project.forms", "forms.list", {});
  const cards = formCards(forms.data?.forms);
  return (
    <div className="v20-form-cards" data-testid="form-cards">
      {props.hint === null ? null : (
        <p className="v20-form-cards-hint" role="alert" data-testid="form-cards-hint">
          {props.hint}
        </p>
      )}
      {forms.error === null ? null : <p className="y10-note note">{readFailureText(forms.error)}</p>}
      {forms.data !== null || forms.error !== null ? null : (
        <p className="y10-note note" role="status">
          正在读取发布带的形态
        </p>
      )}
      {cards.map((card) => (
        <Card key={card.label} card={card} onPick={props.onPick} />
      ))}
    </div>
  );
}
