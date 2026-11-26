#!/usr/bin/env python3
"""最小「三职能互检」循环原型（确定性引擎，不调用模型）。

依据是 Yudao 默认形态 three_departments 的三职能与成果驱动闭环
（产品写需求、工程做、质检核验，放行才算完成），以及语音里对
「三木门」的说明：部门之间质询、挑刺、相互检查并转起来。
本脚本不修改、不驱动 Yudao 本体；对照是结构/定性的。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# 固定小任务（两侧同一份，便于对照）
TASK = (
    "写一个纯函数 clamp(x, lo, hi)：把 x 限制在闭区间 [lo, hi] 后返回。"
    "若 lo > hi，视为参数错误，必须抛出 ValueError，不得默默交换两端。"
)

# 工程首稿（也作为单引擎一次交付）：常见写法，lo>hi 时会默默交换
BUGGY = (
    "def clamp(x, lo, hi):\n"
    "    return max(lo, min(hi, x))\n"
)
FIXED = (
    "def clamp(x, lo, hi):\n"
    "    if lo > hi:\n"
    "        raise ValueError('lo > hi')\n"
    "    return max(lo, min(hi, x))\n"
)

# 隐藏判分（两侧共用，角色在循环里看不到这份清单）
HIDDEN_CASES = [
    ((5, 0, 10), 5, None),
    ((-1, 0, 10), 0, None),
    ((11, 0, 10), 10, None),
    ((0, 0, 10), 0, None),
    ((3, 5, 2), None, ValueError),
]


@dataclass
class Artifacts:
    spec: str = ""
    delivery: str = ""
    defects: list[str] = field(default_factory=list)
    critiques: list[str] = field(default_factory=list)
    released: bool = False


def run_hidden_tests(code: str) -> list[str]:
    ns: dict = {}
    try:
        exec(code, ns, ns)
    except Exception as exc:  # noqa: BLE001 — 原型记录执行失败
        return [f"代码无法执行: {exc}"]
    fn = ns.get("clamp")
    if not callable(fn):
        return ["没有可调用的 clamp"]
    misses: list[str] = []
    for args, expected, err in HIDDEN_CASES:
        try:
            got = fn(*args)
        except Exception as exc:  # noqa: BLE001
            if err is not None and isinstance(exc, err):
                continue
            misses.append(f"clamp{args} 抛出 {type(exc).__name__}: {exc}")
            continue
        if err is not None:
            misses.append(f"clamp{args} 应抛 {err.__name__}，实际返回 {got!r}")
        elif got != expected:
            misses.append(f"clamp{args} 期望 {expected!r}，实际 {got!r}")
    return misses


def product_act(art: Artifacts, log: list[str], cycle: int) -> None:
    """产品：立验收；也可挑工程/质检的刺（合同有漏洞或检查不全）。"""
    if not art.spec:
        art.spec = (
            "验收：\n"
            "1. lo<=x<=hi 时返回 x；x<lo 返回 lo；x>hi 返回 hi。\n"
            "2. lo>hi 时必须抛出 ValueError，不得交换两端后继续计算。\n"
        )
        log.append(f"C{cycle} 产品→合同: 写下含 lo>hi 必须报错的验收")
        return
    if art.delivery and "raise ValueError" not in art.delivery:
        note = "产品挑工程: 交付未落实「lo>hi 报错」，合同第 2 条被丢掉了"
        art.critiques.append(note)
        defect = "未处理 lo>hi：应抛 ValueError"
        if defect not in art.defects:
            art.defects.append(defect)
        log.append(f"C{cycle} {note}")
    if art.released is False and art.delivery and not art.defects:
        # 质检若放过了仍缺第 2 条的实现，产品反过来质询质检
        if "raise ValueError" not in art.delivery:
            note = "产品挑质检: 放行条件未覆盖合同第 2 条"
            art.critiques.append(note)
            log.append(f"C{cycle} {note}")


def engineering_act(art: Artifacts, log: list[str], cycle: int) -> None:
    """工程：按合同交付；也可挑产品合同不可测或自相矛盾。"""
    if art.spec and "抛出 ValueError" not in art.spec and "ValueError" not in art.spec:
        note = "工程挑产品: 合同没写 lo>hi 时的可观测行为，无法实现"
        art.critiques.append(note)
        log.append(f"C{cycle} {note}")
    if not art.delivery:
        art.delivery = BUGGY
        log.append(f"C{cycle} 工程→交付: 首稿使用 max/min（lo>hi 会默默交换）")
        return
    if art.defects:
        art.delivery = FIXED
        cleared = list(art.defects)
        art.defects.clear()
        log.append(f"C{cycle} 工程→返工: 按缺陷修订，已处理 {cleared}")


def quality_act(art: Artifacts, log: list[str], cycle: int) -> None:
    """质检：对照合同核验交付；也可挑产品验收不可执行。"""
    if not art.spec:
        log.append(f"C{cycle} 质检: 还没有合同，等待")
        return
    if "ValueError" not in art.spec and "报错" not in art.spec:
        note = "质检挑产品: 验收第 2 类边界没有可执行断言"
        art.critiques.append(note)
        log.append(f"C{cycle} {note}")
    if not art.delivery:
        log.append(f"C{cycle} 质检: 还没有交付，按合同预写检查（不等放行）")
        return
    issues: list[str] = []
    if "lo > hi" in art.spec or "lo>hi" in art.spec:
        if "ValueError" not in art.delivery and "raise " not in art.delivery:
            issues.append("未处理 lo>hi：应抛 ValueError")
    # 区间端点的常规检查（静态看是否做了夹取）
    if "max(" not in art.delivery or "min(" not in art.delivery:
        if "if " not in art.delivery:
            issues.append("看不出对 x 相对 lo/hi 的夹取")
    if issues:
        for item in issues:
            if item not in art.defects:
                art.defects.append(item)
        note = "质检挑工程: " + "；".join(issues)
        art.critiques.append(note)
        log.append(f"C{cycle} {note} → 缺陷记录，不放行")
        return
    art.released = True
    log.append(f"C{cycle} 质检→放行: 交付覆盖当前合同，事项完成")


def run_loop(max_cycles: int = 4) -> dict:
    art = Artifacts()
    log: list[str] = []
    # 每轮按「产品 → 工程 → 质检」走一圈，对应成果驱动里的依赖方向；
    # 每职能都可以挑另外两方的刺（互检），缺陷则让工程在下一轮返工。
    for cycle in range(1, max_cycles + 1):
        log.append(f"-- 第 {cycle} 圈 --")
        product_act(art, log, cycle)
        engineering_act(art, log, cycle)
        quality_act(art, log, cycle)
        if art.released:
            break
    misses = run_hidden_tests(art.delivery) if art.delivery else ["无交付"]
    return {
        "mode": "sanmumen_loop",
        "cycles": cycle if art.released else max_cycles,
        "released": art.released,
        "spec": art.spec,
        "delivery": art.delivery,
        "defects_open": art.defects,
        "critiques": art.critiques,
        "hidden_misses": misses,
        "pass": art.released and not misses,
        "log": log,
    }


def run_single() -> dict:
    """单引擎：同一任务一次交付，没有部门互检、没有返工圈。"""
    log = [
        "-- 单引擎 --",
        "单引擎→交付: 一次写出 max/min 夹取，未单独处理 lo>hi",
    ]
    delivery = BUGGY
    misses = run_hidden_tests(delivery)
    return {
        "mode": "single_engine",
        "cycles": 1,
        "released": False,
        "spec": "",
        "delivery": delivery,
        "defects_open": [],
        "critiques": [],
        "hidden_misses": misses,
        "pass": not misses,
        "log": log,
    }


def main() -> None:
    loop = run_loop()
    single = run_single()
    out = {
        "task": TASK,
        "engine": "deterministic_stub",
        "note": (
            "未调用真实模型。对照只说明：互检循环能否靠角色交叉检查抓住"
            "单次交付漏掉的 lo>hi 约定。"
        ),
        "loop": loop,
        "single": single,
        "loop_caught_what_single_missed": bool(
            any("lo>hi" in m or "ValueError" in m for m in single["hidden_misses"])
            and not loop["hidden_misses"]
        ),
    }
    text = json.dumps(out, ensure_ascii=False, indent=2)
    print(text)
    dest = Path(__file__).resolve().parent / "run-log.json"
    dest.write_text(text + "\n", encoding="utf-8")
    print("\n======= 循环日志 =======")
    print("\n".join(loop["log"]))
    print("\n======= 单引擎日志 =======")
    print("\n".join(single["log"]))
    print("\n======= 对照 =======")
    print(
        f"循环: {loop['cycles']} 圈, 放行={loop['released']}, "
        f"隐藏用例漏={loop['hidden_misses'] or '无'}"
    )
    print(f"单引擎: 隐藏用例漏={single['hidden_misses'] or '无'}")
    print(
        "循环抓住了单引擎漏掉的问题"
        if out["loop_caught_what_single_missed"]
        else "循环未能比单引擎多抓住问题"
    )


if __name__ == "__main__":
    main()
