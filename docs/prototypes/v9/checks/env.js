// 验收脚本共用的环境：Playwright、Chromium、两版页面的地址与输出目录。
// 脚本按自己所在的检出目录找 v8 与 v9，换一个检出目录（例如 worktree）运行就检查那一份。
const path = require('path');
const { pathToFileURL } = require('url');
const fs = require('fs');

const repoRoot = path.resolve(__dirname, '../../../..');
const playwrightPath = process.env.PLAYWRIGHT_PATH || path.join(repoRoot, '.tmp/v8/pw/node_modules/playwright');
const { chromium } = require(playwrightPath);

const EXE = process.env.CHROMIUM_EXE || 'C:/Users/BA_H3C_Pad/AppData/Local/ms-playwright/chromium-1223/chrome-win64/chrome.exe';
const v8Url = pathToFileURL(path.resolve(__dirname, '../../v8/index.html')).href;
const v9Url = process.env.V9_URL || pathToFileURL(path.resolve(__dirname, '../index.html')).href;
const outDir = path.join(repoRoot, '.tmp/v9-checks');
fs.mkdirSync(outDir, { recursive: true });

// 各版页面的命名空间与存储键前缀：v8 是 Y8 与 y8，v9 是 Y9 与 y9；除 v8 的地址以外一律按 v9 处理
const spaceOf = (root) => (root === v8Url ? { ns: 'Y8', prefix: 'y8' } : { ns: 'Y9', prefix: 'y9' });

module.exports = { chromium, EXE, repoRoot, v8Url, v9Url, outDir, spaceOf };
