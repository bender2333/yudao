/** CI 上算通过的结论。 */
const PASSING = ['SUCCESS', 'NEUTRAL', 'SKIPPED'];

/**
 * PR 的检查结果：一条都没有时不算绿（看不到结果就是没证据），
 * 还在跑、没有 conclusion 的检查项不算数。
 */
export function checkRollup(checks) {
  const seen = (Array.isArray(checks) ? checks : []).filter((c) => c && c.conclusion);
  const bad = seen.filter((c) => !PASSING.includes(c.conclusion));
  return { total: seen.length, bad, green: seen.length > 0 && bad.length === 0 };
}

/** 不通过的检查项写成「名字:结论」，给两处核对拼同一句提示。 */
export function checkLabels(bad) {
  return (Array.isArray(bad) ? bad : [])
    .map((c) => (c.name || c.context || '检查') + ':' + c.conclusion)
    .join(' ');
}
