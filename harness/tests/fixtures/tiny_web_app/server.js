// 一个真实的小网页服务：端口从环境变量 PORT 读（浏览器与 computer use 设计说明「启动方式」）。
// 就绪地址是 http://127.0.0.1:{port}/；任何 HTTP 响应都算就绪。
'use strict';

const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');

const port = Number(process.env.PORT);
if (!Number.isInteger(port) || port <= 0) {
  console.error('PORT must be a positive integer');
  process.exit(2);
}

const page = path.join(__dirname, 'dist', 'index.html');

const server = http.createServer((request, response) => {
  if (request.url === '/health') {
    response.writeHead(200, { 'content-type': 'text/plain; charset=utf-8' });
    response.end('ok');
    return;
  }
  let body;
  try {
    body = fs.readFileSync(page);
  } catch (error) {
    response.writeHead(500, { 'content-type': 'text/plain; charset=utf-8' });
    response.end(`the page has not been built: ${error.message}`);
    return;
  }
  response.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
  response.end(body);
});

server.listen(port, '127.0.0.1', () => {
  console.log(`tiny web app listening on ${port}`);
});
