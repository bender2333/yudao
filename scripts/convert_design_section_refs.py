"""把代码与测试里按节号引用设计说明的地方改成「文档路径 + 小节标题」（工单 #1411）。

用法：
    uv run python scripts/convert_design_section_refs.py --report .tmp/report.md     # 只报告，不改文件
    uv run python scripts/convert_design_section_refs.py --apply --report .tmp/report.md
    uv run python scripts/convert_design_section_refs.py --apply --cache .tmp/cache.json

只认证据，不按文字相似度挑说明与小节（工单 #1411「换算的规矩」第 1 条与第 8 条）。五类证据：

    ⑤ 人定（LINE_DECISIONS，逐行写依据）
    ① 同一段注释点名（含「模型管理设计说明」这类旧叫法）
    ② 同一段注释里引用的「标题」或条目名全库唯一命中一份说明
    ④ 文件开头人写的归属：开头把某一节写给了哪份说明（自动读出来，依据写进报告）
    ③ 写这行的提交对应的工单（`gh issue view` 的「依据」）点名的说明

定节过一道硬门槛（第 2 条）：写出的标题必须等于那份说明在写这条注释的提交里第 N 节的标题，
改过名的按 `docs/CHANGELOG.md`「旧标题 → 新标题」对到现在。候选多份都能定节时看原句
（第 4 条）：注释里的长词组在哪一份说明的那一节正文里命中，就采用哪一份。③ 的候选还要再过一道
原句核对——「依据」写的那份不一定是真出处（工单 #1411 的架构师评论）。命中不唯一或都没有的，
去掉，不换一个像的。

条目名只在那一节当时确实有列表的第 M 条、且首句不超过 20 字时写（第 5 条）；否则只写小节标题。
指向已删的小节、指不出来、或者候选分不开的，去掉这一部分引用、注释其余部分照旧（第 6 条，
用户已确认的兜底），逐条列进报告的「去掉」一栏。

报告每一行写出第几节、证据来源、命中的原句、提交、当时的标题、现在的标题与结果。

写法（第 7 条）：`docs/design/<文件>.md「小节标题」`；同一段注释已经写明是哪份说明时只写
「小节标题」。不写节号与行号。再跑一次没有改动：改完的地方不再有「第 N 节」，剩下的都是写明了
是别的文档的引用（原型、需求记录、ADR、调研、归档、路线图、规则文件与运行配置）。

评价材料（`evals/scenarios/` 下的 checks、reference 与 materials）不在扫描范围：它们按摘要校验，
改一个字的注释也让那次评测运行作废，改 checks 还要用户事前批准（SKIP_PREFIXES）。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 守卫扫的目录（工单 #1411 验收：harness/、client/src、client/tests、evals/、scripts/、.github/workflows/）
SCOPES = ("harness/", "client/src/", "client/tests/", "evals/", "scripts/", ".github/workflows/")

# 评价材料（场景的 checks、reference 与 materials）按摘要校验：改一个字的注释也让那次评测运行作废，
# 改 checks 还要用户事前批准。工单 #1411 的清单里有两处在这下面，脚本跳过它们（交付说明的
# 「自定的边界」写明）；守卫同样不扫这里。
SKIP_PREFIXES = ("evals/scenarios/",)

# 这两个文件是这条规则的工具：正文里要写出这个写法本身（正则、示例、自检用例），
# 扫它们没有意义。列在这里只是跳过这两个文件，不放过仓库里别的任何文件。
SKIP_FILES = (
    "scripts/convert_design_section_refs.py",
    "harness/tests/test_design_section_refs.py",
    "evals/context/rule-set.json",
)

DESIGN_DIR = "docs/design"

# 设计说明的名字（注释里的写法）→ 文件。长的写在前面，先匹配长的。
DOC_ALIASES: dict[str, str] = {
    "应用层与接口层设计说明": "app-and-interface.md",
    "应用层与接口层设计": "app-and-interface.md",
    "应用层与接口层": "app-and-interface.md",
    "接口与应用层设计说明": "app-and-interface.md",
    "接口与应用层": "app-and-interface.md",
    "接口设计说明": "app-and-interface.md",
    "骨架与应用设计说明": "skeleton-and-application.md",
    "骨架与应用": "skeleton-and-application.md",
    "可信内核设计说明": "trusted-kernel.md",
    "受控内核设计说明": "trusted-kernel.md",
    "受控内核": "trusted-kernel.md",
    "可信内核": "trusted-kernel.md",
    "发布检查设计说明": "trusted-kernel.md",
    "模型管理设计说明": "model-management.md",
    "模型管理": "model-management.md",
    "网络取回与 MCP 工具设计说明": "network-and-mcp.md",
    "网络取回与 MCP 设计说明": "network-and-mcp.md",
    "网络取回与 MCP": "network-and-mcp.md",
    "网络与 MCP 设计说明": "network-and-mcp.md",
    "网络与 MCP": "network-and-mcp.md",
    "浏览器与 computer use 设计说明": "browser-and-computer-use.md",
    "浏览器与 computer use": "browser-and-computer-use.md",
    "浏览器说明": "browser-and-computer-use.md",
    "浏览器设计": "browser-and-computer-use.md",
    "验证的独立性设计说明": "independent-verification.md",
    "验证的独立性": "independent-verification.md",
    "独立性说明": "independent-verification.md",
    "检验的有效性设计说明": "independent-verification.md",
    "检验的有效性": "independent-verification.md",
    "画面与播放设计说明": "visualization.md",
    "画面与播放": "visualization.md",
    "评测场景设计说明": "evaluation-scenarios.md",
    "评测场景设计": "evaluation-scenarios.md",
    "评测场景": "evaluation-scenarios.md",
    "形态与核验角色设计说明": "forms-and-verifier-role.md",
    "形态与核验角色": "forms-and-verifier-role.md",
    "部门指导设计说明": "department-guidance.md",
    "部门指导的处理设计": "department-guidance.md",
    "部门指导": "department-guidance.md",
    "测试分层设计说明": "test-pyramid.md",
    "测试分层设计": "test-pyramid.md",
    "测试分层": "test-pyramid.md",
    "网页界面的提供与发布设计说明": "web-interface-and-release.md",
    "网页界面的提供与发布": "web-interface-and-release.md",
    "网页界面设计说明": "web-interface-and-release.md",
    "桌面客户端的安装、更新与发布设计说明": "web-interface-and-release.md",
    "桌面客户端的安装、更新与发布": "web-interface-and-release.md",
    "桌面客户端的安装与更新设计说明": "web-interface-and-release.md",
    "项目的组织设计说明": "project-organization.md",
    "项目的组织": "project-organization.md",
    "语义系统设计说明": "semantic-system.md",
    "语义系统": "semantic-system.md",
    "接入已有项目设计说明": "existing-project-onboarding.md",
    "接入已有项目": "existing-project-onboarding.md",
    "循环与收敛设计说明": "loops-and-convergence.md",
    "循环与收敛": "loops-and-convergence.md",
    "执行环境服务设计说明": "execution-environment.md",
    "执行环境服务": "execution-environment.md",
    "本地通用工具设计说明": "local-tools.md",
    "本地工具设计说明": "local-tools.md",
    "本地通用工具": "local-tools.md",
    "本地工具": "local-tools.md",
    "项目的起始文件夹设计说明": "project-initial-files.md",
    "项目的起始文件夹": "project-initial-files.md",
    "规则登记与参数设计说明": "rules-and-parameters.md",
    "规则登记与参数": "rules-and-parameters.md",
    "规则登记设计说明": "rules-and-parameters.md",
    "规则登记": "rules-and-parameters.md",
    "部门内多角色设计说明": "department-roles.md",
    "部门内多角色": "department-roles.md",
    "外包角色设计说明": "outsourced-roles.md",
    "外包角色": "outsourced-roles.md",
    "内核的代码质量检查设计说明": "kernel-quality-gate.md",
    "内核的代码质量检查": "kernel-quality-gate.md",
    "恢复契约与故障矩阵设计说明": "recovery-contract-and-fault-matrix.md",
    "恢复契约与故障矩阵": "recovery-contract-and-fault-matrix.md",
    "恢复契约": "recovery-contract-and-fault-matrix.md",
    "上下文装配设计说明": "context-assembly.md",
    "上下文装配": "context-assembly.md",
    "三部门的循环结构": "department-loop.md",
    "循环结构设计说明": "department-loop.md",
    "循环结构": "department-loop.md",
    "总体架构设计说明": "architecture/overall-architecture.md",
    "总体架构": "architecture/overall-architecture.md",
    "总图的词与代码名的对照": "architecture/name-map.md",
}

# 注释里写明了是别的文档、不在本单：紧挨着节号出现这些写法时不当设计说明引用处理。
# 工单 #1411：引用原型、需求记录、ADR、调研、归档文档、路线图、规则文件与运行配置的节号不在本单。
EXCLUDED_TOKENS: tuple[str, ...] = (
    r"原型[^。；，）)第与]{0,40}",
    r"docs/(?!design/)[\w./-]*\.md",
    r"RFC\s*\d+",
    r"(?<![\w.])v\d+(?![\w.])",
    r"[\w-]+\.(?:js|ts|tsx|jsx|html)",
    r"需求记录",
    r"D\d{2}",
    r"ADR[- ]?\d*",
    r"BUILD\.md",
    r"调研",
    r"归档",
    r"可观测性设计",
    r"路线图[^。；\n]{0,80}",
    r"规则文件",
    r"设计说明规范",
    r"运行配置",
    r"总图",
    r"Loop System",
    r"架构 [A-Z]\d",
    r"构建约定",
)

# 同一份文件里，原型的设计说明按节号引用了哪些节：注释里只写「第 N 节」而 N 是其中之一时，
# 指的是原型的设计，不换算（客户端页面文件常见：文件开头「原型 v8 设计说明第 3.3 节」，
# 下面只写「第 3.3 节」）。
PROTO_RE = re.compile(r"(?:原型[^。；\n]{0,60}?|(?<![\w.])v\d+[^。；\n]{0,40}?)第\s*(\d+(?:\.\d+)*)\s*节")

# ⑤ 人定：逐行的决定，每行写依据。行号会变，按「文件 + 那一行的片段」认。
# 元组依次是：文件、行里的片段、只对哪个节号生效（空表示都一样）、说明、改写成的节号
# （空表示按注释里的节号）、依据。
# 进来的两类：同一段没有点名是哪份说明、注释原句全库只命中一份说明的；架构师在工单评论里
# 逐条给出目标的（上一轮审查的「说明选错 8 处」）。
LINE_DECISIONS: tuple[tuple[str, str, str, str, str, str], ...] = (
    (
        "harness/kernel_events.py",
        "模型目录与凭据事件（设计第 10 节）",
        "",
        "app-and-interface.md",
        "",
        "写这行的提交里，注释原句「内容由 Provider 保存」「不含 Key」全库只命中应用层与接口层"
        "第 10 节「决定」第 1 条「模型目录与凭据的写入」（工单 #1411 架构师评论实测）",
    ),
    (
        "harness/providers/responses.py",
        "Responses 的图像输入写法",
        "6.2",
        "browser-and-computer-use.md",
        "6.2",
        "架构师评论：这一处是浏览器与 computer use「请求中的图像」；写这行的提交里那一节是第 6.2 节",
    ),
    (
        "harness/__main__.py",
        "访问方式（设计说明第 6.2 节）",
        "6.2",
        "app-and-interface.md",
        "6.2",
        "架构师评论：这一处是应用层与接口层「访问方式与认证」；写这行的提交里那一节是第 6.2 节",
    ),
    (
        "harness/tests/test_cli_entry.py",
        "模型目录与凭据文件的默认位置（工单 #298，设计说明第 3.4 节）",
        "3.4",
        "web-interface-and-release.md",
        "3.3",
        "架构师评论：这一处是网页界面的提供与发布「数据目录」；写这行的提交里那一节是第 3.3 节",
    ),
    (
        "harness/orchestrator.py",
        "工单 #16，ADR-0018、恢复契约第 5.2 节",
        "5.2",
        "recovery-contract-and-fault-matrix.md",
        "5",
        "架构师评论：与 recovery.py 的两处一致；恢复契约讲恢复的是第 5 节「角色任务的恢复」，没有第 5.2 节",
    ),
    (
        "harness/recovery.py",
        "启动时继续一个未结束的 run（恢复契约第 5.2 节",
        "5.2",
        "recovery-contract-and-fault-matrix.md",
        "5",
        "架构师评论：恢复契约讲恢复的是第 5 节「角色任务的恢复」，没有第 5.2 节",
    ),
    (
        "harness/recovery.py",
        "ADR-0018、恢复契约第 5.2 节",
        "5.2",
        "recovery-contract-and-fault-matrix.md",
        "5",
        "架构师评论：恢复契约讲恢复的是第 5 节「角色任务的恢复」，没有第 5.2 节",
    ),
    (
        "harness/definitions/__init__.py",
        "认证方式（设计说明第 4.3 节）",
        "4.3",
        "model-management.md",
        "",
        "架构师评论：这一处是模型管理第 4.3 节「模型访问定义与准入」",
    ),
    (
        "harness/definitions/__init__.py",
        "默认协议：模型没有单独声明协议时预填（设计说明第 4.1 节）",
        "4.1",
        "model-management.md",
        "",
        "架构师评论：这一处是模型管理第 4.1 节「服务方案预置表与模型能力表」",
    ),
    (
        "harness/definitions/__init__.py",
        "服务方案预置表（设计说明第 4.1 节）",
        "4.1",
        "model-management.md",
        "",
        "架构师评论：这一处是模型管理第 4.1 节「服务方案预置表与模型能力表」",
    ),
    (
        "client/src/renderer/src/views/project/flow-segments.ts",
        "// 返工那条（设计说明 department-loop 第 2 节）。阶段状态机删掉以后（工单 #556）流转种类只剩",
        "2",
        "department-loop.md",
        "",
        "架构师 2026-11-06 判定（工单正文的 33 处表）：部门按关注的成果开始工作",
    ),
    (
        "client/src/renderer/src/views/project/labels.ts",
        "// 逐条结论的三种结果（第 7.1 节第 2 点）：通过、不通过、未核验",
        "7.1",
        "independent-verification.md",
        "",
        "架构师 2026-11-06 判定（工单正文的 33 处表）：口径",
    ),
    (
        "client/src/renderer/src/views/timeline/logic.ts",
        "// 点一个刻度时该用的事项范围（接口设计说明第 4.1 节「按位置读取」，工单 #1217）：",
        "4.1",
        "app-and-interface.md",
        "",
        "架构师 2026-11-06 判定（工单正文的 33 处表）：查询清单",
    ),
    (
        "client/tests/e2e/timeline.spec.ts",
        "// 刻度：那一刻的位置与事项范围是两个参数（接口设计说明第 4.1 节「按位置读取」），页面先把 ?w= 换成",
        "4.1",
        "app-and-interface.md",
        "",
        "架构师 2026-11-06 判定（工单正文的 33 处表）：查询清单",
    ),
    (
        "client/tests/unit/timeline-logic.test.js",
        "// 回放的位置与事项范围是两个参数（接口设计说明第 4.1 节「按位置读取」，工单 #1217）：",
        "4.1",
        "app-and-interface.md",
        "",
        "架构师 2026-11-06 判定（工单正文的 33 处表）：查询清单",
    ),
    (
        "evals/runner/run_yudao_eval.py",
        "# 场景 2 的这个上限从新建事项开始计算，建档的时间不算在里面（第 5.2、9 节）",
        "5.2",
        "evaluation-scenarios.md",
        "",
        "架构师 2026-11-06 判定（工单正文的 33 处表）：指标",
    ),
    (
        "evals/runner/run_yudao_eval.py",
        "# 场景 2 的这个上限从新建事项开始计算，建档的时间不算在里面（第 5.2、9 节）",
        "9",
        "evaluation-scenarios.md",
        "",
        "架构师 2026-11-06 判定（工单正文的 33 处表）：前提与未决事项",
    ),
    (
        "evals/runner/yudao.py",
        "\"\"\"当前场景的材料版本（材料 manifest 的 `material_version`，第 6 节）。\"\"\"",
        "6",
        "evaluation-scenarios.md",
        "",
        "架构师 2026-11-06 判定（工单正文的 33 处表）：报告与版本比较",
    ),
    (
        "evals/runner/yudao.py",
        "\"\"\"当前场景的任务上游仓库地址：导出的事件日志里出现时这次运行作废（第 3 节「联网」）。",
        "3",
        "evaluation-scenarios.md",
        "",
        "架构师 2026-11-06 判定（工单正文的 33 处表）：两边的运行条件",
    ),
    (
        "evals/runner/yudao.py",
        "\"\"\"材料摘要与材料版本记录比较：不同时这次运行作废（第 3 节「隔离」）。",
        "3",
        "evaluation-scenarios.md",
        "",
        "架构师 2026-11-06 判定（工单正文的 33 处表）：两边的运行条件",
    ),
    (
        "evals/tests/test_yudao_runner.py",
        "\"\"\"报告的网络一栏写明以关闭取回的启动参数启动，与运行器的启动命令一致（第 3 节「联网」）。\"\"\"",
        "3",
        "evaluation-scenarios.md",
        "",
        "架构师 2026-11-06 判定（工单正文的 33 处表）：两边的运行条件",
    ),
    (
        "evals/tests/test_yudao_runner.py",
        "\"\"\"建档用了多久不影响事项的超时判断：时间上限从新建事项开始量（第 5.2、9 节）。\"\"\"",
        "5.2",
        "evaluation-scenarios.md",
        "",
        "架构师 2026-11-06 判定（工单正文的 33 处表）：指标",
    ),
    (
        "evals/tests/test_yudao_runner.py",
        "\"\"\"建档用了多久不影响事项的超时判断：时间上限从新建事项开始量（第 5.2、9 节）。\"\"\"",
        "9",
        "evaluation-scenarios.md",
        "",
        "架构师 2026-11-06 判定（工单正文的 33 处表）：前提与未决事项",
    ),
    (
        "evals/tests/test_yudao_runner.py",
        "\"\"\"接入的目录是上游仓库本身：带 `.git`，没有需求原文与隐藏检查（第 3 节「隔离」）。\"\"\"",
        "3",
        "evaluation-scenarios.md",
        "",
        "架构师 2026-11-06 判定（工单正文的 33 处表）：两边的运行条件",
    ),
    (
        "evals/tests/test_yudao_runner.py",
        "\"\"\"接入的目录与数据目录同一条规矩：必须在 Yudao 仓库之外（第 3 节「隔离」）。\"\"\"",
        "3",
        "evaluation-scenarios.md",
        "",
        "架构师 2026-11-06 判定（工单正文的 33 处表）：两边的运行条件",
    ),
    (
        "harness/adjudication.py",
        "# 一次提交所依据的成果版本：最小投影里每一种成果的当前版本（设计说明第 4 节，S1d 工单 #860）。",
        "4",
        "skeleton-and-application.md",
        "",
        "架构师 2026-11-06 判定（工单正文的 33 处表）：最小投影",
    ),
    (
        "harness/app/form_commands.py",
        "# 本项目的改动这一版只接受空：合成与结构校验还没接（设计说明第 4.4、4.5 节），先不接受改动",
        "4.4",
        "project-organization.md",
        "",
        "架构师 2026-11-06 判定（工单正文的 33 处表）：草稿与校验",
    ),
    (
        "harness/app/form_commands.py",
        "# 本项目的改动这一版只接受空：合成与结构校验还没接（设计说明第 4.4、4.5 节），先不接受改动",
        "4.5",
        "project-organization.md",
        "",
        "架构师 2026-11-06 判定（工单正文的 33 处表）：采用与历史",
    ),
    (
        "harness/app/form_queries.py",
        "# 一个项目的组织：这一版只问形态这一节（设计说明第 3 节「接口：查询」的组织那一行，",
        "3",
        "project-organization.md",
        "",
        "架构师 2026-11-06 判定（工单正文的 33 处表）：接口",
    ),
    (
        "harness/app/registry.py",
        "# 事实来源：事件对象的 source 字段（设计说明第 4.3 节），覆盖在楼层的事实上。它依赖楼层查询，",
        "4.3",
        "app-and-interface.md",
        "",
        "架构师 2026-11-06 判定（工单正文的 33 处表）：查询清单",
    ),
    (
        "harness/app/trial_queries.py",
        "#   （设计第 6.2 节：不含图像时截图不进请求）。",
        "6.2",
        "browser-and-computer-use.md",
        "",
        "架构师 2026-11-06 判定（工单正文的 33 处表）：请求中的图像",
    ),
    (
        "harness/app/trial_queries.py",
        "# 步骤结果里的可访问性结构：结果工件里的 accessibility 摘录（浏览器工具的输出，设计第 7.1 节）。",
        "7.1",
        "browser-and-computer-use.md",
        "",
        "架构师 2026-11-06 判定（工单正文的 33 处表）：保存与绑定",
    ),
    (
        "harness/context.py",
        "# 检查工作区因此重建（local-tools 第 2 节）",
        "2",
        "local-tools.md",
        "",
        "架构师 2026-11-06 判定（工单正文的 33 处表）：工作区",
    ),
    (
        "harness/kernel_events.py",
        "# 规则（设计说明第 7 节）：内核写入或读取的事件是骨架事件，种类与字段只增，停用不删除，事件一经写入不重新解释； 其余 run 流里的事件是应用事件，由应用登记自己的种类，增加一种不改这个文件（第 5.4 节第 1 条）。 项目流与目录流的事件全部是骨架事件：它们是长期事实，跨版本保存（ADR-0019）。",
        "7",
        "skeleton-and-application.md",
        "",
        "架构师 2026-11-06 判定（工单正文的 33 处表）：骨架事件与应用事件",
    ),
    (
        "harness/kernel_events.py",
        "# 骨架事件（run 流）：内核写入或读取的种类，只增不删（设计说明第 7 节）。清单由这个类给出， 应用事件的种类在应用里声明（第 5.4 节第 1 条），不在这里",
        "7",
        "skeleton-and-application.md",
        "",
        "架构师 2026-11-06 判定（工单正文的 33 处表）：骨架事件与应用事件",
    ),
    (
        "harness/kernel_events.py",
        "# 第 4 节 2026-10-25 第 1 条：模型步数按「模型请求」事件一条条数，内核的最小投影读它， 所以它从此是骨架事件，只加字段（第 7 节的表把 model_* 列在应用事件里，按这一条据以修正）",
        "4",
        "skeleton-and-application.md",
        "",
        "架构师 2026-11-06 判定（工单正文的 33 处表）：最小投影",
    ),
    (
        "harness/kernel_events.py",
        "# 第 4 节 2026-10-25 第 1 条：模型步数按「模型请求」事件一条条数，内核的最小投影读它， 所以它从此是骨架事件，只加字段（第 7 节的表把 model_* 列在应用事件里，按这一条据以修正）",
        "7",
        "skeleton-and-application.md",
        "",
        "架构师 2026-11-06 判定（工单正文的 33 处表）：骨架事件与应用事件",
    ),
    (
        "harness/kernel_events.py",
        "# 目录流的事件全部是骨架事件：控制主机的长期事实，随部署保存 模型目录与凭据事件（设计第 10 节）：内容由 Provider 保存，事件不含 Key",
        "10",
        "app-and-interface.md",
        "",
        "架构师 2026-11-06 判定（工单正文的 33 处表）：决定（第 1 条「模型目录与凭据的写入」）",
    ),
    (
        "harness/providers/credentials.py",
        "# 一步连接按连接 ID 生成引用，非字母开头时使用 HOST_ 前缀（设计说明第 4.2 节）。",
        "4.2",
        "model-management.md",
        "",
        "架构师 2026-11-06 判定（工单正文的 33 处表）：Provider 配置",
    ),
    (
        "harness/tests/test_direct_routing.py",
        "判断的用例。按分层设计说明第 2 节「一个文件中的测试用到不同层级的资源时，整个文件登记为其中最高的一层」",
        "2",
        "test-pyramid.md",
        "",
        "架构师 2026-11-06 判定（工单正文的 33 处表）：三层的定义",
    ),
    (
        "harness/tests/test_release_waits_for_input.py",
        "# 验收第 1 条（#1079，部门指导设计说明第 2.1 节第 2 点、第 4 节第 9 条）：产品决定改了",
        "2.1",
        "department-guidance.md",
        "",
        "架构师 2026-11-06 判定（工单正文的 33 处表）：放行怎么等",
    ),
    (
        "harness/tests/test_release_waits_for_input.py",
        "# 验收第 1 条（#1079，部门指导设计说明第 2.1 节第 2 点、第 4 节第 9 条）：产品决定改了",
        "4",
        "department-guidance.md",
        "",
        "架构师 2026-11-06 判定（工单正文的 33 处表）：必验反例中「产品决定改了有效合同」",
    ),
    (
        "harness/tests/test_thin_driver_names.py",
        "# 写在测试里的固定名单（对照表第 4 节「四层」一行）：内核清单里没有的其余文件——薄驱动、运行层、执行与装配的",
        "4",
        "architecture/name-map.md",
        "",
        "架构师 2026-11-06 判定（工单正文的 33 处表）：每道缝的守卫",
    ),
    (
        "harness/tools.py",
        "设计说明第 5.6 节「请求时」",
        "5.6",
        "model-management.md",
        "",
        "架构师 2026-11-06 判定：那一版 model-management 的 5.6 是「部门的建议能力」，"
        "「请求时」是这一节里的段落小标题（今天在 model-management.md:328）",
    ),
    (
        "harness/definitions/__init__.py",
        "只保留设计说明第 4.1 节的字段",
        "4.1",
        "model-management.md",
        "",
        "与本文件 :481、:498 同一条：模型管理第 4.1 节「服务方案预置表与模型能力表」",
    ),
    (
        "client/tests/unit/check-methods.test.ts",
        "守第 13 节",
        "13",
        "test-pyramid.md",
        "",
        "守第 13 节的 R1/R2/R3 是测试分层设计说明第 13 节「测试按三环留」的说法；同一句里的「第二环的合同」等词与那一节一一对应",
    ),
    (
        "client/tests/unit/snapshot-view.test.ts",
        "守第 13 节",
        "13",
        "test-pyramid.md",
        "",
        "守第 13 节的 R1/R2/R3 是测试分层设计说明第 13 节「测试按三环留」的说法；同一句里的「第二环的合同」等词与那一节一一对应",
    ),
    (
        "client/tests/unit/translate-coverage.test.ts",
        "守第 13 节",
        "13",
        "test-pyramid.md",
        "",
        "守第 13 节的 R1/R2/R3 是测试分层设计说明第 13 节「测试按三环留」的说法；同一句里的「第二环的合同」等词与那一节一一对应",
    ),
    (
        "client/tests/unit/translate-tables.test.ts",
        "守第 13 节",
        "13",
        "test-pyramid.md",
        "",
        "守第 13 节的 R1/R2/R3 是测试分层设计说明第 13 节「测试按三环留」的说法；同一句里的「第二环的合同」等词与那一节一一对应",
    ),
    (
        "client/tests/unit/view-sync.test.js",
        "守第 13 节",
        "13",
        "test-pyramid.md",
        "",
        "守第 13 节的 R1/R2/R3 是测试分层设计说明第 13 节「测试按三环留」的说法；同一句里的「第二环的合同」等词与那一节一一对应",
    ),
    (
        "evals/tests/test_report.py",
        "守第 13 节",
        "13",
        "test-pyramid.md",
        "",
        "守第 13 节的 R1/R2/R3 是测试分层设计说明第 13 节「测试按三环留」的说法；同一句里的「第二环的合同」等词与那一节一一对应",
    ),
    (
        "harness/tests/kernel/test_contract_surface.py",
        "守第 13 节",
        "13",
        "test-pyramid.md",
        "",
        "守第 13 节的 R1/R2/R3 是测试分层设计说明第 13 节「测试按三环留」的说法；同一句里的「第二环的合同」等词与那一节一一对应",
    ),
    (
        "harness/tests/kernel/test_judge_before_explanation.py",
        "守第 13 节",
        "13",
        "test-pyramid.md",
        "",
        "守第 13 节的 R1/R2/R3 是测试分层设计说明第 13 节「测试按三环留」的说法；同一句里的「第二环的合同」等词与那一节一一对应",
    ),
    (
        "harness/tests/kernel/test_only_grows.py",
        "守第 13 节",
        "13",
        "test-pyramid.md",
        "",
        "守第 13 节的 R1/R2/R3 是测试分层设计说明第 13 节「测试按三环留」的说法；同一句里的「第二环的合同」等词与那一节一一对应",
    ),
    (
        "harness/tests/test_artifact_invalidation.py",
        "守第 13 节",
        "13",
        "test-pyramid.md",
        "",
        "守第 13 节的 R1/R2/R3 是测试分层设计说明第 13 节「测试按三环留」的说法；同一句里的「第二环的合同」等词与那一节一一对应",
    ),
    (
        "harness/tests/test_event_kind_registration.py",
        "守第 13 节",
        "13",
        "test-pyramid.md",
        "",
        "守第 13 节的 R1/R2/R3 是测试分层设计说明第 13 节「测试按三环留」的说法；同一句里的「第二环的合同」等词与那一节一一对应",
    ),
    (
        "harness/tests/test_event_type_fixture.py",
        "守第 13 节",
        "13",
        "test-pyramid.md",
        "",
        "守第 13 节的 R1/R2/R3 是测试分层设计说明第 13 节「测试按三环留」的说法；同一句里的「第二环的合同」等词与那一节一一对应",
    ),
    (
        "harness/tests/kernel/test_skeleton_events.py",
        "第 7 节的表把它列在应用事件里",
        "7",
        "skeleton-and-application.md",
        "",
        "同一段第 4、30 行的「第 7 节」已按骨架与应用「骨架事件与应用事件」换算，这里的说法相同",
    ),
    (
        "harness/tests/kernel/test_skeleton_events.py",
        "按第 4 节更正",
        "4",
        "skeleton-and-application.md",
        "",
        "同一段第 4、30 行的「第 4 节」已按骨架与应用「最小投影」换算，这里的说法相同",
    ),
    (
        "harness/tests/kernel/test_skeleton_events.py",
        "种类与设计说明第 7 节一致",
        "7",
        "skeleton-and-application.md",
        "",
        "同一段第 4、30 行的「第 7 节」已按骨架与应用「骨架事件与应用事件」换算，这里的说法相同",
    ),
    (
        "harness/tests/kernel/test_skeleton_events.py",
        "登记表与设计说明第 7 节一致",
        "7",
        "skeleton-and-application.md",
        "",
        "同一段第 4、30 行的「第 7 节」已按骨架与应用「骨架事件与应用事件」换算，这里的说法相同",
    ),
    (
        "harness/projects.py",
        "并发修改时按版本拒绝后提交的修改（设计说明第 5.2 节）",
        "5.2",
        "model-management.md",
        "",
        "架构师评论：这一处是模型管理第 5.2 节「项目部门设置与项目角色设置」",
    ),
)

# 工单 #1411 的「只改」没有把这几处包含进来（用例名、`routings.json` 的 `why`、
# 用户能看到的文字常量），脚本不动它们，原样保留节号；守卫同样不报。按「文件 + 那一行的片段」记，
# 行号变化以后仍然对得上。原因在工单评论与交付说明的「自定的边界」里。
KEEP_AS_IS: tuple[tuple[str, str], ...] = (
    ("client/tests/unit/model-logic.test.js", "选用的状态按设计说明第 9.5 节的用词"),
    ("harness/definitions/routings.json", "三部门的循环结构第 2 节"),
    ("evals/baseline/compute.py", "program-roadmap.md)第 6.1 节"),
    # 失败信息与报告里的文字（用户能看到的文字常量，不是注释）：只改的清单没有包含它们
    ("evals/runner/yudao_report.py", "判定按 D38 的 N-G1（评测场景设计第 6.3 节）"),
    ("evals/runner/yudao_report.py", "建档与事项是两个 run：下面这些数值不计入上面的指标汇总，也不进均值与噪声（第 5.2 节）"),
    ("harness/tests/kernel/test_only_grows.py", "先把设计说明第 7 节的表与内核事件模块一起改"),
    ("harness/tests/kernel/test_only_grows.py", "如果是有意改，先在设计说明第 3.1 节写明"),
    ("harness/tests/kernel/test_only_grows.py", "如果确实要停用一个原因，先在设计说明第 3.1 节写明"),
    ("harness/tests/kernel/test_only_grows.py", "先在恢复契约第 4 节写明"),
    ("harness/tests/test_thin_driver_names.py", "形态与核验角色设计说明第 4.1 节，工单 #1404"),
    ("harness/tests/test_thin_driver_names.py", "这些种类应当从定义取（骨架与应用设计说明第 6 节）"),
    ("scripts/ci_layers.py", "（测试分层设计说明第 10 节第 5 条）；改名的用例显示为一删一增"),
    ("evals/runner/compare_sides.py", "Yudao 对 OpenCode 的对照（评测场景设计第 6.3 节）"),
    ("evals/runner/run_eval.py", "上下文窗口；模型列表没有报告这个模型时用它（第 3 节「模型的容量」）"),
    ("evals/runner/run_yudao_eval.py", "上下文窗口；模型列表没有报告这个模型时用它（第 3 节「模型的容量」）"),
    ("client/tests/unit/rules-view.test.ts", "origin: \"规则登记第 8 节表格\""),
    ("harness/app/project_and_work_item_commands.py", "建档之前的事项（3.8 第 2 节）"),
    ("harness/app/project_commands.py", "3.8"),
    ("harness/projects.py", "3.8"),
)

# 同一行里点名的既是原型又是设计说明、而节号属于原型那份设计的（不在本单）。
# 这几个文件的注释里把原型的设计说明写成「设计说明第 N 节」，按写的工单核过：工单的依据是原型
# v8/v13 的设计说明。与 client/ 下声明了原型的文件同一个结论，只是没有写在文件开头。
PROTO_AS_IS: tuple[tuple[str, str], ...] = (
    ("client/src/renderer/src/pixel/floor/render.ts", "原型 v10 floor.js 的绘制部分"),
    ("client/src/renderer/src/views/project/floor-screen.tsx", "回放到过去的时间点时不显示决定请求"),
    ("client/src/renderer/src/views/project/floor-screen.tsx", "回到那个位置的概览回放"),
    ("client/tests/e2e/shell.spec.ts", "连接断开时窗口整体变灰"),
)

# 工单 #1411 正文点名的几行：那里的第 12 节是已删去的「从现有代码过去的路径」，
# 这一部分引用去掉，其余照旧（当时 blame 到的那一版小节名叫「模块交互」，不能按改名换算）。
DROP_SECTIONS: tuple[tuple[str, str], ...] = (
    ("harness/decision_flow.py:1", "12"),
    ("harness/tests/test_decision_flow.py:2", "12"),
    ("harness/tests/test_routing_contract.py:1", "12"),
    ("harness/tests/test_routing_definition.py:1", "12"),
    ("harness/tests/test_second_routing.py:1", "12"),
)

# 去掉引用以后读不通的那几句：只把剩下的半个动宾改通顺，别的字不动（每条写明改的是哪里）。
DROP_FIXES: tuple[tuple[str, str, str], ...] = (
    ("harness/mcp_session.py", "#的会话部分", "# 这一节的会话部分"),
    ("harness/tests/test_department_providers.py", "窗口按上调", "窗口上调"),
    ("harness/tests/test_mcp_settings.py", "输出上限按写进保存的设置", "输出上限写进保存的设置"),
    ("harness/snapshot.py", "按从公开树排除", "从公开树排除"),
    ("client/src/renderer/src/contract/connection.ts", "服务按回答 401", "服务回答 401"),
    ("harness/app/payloads.py", "（表，工单 #1181）", "（工单 #1181）"),
    ("harness/projects.py", "（表），", "，"),
    ("harness/coverage.py", "（表）：", "："),
    ("harness/tightening.py", "（表）：", "："),
    ("evals/context/replay.py", "写成要的表", "写成表"),
)


# 已经删去的小节：指向它的那一部分引用去掉，注释的其余部分照旧。
DELETED: set[tuple[str, str]] = {
    ("skeleton-and-application.md", "从现有代码过去的路径"),
    ("skeleton-and-application.md", "从现有代码过去的路径（工单）"),
    ("app-and-interface.md", "Web 控制台的删除"),
    ("app-and-interface.md", "Web 控制台的去留"),
    ("execution-environment.md", "现在的代码"),
    ("evaluation-scenarios.md", "实施顺序"),
    ("test-pyramid.md", "引入顺序"),
}

# CHANGELOG 里没有记、但当时与现在的标题能一一对上的。
EXTRA_RENAMES: dict[str, str] = {
    "第二种路由：骨架要满足的条件": "其他路由：骨架要满足的条件",
    "客户端的同步规则": "页面的同步规则",
}

MULTI_RE = re.compile(r"第\s*(\d+(?:\.\d+)*)((?:\s*[、，和与]\s*\d+(?:\.\d+)*)+)\s*节")
RANGE_RE = re.compile(r"第\s*(\d+(?:\.\d+)*)\s*[至到~～-]\s*(\d+(?:\.\d+)*)\s*节")
ITEM_RE = re.compile(r"第\s*(\d+(?:\.\d+)*)\s*节\s*第\s*(\d+)\s*[项条]")
SECTION_RE = re.compile(r"第\s*(\d+(?:\.\d+)*)\s*节")
HEADING_RE = re.compile(r"^(#{2,6})\s+(\d+(?:\.\d+)*)\.?\s+(.+?)\s*$")
ITEM_LINE_RE = re.compile(r"^\s{0,3}(\d+)[.、)]\s+(.+?)\s*$")
QUOTE_RE = re.compile(r"「([^」]{1,60})」")
DOC_PATH_RE = re.compile(r"docs/design/((?:[\w-]+/)*[\w-]+\.md)")
SLICE_RE = re.compile(r"\s*S\d[a-z]?")

COMMENT_STARTS = ("#", "//", "*", "/*", "*/", "--", '"""', "'''")
NAME_SUFFIX = re.compile(r"(设计说明|设计|文档|说明|design|Design)$")
GAP_OK = re.compile(r"(?:[\s）)、，,（(：:；;的]|设计说明|设计|文档|说明)*")
BLAME_LINE_RE = re.compile(r"^([0-9a-f]{40}) \d+ \d+")
# 比原句时去掉空白与标点：注释与设计说明的排版不同，字是一样的
PUNCT_RE = re.compile(r"[\s，。、；：（）()「」『』“”\"'*`#…·!！?？=+<>《》〔〕【】\-—/\\|]+")


def run(cmd: list[str]) -> str:
    out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if out.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} 失败：{out.stderr[:400]}")
    return out.stdout


# ---------------------------------------------------------------- 设计说明与历史版本


@lru_cache(maxsize=None)
def doc_headings(text: str) -> tuple[tuple[str, str], ...]:
    """解析一份设计说明的编号小节：((编号, 标题), ...)。"""
    return tuple((m.group(2), m.group(3).strip()) for m in map(HEADING_RE.match, text.splitlines()) if m)


@lru_cache(maxsize=None)
def current_doc(doc: str) -> str:
    return (ROOT / DESIGN_DIR / doc).read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def now_headings(doc: str) -> dict[str, str]:
    return dict(doc_headings(current_doc(doc)))


@lru_cache(maxsize=None)
def all_docs() -> tuple[str, ...]:
    return tuple(sorted(set(DOC_ALIASES.values())))


_CACHE: dict[str, str | None] = {}
_CACHE_PATH: Path | None = None


def load_cache(path: str | None) -> None:
    global _CACHE_PATH
    if not path:
        return
    _CACHE_PATH = Path(path)
    if _CACHE_PATH.exists():
        _CACHE.update(json.loads(_CACHE_PATH.read_text(encoding="utf-8")))


def save_cache() -> None:
    if _CACHE_PATH:
        _CACHE_PATH.write_text(json.dumps(_CACHE), encoding="utf-8")


@lru_cache(maxsize=None)
def doc_at(commit: str, doc: str) -> str | None:
    key = f"{commit}:{doc}"
    if key in _CACHE:
        return _CACHE[key]
    try:
        text = run(["git", "show", f"{commit}:{DESIGN_DIR}/{doc}"])
    except RuntimeError:
        text = None
    _CACHE[key] = text
    return text


@lru_cache(maxsize=None)
def blame_commits(path: str) -> tuple[str, ...]:
    """每一行是哪个提交写的。跟改名与搬家（-M -C -C）：工单 #1411「换算的规矩」第 3 条。"""
    key = f"blame-mc:{path}"
    if key in _CACHE:
        return tuple(_CACHE[key])  # type: ignore[arg-type]
    out = run(["git", "blame", "-M", "-C", "--line-porcelain", "--", path])
    commits = tuple(m.group(1) for m in map(BLAME_LINE_RE.match, out.splitlines()) if m)
    _CACHE[key] = list(commits)  # type: ignore[assignment]
    return commits


@lru_cache(maxsize=None)
def file_lines(path: str) -> tuple[str, ...]:
    return tuple((ROOT / path).read_text(encoding="utf-8").splitlines())


@lru_cache(maxsize=None)
def renames() -> dict[str, set[str]]:
    """docs/CHANGELOG.md 里的「旧标题 → 新标题」。"""
    text = (ROOT / "docs/CHANGELOG.md").read_text(encoding="utf-8")
    table: dict[str, set[str]] = defaultdict(set)
    for old, new in re.findall(r"「([^」\n]{1,60})」\s*→\s*「([^」\n]{1,60})」", text):
        old = re.sub(r"^\d+(?:\.\d+)*\s*", "", old).strip()
        new = re.sub(r"^\d+(?:\.\d+)*\s*", "", new).strip()
        table[old].add(new)
    return dict(table)


COMMENT_ONLY = ("#", "//", "*", "/*", "*/", "--")


def header_block(lines: tuple[str, ...]) -> str:
    """文件开头的说明：第一段连续的注释或模块文档字符串（遇到只有注释符号的空行就停）。"""
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    block: list[str] = []
    while i < len(lines) and len(block) <= 80:
        t = lines[i].strip()
        if not t:
            if block:
                break
            i += 1
            continue
        if block and t in COMMENT_ONLY:
            break
        if t.startswith(COMMENT_STARTS) or t.startswith('"') or t.startswith("'"):
            block.append(lines[i])
        else:
            break
        i += 1
    return "\n".join(block)


def block_above(lines: tuple[str, ...], line: int, limit: int = 5) -> str:
    """同一段注释里紧挨在这个引用上面的几行。"""
    out: list[str] = []
    i = line - 2
    while i >= 0 and len(out) < limit:
        t = lines[i].strip()
        if not t:
            break
        if not t.startswith(COMMENT_STARTS) and not t.startswith('"'):
            break
        out.append(lines[i])
        i -= 1
    return "\n".join(reversed(out))


def mentions(text: str) -> list[tuple[int, int, str]]:
    """一段文字里出现的设计说明：(起点, 终点, 文件)，按名字长度从长到短匹配，去掉被包含的。"""
    hits: list[tuple[int, int, str]] = []
    for alias, doc in sorted(DOC_ALIASES.items(), key=lambda kv: -len(kv[0])):
        for m in re.finditer(re.escape(alias), text):
            hits.append((m.start(), m.end(), doc))
    for m in DOC_PATH_RE.finditer(text):
        if m.group(1) in all_docs():
            hits.append((m.start(), m.end(), m.group(1)))
    for m in re.finditer(r"([\w-]+)\.md", text):
        if f"{m.group(1)}.md" in all_docs():
            hits.append((m.start(), m.end(), f"{m.group(1)}.md"))
    for stem, doc in doc_stems().items():
        for m in re.finditer(rf"(?<![\w./-]){re.escape(stem)}(?![\w-])", text):
            hits.append((m.start(), m.end(), doc))
    hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
    kept: list[tuple[int, int, str]] = []
    for h in hits:
        if kept and h[0] < kept[-1][1]:
            continue
        kept.append(h)
    return kept


@lru_cache(maxsize=None)
def doc_stems() -> dict[str, str]:
    """设计说明文件名的词干 → 文件（注释里常只写 `local-tools`、`test-pyramid`）。"""
    out: dict[str, str] = {}
    for doc in all_docs():
        stem = doc.rsplit("/", 1)[-1][:-3]
        out.setdefault(stem, doc)
    return out


def nearest_before(text: str, pos: int, hits: list[tuple[int, int, str]]) -> str | None:
    """紧挨在 pos 前面的那个名字（中间只有标点）：名字写在同一行的写法。"""
    for start, end, doc in reversed(hits):
        if end <= pos and GAP_OK.fullmatch(text[end:pos]):
            return doc
    return None


def bare_name_before(text: str, pos: int, doc: str) -> int | None:
    """紧挨在 pos 前面的是设计说明的**文件名**（`local-tools`、`test-pyramid`）时，给出它的起点。"""
    for start, end, hit_doc in mentions(text):
        if hit_doc == doc and end <= pos and GAP_OK.fullmatch(text[end:pos]) and text[start:end] == Path(doc).stem:
            return start
    return None


def excluded_before(text: str, pos: int) -> str | None:
    """紧挨着节号前面的「原型 v8」「ADR-0007」「docs/requirements/x.md」这类词。"""
    for pat in EXCLUDED_TOKENS:
        for m in re.finditer(pat, text):
            if m.end() <= pos:
                if GAP_OK.fullmatch(text[m.end() : pos]):
                    return m.group(0)
            elif m.start() < pos <= m.end():
                return m.group(0)
    return None


def kept_as_is(path: str, line: str) -> bool:
    """「只改」之外、原样保留节号的那几处。"""
    return any(path == p and snippet in line for p, snippet in KEEP_AS_IS)


# ---------------------------------------------------------------- 换算


@dataclass
class Ref:
    file: str
    line: int
    start: int
    end: int
    sec: str
    secs: tuple[str, ...] = ()
    items: tuple[int, ...] = ()
    doc: str | None = None
    how: str = ""
    title: str | None = None
    status: str = "未定"
    quote: str = ""
    named: bool = False
    bare: bool = False
    commit: str = ""
    old: str = ""
    now: str = ""
    evidence: str = ""
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "换算"

    @property
    def dropped(self) -> bool:
        return self.status == "去掉"


@dataclass
class Group:
    """一段被替换的文字：一个或几个连写的节号。"""

    file: str
    line: int
    start: int
    end: int
    refs: list[Ref] = field(default_factory=list)

    def render(self) -> str | None:
        names = list(dict.fromkeys(r.title for r in self.refs if r.title))
        if not names:
            if any(r.dropped for r in self.refs) or all(r.doc is None for r in self.refs):
                return "" if any(r.dropped for r in self.refs) else None
            return None
        return "、".join(names)


@lru_cache(maxsize=None)
def proto_file(path: str) -> bool:
    """这份文件是照原型的设计做的：客户端文件的**开头**声明了「原型 vN 设计说明第 K 节」。"""
    if not path.startswith("client/"):
        return False
    for m in PROTO_RE.finditer(header_block(file_lines(path))):
        head = m.group(0).rsplit("第", 1)[0]
        if "与设计说明" in head or "及设计说明" in head:
            continue
        return True
    return False


def in_scope(path: str) -> bool:
    if path.startswith(SKIP_PREFIXES) or path in SKIP_FILES:
        return False
    return any(path.startswith(s) for s in SCOPES)


def collect(files: list[str]) -> tuple[list[Group], dict[str, str]]:
    groups: list[Group] = []
    texts: dict[str, str] = {}
    for path in files:
        try:
            text = (ROOT / path).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        texts[path] = text
        for i, line in enumerate(text.splitlines(), start=1):
            taken: list[tuple[int, int]] = []
            for m in MULTI_RE.finditer(line):
                secs = (m.group(1),) + tuple(re.findall(r"\d+(?:\.\d+)*", m.group(2)))
                groups.append(Group(path, i, m.start(), m.end(), [Ref(path, i, m.start(), m.end(), s, secs) for s in secs]))
                taken.append((m.start(), m.end()))
            for m in RANGE_RE.finditer(line):
                if any(a <= m.start() < b for a, b in taken):
                    continue
                secs = expand_range(m.group(1), m.group(2))
                groups.append(Group(path, i, m.start(), m.end(), [Ref(path, i, m.start(), m.end(), s, secs) for s in secs]))
                taken.append((m.start(), m.end()))
            for m in ITEM_RE.finditer(line):
                if any(a <= m.start() < b for a, b in taken):
                    continue
                groups.append(Group(path, i, m.start(), m.end(), [Ref(path, i, m.start(), m.end(), m.group(1), (), (int(m.group(2)),))]))
                taken.append((m.start(), m.end()))
            for m in SECTION_RE.finditer(line):
                if any(a <= m.start() < b for a, b in taken):
                    continue
                groups.append(Group(path, i, m.start(), m.end(), [Ref(path, i, m.start(), m.end(), m.group(1))]))
    return groups, texts


def commit_of(ref: Ref) -> str | None:
    commits = blame_commits(ref.file)
    return commits[ref.line - 1] if ref.line - 1 < len(commits) else None


def expand_range(lo: str, hi: str) -> tuple[str, ...]:
    """「第 3-5 节」「第 7.1 至 7.3 节」展开成逐节的编号；对不上就只留两头。"""
    if "." in lo or "." in hi:
        head_lo, _, last_lo = lo.rpartition(".")
        head_hi, _, last_hi = hi.rpartition(".")
        if head_lo == head_hi and last_lo.isdigit() and last_hi.isdigit() and 0 <= int(last_hi) - int(last_lo) <= 12:
            return tuple(f"{head_lo}.{i}" for i in range(int(last_lo), int(last_hi) + 1))
        return (lo, hi)
    if not (lo.isdigit() and hi.isdigit()) or int(hi) < int(lo) or int(hi) - int(lo) > 12:
        return (lo, hi)
    return tuple(str(i) for i in range(int(lo), int(hi) + 1))


def renamed(doc: str, old: str) -> str | None:
    """旧标题对到现在 main 上的名字。"""
    now = set(now_headings(doc).values())
    if old in now:
        return old
    cands = {t for t in renames().get(old, set()) if t in now}
    if not cands and EXTRA_RENAMES.get(old) in now:
        cands = {EXTRA_RENAMES[old]}
    return cands.pop() if len(cands) == 1 else None


def heading_in(doc_text: str, sec: str) -> str | None:
    """一份说明里第 sec 节的标题。"""
    for num, title in doc_headings(doc_text):
        if num == sec:
            return title
    return None


def section_body(doc_text: str, sec: str) -> str:
    """一份说明里第 sec 节的正文（到下一节为止）。"""
    lines = doc_text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if HEADING_RE.match(line) and HEADING_RE.match(line).group(2) == sec:  # type: ignore[union-attr]
            start = i + 1
            break
    if start is None:
        return ""
    out: list[str] = []
    for line in lines[start:]:
        if HEADING_RE.match(line):
            break
        out.append(line)
    return "\n".join(out)


@lru_cache(maxsize=None)
def bare_title(title: str) -> str:
    """标题去掉整体的「」包裹（标题里的引号不删）。"""
    t = title.strip()
    if len(t) >= 2 and t.startswith("「") and t.endswith("」"):
        return t[1:-1]
    return t


def body_by_title(doc: str, title: str) -> str:
    """一份说明里某一节的正文（到下一节为止）：现在的版本。"""
    lines = current_doc(doc).splitlines()
    for i, line in enumerate(lines):
        m = HEADING_RE.match(line)
        if m and bare_title(m.group(3)) == bare_title(title):
            out = [line]
            for later in lines[i + 1 :]:
                if HEADING_RE.match(later):
                    break
                out.append(later)
            return "\n".join(out)[:8000]
    return ""


def item_texts(doc_text: str, sec: str) -> list[tuple[str, str]]:
    """某节下面的有序列表项：((编号, 名字), ...)。"""
    lines = doc_text.splitlines()
    start = None
    for i, line in enumerate(lines):
        m = HEADING_RE.match(line)
        if m and m.group(2) == sec:
            start = i + 1
            break
    if start is None:
        return []
    items = []
    for line in lines[start:]:
        if HEADING_RE.match(line):
            break
        m = ITEM_LINE_RE.match(line)
        if m:
            items.append((m.group(1), item_name(m.group(2))))
    return items


def item_name(text: str) -> str:
    """一项的名字：去掉加粗与句读，取第一句，不截断。"""
    t = re.sub(r"^\*\*(.+?)\*\*\s*", r"\1", text.strip())
    t = re.split(r"[。：:（(]\s*", t, maxsplit=1)[0]
    return t.strip("* ")


def item_ref(name: str) -> str:
    """一项的名字包在「」里；名字自身带引号的原样写，不再补一对。"""
    if "「" in name or "」" in name:
        return name
    return "「" + name + "」"


def item_at(doc_text: str, sec: str, n: int) -> str:
    items = item_texts(doc_text, sec)
    return items[n - 1][1] if 1 <= n <= len(items) else ""


def quote_key(text: str) -> str:
    """引号写法不同（「」与『』）的同一个名字按同一个键比。"""
    return text.replace("『", "「").replace("』", "」").replace("“", "「").replace("”", "」")


def quote_after(ref: Ref) -> str:
    line = line_text(ref)
    m = QUOTE_RE.search(line, ref.end)
    if not m or m.start() - ref.end > 4:
        return ""
    return m.group(1)


def quote_end(ref: Ref) -> int:
    line = line_text(ref)
    m = QUOTE_RE.search(line, ref.end)
    return m.end() if m and m.start() - ref.end <= 4 else ref.end


def line_text(ref: Ref) -> str:
    return file_lines(ref.file)[ref.line - 1]


def squash(text: str) -> str:
    return PUNCT_RE.sub("", text)


# ---------------------------------------------------------------- 证据


@dataclass
class Candidate:
    """一处引用的一个候选说明：它凭什么被列为候选。"""

    doc: str
    tier: str
    detail: str
    hard: bool = False
    sec: str = ""
    strong: bool = True


@dataclass
class Decision:
    """硬门槛的结论：写出的标题，或者去掉的理由。"""

    ok: bool
    title: str = ""
    old: str = ""
    now: str = ""
    reason: str = ""


@dataclass
class Evidence:
    """工单「依据」里点名的说明：有的带节号，有的带标题。"""

    doc: str
    sections: frozenset[str]
    titles: frozenset[str]
    text: str = ""


_ISSUE_CACHE: dict[str, str] = {}
_ISSUE_PATH: Path | None = None


def load_issue_cache(path: str | None) -> None:
    global _ISSUE_PATH
    if path:
        _ISSUE_PATH = Path(path)
        if _ISSUE_PATH.exists():
            _ISSUE_CACHE.update(json.loads(_ISSUE_PATH.read_text(encoding="utf-8")))


def save_issue_cache() -> None:
    if _ISSUE_PATH:
        _ISSUE_PATH.write_text(json.dumps(_ISSUE_CACHE, ensure_ascii=False), encoding="utf-8")


def issue_body(number: str) -> str:
    if number in _ISSUE_CACHE:
        return _ISSUE_CACHE[number]
    print(f"取工单 #{number}", file=sys.stderr)
    try:
        body = run(["gh", "issue", "view", number, "--json", "body", "-q", ".body"])
    except RuntimeError:
        body = ""
    _ISSUE_CACHE[number] = body
    if len(_ISSUE_CACHE) % 10 == 0:
        save_issue_cache()
    return body


def prefetch_issues(files: list[str]) -> None:
    """把要用的工单一次批量取回来（逐个 gh 调用太慢）。"""
    subjects: dict[str, str] = {}
    for line in run(["git", "log", "--format=%H%x09%s"]).splitlines():
        sha, _, subject = line.partition("\t")
        subjects[sha] = subject
    numbers: list[str] = []
    for path in files:
        try:
            commits = blame_commits(path)
        except RuntimeError:
            continue
        for commit in commits:
            number = issue_number(subjects.get(commit, ""))
            if number and number not in _ISSUE_CACHE and number not in numbers:
                numbers.append(number)
    print(f"要取的工单 {len(numbers)} 个", file=sys.stderr)
    for start in range(0, len(numbers), 40):
        batch = numbers[start : start + 40]
        fields = " ".join(f'i{n}: issue(number: {num}) {{ body }}' for n, num in enumerate(batch))
        query = f'query {{ repository(owner: "bender2333", name: "yudao") {{ {fields} }} }}'
        try:
            out = run(["gh", "api", "graphql", "-f", f"query={query}"])
            data = json.loads(out)["data"]["repository"]
        except (RuntimeError, KeyError, json.JSONDecodeError):
            data = {}
        for n, num in enumerate(batch):
            body = (data.get(f"i{n}") or {}).get("body") or ""
            _ISSUE_CACHE[num] = body
        print(f"  取到 {min(start + 40, len(numbers))}/{len(numbers)}", file=sys.stderr)
    save_issue_cache()


def issue_number(subject: str) -> str | None:
    """提交标题里的工单号：`工单 #1397：…`，或者 `（#1179） (#1323)` 里括号的那一个。"""
    m = re.search(r"工单\s*#(\d+)", subject)
    if m:
        return m.group(1)
    nums = list(re.finditer(r"#(\d+)", subject))
    if len(nums) >= 2:
        return nums[0].group(1)
    return None


def section_numbers(text: str) -> frozenset[str]:
    """一段文字里按节号提到的所有节：连写、范围、第 N 节第 M 项都算。"""
    nums: set[str] = set()
    for m in MULTI_RE.finditer(text):
        nums.add(m.group(1))
        nums.update(re.findall(r"\d+(?:\.\d+)*", m.group(2)))
    for m in RANGE_RE.finditer(text):
        nums.update(expand_range(m.group(1), m.group(2)))
    for m in ITEM_RE.finditer(text):
        nums.add(m.group(1))
    for m in SECTION_RE.finditer(text):
        nums.add(m.group(1))
    return frozenset(nums)


def parse_evidence(text: str) -> tuple[Evidence, ...]:
    """工单「依据」一行里的说明、节号与标题。"""
    if "依据" not in text:
        return ()
    line = text.split("依据", 1)[1]
    hits = [h for h in mentions(line) if h[2] in all_docs()]
    out: list[Evidence] = []
    for i, (start, end, doc) in enumerate(hits):
        nxt = hits[i + 1][0] if i + 1 < len(hits) else len(line)
        span = line[end:nxt]
        sections = section_numbers(span)
        titles = frozenset(m.group(1) for m in QUOTE_RE.finditer(span))
        out.append(Evidence(doc, sections, titles, span.strip()))
    return tuple(out)


@lru_cache(maxsize=None)
def issue_evidence(commit: str) -> tuple[str, tuple[Evidence, ...]]:
    """写这条注释的提交对应的工单号与「依据」里点名的说明。"""
    subject = run(["git", "log", "-1", "--format=%s", commit]).strip()
    number = issue_number(subject)
    if not number:
        return "", ()
    body = issue_body(number)
    if "工单" in body and "依据" not in body:
        # 拿到的是 PR 本身：按 PR 正文里写的工单号再取一次
        m = re.search(r"工单\s*#(\d+)", body)
        if m:
            number = m.group(1)
            body = issue_body(number)
    return number, parse_evidence(body)


@lru_cache(maxsize=None)
def header_attribution(path: str) -> tuple[tuple[str, frozenset[str]], ...]:
    """文件开头的归属：开头把哪些节写给了哪份说明。"""
    header = header_block(file_lines(path))
    hits = [h for h in mentions(header) if h[2] in all_docs()]
    out: list[tuple[str, frozenset[str]]] = []
    for i, (start, end, doc) in enumerate(hits):
        nxt = hits[i + 1][0] if i + 1 < len(hits) else len(header)
        span = header[end:nxt]
        sections = section_numbers(span)
        if (doc, sections) not in out:
            out.append((doc, sections))
    return tuple(out)


@lru_cache(maxsize=None)
def unique_quotes() -> tuple[dict[str, frozenset[str]], dict[str, frozenset[str]]]:
    """全库唯一的标题与条目名：引用「X」时只可能指到一份说明。"""
    by_title: dict[str, set[str]] = defaultdict(set)
    by_item: dict[str, set[str]] = defaultdict(set)
    for doc in all_docs():
        for num, title in now_headings(doc).items():
            by_title[title].add(doc)
            for _n, name in item_texts(current_doc(doc), num):
                if name:
                    by_item[name].add(doc)
    return (
        {t: frozenset(docs) for t, docs in by_title.items() if len(docs) == 1},
        {t: frozenset(docs) for t, docs in by_item.items() if len(docs) == 1},
    )


def candidates_for(ref: Ref) -> list[Candidate]:
    """这一处的五类证据。"""
    out: list[Candidate] = []
    line = line_text(ref)
    for path, snippet, ref_sec, doc, sec, basis in LINE_DECISIONS:
        if path == ref.file and snippet in line and (not ref_sec or ref_sec == ref.sec):
            out.append(Candidate(doc, "⑤", basis, True, sec))
    if out:
        stem = bare_name_before(line, ref.start, out[0].doc)
        if stem is not None:
            ref.bare = True
            ref.start = stem
        return out

    hits = mentions(line)
    named = nearest_before(line, ref.start, hits)
    if named:
        out.append(Candidate(named, "①", "同一行写了这份说明的名字", True))
        stem = bare_name_before(line, ref.start, named)
        if stem is not None:
            ref.bare = True
            ref.start = stem
    else:
        above = block_above(file_lines(ref.file), ref.line)
        if above:
            in_block = {h[2] for h in mentions(above)}
            if len(in_block) == 1:
                out.append(Candidate(in_block.pop(), "①", "同一段注释的上面几行只点名了这一份说明", False))
            else:
                found = nearest_before(above + "\n", len(above), mentions(above))
                if found:
                    out.append(Candidate(found, "①", "同一段注释的上面几行写了这份说明的名字", False))
        docs_in_line = {h[2] for h in hits}
        if len(docs_in_line) == 1:
            out.append(Candidate(docs_in_line.pop(), "①", "同一行后面写了这份说明的名字", True))

    context = line
    by_title, by_item = unique_quotes()
    commit = commit_of(ref)
    hist_cache: dict[str, str | None] = {}
    for m in QUOTE_RE.finditer(context):
        if not (ref.start - 60 <= m.start() <= ref.end + 60):
            continue
        quote = m.group(1)
        for table, what in ((by_title, "小节标题"), (by_item, "条目名")):
            if quote in table:
                doc = next(iter(table[quote]))
                if doc not in hist_cache:
                    hist_cache[doc] = doc_at(commit, doc) if commit else None
                hist = hist_cache[doc]
                strong = False
                if hist is not None:
                    if what == "小节标题":
                        strong = heading_in(hist, ref.sec) == quote
                    else:
                        strong = quote in {name for _n, name in item_texts(hist, ref.sec)}
                out.append(Candidate(doc, "②", f"同一段引用的{what}「{quote}」全库只在{path_name(doc)}里", False, "", strong))
                break

    header = header_attribution(ref.file)
    nearby = {h[2] for h in mentions(line)} | {h[2] for h in mentions(block_above(file_lines(ref.file), ref.line))}
    for doc, sections in header:
        if doc not in nearby:
            continue
        if sections and ref.sec in sections:
            out.append(Candidate(doc, "④", f"文件开头把第 {ref.sec} 节写给了{path_name(doc)}", True))
        elif not sections and len(header) == 1:
            out.append(Candidate(doc, "④", f"文件开头只点名{path_name(doc)}", False))

    commit = commit_of(ref)
    ref.commit = commit or ""
    if commit:
        number, evidence = issue_evidence(commit)
        for ev in evidence:
            quote = ev.text[:60].replace("`", "")
            if ev.sections and ref.sec in ev.sections:
                out.append(Candidate(ev.doc, "③a", f"工单 #{number} 的依据写「{quote}」", False))
            elif not ev.sections:
                out.append(Candidate(ev.doc, "③b", f"工单 #{number} 的依据写「{quote}」", False))

    # 同一份说明取最高的一档
    order = {"⑤": 0, "①": 1, "②": 2, "④": 3, "③a": 4, "③b": 5}
    best: dict[str, Candidate] = {}
    for c in out:
        if c.doc not in best or order[c.tier] < order[best[c.doc].tier]:
            best[c.doc] = c
    return sorted(best.values(), key=lambda c: order[c.tier])


def path_name(doc: str) -> str:
    return f"{DESIGN_DIR}/{doc}"


def gate(ref: Ref, doc: str, override: str = "") -> Decision:
    """硬门槛：写出的标题等于那份说明在写这行的提交里第 N 节的标题，改过名的对到现在。"""
    commit = commit_of(ref)
    ref.commit = commit or ""
    hist = doc_at(commit, doc) if commit else None
    if hist is None:
        return Decision(False, reason=f"写这行的提交里没有{path_name(doc)}")
    sec = override or ref.sec
    items = list(ref.items)
    old = heading_in(hist, sec)
    if old is None:
        return Decision(False, reason=f"当时那份说明没有第 {ref.sec} 节")
    if (doc, old) in DELETED:
        return Decision(False, reason=f"第 {ref.sec} 节是已删去的「{old}」")
    now = renamed(doc, old)
    if now is None:
        return Decision(False, reason=f"旧标题「{old}」对不到现在的小节")
    title = "「" + now + "」"
    if items:
        name = item_at(hist, sec, items[0])
        if name and len(name) <= 20 and name in body_by_title(doc, now):
            title += "中" + item_ref(name)
    return Decision(True, title, old, now)


def body_at(commit: str, doc: str, title: str) -> str:
    """那份说明在那个提交里某一节的正文（到下一节为止）。"""
    text = doc_at(commit, doc)
    if not text:
        return ""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = HEADING_RE.match(line)
        if m and bare_title(m.group(3)) == bare_title(title):
            out = [line]
            for later in lines[i + 1 :]:
                if HEADING_RE.match(later):
                    break
                out.append(later)
            return "\n".join(out)
    return ""


@lru_cache(maxsize=None)
def squashed_body(commit: str, doc: str, title: str) -> str:
    return squash(body_at(commit, doc, title))


def phrase_hit(ref: Ref, doc: str, title: str) -> str:
    """注释里的长词组在那份说明的那一节正文里命中的最长一段（去掉标点比）。"""
    commit = commit_of(ref) or ""
    if not commit or not title:
        return ""
    body = squashed_body(commit, doc, title)
    if not body:
        return ""
    line = line_text(ref)
    cleaned = SECTION_RE.sub("", line)
    for alias in sorted(DOC_ALIASES, key=len, reverse=True):
        if alias in cleaned:
            cleaned = cleaned.replace(alias, "")
    best = ""
    for run in re.split(r"[，。；：、（）()「」『』,.;:]+", cleaned):
        text = squash(run)
        for width in (24, 20, 16, 12, 10, 8, 6):
            if width > len(text):
                continue
            for i in range(0, len(text) - width + 1):
                piece = text[i : i + width]
                if piece in body and len(piece) > len(best):
                    best = piece
            if len(best) >= width:
                break
    return best


def decide(ref: Ref, proto: bool = False) -> None:
    """按五类证据与硬门槛定这一处。原型文件里的引用，只有写明了是哪份说明的才换算。"""
    cands = candidates_for(ref)
    if proto and not any(c.tier in ("⑤", "①", "②", "④") for c in cands):
        ref.status, ref.how, ref.reason = "排除", "排除", "原型"
        return
    reasons: list[str] = []
    strong_tiers = ("⑤", "①", "②", "④", "③a")
    for tier in strong_tiers:
        group = [c for c in cands if c.tier == tier and (tier != "②" or c.strong)]
        if not group:
            continue
        passed: list[tuple[Candidate, Decision]] = []
        for c in group:
            d = gate(ref, c.doc, c.sec)
            if d.ok:
                passed.append((c, d))
            else:
                reasons.append(d.reason)
        hard = [c for c in group if c.hard]
        if not passed:
            if hard:
                ref.status = "去掉"
                ref.doc = hard[0].doc
                ref.evidence = f"{tier} {hard[0].detail}"
                ref.reason = reasons[-1] if reasons else "对不上"
                return
            continue
        if len(passed) == 1:
            accept(ref, *passed[0], "")
            return
        chosen = pick_by_phrase(ref, passed)
        if chosen is not None:
            accept(ref, *chosen)
            return
        ref.evidence = f"{tier} " + "、".join(c.detail for c, _d in passed)
        ref.reason = "候选多份都能定节，原句没有唯一命中"
        ref.status = "去掉"
        return

    # 弱的证据（同一段引用的标题不是这一节的、工单依据只点了名的）放在一起：原句必须在其中一份里唯一命中
    weak = [c for c in cands if c.tier == "③b" or (c.tier == "②" and not c.strong)]
    weak_passed = [(c, gate(ref, c.doc, c.sec)) for c in weak]
    weak_passed = [x for x in weak_passed if x[1].ok]
    if weak_passed:
        chosen = pick_by_phrase(ref, weak_passed)
        if chosen is not None:
            accept(ref, *chosen)
            return
        ref.evidence = "、".join(c.detail for c, _d in weak_passed)
        ref.reason = "候选多份都能定节，原句没有唯一命中" if len(weak_passed) > 1 else "唯一候选的说明与原句对不上"
        ref.status = "去掉"
        return
    ref.status = "去掉"
    ref.reason = reasons[-1] if reasons else "五类证据都没有"
    ref.evidence = cands[0].tier + " " + cands[0].detail if cands else ""


def pick_by_phrase(ref: Ref, passed: list[tuple[Candidate, Decision]]) -> tuple[Candidate, Decision, str] | None:
    """候选多份：看注释原句在哪一份说明的那一节正文里命中；唯一命中才采用。"""
    hits = [(c, d, phrase_hit(ref, c.doc, d.old)) for c, d in passed]
    found = [x for x in hits if x[2]]
    return found[0] if len(found) == 1 else None


G1_FAILED: list[str] = []


def accept(ref: Ref, cand: Candidate, decision: Decision, phrase: str) -> None:
    # G1：选中的说明今天的正文里必须有这一节，写出的标题等于今天的标题
    if decision.now and decision.now not in set(now_headings(cand.doc).values()):
        G1_FAILED.append(f"{ref.file}:{ref.line} {cand.doc}「{decision.now}」")
        ref.status = "去掉"
        ref.reason = f"G1：{cand.doc} 今天没有「{decision.now}」这一节"
        ref.evidence = cand.tier + " " + cand.detail
        return
    ref.doc = cand.doc
    if cand.sec:
        ref.sec = cand.sec
    ref.how = cand.tier
    ref.evidence = cand.detail
    ref.quote = phrase
    ref.old = decision.old
    ref.now = decision.now
    ref.title = settle_quote(ref, decision)
    ref.status = "换算"


def item_names_by_title(doc: str, title: str) -> set[str]:
    """一份说明里标题为 title 的那一节的有序列表项名。"""
    for num, name in now_headings(doc).items():
        if name == title:
            return {item for _n, item in item_texts(current_doc(doc), num)}
    return set()


def settle_quote(ref: Ref, decision: Decision) -> str:
    """引用后面紧跟的「…」：与标题一致时并进来；是那一节有序列表里的一条时写成「标题」中「条目名」。"""
    title = decision.title
    quote = quote_after(ref)
    if not quote:
        return title
    if "中「" in title:
        return title
    if quote_key(quote) == quote_key(decision.now) or quote in decision.now:
        ref.end = max(ref.end, quote_end(ref))
        return title
    if len(quote) <= 20 and quote in item_names_by_title(ref.doc or "", decision.now):
        ref.end = max(ref.end, quote_end(ref))
        return "「" + decision.now + "」中「" + quote + "」"
    return title


def resolve(groups: list[Group], texts: dict[str, str]) -> None:
    refs = [r for g in groups for r in g.refs]
    print(f"处数 {len(refs)}，开始定说明与定节", file=sys.stderr)
    for n, ref in enumerate(refs, start=1):
        if n % 250 == 0:
            print(f"  ... {n}/{len(refs)}", file=sys.stderr)
        line = line_text(ref)
        if (f"{ref.file}:{ref.line}", ref.sec) in DROP_SECTIONS:
            ref.status, ref.how = "去掉", "去掉"
            ref.reason = "工单点名的已删小节"
            continue
        if ref.doc is None:
            named_here = {h[2] for h in mentions(line)}
            if len(named_here) == 1:
                ref.doc = named_here.pop()
        if kept_as_is(ref.file, line):
            ref.status, ref.how = "排除", "排除"
            ref.reason = "只改之外"
            continue
        if any(ref.file == p and snippet in line for p, snippet in PROTO_AS_IS):
            ref.status, ref.how = "排除", "排除"
            ref.reason = "原型"
            continue
        if excluded_before(line, ref.start):
            ref.status, ref.how = "排除", "排除"
            ref.reason = "别的文档"
            continue
        decide(ref, proto_file(ref.file))


# ---------------------------------------------------------------- 写回


def collapse_duplicates(line: str) -> str:
    """同一行里同一个标题写了两次（两个节号落到同一节）时只留一处。"""
    pattern = re.compile(r"(「[^」]{1,60}」)(?:、)?\1")
    for _ in range(3):
        new = pattern.sub(r"\1", line)
        if new == line:
            break
        line = new
    return line


def apply_groups(groups: list[Group], texts: dict[str, str]) -> tuple[list[str], int]:
    changed_files: list[str] = []
    changed_refs = 0
    by_file: dict[str, list[Group]] = defaultdict(list)
    for g in groups:
        by_file[g.file].append(g)
    for path, gs in sorted(by_file.items()):
        text = texts[path]
        lines = text.splitlines(keepends=True)
        by_line: dict[int, list[Group]] = defaultdict(list)
        for g in gs:
            by_line[g.line].append(g)
        touched = 0
        for lineno, line_groups in by_line.items():
            line = lines[lineno - 1]
            original = line
            for g in sorted(line_groups, key=lambda x: x.start, reverse=True):
                new = g.render()
                if new is None:
                    continue
                doc = next((r.doc for r in g.refs if r.doc), None)
                # 每一处引用都写 docs/design/<文件>.md（工单「换算的规矩」第 7 条，2026-11-06 改）
                named = False
                start, end = min([g.start] + [r.start for r in g.refs]), max([g.end] + [r.end for r in g.refs])
                if any(r.dropped for r in g.refs):
                    slice_match = SLICE_RE.match(line, end)
                    if slice_match:
                        end = slice_match.end()
                    following = QUOTE_RE.search(line, end)
                    if following and following.start() - end <= 4:
                        end = following.end()
                if new == "":
                    # 去掉这一部分引用时，「设计说明」这几个字一起去掉，不留「（设计说明）」这种空引用
                    before = line[:start].rstrip(" \t")
                    suffix = NAME_SUFFIX.search(before)
                    if suffix:
                        start = suffix.start()
                    elif before.endswith("的"):
                        start = len(before) - 1
                    if end < len(line) and line[end] == "的":
                        before_char = line[start - 1] if start > 0 else ""
                        if before_char and ("\u4e00" <= before_char <= "\u9fff" or before_char in "（(#*/"):
                            end += 1
                    _, start, end = drop_span(line, start, end)
                    line = (line[:start] + line[end:]).replace("（：", "（").replace("(: ", "(")
                else:
                    trimmed = line[:start].rstrip(" \t")
                    if trimmed.endswith(".md") and trimmed != line[:start]:
                        start = len(trimmed)
                    if not named:
                        if doc:
                            new = f"{DESIGN_DIR}/{doc}" + new
                            before = line[:start].rstrip(" \t")
                            suffix = NAME_SUFFIX.search(before)
                            if suffix:
                                start = suffix.start()
                            elif before.endswith("的"):
                                start = len(before) - 1
                            if start > 0 and (
                                re.match(r"[\w\u4e00-\u9fff]", line[start - 1]) or line[start - 1] in "#/"
                            ):
                                new = " " + new
                    line = line[:start] + new + line[end:]
                touched += 1
            for path_name, old, new in DROP_FIXES:
                if path_name == path and old in line:
                    line = line.replace(old, new)
            lines[lineno - 1] = collapse_duplicates(line)
        new_text = "".join(lines)
        if new_text != text:
            (ROOT / path).write_text(new_text, encoding="utf-8")
            changed_files.append(path)
            changed_refs += touched
    return changed_files, changed_refs


def drop_span(line: str, start: int, end: int) -> tuple[str, int, int]:
    """删掉一处引用以后，连带去掉空掉的括注与多余的标点。"""
    left, right = line[:start], line[end:]
    openers = {"（": "）", "(": ")"}
    if left and left[-1] in openers and right.startswith(openers[left[-1]]):
        start -= 1
        end += 1
        left, right = line[:start], line[end:]
    if left.endswith(("、", "，", ",", "；", ";")) and right.startswith(("、", "，", ",", "）", ")", "；", ";", "。")):
        start -= 1
    elif right.startswith(("、", "，", ",", "；", ";")):
        end += 1
    while start > 0 and line[start - 1] in " \t":
        start -= 1
    return line, start, end


# ---------------------------------------------------------------- 报告与主流程


def write_report(path: str, refs: list[Ref]) -> None:
    ok = [r for r in refs if r.ok]
    dropped = [r for r in refs if r.dropped]
    excluded = [r for r in refs if r.status == "排除"]
    fixed = [r for r in ok if r.how == "⑤"]
    rows = [
        "# 换算报告（工单 #1411）",
        "",
        f"处数 {len(refs)}，换算 {len(ok)}（其中人定 {len(fixed)}），去掉 {len(dropped)}，"
        f"排除（别的文档、原型、只改之外）{len(excluded)}，"
        f"未定 {len(refs) - len(ok) - len(dropped) - len(excluded)}",
        "",
        "证据一栏的五档：⑤ 人定；① 同一段注释点名；② 同一段引用的标题或条目名全库唯一；"
        "④ 文件开头人写的归属；③ 写这行的提交的工单「依据」点名的说明。",
        "",
        "## 每一处",
        "",
        "| 文件:行 | 第几节 | 选中的说明 | 证据 | 命中的原句 | 提交 | 当时的标题 | 现在的标题 | 结果 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in sorted(refs, key=lambda x: (x.file, x.line, x.start)):
        if r.status == "排除":
            continue
        rows.append(
            "| `{}:{}` | {} | {} | {} | {} | {} | {} | {} | {} |".format(
                r.file,
                r.line,
                r.sec,
                r.doc or "",
                (r.how + " " + r.evidence).replace("|", "/") if r.evidence else r.how,
                r.quote or "",
                r.commit[:8],
                r.old,
                r.now,
                r.status,
            )
        )
    rows += ["", "## 去掉", "", "| 文件:行 | 第几节 | 原因 |", "| --- | --- | --- |"]
    for r in sorted(dropped, key=lambda x: (x.file, x.line, x.start)):
        rows.append(f"| `{r.file}:{r.line}` | {r.sec} | {r.reason or '指不出来'} |")
    rows += ["", "## 人定", "", "| 文件:行 | 第几节 | 依据 | 现在的标题 |", "| --- | --- | --- | --- |"]
    for r in sorted(fixed, key=lambda x: (x.file, x.line, x.start)):
        rows.append(f"| `{r.file}:{r.line}` | {r.sec} | {r.evidence} | {r.now} |")
    rows += ["", "## 排除", "", "| 文件:行 | 选中的说明 | 原因 |", "| --- | --- | --- |"]
    for r in sorted(excluded, key=lambda x: (x.file, x.line, x.start)):
        rows.append(f"| `{r.file}:{r.line}` | {r.doc or ''} | {r.reason} |")
    Path(path).write_text("\n".join(rows) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", help="把换算结果写到这个 Markdown，不改文件")
    ap.add_argument("--apply", action="store_true", help="改文件")
    ap.add_argument("--only", help="只处理这些文件（逗号分隔）")
    ap.add_argument("--cache", help="历史版本设计说明的缓存（只在开发脚本时用）")
    ap.add_argument("--issue-cache", help="工单「依据」的缓存（默认与 --cache 放在一起）")
    ap.add_argument("--prefetch", action="store_true", help="只把要用的工单取回来，不换算")
    args = ap.parse_args(argv)

    load_cache(args.cache)
    issue_cache = args.issue_cache or (str(Path(args.cache).with_suffix(".issues.json")) if args.cache else None)
    load_issue_cache(issue_cache)
    files = [f for f in run(["git", "ls-files"]).splitlines() if f and in_scope(f)]
    if args.only:
        keep = set(args.only.split(","))
        files = [f for f in files if f in keep]
    if args.prefetch:
        prefetch_issues(files)
        save_cache()
        return 0
    groups, texts = collect(files)
    resolve(groups, texts)

    refs = [r for g in groups for r in g.refs]
    if args.report:
        write_report(args.report, refs)

    if args.apply:
        changed_files, changed_refs = apply_groups(groups, texts)
        print(f"改了 {len(changed_files)} 个文件、{changed_refs} 处")

    ok = sum(1 for r in refs if r.ok)
    dropped = sum(1 for r in refs if r.dropped)
    excluded = sum(1 for r in refs if r.status == "排除")
    fixed = sum(1 for r in refs if r.ok and r.how == "⑤")
    print(f"处数 {len(refs)}，换算 {ok}（其中人定 {fixed}），去掉 {dropped}，排除 {excluded}，未定 {len(refs) - ok - dropped - excluded}，G1 失败 {len(G1_FAILED)}")
    save_cache()
    save_issue_cache()
    return 0


if __name__ == "__main__":
    sys.exit(main())

