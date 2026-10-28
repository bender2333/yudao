const CHECKBOX = /^[ \t]*[-*][ \t]*\[( |x|X|~|-)\][ \t]*(.*)$/;
const TABLE_ROW = /^[ \t]*\|[ \t]*([A-Za-z0-9._-]+)[ \t]*\|/;

/** 任务行里认得的依赖写法：(after T-030)、依赖 T-030、blocked by #42。 */
export function parseAfter(body) {
  const ids = new Set();
  const patterns = [
    /\(\s*after\s+([^)]+)\)/gi,
    /（\s*after\s+([^)）]+)）/gi,
    /\bdepends on\s+([^)]+)/gi,
    /\bblocked by\s+([^,;)\]]+)/gi,
    /依赖\s+([^，,；;）)]+)/g,
  ];
  for (const re of patterns) {
    let m;
    while ((m = re.exec(body)) !== null) {
      for (const token of m[1].split(/[\s,;、]+/)) {
        const id = token.trim().replace(/^#/, '');
        if (/^[A-Za-z0-9._-]+$/.test(id)) ids.add(id);
      }
    }
  }
  return [...ids];
}

/** 解析 tasks.md：一条复选框一行；旧的表格行按已完成算。 */
export function parseTasksText(text) {
  const tasks = [];
  text.split(/\r?\n/).forEach((raw, index) => {
    const line = raw.replace(/\s+$/, '');
    const box = CHECKBOX.exec(line);
    if (box) {
      const marker = box[1].toLowerCase();
      const body = box[2];
      const idMatch = /^([A-Za-z0-9._-]+)/.exec(body);
      const issueMatch = /#(\d+)/.exec(body);
      const waiting = /[（(][^）)]*(\bwaiting\b|等用户|等前提条件|中断)[^）)]*[)）]/i.test(body);
      const status = marker === 'x' ? 'done'
        : marker === '~' ? 'escalated'
          : waiting ? 'waiting'
            : 'pending';
      tasks.push({
        id: idMatch ? idMatch[1] : '',
        issue: issueMatch ? Number(issueMatch[1]) : null,
        status,
        blocked: waiting,
        exclusive: /@exclusive/i.test(body),
        after: parseAfter(body),
        text: body,
        lineNo: index + 1,
        raw: line,
      });
      return;
    }
    const row = TABLE_ROW.exec(line);
    if (row && !/^[-.]+$/.test(row[1])) {
      tasks.push({
        id: row[1],
        issue: null,
        status: 'done',
        blocked: false,
        exclusive: false,
        after: [],
        text: line.trim(),
        lineNo: index + 1,
        raw: line,
      });
    }
  });
  return tasks;
}
