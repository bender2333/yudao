#!/usr/bin/env node
/**
 * solo — 识图。把截图交给一个视觉模型，让它按给定的验收条目逐条回答。
 *
 *   node .claude/skills/solo/scripts/vision.mjs --image <png> [--image ...] \
 *        --ask "检查这几条：1) … 2) …" [--model ds] [--json]
 *
 * 凭据与端点走环境变量（与评测用的同一组，不写进代码、不打印）：
 *   SOLO_VISION_BASE_URL / SOLO_VISION_API_KEY / SOLO_VISION_MODEL
 *   或退回 YUDAO_EVAL_BASE_URL / YUDAO_EVAL_API_KEY / YUDAO_EVAL_MODEL
 *
 * 退出码：0 有结论；2 缺凭据或端点（调用方应当跳过这一步，而不是当成失败）；
 *         1 调用失败。
 */
import fs from 'node:fs';
import path from 'node:path';

function parseArgs(argv) {
  const args = { _: [], image: [] };
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith('--')) {
      args._.push(token);
      continue;
    }
    const key = token.slice(2);
    const next = argv[i + 1];
    if (next === undefined || next.startsWith('--')) {
      args[key] = true;
      continue;
    }
    if (key === 'image') args.image.push(next);
    else args[key] = next;
    i += 1;
  }
  return args;
}

const args = parseArgs(process.argv.slice(2));
const baseUrl = (process.env.SOLO_VISION_BASE_URL || process.env.YUDAO_EVAL_BASE_URL || '').replace(/\/$/, '');
const apiKey = process.env.SOLO_VISION_API_KEY || process.env.YUDAO_EVAL_API_KEY || '';
// 注意：YUDAO_EVAL_MODEL 默认是 `ds`，deepseek 这条线路没有视觉，网关会把图换成
// 「[image omitted: model has no vision support]」占位符——所以默认用 gemini。
const model = args.model || process.env.SOLO_VISION_MODEL || 'gemini';

if (!baseUrl || !apiKey) {
  process.stderr.write('缺少视觉模型端点或凭据：设 SOLO_VISION_BASE_URL 与 SOLO_VISION_API_KEY（或沿用 YUDAO_EVAL_*）后重试\n');
  process.exit(2);
}
if (!args.image.length) {
  process.stderr.write('要给图：--image <png> [--image ...]\n');
  process.exit(2);
}
const ask = typeof args.ask === 'string' && args.ask.trim()
  ? args.ask.trim()
  : '逐条读出这张页面截图上的文字与可见控件，说明每个区域里有什么。';

const images = [];
for (const file of args.image) {
  const abs = path.resolve(file);
  if (!fs.existsSync(abs)) {
    process.stderr.write('读不到图：' + abs + '\n');
    process.exit(1);
  }
  const ext = path.extname(abs).toLowerCase();
  const mime = ext === '.jpg' || ext === '.jpeg' ? 'image/jpeg' : ext === '.webp' ? 'image/webp' : 'image/png';
  images.push('data:' + mime + ';base64,' + fs.readFileSync(abs).toString('base64'));
}

const body = {
  model,
  messages: [
    {
      role: 'system',
      content: '你是一个严格的界面验收员。只描述你在图里真的看到的东西；看不清、被遮挡、图上没有的，写「看不到」。不要猜测，不要复述题目里的词。',
    },
    {
      role: 'user',
      content: [
        { type: 'text', text: ask },
        ...images.map((url) => ({ type: 'image_url', image_url: { url } })),
      ],
    },
  ],
  temperature: 0,
  max_tokens: 1200,
  stream: false,
};

const response = await fetch(baseUrl + '/v1/chat/completions', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + apiKey },
  body: JSON.stringify(body),
}).catch((error) => ({ ok: false, statusText: error.message }));

if (!response.ok) {
  const text = typeof response.text === 'function' ? await response.text().catch(() => '') : '';
  process.stderr.write('视觉模型调用失败：' + (response.status || '') + ' ' + (response.statusText || '') + '\n' + String(text).slice(0, 400) + '\n');
  process.exit(1);
}

// 有的网关不管 stream:false，照样按 SSE 回：逐行拼 delta。
const contentType = response.headers.get('content-type') || '';
let payload = null;
let answer = '';
if (contentType.includes('text/event-stream')) {
  const raw = await response.text();
  for (const line of raw.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed.startsWith('data:')) continue;
    const data = trimmed.slice(5).trim();
    if (!data || data === '[DONE]') continue;
    let chunk;
    try {
      chunk = JSON.parse(data);
    } catch {
      continue;
    }
    const delta = chunk.choices && chunk.choices[0] && (chunk.choices[0].delta || chunk.choices[0].message);
    if (delta && typeof delta.content === 'string') answer += delta.content;
    if (chunk.model) payload = { model: chunk.model };
  }
} else {
  payload = await response.json();
  answer = (payload.choices && payload.choices[0] && payload.choices[0].message && payload.choices[0].message.content) || '';
}
if (args.json) {
  process.stdout.write(JSON.stringify({ model: payload.model || model, files: args.image.length, answer }) + '\n');
} else {
  process.stdout.write(answer.trim() + '\n');
}
