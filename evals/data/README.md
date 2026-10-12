# 不可变输入：场景 3 旧口径报告

`scenario-3-yudao-historical.json` 是旧口径的场景 3 评测报告原文，取自提交
`aaa91883` 的 `docs/evaluation/scenario-3-yudao.json`（`git show
aaa91883:docs/evaluation/scenario-3-yudao.json` 原样取出，未做任何修改）。

该文件是 `evals/runner/regen_scenario3.py` 的默认输入，也是新口径报告
`docs/evaluation/scenario-3-yudao.json` 的重算起点。文件内容不可修改：
任何改动都会破坏重算测试的逐字节一致性。如需更新口径，改重算脚本，
不要动这个文件。
