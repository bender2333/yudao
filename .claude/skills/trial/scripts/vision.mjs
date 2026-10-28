#!/usr/bin/env node
// 看图：把截图发给具备图像输入的模型，拿回它对画面的描述。
// 只用 Node 内置模块。凭据从环境变量读，不写进文件。
//
// 环境变量：
//   YUDAO_VISION_BASE_URL  默认 https://9router.huiju.asia/v1
//   YUDAO_VISION_API_KEY   必填（也可用 YUDAO_EVAL_API_KEY）
//   YUDAO_VISION_MODEL     默认 ag/gemini-3.8-flash-high
//
// 用法：
//   node vision.mjs --image shot/a.png --image shot/b.png --prompt "画面上有哪些字"
//   node vision.mjs --image shot/a.png --prompt-file ask.txt --max-tokens 1200
//
// 输出：stdout 打印模型的原话；退出码 0 成功，1 失败（stderr 写原因）。

import { readFile } from "node:fs/promises";
import { extname, resolve } from "node:path";

const DEFAULT_MODEL = "ag/gemini-3.8-flash-high";
const DEFAULT_BASE_URL = "https://9router.huiju.asia/v1";

function parseArgs(argv) {
  const out = { images: [], prompt: "", promptFile: "", model: "", baseUrl: "", maxTokens: 1200 };
  for (let i = 0; i < argv.length; i += 1) {
    const key = argv[i];
    const next = () => {
      const value = argv[i + 1];
      if (value === undefined) fail(`参数 ${key} 缺少值`);
      i += 1;
      return value;
    };
    switch (key) {
      case "--image": out.images.push(next()); break;
      case "--prompt": out.prompt = next(); break;
      case "--prompt-file": out.promptFile = next(); break;
      case "--model": out.model = next(); break;
      case "--base-url": out.baseUrl = next(); break;
      case "--max-tokens": out.maxTokens = Number(next()); break;
      case "-h":
      case "--help": out.help = true; break;
      default: fail(`不认识的参数 ${key}`);
    }
  }
  return out;
}

function fail(message) {
  process.stderr.write(`vision: ${message}\n`);
  process.exit(1);
}

const MIME = { ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif" };

// 模型接口对单张图有体积上限（实测整页长图会得到 413）；从文件头读出像素数，过大就当场报清楚怎么缩
function imagePixels(bytes, mime) {
  if (mime === "image/png" && bytes.length > 24 && bytes.toString("latin1", 12, 16) === "IHDR") {
    return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
  }
  if (mime === "image/jpeg") {
    let offset = 2;
    while (offset < bytes.length - 9) {
      if (bytes[offset] !== 0xff) { offset += 1; continue; }
      const marker = bytes[offset + 1];
      const size = bytes.readUInt16BE(offset + 2);
      if (marker >= 0xc0 && marker <= 0xcf && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc) {
        return { width: bytes.readUInt16BE(offset + 7), height: bytes.readUInt16BE(offset + 5) };
      }
      offset += 2 + size;
    }
  }
  return null;
}

const MAX_BYTES = 4 * 1024 * 1024;
const MAX_PIXELS = 25 * 1000 * 1000;

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    process.stdout.write("用法：node vision.mjs --image <png> [--image <png>…] --prompt <要求> | --prompt-file <文件>\n");
    return;
  }
  if (args.images.length === 0) fail("至少给一张 --image");
  if (args.promptFile) args.prompt = await readFile(args.promptFile, "utf8");
  if (!args.prompt.trim()) fail("给 --prompt 或 --prompt-file，说明要它看什么");

  const key = process.env.YUDAO_VISION_API_KEY || process.env.YUDAO_EVAL_API_KEY || "";
  if (!key.trim()) fail("没有凭据：设 YUDAO_VISION_API_KEY（或 YUDAO_EVAL_API_KEY）");
  const baseUrl = (args.baseUrl || process.env.YUDAO_VISION_BASE_URL || DEFAULT_BASE_URL).replace(/\/+$/, "");
  const model = args.model || process.env.YUDAO_VISION_MODEL || DEFAULT_MODEL;

  const parts = [{ type: "text", text: args.prompt }];
  for (const image of args.images) {
    const absolute = resolve(image);
    const mime = MIME[extname(absolute).toLowerCase()];
    if (!mime) fail(`不认识的图片类型：${image}`);
    let bytes;
    try {
      bytes = await readFile(absolute);
    } catch (error) {
      fail(`读不到图片 ${image}：${error.message}`);
    }
    const dims = imagePixels(bytes, mime);
    const pixels = dims ? dims.width * dims.height : 0;
    if (bytes.length > MAX_BYTES || pixels > MAX_PIXELS) {
      const size = `${Math.round(bytes.length / 1024)} KB${dims ? `，${dims.width}×${dims.height} 像素` : ""}`;
      fail(
        `图太大（${size}）：模型接口会返回 413。先缩图再送——` +
          `重截用 \`node browser.mjs shot --out x.jpg --jpeg --max-height 3000\`，` +
          `或用 python PIL 裁小（PIL 读长图要先设 Image.MAX_IMAGE_PIXELS = None）`,
      );
    }
    parts.push({ type: "image_url", image_url: { url: `data:${mime};base64,${bytes.toString("base64")}` } });
  }

  const body = {
    model,
    max_tokens: args.maxTokens,
    stream: false,
    messages: [{ role: "user", content: parts }],
  };

  let response;
  try {
    response = await fetch(`${baseUrl}/chat/completions`, {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${key}` },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(180_000),
    });
  } catch (error) {
    fail(`请求失败：${error.message}`);
  }
  const text = await response.text();
  if (!response.ok) fail(`接口返回 ${response.status}：${text.slice(0, 600)}`);

  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    fail(`返回的不是 JSON：${text.slice(0, 300)}`);
  }
  const content = payload?.choices?.[0]?.message?.content;
  const answer = Array.isArray(content)
    ? content.map((piece) => (typeof piece === "string" ? piece : piece?.text ?? "")).join("")
    : content;
  if (!answer || !String(answer).trim()) fail(`模型没有返回文字内容：${text.slice(0, 400)}`);
  process.stdout.write(`${String(answer).trim()}\n`);
  const usage = payload.usage;
  if (usage) {
    process.stderr.write(`用量 prompt=${usage.prompt_tokens ?? "?"} completion=${usage.completion_tokens ?? "?"} 实际模型=${payload.model ?? model}\n`);
  }
}

main().catch((error) => fail(error?.stack || String(error)));
