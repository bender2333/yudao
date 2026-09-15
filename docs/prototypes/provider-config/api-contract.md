# 2.2 实现合同

实现按 [README](README.md) 和 [预览](provider-config.html)。主代理已确认：最小列表+表单，不另起框架。

## 文件

- 新增 `harness/web/static/provider-config.js`，由 `index.html` 加载
- 更新 `harness/web/server.py` 路由
- 需要时更新 `harness/runtime.py`：保存目录文件、替换 `provider_catalog`（已有 setter）
- 测试放在现有 `harness/tests/test_web.py` / 新的定向测试，不要全仓跑 pytest
- 不改部门 Prompt、不改 D17 重试、不改在途 run 事件

## 持久化

启动时的 `--provider-config` 路径是唯一文件。保存 = `catalog.to_dict()` 写回该路径，再 `system.provider_catalog = ProviderCatalog.from_dict(...)`。文件不可写则 503，保持旧目录。

## 测试连接

最小 Responses 请求，超时用该 Provider 的 `timeout_sec`。返回 `{ok, error, actual_model, elapsed_ms}`。密钥不得进入响应。失败分类沿用现有 ProviderError，不要新造一套。

## 删除依赖

模型引用该 Provider、或任一部门绑定该 Provider/模型 → 409，指出依赖位置。
