#!/usr/bin/env node
// 试用用的浏览器通道：一个专用浏览器、一个远程调试端口，用 DevTools 协议操作页面、整页截图、
// 收集控制台与网络错误。不依赖 MCP，只用 Node 22 以上的内置模块（全局 WebSocket 与 fetch）。
//
// 用法（端口默认 9222，浏览器默认按 Chrome、Edge 的顺序找）：
//   node browser.mjs start  [--browser chrome|edge] [--port 9222] [--profile <目录>] [--size 1440x900]
//   node browser.mjs stop   [--port 9222]
//   node browser.mjs tabs   [--port 9222]
//   node browser.mjs open   --url <地址>           打开或复用标签页
//   node browser.mjs url                           当前地址
//   node browser.mjs shot   --out <文件> [--full] [--jpeg] [--quality 72] [--max-height 4000]
//   node browser.mjs text   [--css <选择器>]       页面可见文字（或某个元素的文字）
//   node browser.mjs audit                         视觉与结构的读数：横向溢出、画布是否空白、对比度、图片、被截断的文字
//   node browser.mjs click  --css <选择器> | --text <文字>
//   node browser.mjs type   (--css <选择器> | --text <文字>) --value <文本>
//   node browser.mjs press  --key Enter|Tab|Escape|Backspace|ArrowDown
//   node browser.mjs eval   --expr '<JavaScript>'
//   node browser.mjs watch  --out <errors.log> [--seconds <秒>]
//
// 所有命令都把结果打印成一行 JSON，失败时打印 {"ok":false,"error":"..."} 并以退出码 1 结束。

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';

const DEFAULT_PORT = 9222;

function parseArgs(argv) {
  const args = { _: [] };
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (token.startsWith('--')) {
      const name = token.slice(2);
      const next = argv[i + 1];
      if (next === undefined || next.startsWith('--')) {
        args[name] = true;
      } else {
        args[name] = next;
        i += 1;
      }
    } else {
      args._.push(token);
    }
  }
  return args;
}

function port(args) {
  return Number(args.port ?? DEFAULT_PORT);
}

function out(value) {
  process.stdout.write(JSON.stringify(value) + '\n');
}

function fail(message) {
  out({ ok: false, error: message });
  process.exit(1);
}

// ---------------------------------------------------------------- HTTP 与 CDP

async function httpJson(url, method = 'GET') {
  const response = await fetch(url, { method });
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(`不是 JSON：${text.slice(0, 200)}`);
  }
}

async function versionInfo(p) {
  return httpJson(`http://127.0.0.1:${p}/json/version`);
}

async function listTargets(p) {
  return httpJson(`http://127.0.0.1:${p}/json/list`);
}

function connect(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    const state = { ws, nextId: 0, pending: new Map(), listeners: new Set() };
    const send = (method, params = {}, sessionId) => {
      const id = (state.nextId += 1);
      const payload = { id, method, params };
      if (sessionId) payload.sessionId = sessionId;
      return new Promise((res, rej) => {
        // 定时器要 unref 并清掉，否则命令执行完进程还会多挂 60 秒
        const timer = setTimeout(() => {
          if (state.pending.delete(id)) rej(new Error(`CDP 超时：${method}`));
        }, 60000);
        if (typeof timer.unref === 'function') timer.unref();
        state.pending.set(id, { res, rej, timer });
        ws.send(JSON.stringify(payload));
      });
    };
    ws.addEventListener('open', () => resolve({ ...state, send }));
    ws.addEventListener('error', (event) => reject(new Error(`WebSocket 失败：${event.message ?? '未知'}`)));
    ws.addEventListener('message', async (event) => {
      let raw = event.data;
      if (typeof raw !== 'string') {
        if (raw instanceof ArrayBuffer) raw = Buffer.from(raw).toString('utf8');
        else if (raw && typeof raw.text === 'function') raw = await raw.text();
        else if (ArrayBuffer.isView(raw)) raw = Buffer.from(raw.buffer).toString('utf8');
        else raw = String(raw);
      }
      let message;
      try {
        message = JSON.parse(raw);
      } catch {
        return;
      }
      if (message.id && state.pending.has(message.id)) {
        const { res, rej, timer } = state.pending.get(message.id);
        state.pending.delete(message.id);
        if (timer) clearTimeout(timer);
        if (message.error) rej(new Error(message.error.message ?? 'CDP 报错'));
        else res(message.result);
        return;
      }
      if (message.method) {
        for (const listener of state.listeners) listener(message);
      }
    });
  });
}

async function pageTarget(p) {
  const targets = await listTargets(p);
  const pages = targets.filter((t) => t.type === 'page' && !String(t.url).startsWith('devtools://'));
  if (pages.length > 0) return pages[0];
  const created = await httpJson(`http://127.0.0.1:${p}/json/new?about:blank`, 'PUT');
  return created;
}

async function withPage(p, work) {
  const target = await pageTarget(p);
  const cdp = await connect(target.webSocketDebuggerUrl);
  try {
    await cdp.send('Page.enable');
    await cdp.send('Runtime.enable');
    return await work(cdp, target);
  } finally {
    cdp.ws.close();
  }
}

// 找元素：--css 直接选；--text 按完整文字匹配最深的那个可点元素
function resolverExpression(args) {
  if (args.css) {
    return `(() => { const el = document.querySelector(${JSON.stringify(args.css)}); return el ? { ok: true, el } : { ok: false, reason: '选择器没有命中' }; })()`;
  }
  if (args.text) {
    const text = JSON.stringify(args.text);
    return `(() => {
      const wanted = ${text};
      const candidates = Array.from(document.querySelectorAll('button,a,[role=button],input[type=submit],label,li,td,th,span,div,p,h1,h2,h3,h4'));
      const area = (n) => { const r = n.getBoundingClientRect(); return r.width * r.height; };
      const visible = candidates.filter((n) => {
        const r = n.getBoundingClientRect();
        const style = getComputedStyle(n);
        return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
      });
      const exact = visible.filter((n) => (n.textContent || '').trim() === wanted).sort((a, b) => area(a) - area(b));
      const partial = visible.filter((n) => (n.textContent || '').includes(wanted)).sort((a, b) => area(a) - area(b));
      const el = exact[0] || partial[0];
      return el ? { ok: true, el } : { ok: false, reason: '页面文字里没有找到「' + wanted + '」' };
    })()`;
  }
  return null;
}

async function evaluate(cdp, expression) {
  const result = await cdp.send('Runtime.evaluate', {
    expression,
    returnByValue: true,
    awaitPromise: true,
    userGesture: true,
  });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.exception?.description ?? result.exceptionDetails.text ?? '脚本报错');
  }
  return result.result?.value;
}

const KEYS = {
  Enter: { key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, text: '\r' },
  Tab: { key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 },
  Escape: { key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 },
  Backspace: { key: 'Backspace', code: 'Backspace', windowsVirtualKeyCode: 8 },
  ArrowDown: { key: 'ArrowDown', code: 'ArrowDown', windowsVirtualKeyCode: 40 },
  ArrowUp: { key: 'ArrowUp', code: 'ArrowUp', windowsVirtualKeyCode: 38 },
};

// ---------------------------------------------------------------- 启动与停止

function browserCandidates(kind) {
  const programFiles = process.env.ProgramFiles ?? 'C:\\Program Files';
  const programFilesX86 = process.env['ProgramFiles(x86)'] ?? 'C:\\Program Files (x86)';
  const localAppData = process.env.LOCALAPPDATA ?? path.join(os.homedir(), 'AppData', 'Local');
  const chrome = [
    path.join(programFiles, 'Google', 'Chrome', 'Application', 'chrome.exe'),
    path.join(programFilesX86, 'Google', 'Chrome', 'Application', 'chrome.exe'),
    path.join(localAppData, 'Google', 'Chrome', 'Application', 'chrome.exe'),
  ];
  const edge = [
    path.join(programFilesX86, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
    path.join(programFiles, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
  ];
  if (kind === 'chrome') return chrome;
  if (kind === 'edge') return edge;
  return [...chrome, ...edge];
}

function resolveBrowser(kind) {
  for (const candidate of browserCandidates(kind)) {
    if (fs.existsSync(candidate)) return candidate;
  }
  return null;
}

async function start(args) {
  const p = port(args);
  try {
    const info = await versionInfo(p);
    out({ ok: true, already: true, port: p, browser: info.Browser, webSocketDebuggerUrl: info.webSocketDebuggerUrl });
    return;
  } catch {
    // 端口上没有浏览器，继续启动
  }
  const executable = resolveBrowser(args.browser);
  if (!executable) fail(`没有找到浏览器（--browser ${args.browser ?? 'chrome|edge'}）`);
  const profile = args.profile ? path.resolve(args.profile) : path.join(os.tmpdir(), `yudao-trial-${p}`);
  fs.mkdirSync(profile, { recursive: true });
  const size = args.size ?? '1440x900';
  const child = spawn(
    executable,
    [
      `--remote-debugging-port=${p}`,
      `--user-data-dir=${profile}`,
      '--no-first-run',
      '--no-default-browser-check',
      '--disable-search-engine-choice-screen',
      '--disable-features=Translate,MediaRouter',
      `--window-size=${size}`,
      'about:blank',
    ],
    { detached: true, stdio: 'ignore' },
  );
  child.unref();
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 300));
    try {
      const info = await versionInfo(p);
      out({ ok: true, port: p, browser: info.Browser, profile, executable, pid: child.pid });
      return;
    } catch {
      // 继续等
    }
  }
  fail('浏览器在 30 秒内没有开放调试端口');
}

async function stop(args) {
  const p = port(args);
  try {
    const info = await versionInfo(p);
    const cdp = await connect(info.webSocketDebuggerUrl);
    await cdp.send('Browser.close');
    cdp.ws.close();
    out({ ok: true, port: p, stopped: true });
  } catch {
    out({ ok: true, port: p, stopped: false, note: '端口上没有在跑的浏览器' });
  }
}

// ---------------------------------------------------------------- 页面操作

async function open(args) {
  if (!args.url) fail('缺少 --url');
  const p = port(args);
  const target = await pageTarget(p);
  const cdp = await connect(target.webSocketDebuggerUrl);
  try {
    await cdp.send('Page.enable');
    await cdp.send('Page.navigate', { url: args.url });
    await new Promise((resolve) => setTimeout(resolve, Number(args.wait ?? 1500)));
    const current = await evaluate(cdp, 'location.href');
    out({ ok: true, url: current });
  } finally {
    cdp.ws.close();
  }
}

async function shot(args) {
  if (!args.out) fail('缺少 --out');
  const p = port(args);
  const file = path.resolve(args.out);
  const format = args.jpeg || args.jpg ? 'jpeg' : 'png';
  const quality = Number(args.quality ?? 72);
  const maxHeight = Number(args['max-height'] ?? 4000);
  await withPage(p, async (cdp) => {
    await cdp.send('Page.bringToFront').catch(() => {});
    const metrics = await cdp.send('Page.getLayoutMetrics');
    const content = metrics.cssContentSize ?? metrics.contentSize;
    if (args.full) {
      // Chrome 155 上 captureBeyondViewport 配 clip 会一直不返回；改为临时把视口撑到整页高度
      const width = Math.ceil(metrics.cssLayoutViewport?.clientWidth ?? content.width);
      const pageHeight = Math.ceil(content.height);
      // 长页面（如观测）整页高度可达二十万像素，图会过不了模型接口的上限；按 --max-height 截断
      const height = Math.min(pageHeight, maxHeight);
      await cdp.send('Emulation.setDeviceMetricsOverride', {
        width,
        height,
        deviceScaleFactor: 1,
        mobile: false,
      });
      await new Promise((resolve) => setTimeout(resolve, 200));
      const result = await cdp.send('Page.captureScreenshot', format === 'jpeg' ? { format, quality } : { format });
      fs.mkdirSync(path.dirname(file), { recursive: true });
      fs.writeFileSync(file, Buffer.from(result.data, 'base64'));
      await cdp.send('Emulation.clearDeviceMetricsOverride').catch(() => {});
      out({
        ok: true,
        file,
        width,
        height,
        pageHeight,
        clipped: pageHeight > height,
        format,
        kb: Math.round(fs.statSync(file).size / 1024),
        full: true,
      });
      return;
    }
    const result = await cdp.send('Page.captureScreenshot', format === 'jpeg' ? { format, quality } : { format });
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, Buffer.from(result.data, 'base64'));
    out({
      ok: true,
      file,
      width: metrics.cssLayoutViewport?.clientWidth ?? content.width,
      height: metrics.cssLayoutViewport?.clientHeight ?? content.height,
      pageHeight: Math.ceil(content.height),
      format,
      kb: Math.round(fs.statSync(file).size / 1024),
      full: false,
    });
  });
}

async function text(args) {
  const p = port(args);
  await withPage(p, async (cdp) => {
    const expression = args.css
      ? `(() => { const el = document.querySelector(${JSON.stringify(args.css)}); return el ? el.innerText : null; })()`
      : 'document.body ? document.body.innerText : ""';
    const value = await evaluate(cdp, expression);
    out({ ok: true, text: value });
  });
}

async function click(args) {
  const p = port(args);
  await withPage(p, async (cdp) => {
    const expression = resolverExpression(args);
    if (!expression) fail('需要 --css 或 --text');
    const box = await evaluate(cdp, `(() => { const found = ${expression}; if (!found.ok) return found;
      const el = found.el; el.scrollIntoView({ block: 'center', inline: 'center' });
      const r = el.getBoundingClientRect();
      return { ok: true, x: r.left + r.width / 2, y: r.top + r.height / 2, tag: el.tagName,
               text: (el.textContent || '').trim().slice(0, 80) }; })()`);
    if (!box.ok) fail(box.reason ?? '没有找到元素');
    const point = { x: Math.round(box.x), y: Math.round(box.y) };
    await cdp.send('Input.dispatchMouseEvent', { type: 'mouseMoved', ...point });
    await cdp.send('Input.dispatchMouseEvent', { type: 'mousePressed', button: 'left', clickCount: 1, ...point });
    await cdp.send('Input.dispatchMouseEvent', { type: 'mouseReleased', button: 'left', clickCount: 1, ...point });
    await new Promise((resolve) => setTimeout(resolve, Number(args.wait ?? 300)));
    out({ ok: true, clicked: box.text, tag: box.tag, at: point });
  });
}

async function type(args) {
  if (args.value === undefined) fail('缺少 --value');
  const p = port(args);
  await withPage(p, async (cdp) => {
    const expression = resolverExpression(args);
    if (!expression) fail('需要 --css 或 --text');
    const focused = await evaluate(cdp, `(() => { const found = ${expression}; if (!found.ok) return found;
      const el = found.el; el.scrollIntoView({ block: 'center' }); el.focus();
      if (typeof el.setSelectionRange === 'function' && typeof el.value === 'string') {
        el.setSelectionRange(el.value.length, el.value.length);
      }
      return { ok: true, tag: el.tagName, name: el.getAttribute('name') || el.getAttribute('placeholder') || '' }; })()`);
    if (!focused.ok) fail(focused.reason ?? '没有找到输入位置');
    await cdp.send('Input.insertText', { text: args.value });
    await new Promise((resolve) => setTimeout(resolve, Number(args.wait ?? 300)));
    out({ ok: true, tag: focused.tag, name: focused.name, length: args.value.length });
  });
}

async function press(args) {
  const spec = KEYS[args.key];
  if (!spec) fail(`不支持的键：${args.key}（支持 ${Object.keys(KEYS).join('、')}）`);
  const p = port(args);
  await withPage(p, async (cdp) => {
    await cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', ...spec });
    await cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', ...spec });
    await new Promise((resolve) => setTimeout(resolve, Number(args.wait ?? 300)));
    out({ ok: true, key: args.key });
  });
}

async function evalCommand(args) {
  if (!args.expr) fail('缺少 --expr');
  const p = port(args);
  await withPage(p, async (cdp) => {
    const value = await evaluate(cdp, args.expr);
    out({ ok: true, value });
  });
}

async function tabs(args) {
  const p = port(args);
  const targets = await listTargets(p);
  out({
    ok: true,
    tabs: targets.filter((t) => t.type === 'page').map((t) => ({ id: t.id, url: t.url, title: t.title })),
  });
}

// ---------------------------------------------------------------- 视觉核对（不靠肉眼，读数）

const AUDIT_EXPRESSION = `(() => {
  const parseColor = (value) => {
    const match = String(value || '').match(/rgba?\\(([^)]+)\\)/);
    if (!match) return null;
    const parts = match[1].split(/[,/\\s]+/).filter(Boolean).map(Number);
    if (parts.length < 3) return null;
    return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 };
  };
  const luminance = (c) => {
    const channel = (v) => { const s = v / 255; return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4); };
    return 0.2126 * channel(c.r) + 0.7152 * channel(c.g) + 0.0722 * channel(c.b);
  };
  const ratio = (a, b) => {
    const l1 = luminance(a); const l2 = luminance(b);
    return Math.round(((Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)) * 100) / 100;
  };
  const background = (el) => {
    let node = el;
    while (node && node !== document.documentElement) {
      const style = getComputedStyle(node);
      const color = parseColor(style.backgroundColor);
      if (color && color.a > 0.5) return color;
      node = node.parentElement;
    }
    return { r: 255, g: 255, b: 255, a: 1 };
  };
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none' && Number(style.opacity || 1) > 0.05;
  };
  const describe = (el) => {
    const id = el.id ? '#' + el.id : '';
    const cls = (el.className && typeof el.className === 'string') ? '.' + el.className.trim().split(/\\s+/).slice(0, 2).join('.') : '';
    const text = (el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 40);
    return el.tagName.toLowerCase() + id + cls + (text ? ' 「' + text + '」' : '');
  };

  const viewportWidth = document.documentElement.clientWidth;
  const wide = [];
  for (const el of document.querySelectorAll('body *')) {
    if (!visible(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.right > viewportWidth + 2 && r.width <= viewportWidth * 3) wide.push({ el: describe(el), right: Math.round(r.right), width: Math.round(r.width) });
    if (wide.length >= 12) break;
  }

  const canvases = Array.from(document.querySelectorAll('canvas')).filter(visible).map((canvas) => {
    const w = canvas.width; const h = canvas.height;
    if (!w || !h) return { size: w + 'x' + h, nonBlank: null };
    try {
      const context = canvas.getContext('2d');
      const data = context.getImageData(0, 0, w, h).data;
      let nonTransparent = 0; let colored = 0;
      const step = 4 * Math.max(1, Math.floor((w * h) / 4000));
      for (let i = 0; i < data.length; i += step) {
        if (data[i + 3] > 8) nonTransparent += 1;
        if (data[i] + data[i + 1] + data[i + 2] < 720) colored += 1;
      }
      const total = Math.ceil(data.length / step);
      return { size: w + 'x' + h, nonBlank: Math.round((nonTransparent / total) * 1000) / 1000, dark: Math.round((colored / total) * 1000) / 1000 };
    } catch (error) {
      return { size: w + 'x' + h, nonBlank: null, error: '读不到像素（可能是跨域图片）' };
    }
  });

  const contrasts = [];
  const textBlocks = ['h1', 'h2', 'h3', 'p', 'label', 'button', 'td', 'th', 'li', 'a', 'span'];
  for (const el of document.querySelectorAll(textBlocks.join(','))) {
    if (contrasts.length >= 15) break;
    const own = Array.from(el.childNodes).some((n) => n.nodeType === 3 && n.textContent.trim().length > 0);
    if (!own || !visible(el)) continue;
    const style = getComputedStyle(el);
    const fg = parseColor(style.color);
    if (!fg) continue;
    const bg = background(el);
    const value = ratio(fg, bg);
    if (value < 4.5) contrasts.push({ el: describe(el), ratio: value, font: parseFloat(style.fontSize), weight: style.fontWeight });
  }

  const images = Array.from(document.images).filter(visible).map((img) => ({
    src: String(img.currentSrc || img.src).slice(0, 120),
    shown: Math.round(img.getBoundingClientRect().width) + 'x' + Math.round(img.getBoundingClientRect().height),
    natural: img.naturalWidth + 'x' + img.naturalHeight,
    broken: img.complete && img.naturalWidth === 0,
  }));

  const clipped = [];
  for (const el of document.querySelectorAll('body *')) {
    if (clipped.length >= 10) break;
    const style = getComputedStyle(el);
    if (style.textOverflow === 'ellipsis' && el.scrollWidth > el.clientWidth + 1 && el.clientWidth > 0) clipped.push(describe(el));
  }

  return {
    url: location.href,
    title: document.title,
    viewport: viewportWidth + 'x' + document.documentElement.clientHeight,
    overflowX: document.documentElement.scrollWidth > viewportWidth + 2 ? document.documentElement.scrollWidth : 0,
    wideElements: wide,
    canvases,
    lowContrast: contrasts,
    images,
    clippedText: clipped,
    counts: {
      buttons: Array.from(document.querySelectorAll('button,[role=button]')).filter(visible).length,
      links: Array.from(document.querySelectorAll('a')).filter(visible).length,
      inputs: Array.from(document.querySelectorAll('input,textarea,select')).filter(visible).length,
      headings: Array.from(document.querySelectorAll('h1,h2,h3')).filter(visible).length,
    },
    bodyTextLength: (document.body.innerText || '').length,
  };
})()`;

async function audit(args) {
  const p = port(args);
  await withPage(p, async (cdp) => {
    const value = await evaluate(cdp, AUDIT_EXPRESSION);
    out({ ok: true, audit: value });
  });
}

// ---------------------------------------------------------------- 错误收集

function stamp() {
  const now = new Date();
  const pad = (n, w = 2) => String(n).padStart(w, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
}

async function watch(args) {
  if (!args.out) fail('缺少 --out');
  const p = port(args);
  const file = path.resolve(args.out);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const stream = fs.createWriteStream(file, { flags: 'a' });
  const seconds = args.seconds ? Number(args.seconds) : 0;
  const pageUrls = new Map();
  const recent = new Map();

  const record = (entry) => {
    // 浏览器自身的页面（地址栏下拉、开发者工具）不进日志；同一条两秒内重复出现的只记一次
    if (entry.url && /^(chrome|devtools|chrome-extension):\/\//.test(entry.url)) return;
    const key = [entry.kind, entry.level ?? '', entry.status ?? '', entry.url ?? '', entry.text ?? entry.error ?? ''].join('|');
    const now = Date.now();
    if (now - (recent.get(key) ?? 0) < 2000) return;
    recent.set(key, now);
    if (recent.size > 2000) recent.clear();
    stream.write(JSON.stringify({ ts: stamp(), ...entry }) + '\n');
  };

  let closed = false;
  const attach = async () => {
    let info;
    try {
      info = await versionInfo(p);
    } catch {
      return false;
    }
    const cdp = await connect(info.webSocketDebuggerUrl);
    cdp.listeners.add(async (message) => {
      const { method, params, sessionId } = message;
      if (method === 'Target.attachedToTarget') {
        const targetInfo = params.targetInfo;
        pageUrls.set(params.sessionId, targetInfo.url);
        for (const name of ['Runtime.enable', 'Log.enable', 'Network.enable']) {
          try {
            await cdp.send(name, {}, params.sessionId);
          } catch {
            // 目标可能已经关闭
          }
        }
        record({ kind: 'tab', url: targetInfo.url });
        return;
      }
      if (method === 'Target.targetInfoChanged') {
        if (params.targetInfo.type === 'page') record({ kind: 'tab', url: params.targetInfo.url });
        return;
      }
      if (method === 'Runtime.consoleAPICalled' && ['error', 'warning', 'assert'].includes(params.type)) {
        record({
          kind: 'console',
          level: params.type,
          url: pageUrls.get(sessionId) ?? '',
          text: (params.args ?? []).map((a) => a.value ?? a.description ?? a.type).join(' ').slice(0, 2000),
        });
        return;
      }
      if (method === 'Log.entryAdded') {
        const entry = params.entry;
        record({ kind: 'log', level: entry.level, url: entry.url ?? '', text: (entry.text ?? '').slice(0, 2000) });
        return;
      }
      if (method === 'Network.responseReceived') {
        const response = params.response;
        if (response.status >= 400) {
          record({ kind: 'response', status: response.status, method: response.requestHeadersText ? '' : '', url: response.url, mime: response.mimeType });
        }
        return;
      }
      if (method === 'Network.loadingFailed') {
        record({ kind: 'failed', url: pageUrls.get(sessionId) ?? '', error: params.errorText });
      }
    });
    await cdp.send('Target.setDiscoverTargets', { discover: true });
    await cdp.send('Target.setAutoAttach', { autoAttach: true, waitForDebuggerOnStart: false, flatten: true });
    const existing = await listTargets(p);
    for (const target of existing.filter((t) => t.type === 'page')) {
      try {
        const attached = await cdp.send('Target.attachToTarget', { targetId: target.id, flatten: true });
        pageUrls.set(attached.sessionId, target.url);
        for (const name of ['Runtime.enable', 'Log.enable', 'Network.enable']) {
          await cdp.send(name, {}, attached.sessionId);
        }
      } catch {
        // 目标可能已经关闭
      }
    }
    record({ kind: 'watching', port: p });
    const closer = () => {
      if (!closed) {
        closed = true;
        stream.end();
        process.exit(0);
      }
    };
    process.on('SIGINT', closer);
    process.on('SIGTERM', closer);
    if (seconds > 0) setTimeout(closer, seconds * 1000);
    return true;
  };

  if (!(await attach())) fail('端口上没有在跑的浏览器，先执行 start');
  out({ ok: true, file, port: p, note: '保持运行；Ctrl+C 或 --seconds 到时结束' });
}

// ---------------------------------------------------------------- 入口

const args = parseArgs(process.argv.slice(2));
const command = args._[0];

const table = {
  start,
  stop,
  tabs,
  open,
  url: async (a) => {
    const value = await withPage(port(a), (cdp) => evaluate(cdp, 'location.href'));
    out({ ok: true, url: value });
  },
  shot,
  text,
  audit,
  click,
  type,
  press,
  eval: evalCommand,
  watch,
};

if (!command || !table[command]) {
  fail(`用法：node browser.mjs <${Object.keys(table).join('|')}> [选项]，见文件顶部注释`);
}

try {
  await table[command](args);
} catch (error) {
  fail(error?.message ?? String(error));
}
