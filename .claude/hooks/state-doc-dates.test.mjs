import { test } from "node:test";
import assert from "node:assert/strict";
import { isStateDoc, newDates } from "./state-doc-dates.mjs";

test("状态文档与记录文档分开", () => {
  for (const p of ["CLAUDE.md", "docs/architecture.html", "docs/design/visualization.md", ".claude/skills/flow/SKILL.md", "docs/requirements/a.md", ".claude/worktrees/agent-a/docs/agents/shared-rules.md", "docs\\design\\a.md"]) {
    assert.ok(isStateDoc(p), p);
  }
  for (const p of ["docs/CHANGELOG.md", "docs/decision.md", "claude_jour.md", "docs/adr/0044-x.md", "harness/a.py"]) {
    assert.ok(!isStateDoc(p), p);
  }
});

test("只报新写进去的日期", () => {
  assert.deepEqual(newDates("改于 2026-10-31", ""), ["2026-10-31"]);
  assert.deepEqual(newDates("见 2026-10-30 的决定，另 2026-10-31", "见 2026-10-30 的决定"), ["2026-10-31"]);
  assert.deepEqual(newDates("没有日期", ""), []);
});
