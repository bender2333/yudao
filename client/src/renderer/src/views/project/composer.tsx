// 输入框与收件人（工单 #1639，项目的组织设计说明 4.14「项目页是循环图加对话」的交互骨架第 2 条）。
//
// 输入框在对话底部，上方一行收件人，默认按状态选好，能切；点循环图上的节点也切到给这个职能的指导。
// 选项与默认值由 thread-model 从在跑事项冻结的组织推出（换过形态以后仍按那份），这里只画与提交：
//   - 开始一个新事项 → work_item.create
//   - 追加输入 → work_item.append_input（按成果轮转才有；已有的交付要重新验收）
//   - 给某个职能的指导 → guidance.send
//
// 草稿、收件人与页面的滚动都不随事项进展更新而清掉；发送成功以后清空草稿、回到按状态选的默认。

import { useEffect, useMemo, useRef, useState } from "react";
import type { ClientApp } from "../../contract/client-app";
import { CommandFeedback, hasCommand } from "./common";
import { useCommand } from "./use-snapshot";
import {
  afterSend, chosenRecipient, draftChanged, recipientHint, recipientOptions,
  type ComposerInput, type ComposerState, type RecipientOption,
} from "./thread-model";

export function Composer(props: {
  app: ClientApp | null;
  projectId: string;
  /** 收件人一行读的事实：在跑事项冻结的组织、接输入的职能、正在工作的职能、点过的节点 */
  input: ComposerInput;
  /** 在跑的那件事项（指导与追加输入发到它上面）；没有在跑的事项时为空 */
  activeItemId: string | null;
  /** 在跑事项的标题：开始一个新事项时写「排在谁后面」 */
  activeTitle: string;
  /** 数据变化以后清掉「已提交」提示的签名 */
  dataKey: string;
  /** 发送成功：页面把线程滚到最新一条 */
  onSent: () => void;
}) {
  const [draft, setDraft] = useState("");
  const [state, setState] = useState<ComposerState>({ manual: null, hold: null });
  const command = useCommand(props.app, props.dataKey);
  const options = useMemo(() => recipientOptions(props.input), [props.input]);
  const chosen = chosenRecipient(props.input, state);
  // 点循环图的节点：收件人切到给这个职能的指导。这是用户的一次选择，输入框里有字也照切（与原型一致），
  // 切过去以后重新冻住；点的职能不在这份组织里时不理会。
  const seenFocus = useRef(props.input.focus);
  useEffect(() => {
    const next = props.input.focus;
    if (next === seenFocus.current) {
      return;
    }
    seenFocus.current = next;
    if (next === null) {
      return;
    }
    const id = `guide:${next}`;
    if (!options.some((option) => option.id === id)) {
      return;
    }
    setState({ manual: id, hold: draft.trim() === "" ? null : id });
  }, [props.input.focus, options, draft]);
  const option: RecipientOption = options.find((candidate) => candidate.id === chosen) ?? options[0];
  const hint = recipientHint(props.input, option.id, props.activeTitle);
  // 指导与追加输入要发到在跑的那件事项上；没有在跑的事项时这两项发不出去，写明原因
  const targetless = option.kind !== "new" && props.activeItemId === null;
  const commandName = option.kind === "new" ? "work_item.create"
    : option.kind === "append" ? "work_item.append_input" : "guidance.send";
  const allowed = hasCommand(props.app, commandName);
  const disabled = draft.trim() === "" || command.busy || targetless || !allowed;

  const pick = (next: RecipientOption): void => {
    // 输入框里有字时点收件人仍然能切：切过去以后就冻住在这个选择上
    setState({ manual: next.kind === "guide" ? next.id : null, hold: draft.trim() === "" ? null : next.id });
  };

  const changeDraft = (value: string): void => {
    setState(draftChanged(state, value, chosenRecipient(props.input, state)));
    setDraft(value);
  };

  const send = (): void => {
    const text = draft.trim();
    if (text === "" || disabled) {
      return;
    }
    let body: Record<string, unknown>;
    if (option.kind === "new") {
      body = { project_id: props.projectId, text };
    } else if (option.kind === "append") {
      body = { work_item_id: props.activeItemId, text };
    } else {
      body = { work_item_id: props.activeItemId, department: option.department, text };
    }
    void command.submit(commandName, body).then((ok) => {
      if (!ok) {
        return;
      }
      setState(afterSend(state, option.id));
      setDraft("");
      props.onSent();
    });
  };

  return (
    <section className="y10-cv-composer" aria-label="输入框">
      <div className="y10-cv-to" role="radiogroup" aria-label="收件人">
        <span className="y10-cv-to-label">收件人</span>
        {options.map((candidate) => (
          <button
            key={candidate.id}
            type="button"
            role="radio"
            aria-checked={candidate.id === option.id}
            className={`y10-cv-pill${candidate.id === option.id ? " is-on" : ""}`}
            onClick={() => pick(candidate)}
          >
            {candidate.label}
          </button>
        ))}
      </div>
      <p className="y10-cv-hint">{targetless ? "没有在做的事项，先开始一个新事项；指导与追加输入没有可以发的地方" : hint}</p>
      <form
        className="y10-cv-input"
        onSubmit={(event) => {
          event.preventDefault();
          send();
        }}
      >
        <textarea
          className="y10-textarea"
          aria-label={option.label}
          placeholder={option.kind === "new" ? "说说你想做什么……" : option.kind === "append" ? "补充这个事项的要求……" : `${option.label}……`}
          rows={2}
          value={draft}
          onChange={(event) => changeDraft(event.target.value)}
        />
        <button type="submit" className="y10-btn primary" disabled={disabled}>发送</button>
      </form>
      <CommandFeedback submitted={command.submitted} problem={command.problem} />
      {!allowed ? <p className="y10-note">这台主机没有提供「{option.label}」对应的操作</p> : null}
    </section>
  );
}
