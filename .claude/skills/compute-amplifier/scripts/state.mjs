export function initialState(identity) {
  return { version: 1, identity, rounds: 0, failures: {}, status: 'ready', phase: null, notificationPending: false };
}

export function validateConfig(config) {
  if (!Array.isArray(config.worktrees) || !config.worktrees.length || typeof config.approval !== 'string' || !config.approval.trim()) throw new Error('缺少工作区或批准记录');
  const budget = config.budget;
  if (!Number.isSafeInteger(budget?.totalTokens) || budget.totalTokens < 1 || budget.planning !== 0.3 || budget.implementation !== 0.4 || budget.trial !== 0.3) throw new Error('需要有效硬预算与 30/40/30 分配');
  for (const role of ['preflight', 'solo', 'trial', 'architect']) {
    if (!config.adapters?.[role]) throw new Error(`缺少执行器: ${role}`);
  }
}

export function startRound(state) {
  if (state.status !== 'ready') throw new Error(`不能启动: ${state.status}`);
  if (state.rounds >= 3) return suspend(state, '达到三轮上限');
  return { ...state, rounds: state.rounds + 1, status: 'running', phase: 'solo' };
}

export function suspend(state, reason) {
  return { ...state, status: 'ready-for-human', reason, notificationPending: true };
}

export function recordSolo(state, result) {
  if (state.status !== 'running' || state.phase !== 'solo') throw new Error('Solo 阶段身份无效');
  if (!['completed', 'failed', 'blocked'].includes(result.status) || !Array.isArray(result.issues)) throw new Error('Solo 结果格式无效');
  const failures = { ...state.failures };
  const seen = new Set();
  for (const issue of result.issues) {
    if (!Number.isSafeInteger(issue.number) || issue.number < 1 || seen.has(issue.number) || !['passed', 'failed'].includes(issue.status)) throw new Error('工单结果无效或重复');
    seen.add(issue.number);
    failures[issue.number] = issue.status === 'passed' ? 0 : (failures[issue.number] ?? 0) + 1;
  }
  const next = { ...state, failures };
  if (Object.values(failures).some(count => count >= 3)) return suspend(next, '同一工单连续失败三次');
  if (result.status === 'blocked') return suspend(next, 'Solo 执行环境或批准受阻');
  if (result.status === 'completed' && result.issues.some(i => i.status === 'failed')) throw new Error('队列完成与工单失败结果矛盾');
  if (result.status === 'completed') return { ...next, phase: 'trial' };
  return state.rounds >= 3 ? suspend(next, '第三轮 Solo 尚未完成') : { ...next, phase: 'architect' };
}

export function recordTrial(state, result) {
  if (state.status !== 'running' || state.phase !== 'trial' || !['passed', 'failed', 'blocked'].includes(result.status)) throw new Error('试用结果或阶段无效');
  if (result.status === 'blocked') return suspend(state, '独立试用受阻');
  if (result.status === 'passed') {
    if (!/^[a-f0-9]{40}$/.test(result.commit) || !/^[a-f0-9]{64}$/.test(result.wheel_sha256) || !Array.isArray(result.unresolved) || result.unresolved.length) throw new Error('试用通过缺少完整身份或仍有未解决项');
    return { ...state, status: 'passed', phase: null, accepted: result };
  }
  return state.rounds >= 3 ? suspend(state, '第三轮独立试用仍未通过') : { ...state, phase: 'architect' };
}

export function recordArchitect(state, result) {
  if (state.status !== 'running' || state.phase !== 'architect' || !['ready', 'blocked'].includes(result.status)) throw new Error('架构师结果或阶段无效');
  if (result.status === 'blocked') return suspend(state, '修复设计需要用户决定');
  if (!Array.isArray(result.issues) || !result.issues.length || !result.issues.every(n => Number.isSafeInteger(n) && n > 0) || !Array.isArray(result.unresolved) || result.unresolved.length) throw new Error('缺少修复工单或仍有未决设计');
  return { ...state, status: 'ready', phase: null };
}
