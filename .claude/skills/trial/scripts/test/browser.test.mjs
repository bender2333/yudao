// 试用工具 browser.mjs 的自测（工单 #1353）：在真 Chromium 里操作一个由 React 渲染的页面。
//
// 守的是两条试用里出过的事故：
//   1. `type --replace` 只发了一个合成的 Ctrl+A 键。页面不渲染时（窗口被别的窗口盖住、最小化、
//      标签页在后台）Chrome 不把合成的鼠标与按键事件交给渲染器，Ctrl+A 于是没选中，insertText
//      追加在原值后面：输入框变成 ag/gemini-3.8ag/gemini-3.8-flash-high。
//   2. `click` 也一样：命令报告成功、元素也在坐标上，但页面收不到 click，React 的 onClick 不跑，
//      服务端收不到请求。
//
// 两条的根因相同（页面没有被渲染），所以用例先把窗口最小化，确认页面确实处于「不渲染」状态，
// 再跑命令；断言的落点是 React 的 state 与服务端收到的请求，不是坐标。
//
// 运行方式（trial 技能目录下的用例不进 CI 的「工作台脚本」作业）：
//   cd client && npm ci                 # 页面用 client 的 React 与 Vite 模块服务器
//   node --test --test-reporter=spec .claude/skills/trial/scripts/test/*.test.mjs
//
// 需要本机有 Chrome 或 Edge（browser.mjs start 自己找），以及能最小化的窗口（Windows）。
import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { cpSync, existsSync, mkdtempSync, rmSync } from 'node:fs';
import { createRequire } from 'node:module';
import { createServer as createNetServer } from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const execFileAsync = promisify(execFile);
const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, '..', '..', '..', '..', '..');
const clientRoot = path.join(repoRoot, 'client');
const browserScript = path.join(repoRoot, '.claude', 'skills', 'trial', 'scripts', 'browser.mjs');

let vite;
let cdpPort;
let fixtureUrl;
let workDir;
const apiRequests = [];

async function freePort() {
  const server = createNetServer();
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const value = server.address().port;
  await new Promise((resolve) => server.close(resolve));
  return value;
}

// 跑一条 browser.mjs 命令，取最后一行 JSON
async function browserCommand(args) {
  const { stdout } = await execFileAsync(process.execPath, [browserScript, ...args], {
    cwd: repoRoot,
    timeout: 120_000,
    maxBuffer: 4 * 1024 * 1024,
  });
  const lines = stdout.trim().split(/\r?\n/).filter(Boolean);
  return JSON.parse(lines[lines.length - 1]);
}

async function browserEval(expression) {
  const result = await browserCommand(['eval', '--port', String(cdpPort), '--expr', expression]);
  if (!result.ok) throw new Error(result.error ?? 'eval 失败');
  return result.value;
}

async function waitFor(expression, accept, { tries = 40, interval = 150 } = {}) {
  let last;
  for (let i = 0; i < tries; i += 1) {
    last = await browserEval(expression);
    if (accept(last)) return last;
    await new Promise((resolve) => setTimeout(resolve, interval));
  }
  throw new Error(`等不到期望的值，最后一次：${JSON.stringify(last)}`);
}

// 服务端（Vite 中间件）收到的请求在测试进程里，直接查
async function waitForRequest(accept, { tries = 40, interval = 100 } = {}) {
  for (let i = 0; i < tries; i += 1) {
    if (apiRequests.some(accept)) return true;
    await new Promise((resolve) => setTimeout(resolve, interval));
  }
  return false;
}

// 删除测试自己建的临时目录：浏览器进程收尾时 Windows 会占住 profile 一会儿
async function removeTemp(target) {
  for (let i = 0; i < 40; i += 1) {
    try {
      rmSync(target, { recursive: true, force: true });
      return;
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
  }
}

async function waitForBrowserExit() {
  for (let i = 0; i < 50; i += 1) {
    try {
      await fetch(`http://127.0.0.1:${cdpPort}/json/version`);
    } catch {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
}

// 浏览器级 CDP 连接：只用来把窗口最小化，让页面进入「不渲染」状态
async function browserLevelSend(calls) {
  const version = await (await fetch(`http://127.0.0.1:${cdpPort}/json/version`)).json();
  const targets = await (await fetch(`http://127.0.0.1:${cdpPort}/json/list`)).json();
  const page = targets.find((target) => target.type === 'page' && !String(target.url).startsWith('devtools://'));
  const ws = new WebSocket(version.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve);
    ws.addEventListener('error', () => reject(new Error('连不上浏览器级的调试端口')));
  });
  let nextId = 0;
  const send = (method, params) => new Promise((resolve, reject) => {
    const id = (nextId += 1);
    const timer = setTimeout(() => reject(new Error(`CDP 超时：${method}`)), 20_000);
    const listener = (event) => {
      const message = JSON.parse(event.data);
      if (message.id !== id) return;
      ws.removeEventListener('message', listener);
      clearTimeout(timer);
      message.error ? reject(new Error(message.error.message)) : resolve(message.result);
    };
    ws.addEventListener('message', listener);
    ws.send(JSON.stringify({ id, method, params }));
  });
  try {
    return await calls(send, page);
  } finally {
    ws.close();
  }
}

// 把窗口最小化，并确认页面确实处于隐藏（不渲染）状态——两条用例的前提
async function hideWindow() {
  await browserLevelSend(async (send, page) => {
    const { windowId } = await send('Browser.getWindowForTarget', { targetId: page.id });
    await send('Browser.setWindowBounds', { windowId, bounds: { windowState: 'minimized' } });
  });
  const visibility = await waitFor('document.visibilityState', (value) => value === 'hidden', { tries: 40 });
  assert.equal(visibility, 'hidden', '前提：窗口最小化以后页面不渲染（visibilityState 为 hidden）');
}

before(async () => {
  if (!existsSync(path.join(clientRoot, 'node_modules', 'vite'))) {
    throw new Error(`缺少客户端依赖：先在 ${clientRoot} 里运行 npm ci`);
  }
  workDir = mkdtempSync(path.join(os.tmpdir(), 'yudao-browser-test-'));
  // Vite 的模块服务器从 client 的依赖里解析 React，夹具页面复制到 client/.tmp 下
  const fixtureDirName = path.join('.tmp', `browser-test-${process.pid}`);
  const fixtureDir = path.join(clientRoot, fixtureDirName);
  cpSync(path.join(here, 'fixtures'), fixtureDir, { recursive: true });

  const require = createRequire(import.meta.url);
  const vitePackage = require.resolve('vite/package.json', { paths: [clientRoot] });
  const viteModule = await import(pathToFileURL(path.join(path.dirname(vitePackage), 'dist', 'node', 'index.js')).href);
  vite = await viteModule.createServer({
    root: clientRoot,
    cacheDir: path.join(clientRoot, 'node_modules', '.vite-browser-test'),
    server: { host: '127.0.0.1', port: 0, strictPort: false },
    logLevel: 'error',
    appType: 'spa',
    plugins: [
      {
        name: 'trial-browser-test-api',
        configureServer(devServer) {
          devServer.middlewares.use((request, response, next) => {
            if (!String(request.url).startsWith('/api/')) return next();
            apiRequests.push({ method: request.method, url: request.url });
            response.statusCode = 200;
            response.setHeader('content-type', 'application/json');
            response.end('{"ok":true}');
          });
        },
      },
    ],
  });
  await vite.listen();
  const viteUrl = vite.resolvedUrls?.local?.[0];
  if (!viteUrl) throw new Error('Vite 没有给出地址');
  fixtureUrl = new URL(`${fixtureDirName.split(path.sep).join('/')}/index.html`, viteUrl).href;

  cdpPort = await freePort();
  const started = await browserCommand(['start', '--port', String(cdpPort), '--profile', path.join(workDir, 'profile')]);
  if (!started.ok) throw new Error(started.error ?? '浏览器没有启动');
  await browserCommand(['open', '--port', String(cdpPort), '--url', fixtureUrl, '--wait', '2500']);
  // React 首次挂载要等模块服务器把依赖转好
  await waitFor('document.querySelector("#search") !== null', (value) => value === true, { tries: 60 });
});

after(async () => {
  if (cdpPort) {
    await browserCommand(['stop', '--port', String(cdpPort)]).catch(() => {});
    await waitForBrowserExit();
  }
  await vite?.close();
  await removeTemp(path.join(clientRoot, '.tmp', `browser-test-${process.pid}`));
  if (workDir) await removeTemp(workDir);
});

test('type --replace 在输入框已有内容时只留新值（不拼接）', async () => {
  await hideWindow();
  const typed = await browserCommand(['type', '--port', String(cdpPort), '--css', '#search', '--value', 'ag/gemini-3.8-flash-high', '--replace']);
  assert.equal(typed.ok, true);
  const state = JSON.parse(await browserEval(
    'JSON.stringify({ value: document.querySelector("#search").value, state: document.querySelector("#search-state").textContent })',
  ));
  assert.equal(state.value, 'ag/gemini-3.8-flash-high', '输入框里只有新值，不是原值加新值');
  assert.equal(state.state, 'ag/gemini-3.8-flash-high', 'React 的 state 跟着换成新值（受控组件收到了 input 事件）');
});

test('type --replace 在输入框为空时写入新值', async () => {
  await hideWindow();
  const typed = await browserCommand(['type', '--port', String(cdpPort), '--css', '#empty', '--value', 'ag/gemini-3.8-flash-high', '--replace']);
  assert.equal(typed.ok, true);
  const state = JSON.parse(await browserEval(
    'JSON.stringify({ value: document.querySelector("#empty").value, state: document.querySelector("#empty-state").textContent })',
  ));
  assert.equal(state.value, 'ag/gemini-3.8-flash-high');
  assert.equal(state.state, 'ag/gemini-3.8-flash-high');
});

test('click 触发 React 的 onClick，服务端收到请求', async () => {
  await hideWindow();
  apiRequests.length = 0;
  const clicked = await browserCommand(['click', '--port', String(cdpPort), '--text', '刷新模型列表']);
  // 现有输出格式不变：仍然报告点了哪个元素、在哪
  assert.equal(clicked.ok, true);
  assert.equal(clicked.clicked, '刷新模型列表');
  assert.equal(clicked.tag, 'BUTTON');
  assert.equal(typeof clicked.at?.x, 'number');
  assert.equal(typeof clicked.at?.y, 'number');
  const clickCount = await waitFor('document.querySelector("#click-state").textContent', (value) => value === '1');
  assert.equal(clickCount, '1', 'React 的 onClick 跑了（state 增加）');
  const received = await waitForRequest((entry) => entry.method === 'POST' && entry.url === '/api/candidates');
  assert.ok(received, `服务端收到了点击发出的请求，实际收到：${JSON.stringify(apiRequests)}`);
});

test('press Enter 在表单里提交，服务端收到请求', async () => {
  await hideWindow();
  apiRequests.length = 0;
  await browserCommand(['type', '--port', String(cdpPort), '--css', '#form-field', '--value', 'x']);
  const pressed = await browserCommand(['press', '--port', String(cdpPort), '--key', 'Enter']);
  assert.equal(pressed.ok, true);
  await waitFor('document.querySelector("#submit-state").textContent', (value) => value === 'yes', { tries: 20 });
  assert.ok(
    apiRequests.some((entry) => entry.method === 'POST' && entry.url === '/api/submit'),
    `服务端收到了表单提交的请求，实际收到：${JSON.stringify(apiRequests)}`,
  );
});
