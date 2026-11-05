// 构建：把 index.html 复制到 dist/index.html。构建产物不在公开树里，由启动命令自己准备
// （浏览器与 computer use 设计说明第 3.3 节）。
'use strict';

const fs = require('node:fs');
const path = require('node:path');

fs.mkdirSync(path.join(__dirname, 'dist'), { recursive: true });
fs.copyFileSync(path.join(__dirname, 'index.html'), path.join(__dirname, 'dist', 'index.html'));
console.log('tiny web app built');
