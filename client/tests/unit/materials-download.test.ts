// 交付文件的下载入口（工单 #748）：文本文件的内容已经在页面上，同样给下载链接；
// 下载的文件名取交付里的路径名，同一交付里两个同名文件不会互相覆盖。

import { test } from "node:test";
import assert from "node:assert/strict";

import { fileDownload } from "../../src/renderer/src/views/project/materials-download.ts";

test("文本文件有下载入口，链接里的内容与文件内容逐字相同", () => {
  const content = "#!/usr/bin/env python3\nprint('hello')\n";
  const download = fileDownload({ path: "src/echo.py", content, base64: null });
  assert.notEqual(download, null);
  assert.equal(download!.name, "src/echo.py");
  const encoded = download!.href.split(",")[1];
  assert.equal(decodeURIComponent(encoded), content);
});

test("二进制文件有下载入口，链接里是 base64", () => {
  const download = fileDownload({ path: "assets/logo.png", content: null, base64: "AAECAw==" });
  assert.notEqual(download, null);
  assert.equal(download!.name, "assets/logo.png");
  assert.match(download!.href, /^data:application\/octet-stream;base64,/);
});

test("下载文件名是交付里的路径名：两个同名文件不会互相覆盖", () => {
  const first = fileDownload({ path: "a/x.py", content: "a", base64: null });
  const second = fileDownload({ path: "b/x.py", content: "b", base64: null });
  assert.notEqual(first!.name, second!.name);
});

test("没有内容的文件没有下载入口", () => {
  assert.equal(fileDownload({ path: "x.py", content: null, base64: null }), null);
});
