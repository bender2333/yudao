"""Yudao 本体的第一块（本体方案线，`docs/research/yudao-ontology.md` 第 10.1 节，已定 C）。

和规则事实线重叠的概念以 `data/canon.json`、`data/roles.json` 为正本：这里只读它们、编译成本体事实，
不另存一份、不改它们。规则在 `rules/ontology/`。只提醒、不拦提交，不调用任何 LLM。
"""
