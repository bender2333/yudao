// 编辑 JSON 弹窗（原型 v8 设计说明第 9.1 节「编辑 JSON」行，设计说明第 4.6 节，工单 #93）。
// 目录文档 = Provider 配置 + 模型访问定义 + 部门默认，不含 Key、准入记录与项目设置。
// 校验由后端完成：catalog.document.save 通过则整份写入，任何一项不过则整份拒绝并指出字段位置。
// 界面这一侧只做 JSON 解析；解析失败时整份拒绝，不发命令。

import { useCallback, useEffect, useRef, useState } from "react";

// 可编辑的目录文档文本形状（后端 catalog.document 查询交回的 providers/models/bindings 三项）
export type EditableDocument = {
  providers: unknown[];
  models: unknown[];
  bindings: Record<string, Record<string, unknown>>;
};

export type JsonDialogProps = {
  document: EditableDocument | null;
  onSave: (document: EditableDocument) => Promise<{ ok: boolean; message: string }>;
  onClose: () => void;
};

// 交回可编辑的文档文本：只保留三项，来源是查询结果的原始形状
export function documentToText(document: EditableDocument): string {
  return JSON.stringify(document, null, 2);
}

// 导入的文件文本 → 文档：只接受合法 JSON 与三项数组；字段形状的校验由保存命令完成
export function parseDocumentText(text: string): EditableDocument | string {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (error) {
    return `JSON 无法解析：${error instanceof Error ? error.message : String(error)}`;
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    return "目录文档必须是一个对象，包含 providers、models 与 bindings";
  }
  const document = parsed as Partial<EditableDocument>;
  if (!Array.isArray(document.providers) || !Array.isArray(document.models)) {
    return "目录文档缺少 providers 或 models 数组";
  }
  return {
    providers: document.providers,
    models: document.models,
    bindings: document.bindings ?? {},
  };
}

export function JsonDialog(props: JsonDialogProps) {
  const [text, setText] = useState(() => (props.document ? documentToText(props.document) : ""));
  const [status, setStatus] = useState<{ kind: "ok" | "error"; message: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  // Esc 关闭：弹窗是对话框，键盘操作要能用
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        props.onClose();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [props.onClose]);

  const format = useCallback(() => {
    const parsed = parseDocumentText(text);
    if (typeof parsed === "string") {
      setStatus({ kind: "error", message: parsed });
      return;
    }
    setStatus(null);
    setText(JSON.stringify(parsed, null, 2));
  }, [text]);

  const reset = useCallback(() => {
    setText(props.document ? documentToText(props.document) : "");
    setStatus(null);
  }, [props.document]);

  const copy = useCallback(() => {
    void navigator.clipboard.writeText(text).then(
      () => setStatus({ kind: "ok", message: "已复制到剪贴板。" }),
      () => setStatus({ kind: "error", message: "复制失败，请手动选择文本复制。" }),
    );
  }, [text]);

  const exportFile = useCallback(() => {
    const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "providers.json";
    link.click();
    URL.revokeObjectURL(url);
  }, [text]);

  const importFile = useCallback((file: File) => {
    const reader = new FileReader();
    reader.onload = () => {
      setText(String(reader.result ?? ""));
      setStatus(null);
    };
    reader.readAsText(file);
  }, []);

  const save = useCallback(async () => {
    const parsed = parseDocumentText(text);
    if (typeof parsed === "string") {
      setStatus({ kind: "error", message: parsed });
      return;
    }
    setSaving(true);
    const result = await props.onSave(parsed);
    setSaving(false);
    setStatus({ kind: result.ok ? "ok" : "error", message: result.message });
  }, [text, props.onSave]);

  return (
    <div className="modal-backdrop" role="presentation" onClick={props.onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label="编辑 JSON"
           onClick={(event) => event.stopPropagation()}>
        <h2>编辑 JSON</h2>
        <p className="hint">
          目录文档是 Provider 配置、模型访问定义与部门默认的完整文本，不含 API Key 与准入记录。
          校验通过时整份写入；任何一项不通过时整份拒绝，并指出字段位置。
        </p>
        <textarea className="json-editor" aria-label="目录文档 JSON" value={text} spellCheck={false}
                  onChange={(event) => setText(event.target.value)} />
        {status && (
          <p className={status.kind === "ok" ? "hint" : "hint mm-error"} role="status">{status.message}</p>
        )}
        <div className="mm-actions">
          <button type="button" onClick={format}>格式化</button>
          <button type="button" onClick={reset}>重置</button>
          <button type="button" onClick={copy}>复制</button>
          <button type="button" onClick={() => fileRef.current?.click()}>导入</button>
          <input ref={fileRef} type="file" accept="application/json,.json" aria-label="导入目录 JSON 文件" hidden
                 onChange={(event) => {
                   const file = event.target.files?.[0];
                   if (file) {
                     importFile(file);
                   }
                   event.target.value = "";
                 }} />
          <button type="button" onClick={exportFile}>导出</button>
          <button className="primary" type="button" disabled={saving} onClick={() => void save()}>
            {saving ? "保存中…" : "保存"}
          </button>
          <button type="button" onClick={props.onClose}>关闭</button>
        </div>
      </div>
    </div>
  );
}
