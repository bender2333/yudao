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
  activeChanged, afterSend, chosenRecipient, draftChanged, focusRecipient, pickRecipient,
  recipientHint, recipientOptions, type ComposerInput, type ComposerState, type RecipientOption,
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
  const input = useMemo(
    () => (props.activeItemId === null && props.input.active ? { ...props.input, active: false } : props.input),
    [props.activeItemId, props.input],
  );
  const options = useMemo(() => recipientOptions(input), [input]);
  const chosen = chosenRecipient(input, state);
  const seenActive = useRef(input.active);
  useEffect(() => {
    if (input.active === seenActive.current) {
      return;
    }
    seenActive.current = input.active;
    setState((prev) => activeChanged(prev, input.active));
  }, [input.active]);
  // 点击循环图节点：有在跑事项时收件人切换到对应职能的指导；草稿非空时一并冻住；无在跑事项时保持原收件人。
  const seenFocus = useRef(input.focus);
  useEffect(() => {
    const next = input.focus;
    if (next === seenFocus.current) {
      return;
    }
    seenFocus.current = next;
    setState((prev) => focusRecipient(input, prev, next, draft));
  }, [input, draft]);
  const option: RecipientOption = options.find((candidate) => candidate.id === chosen) ?? options[0];
  const hint = recipientHint(input, option.id, props.activeTitle);
  // 指导与追加输入要发到在跑的那件事项上；没有在跑的事项时这两项发不出去，写明原因
  const targetless = option.kind !== "new" && props.activeItemId === null;
  const commandName = option.kind === "new" ? "work_item.create"
    : option.kind === "append" ? "work_item.append_input" : "guidance.send";
  const allowed = hasCommand(props.app, commandName);
  const disabled = draft.trim() === "" || command.busy || targetless || !allowed;

  const pick = (next: RecipientOption): void => {
    setState((prev) => pickRecipient(input, prev, next.id, draft));
  };

  const changeDraft = (value: string): void => {
    setState((prev) => draftChanged(prev, value, chosenRecipient(input, prev)));
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
      setState((prev) => afterSend(prev, option.id));
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
