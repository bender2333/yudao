# 看板费用与模型指标

上一手机入口已推送4ea6f18。本次只做小型观测补齐，范围限 `harness/web/**` 与对应 Web 测试，不改后端、配置或CLI，不操作 git。

已确认 `harness/views.py` 的运行响应有 `aggregates.cost`、`board.model`、`events[].model`。`board.provider` 当前来自adapter名称，通常为omp/fake，并不等同于实际模型服务商。

在现有响应式指标网格加入费用与模型，不增加视图。模型优先取按事件顺序最近一次非空的events[].model，使用实际事件证据；没有事件模型就显示“未上报”，不要用选项、默认名字或猜测值冒充实际调用。模型文本继续按不可信文本转义，长模型名可换行。

费用显示现有aggregates.cost的有限正数，不做token价格估算、不擅自加美元等币种。当前模型的Usage.cost和投影cost均默认0，API没有费用上报标记，无法区分未上报与真实0：对0/null/缺失显示明确的“未上报”（或“上报状态未知”），不能伪称已经确认免费。异常数值同样明确缺失。保留可审计的原始汇总，不把小额正数格式化成0。

现有Provider指标当前应明确叫“适配器”，展示omp/fake时不能把它称为实际服务商。后端另有C批将修正标识语义，本次不引入未来配置或自行修改后端；真实服务商可等明确数据契约后再补，不猜测。

为已上报费用、零/缺失、事件模型和缺失模型、长模型名/文本转义增加少量行为测试。用8771假数据页面或Playwright拦截JSON验证1440和390宽布局，没有真实provider调用。不得破坏新任务入口、三部门循环带、开始/取消和原有指标布局。

运行 `python -m pytest harness/tests/test_web.py -q` 与 `node --test harness/tests/test_web_ui.js`，使用已知本机Chrome/Playwright做UI检查。完成后报告实际改动和验证，交主代理立即提交。
