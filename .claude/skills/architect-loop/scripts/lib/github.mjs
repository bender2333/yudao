/** 从 GitHub 读工单。拉不全一律抛错。 */
import { graphql, REPO } from './proc.mjs';

const [OWNER, NAME] = REPO.split('/');

const LIST_FIELDS = `number title milestone { number title }
  labels(first: 50) { nodes { name } }
  blockedBy(first: 30) { totalCount nodes { number state } }
  subIssues(first: 100) { totalCount nodes { number state closedAt } }`;

export function normalizeIssue(n) {
  const sub = n.subIssues || { nodes: [], totalCount: 0 };
  const blk = n.blockedBy || { nodes: [], totalCount: 0 };
  if (sub.totalCount > sub.nodes.length) throw new Error(`#${n.number} 的子工单超过 ${sub.nodes.length}，没拉全`);
  if (blk.totalCount > blk.nodes.length) throw new Error(`#${n.number} 的阻塞方超过 ${blk.nodes.length}，没拉全`);
  return {
    number: n.number,
    title: n.title,
    milestone: n.milestone ? n.milestone.title : '',
    milestoneNumber: n.milestone ? n.milestone.number : 0,
    labels: (n.labels?.nodes || []).map((l) => l.name),
    blockedBy: blk.nodes.map((b) => ({ number: b.number, state: b.state })),
    subIssues: sub.nodes.map((s) => ({ number: s.number, state: s.state, closedAt: s.closedAt })),
    comments: undefined,
  };
}

export function fetchOpenIssues(maxPages = 10) {
  const out = [];
  let cursor = null;
  for (let page = 0; page < maxPages; page += 1) {
    const after = cursor ? `, after: "${cursor}"` : '';
    const data = graphql(`query { repository(owner: "${OWNER}", name: "${NAME}") { issues(first: 50${after}, states: OPEN) { pageInfo { hasNextPage endCursor } nodes { ${LIST_FIELDS} } } } }`);
    const block = data?.repository?.issues;
    if (!block) throw new Error('返回里没有 issues');
    for (const n of block.nodes) out.push(normalizeIssue(n));
    if (!block.pageInfo.hasNextPage) return out;
    cursor = block.pageInfo.endCursor;
  }
  throw new Error(`开放工单超过 ${maxPages * 50} 张，分页没有拉完`);
}

export function fetchComments(number, maxPages = 20) {
  const out = [];
  let cursor = null;
  for (let page = 0; page < maxPages; page += 1) {
    const after = cursor ? `, after: "${cursor}"` : '';
    const data = graphql(`query { repository(owner: "${OWNER}", name: "${NAME}") { issue(number: ${number}) { comments(first: 100${after}) { pageInfo { hasNextPage endCursor } nodes { body createdAt author { login } } } } } }`);
    const block = data?.repository?.issue?.comments;
    if (!block) throw new Error(`#${number} 读不到评论`);
    for (const c of block.nodes) out.push({ body: c.body || '', createdAt: c.createdAt, author: c.author?.login || '' });
    if (!block.pageInfo.hasNextPage) return out;
    cursor = block.pageInfo.endCursor;
  }
  throw new Error(`#${number} 的评论分页没有拉完`);
}

export function fetchMeta(number) {
  const data = graphql(`query { repository(owner: "${OWNER}", name: "${NAME}") { issue(number: ${number}) { number state closedAt title labels(first: 50) { nodes { name } } } } }`);
  const n = data?.repository?.issue;
  if (!n) throw new Error(`#${number} 不存在`);
  return { number: n.number, state: n.state, closedAt: n.closedAt, title: n.title, labels: n.labels.nodes.map((l) => l.name) };
}

/** 一张工单的列表字段（含子工单）。 */
export function fetchIssue(number) {
  const data = graphql(`query { repository(owner: "${OWNER}", name: "${NAME}") { issue(number: ${number}) { ${LIST_FIELDS} } } }`);
  if (!data?.repository?.issue) throw new Error(`#${number} 不存在`);
  return normalizeIssue(data.repository.issue);
}
