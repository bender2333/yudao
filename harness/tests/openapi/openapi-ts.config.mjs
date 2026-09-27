// 输入是仓库中的 OpenAPI 快照（test_openapi_snapshot.py 核对它与服务返回的文档相同），输出不提交
/** @type {import('@hey-api/openapi-ts').UserConfig} */
export default {
  input: './openapi.json',
  output: './generated',
};
