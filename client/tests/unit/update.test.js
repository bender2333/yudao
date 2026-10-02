// 客户端的更新地址与失败原因的单元测试（设计说明第 5.2、5.3 节，工单 #208）。
// 只核对不依赖 Electron 与网络的纯函数：地址拼接与失败原因映射。

import { test } from "node:test";
import assert from "node:assert/strict";
import { describeUpdateError, NO_INSTALLER_MESSAGE, UPDATE_PATH, updateFeedUrl } from "../../src/main/update.ts";

test("更新地址是已连接的地址加 /client-update/", () => {
  assert.equal(updateFeedUrl("http://127.0.0.1:8765"), "http://127.0.0.1:8765/client-update/");
  assert.equal(UPDATE_PATH, "/client-update/");
});

test("地址末尾的斜杠不产生两条斜杠", () => {
  assert.equal(updateFeedUrl("http://192.168.1.10:8765/"), "http://192.168.1.10:8765/client-update/");
  assert.equal(updateFeedUrl("http://192.168.1.10:8765///"), "http://192.168.1.10:8765/client-update/");
});

test("latest.yml 请求得到 404 时报告控制主机没有提供客户端安装包", () => {
  const error = Object.assign(new Error("HttpError: 404 Not Found"), { statusCode: 404 });
  assert.equal(describeUpdateError(error), NO_INSTALLER_MESSAGE);
});

test("latest.yml 找不到时（electron-updater 的 ERR_UPDATER_CHANNEL_FILE_NOT_FOUND）报告没有提供客户端安装包", () => {
  const error = Object.assign(new Error('Cannot find channel "latest.yml" update info: HttpError: 404'),
    { code: "ERR_UPDATER_CHANNEL_FILE_NOT_FOUND" });
  assert.equal(describeUpdateError(error), NO_INSTALLER_MESSAGE);
});

test("打包内缺少更新配置时报告控制主机没有提供客户端安装包", () => {
  assert.equal(describeUpdateError(new Error("ENOENT: no such file or directory, open 'app-update.yml'")),
    NO_INSTALLER_MESSAGE);
});

test("下载中断与校验失败保留原始原因，便于用户看出问题", () => {
  assert.equal(describeUpdateError(new Error("net::ERR_CONNECTION_RESET")), "net::ERR_CONNECTION_RESET");
  const checksum = Object.assign(new Error("sha512 checksum mismatch, expected abc, actual def"),
    { code: "ERR_CHECKSUM_MISMATCH" });
  assert.match(describeUpdateError(checksum), /sha512 checksum mismatch/);
});

test("非错误值也给出可读的一句话", () => {
  assert.equal(describeUpdateError("boom"), "boom");
});
