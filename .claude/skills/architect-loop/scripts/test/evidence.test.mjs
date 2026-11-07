import test from 'node:test';
import assert from 'node:assert/strict';
import { parseEvidence, parseTestRef, checkComments } from '../lib/evidence.mjs';

const PACK = `EVIDENCE: 验收 @ abc1234
CI: 12345678
1. 标准甲
   - test: harness/tests/a.py::test_alpha（单元）
   - commit: def5678
2. 标准乙
   - local: pytest -k beta（本地跑过：passed）
3. 标准丙
   - none: 没找到用例
— 架构师循环（取证，m）`;

const fakeDeps = (o = {}) => ({
  isAncestor: (a, b) => (o.ancestors ? o.ancestors.some(([x, y]) => x === a && y === b) : true),
  commitExists: (s) => !(o.missingCommits || []).includes(s),
  fileAt: (sha, p) => (o.files ? o.files[p] ?? null : 'def test_alpha(): pass'),
  ciRun: () => (o.ci === undefined ? { conclusion: 'success', headSha: 'abc1234' } : o.ci),
  mainCommitBefore: () => o.mainBefore || '',
});
const cm = (body, createdAt = '2026-11-05T00:00:00Z') => ({ body, createdAt, author: 'x' });

test('解析验收证据包', () => {
  const p = parseEvidence(PACK);
  assert.equal(p.kind, '验收'); assert.equal(p.head, 'abc1234'); assert.equal(p.ci, '12345678');
  assert.deepEqual(p.entries.map((e) => e.lines.map((l) => l.type)), [['test', 'commit'], ['local'], ['none']]);
  assert.equal(p.entries[0].text, '标准甲');
});
test('解析分诊证据包与重做标记', () => {
  const p = parseEvidence('EVIDENCE: 分诊 @ abc1234（重做）\n- 前提：#5 已合并 → 还成立\n  - commit: abc1234\n- 前提：名字没搬 → 已经变了\n  - none: x');
  assert.equal(p.redo, true);
  assert.deepEqual(p.entries.map((e) => e.verdict), ['还成立', '已经变了']);
  assert.equal(p.entries[0].lines.length, 1);
  assert.equal(parseEvidence('随便一句'), null);
});
test('test 行解析', () => {
  assert.deepEqual(parseTestRef('a/b.py::test_x（模块）'), { file: 'a/b.py', name: 'test_x' });
  assert.equal(parseTestRef('没有双冒号'), null);
});
test('全部核对通过：ok、未核对分开计数', () => {
  const r = checkComments([cm(PACK)], {}, fakeDeps());
  assert.equal(r.valid, true); assert.equal(r.mismatches, 0); assert.equal(r.unchecked, 2); assert.equal(r.needsRedo, false);
});
test('test 行：文件不存在、用例名不在文件里都对不上', () => {
  assert.equal(checkComments([cm(PACK)], {}, fakeDeps({ files: {} })).mismatches, 1);
  assert.equal(checkComments([cm(PACK)], {}, fakeDeps({ files: { 'harness/tests/a.py': 'def test_other(): ...' } })).mismatches, 1);
});
test('commit 行不存在对不上；有对不上且没重做过要重做，重做过的不再重做', () => {
  const r = checkComments([cm(PACK)], {}, fakeDeps({ missingCommits: ['def5678'] }));
  assert.equal(r.mismatches, 1); assert.equal(r.valid, true); assert.equal(r.needsRedo, true);
  const r2 = checkComments([cm(PACK.replace('abc1234', 'abc1234（重做）'))], {}, fakeDeps({ missingCommits: ['def5678'] }));
  assert.equal(r2.needsRedo, false);
});
test('头部提交不在 main：无效要重做', () => {
  const r = checkComments([cm(PACK)], {}, fakeDeps({ ancestors: [] }));
  assert.equal(r.valid, false); assert.equal(r.needsRedo, true);
  assert.match(r.problems[0], /不是 origin\/main 的祖先/);
});
test('CI：缺行、失败、提交不是头部祖先都无效', () => {
  assert.equal(checkComments([cm(PACK.replace('CI: 12345678\n', ''))], {}, fakeDeps()).valid, false);
  assert.equal(checkComments([cm(PACK)], {}, fakeDeps({ ci: { conclusion: 'failure', headSha: 'abc1234' } })).valid, false);
  assert.equal(checkComments([cm(PACK)], {}, fakeDeps({ ci: null })).valid, false);
  const anc = [['abc1234', 'origin/main']];
  assert.equal(checkComments([cm(PACK)], {}, fakeDeps({ ancestors: anc })).valid, false);
  assert.equal(checkComments([cm(PACK)], {}, fakeDeps({ ancestors: [...anc, ['abc1234', 'abc1234']] })).valid, true);
});
test('验收过期：最近一张子工单关闭时的 main 不是头部提交的祖先', () => {
  const ctx = { lastChildClosedAt: '2026-11-06T00:00:00Z' };
  const base = [['abc1234', 'origin/main'], ['abc1234', 'abc1234']];
  assert.equal(checkComments([cm(PACK)], ctx, fakeDeps({ mainBefore: 'zzz9999', ancestors: base })).stale, true);
  assert.equal(checkComments([cm(PACK)], ctx, fakeDeps({ mainBefore: 'zzz9999', ancestors: [...base, ['zzz9999', 'abc1234']] })).stale, false);
});
test('分诊过期：证据包早于最近的交回评论，或早于 architecture 工单关闭', () => {
  const pack = 'EVIDENCE: 分诊 @ abc1234\n- 前提：x → 还成立\n  - commit: abc1234';
  assert.equal(checkComments([cm(pack, '2026-11-05T00:00:00Z'), cm('ARCHITECT: 又卡了', '2026-11-06T00:00:00Z')], {}, fakeDeps()).stale, true);
  assert.equal(checkComments([cm('ARCHITECT: 卡', '2026-11-04T00:00:00Z'), cm(pack, '2026-11-05T00:00:00Z')], {}, fakeDeps()).stale, false);
  assert.equal(checkComments([cm(pack, '2026-11-05T00:00:00Z')], { notBefore: '2026-11-06T00:00:00Z' }, fakeDeps()).stale, true);
});
test('证据包之后已有 VERDICT/TRIAGE：judged，不重做', () => {
  const r = checkComments([cm(PACK, '2026-11-05T00:00:00Z'), cm('VERDICT: 全部过了 @ abc', '2026-11-06T00:00:00Z')], {}, fakeDeps());
  assert.equal(r.judged, true); assert.equal(r.valid, false); assert.equal(r.needsRedo, false);
});
test('没有证据包 / 取最后一条', () => {
  assert.equal(checkComments([cm('DELIVERY: x')], {}, fakeDeps()).exists, false);
  const r = checkComments([cm(PACK.replace('abc1234', 'old1234'), '2026-11-04T00:00:00Z'), cm(PACK, '2026-11-05T00:00:00Z')], {}, fakeDeps());
  assert.equal(r.head, 'abc1234');
});

test('防编造：格式不对的证据行、不在 main 的提交、名字只是子串的用例都对不上', () => {
  const bad = 'EVIDENCE: 验收 @ abc1234\nCI: 12345678\n1. 标准\n   - tests: a.py::test_x';
  assert.equal(parseEvidence(bad).entries[0].lines[0].type, '?');
  assert.equal(checkComments([cm(bad)], {}, fakeDeps()).mismatches, 1);
  const notMain = checkComments([cm(PACK)], {}, fakeDeps({ ancestors: [['abc1234', 'origin/main'], ['abc1234', 'abc1234']] }));
  assert.equal(notMain.items.find((i) => i.type === 'commit').status, '对不上');
  const sub = checkComments([cm(PACK)], {}, fakeDeps({ files: { 'harness/tests/a.py': 'def test_alpha_extra(): ...' } }));
  assert.equal(sub.items.find((i) => i.type === 'test').status, '对不上');
});
test('防编造：分诊「还成立」没有一行核对过的证据、前提缺结论都对不上', () => {
  const d = fakeDeps();
  const r = checkComments([cm('EVIDENCE: 分诊 @ abc1234\n- 前提：甲 → 还成立\n  - none: 没找到\n- 前提：乙')], {}, d);
  assert.equal(r.mismatches, 3);
  assert.equal(checkComments([cm('EVIDENCE: 分诊 @ abc1234\n- 前提：甲 → 已经变了\n  - none: 没找到')], {}, d).mismatches, 0);
});
