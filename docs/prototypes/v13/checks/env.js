// 验收脚本共用的环境：Playwright、Chromium、各版页面的地址与输出目录。
// 脚本按自己所在的检出目录找 v9、v12 与 v13，换一个检出目录（例如 worktree）运行就检查那一份。
const path = require('path');
const { pathToFileURL } = require('url');
const fs = require('fs');

const repoRoot = path.resolve(__dirname, '../../../..');
const playwrightPath = process.env.PLAYWRIGHT_PATH || path.join(repoRoot, '.tmp/v8/pw/node_modules/playwright');
const { chromium } = require(playwrightPath);

const EXE = process.env.CHROMIUM_EXE || 'C:/Users/BA_H3C_Pad/AppData/Local/ms-playwright/chromium-1223/chrome-win64/chrome.exe';
const v9Url = pathToFileURL(path.resolve(__dirname, '../../v9/index.html')).href;
const v12Url = pathToFileURL(path.resolve(__dirname, '../../v12/index.html')).href;
const v13Url = process.env.V13_URL || pathToFileURL(path.resolve(__dirname, '../index.html')).href;
const outDir = path.join(repoRoot, '.tmp/v13-checks');
fs.mkdirSync(outDir, { recursive: true });

// 各版页面的命名空间与存储键前缀：v9 是 Y9 与 y9，v12 是 Y12 与 y12，其余地址按 v13 处理
const spaceOf = (root) => (root === v9Url ? { ns: 'Y9', prefix: 'y9' } : root === v12Url ? { ns: 'Y12', prefix: 'y12' } : { ns: 'Y13', prefix: 'y13' });

module.exports = { chromium, EXE, repoRoot, v9Url, v12Url, v13Url, outDir, spaceOf };
