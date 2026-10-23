// 验收脚本共用的环境：Playwright、Chromium、两版页面的地址与输出目录。
// 脚本按自己所在的检出目录找 v9 与 v11，换一个检出目录（例如 worktree）运行就检查那一份。
const path = require('path');
const { pathToFileURL } = require('url');
const fs = require('fs');

const repoRoot = path.resolve(__dirname, '../../../..');
const playwrightPath = process.env.PLAYWRIGHT_PATH || path.join(repoRoot, '.tmp/v8/pw/node_modules/playwright');
const { chromium } = require(playwrightPath);

const EXE = process.env.CHROMIUM_EXE || 'C:/Users/BA_H3C_Pad/AppData/Local/ms-playwright/chromium-1223/chrome-win64/chrome.exe';
const v9Url = pathToFileURL(path.resolve(__dirname, '../../v9/index.html')).href;
const v11Url = process.env.V11_URL || pathToFileURL(path.resolve(__dirname, '../index.html')).href;
const outDir = path.join(repoRoot, '.tmp/v11-checks');
fs.mkdirSync(outDir, { recursive: true });

// 各版页面的命名空间与存储键前缀：v9 是 Y9 与 y9，v11 是 Y11 与 y11；除 v9 的地址以外一律按 v11 处理
const spaceOf = (root) => (root === v9Url ? { ns: 'Y9', prefix: 'y9' } : { ns: 'Y11', prefix: 'y11' });

module.exports = { chromium, EXE, repoRoot, v9Url, v11Url, outDir, spaceOf };
