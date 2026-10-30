// 规则与参数页（工单 #1195，应用层与接口层设计说明「规则与参数在页面上的显示」，
// 系统页路径 #/sys/rules，与其他系统页并列）。
// 数据全部来自 rules.registry；修改走 parameter.set，撤回走 parameter.withdraw。
// 查询返回的参数版本作为本次修改命令的基准版本；查询位置由视图同步保持，用于回放与刷新。
// 页面不填写或覆盖提出者：提出者由认证身份确定，请求体不携带 modified_by。
// 服务接受后先显示提交中的状态，事件流到达后以登记查询结果更新现值与修改历史；
// 拒绝显示服务返回的中文说明并重新读取规则登记，拒绝不改变页面已有的值。

import { useState } from "react";
import type { RuleRegistry, RuleEntry } from "../../api/generated/types.gen";
import type { ClientApp } from "../../contract/client-app";
import { type CommandProblem } from "../../contract/command-problem.ts";
import { newCommandId } from "../../contract/command-id.ts";
import { PageHead } from "../../shell/kit";
import {
  CommandFeedback, KeyValue, Loading, Modal, SubmitButton, TextInput, hasCommand,
} from "../project/common";
import { formatTime } from "../project/labels";
import { useSnapshot } from "../project/use-snapshot";
import {
  RECORD_FIELD_LABELS, RULE_FORM_TEXT, RULE_KIND_TEXT, RULES_PAGE_NOTE,
  WITHDRAW_BLOCK_TEXT, boundsText, changeLine, editable, groupRules, latestChange,
  notWiredText, numericBounds, recentChanges, valueText, withdrawCheck, withdrawReason,
} from "./rules-view";

const VIEW_ID = "page.sys.rules";

export function RulesPage(props: { app: ClientApp }) {
  const registry = useSnapshot<RuleRegistry>(props.app, VIEW_ID, "rules.registry", {});
  const data = registry.data;
  // 编辑区域只在能力清单同时声明所需查询与命令时显示（设计说明第 571 行）；
  // rules.registry 这一页本身由入口按查询出现，这里再核对两条命令
  const canEdit = hasCommand(props.app, "parameter.set") && hasCommand(props.app, "parameter.withdraw");
  // 拒绝以后重新读取规则登记：直接刷新这一页的视图，页面已有的值（表单草稿）不动
  const onRefresh = () => {
    void props.app.viewSync?.refresh(VIEW_ID);
  };
  return (
    <div className="page y10-sys-rules">
      <PageHead
        eyebrow="规则与参数"
        title="规则登记"
        subtitle="每条规则的现值、默认值、界限、种类、形式、是否接入运行、四项记录与修改历史；数值型参数在这里修改与撤回。"
      />
      <p className="y10-note note" role="status">{RULES_PAGE_NOTE}</p>
      <p className="y10-muted hint" data-testid="rules-parameters-version">
        {data ? `参数版本 ${data.parameters_version}，定义版本 ${data.definitions_version}` : ""}
      </p>
      <Loading state={registry} />
      {registry.error !== null ? (
        <p className="y10-note note" role="status">规则登记读不出来：{registry.error}</p>
      ) : null}
      {data ? (
        <RuleGroups app={props.app} data={data} baseVersion={data.parameters_version} canEdit={canEdit} onRefresh={onRefresh} />
      ) : null}
    </div>
  );
}

// 按领域分组的全部条目（设计说明「每行按领域分组」）；baseVersion 是登记返回的参数版本，
// 修改与撤回命令按它（撤回按重读后的最新值）作为基准版本提交
function RuleGroups(props: {
  app: ClientApp;
  data: RuleRegistry;
  baseVersion: string;
  canEdit: boolean;
  onRefresh: () => void;
}) {
  const groups = groupRules(props.data.rules);
  return (
    <>
      {groups.map((group) => (
        <RuleGroupBlock
          key={group.domain}
          app={props.app}
          domain={group.domain}
          rules={group.rules}
          baseVersion={props.baseVersion}
          canEdit={props.canEdit}
          onRefresh={props.onRefresh}
        />
      ))}
    </>
  );
}

function RuleGroupBlock(props: {
  app: ClientApp;
  domain: string;
  rules: RuleEntry[];
  baseVersion: string;
  canEdit: boolean;
  onRefresh: () => void;
}) {
  return (
    <section className="y10-block card y10-rules-group" data-testid={`rules-group-${props.domain}`}>
      <div className="y10-block-head">
        <div className="y10-block-titles">
          <h2 className="y10-block-title">{props.domain}</h2>
          <p className="y10-block-sub">{props.rules.length} 条</p>
        </div>
      </div>
      <div className="y10-block-body">
        <div className="y10-rules-list">
          {props.rules.map((entry) => (
            <RuleRow key={entry.name} app={props.app} entry={entry} baseVersion={props.baseVersion} canEdit={props.canEdit} onRefresh={props.onRefresh} />
          ))}
        </div>
      </div>
    </section>
  );
}

// 一条登记：条目名、现值、默认值、界限、种类、形式、是否接入运行、四项记录、来源与修改历史
function RuleRow(props: { app: ClientApp; entry: RuleEntry; baseVersion: string; canEdit: boolean; onRefresh: () => void }) {
  const entry = props.entry;
  const bounds = numericBounds(entry);
  const canModify = props.canEdit && editable(entry) && bounds !== null;
  return (
    <article className={`y10-rule-row${entry.wired ? "" : " is-not-wired"}`} data-testid={`rule-${entry.name}`}>
      <header className="y10-rule-head">
        <h3 className="y10-rule-name">{entry.name}</h3>
        <span className="y10-rule-tags">
          <span className="y10-tag tag muted">{RULE_KIND_TEXT[entry.kind] ?? entry.kind}</span>
          <span className="y10-tag tag muted">{RULE_FORM_TEXT[entry.form] ?? entry.form}</span>
          {entry.wired ? (
            <span className="y10-tag tag ok">已接入运行</span>
          ) : (
            <span className="y10-tag tag warn">未接入运行</span>
          )}
        </span>
      </header>
      <p className="y10-rule-values">
        现值 <strong>{valueText(entry.value)}</strong>
        <span className="y10-muted">默认 {valueText(entry.default_value)}</span>
        {bounds !== null ? <span className="y10-muted">{boundsText(bounds)}</span> : null}
      </p>
      {notWiredText(entry) === "" ? null : (
        <p className="y10-note note" data-testid={`rule-not-wired-${entry.name}`}>{notWiredText(entry)}</p>
      )}
      {entry.kind === "structure" ? (
        <p className="y10-note note">结构条目只读：结构修改走候选流程。</p>
      ) : null}
      <KeyValue
        className="y10-rule-records"
        items={RECORD_FIELD_LABELS.map(([field, label]) => [
          label,
          <span key={field}>{entry[field] === "" ? "—" : entry[field]}</span>,
        ])}
      />
      <p className="y10-muted hint">来源：{entry.origin === "" ? "—" : entry.origin}</p>
      <ChangeHistory entry={entry} />
      {canModify && bounds !== null ? (
        <EditForm app={props.app} entry={entry} bounds={bounds} baseVersion={props.baseVersion} onRefresh={props.onRefresh} />
      ) : null}
      {props.canEdit && latestChange(entry) !== null ? (
        <WithdrawForm app={props.app} entry={entry} onRefresh={props.onRefresh} />
      ) : null}
    </article>
  );
}

// 修改历史（设计说明第 563 行）：按时间倒序显示修改者、原值、新值、理由和发生时间，
// 每条记录带稳定身份（事件身份）供撤回核对
function ChangeHistory(props: { entry: RuleEntry }) {
  const changes = recentChanges(props.entry);
  if (changes.length === 0) {
    return <p className="y10-muted hint">没有修改记录：现值是登记的初始值。</p>;
  }
  return (
    <div className="y10-rule-history">
      <h4 className="y10-h3 sub">修改历史</h4>
      <ul className="y10-list">
        {changes.map((change) => (
          <li key={change.event_id} data-change-id={change.event_id}>
            <span>{changeLine(change)}</span>
            <span className="y10-muted">
              {formatTime(change.created_at)} · 修改后参数版本 {change.parameters_version.slice(0, 8)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// 数值型全局参数的修改表单（设计说明第 565、567 行）：初始值为登记返回的当前值，边界来自登记的界限；
// 提交新值与非空理由；命令带命令身份与查询位置对应的基准版本（登记返回的参数版本），不填写提出者
function EditForm(props: {
  app: ClientApp;
  entry: RuleEntry;
  bounds: { min: number; max: number };
  baseVersion: string;
  onRefresh: () => void;
}) {
  const entry = props.entry;
  const [draft, setDraft] = useState(() => String(entry.value));
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [problem, setProblem] = useState<CommandProblem | null>(null);
  const parsed = Number(draft);
  // 页面只核对「填了一个数」：界限由服务核对（设计说明：取值越界显示服务返回的中文说明），
  // 页面不在客户端拦截越界值，提交以后由服务拒绝并重读登记
  const ready = draft.trim() !== "" && Number.isFinite(parsed) && reason.trim() !== "";

  const submit = async () => {
    if (!ready) {
      return;
    }
    setBusy(true);
    setProblem(null);
    setSubmitted(false);
    try {
      const outcome = await props.app.command("parameter.set", {
        command_id: newCommandId(),
        // 基准版本：页面拿到的登记是哪一版，修改就按哪一版提交；过期时服务按 stale_base 拒绝并给当前版本
        base_version: props.baseVersion,
        name: entry.name,
        value: parsed,
        reason: reason.trim(),
      });
      if (outcome.ok) {
        // 服务接受：显示提交中的状态；事件流到达后登记查询结果更新现值与修改历史
        setSubmitted(true);
        setReason("");
      } else {
        // 拒绝显示服务返回的中文说明并重新读取规则登记；页面已有的值不动
        setProblem(outcome.problem);
      }
      props.onRefresh();
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      className="y10-rule-edit"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <div className="y10-rule-edit-fields">
        <label className="y10-field field">
          <span>新值</span>
          <input
            className="y10-input"
            type="number"
            value={draft}
            min={props.bounds.min}
            max={props.bounds.max}
            step="any"
            onChange={(event) => {
              setDraft(event.target.value);
              setSubmitted(false);
              setProblem(null);
            }}
          />
          <small className="y10-muted">{boundsText(props.bounds)}</small>
        </label>
        <TextInput
          label="理由"
          value={reason}
          placeholder="为什么改成这个值"
          onInput={(value) => {
            setReason(value);
            setSubmitted(false);
            setProblem(null);
          }}
        />
      </div>
      <div className="y10-row">
        <SubmitButton label="提交修改" busy={busy} disabled={!ready} onClick={() => void submit()} />
      </div>
      <CommandFeedback submitted={submitted} problem={problem} />
    </form>
  );
}

// 一键撤回（设计说明第 569 行）：撤回使用最近一次修改记录中的原值，仍通过参数修改命令完成。
// 点击撤回后先重新读取规则登记；只有最近修改记录的稳定身份与用户选中的记录一致、
// 且现值仍等于该记录的新值时，才显示确认框（现值经历修改后又变回相同数值时，记录身份改变，同样放弃）。
// 确认后、提交前再按同一身份核对一次；提交 parameter.withdraw，携带 expected_change_id 与最新登记的参数版本，
// 理由由「撤回：」与原理由组成
function WithdrawForm(props: { app: ClientApp; entry: RuleEntry; onRefresh: () => void }) {
  const entry = props.entry;
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<CommandProblem | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [blocked, setBlocked] = useState<string | null>(null);
  const [pending, setPending] = useState<{ changeId: string; oldValue: unknown; reason: string } | null>(null);
  // 用户选中的记录：一键撤回针对的是页面上的最近一次修改（它的稳定身份）
  const selectedId = latestChange(entry)?.event_id ?? "";

  // 重新读取登记并按最新数据核对：身份一致且现值仍等于记录的新值才进入确认框。
  // 返回核对用的那条记录与最新登记（提交时按它带基准版本）
  const check = async (): Promise<{ fresh: RuleRegistry; freshEntry: RuleEntry } | null> => {
    const snapshot = await props.app.queryOne<RuleRegistry>("rules.registry", {});
    const fresh = snapshot.data;
    const freshEntry = fresh.rules.find((rule) => rule.name === entry.name);
    if (freshEntry === undefined) {
      setError("规则登记里已经没有这个条目：这次撤回放弃。");
      props.onRefresh();
      return null;
    }
    const outcome = withdrawCheck(freshEntry, selectedId);
    if (!outcome.ok) {
      setBlocked(WITHDRAW_BLOCK_TEXT[outcome.reason]);
      props.onRefresh();
      return null;
    }
    return { fresh, freshEntry };
  };

  const click = async () => {
    setBusy(true);
    setProblem(null);
    setError(null);
    setBlocked(null);
    try {
      const result = await check();
      if (result === null) {
        return;
      }
      const change = latestChange(result.freshEntry);
      if (change === null) {
        return;
      }
      setPending({ changeId: change.event_id, oldValue: change.old_value, reason: change.reason });
    } catch {
      setError("规则登记读不出来：这次撤回放弃，请稍后再试。");
    } finally {
      setBusy(false);
    }
  };

  const submit = async () => {
    if (pending === null) {
      setConfirming(false);
      return;
    }
    setBusy(true);
    setProblem(null);
    setError(null);
    try {
      // 确认后、提交前再按同一身份核对一次，使用最新登记的参数版本提交
      const result = await check();
      if (result === null) {
        setConfirming(false);
        return;
      }
      const outcome = await props.app.command("parameter.withdraw", {
        command_id: newCommandId(),
        name: entry.name,
        expected_change_id: pending.changeId,
        reason: withdrawReason(pending.reason),
        base_version: result.fresh.parameters_version,
      });
      setConfirming(false);
      if (outcome.ok) {
        // 服务接受：事件流到达后登记查询结果更新现值与修改历史
        setPending(null);
      } else {
        setProblem(outcome.problem);
      }
      props.onRefresh();
    } catch {
      setConfirming(false);
      setError("这次请求没有送到服务端：联系不上服务，请确认服务还在运行以后再提交。");
    } finally {
      setBusy(false);
    }
  };

  const setConfirming = (open: boolean) => {
    if (!open) {
      setPending(null);
    }
  };
  const confirming = pending !== null;
  if (selectedId === "") {
    return null;
  }
  return (
    <div className="y10-rule-withdraw">
      <button type="button" className="y10-btn" disabled={busy} onClick={() => void click()}>
        撤回最近一次修改
      </button>
      {blocked !== null ? <p className="y10-note note" role="status">{blocked}</p> : null}
      {error !== null ? <p className="error" role="status">{error}</p> : null}
      <CommandFeedback submitted={false} problem={problem} />
      {confirming && pending !== null ? (
        <Modal title={`撤回 ${entry.name} 的最近一次修改？`} onClose={() => setConfirming(false)}>
          <p className="y10-note note">
            现值 {valueText(entry.value)}，撤回以后恢复成 {valueText(pending.oldValue)}。
          </p>
          <p className="y10-note note">提交理由：{withdrawReason(pending.reason)}</p>
          <p className="y10-note note">
            撤回也是一次修改，会写进修改历史；服务在写入前核对这条记录仍是最近的一次修改，不符就拒绝。
          </p>
          <p className="y10-row">
            <button type="button" className="y10-btn primary" disabled={busy} onClick={() => void submit()}>
              确认撤回
            </button>
            <button type="button" className="y10-btn" onClick={() => setConfirming(false)}>
              先不撤回
            </button>
          </p>
        </Modal>
      ) : null}
    </div>
  );
}
