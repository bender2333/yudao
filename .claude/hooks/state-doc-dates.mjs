// 写状态文档时带进了日期，就提醒写的人：历史只进记录文档与提交说明（共同规则「文档与记录」）。
// Claude Code 的 PostToolUse 钩子，只提醒、不拦截。
import { relative } from "node:path";
import { pathToFileURL } from "node:url";

const STATE_DOCS = [
  /^(CLAUDE|AGENTS|CONTEXT|README)\.md$/,
  /^docs\/(architecture|architecture-view)\.html$/,
  /^docs\/(program-roadmap|foundation-rules)\.md$/,
  /^docs\/(agents|design|requirements)\//,
  /^\.claude\/skills\/.+\.md$/,
];
const DATE = /\b20\d\d-\d\d-\d\d\b/g;

export function isStateDoc(relPath) {
  const p = relPath.replaceAll("\\", "/").replace(/^\.claude\/worktrees\/[^/]+\//, "");
  return STATE_DOCS.some((re) => re.test(p));
}

// 只报这次新写进去的日期：Edit 的上下文里本来就有的不算。
export function newDates(newText, oldText = "") {
  const old = new Set(oldText.match(DATE) ?? []);
  return [...new Set(newText.match(DATE) ?? [])].filter((d) => !old.has(d));
}

function main(input) {
  const t = input.tool_input ?? {};
  if (!t.file_path) return;
  const rel = relative(input.cwd ?? process.cwd(), t.file_path);
  if (!isStateDoc(rel)) return;
  const pairs = t.edits ?? [{ new_string: t.new_string ?? t.content ?? "", old_string: t.old_string ?? "" }];
  const dates = pairs.flatMap((e) => newDates(e.new_string ?? "", e.old_string ?? ""));
  if (dates.length === 0) return;
  process.stderr.write(
    `「${rel}」是状态文档，只写现在的样子；这次写进了日期 ${[...new Set(dates)].join("、")}。` +
      "日期、谁定的、原来怎样改成怎样写进提交说明与 docs/CHANGELOG.md、docs/decision.md 或日记（共同规则「文档与记录」）；确实不是历史的，可以留下。\n",
  );
  process.exit(2);
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  let raw = "";
  process.stdin.on("data", (c) => (raw += c));
  process.stdin.on("end", () => {
    let input;
    try {
      input = JSON.parse(raw || "{}");
    } catch {
      return; // 读不懂输入就不提醒，不挡住写入
    }
    main(input);
  });
}
