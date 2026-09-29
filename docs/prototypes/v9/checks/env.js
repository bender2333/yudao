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

module.exports = { chromium, EXE, repoRoot, v8Url, v9Url, outDir };
