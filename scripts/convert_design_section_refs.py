"""把代码与测试里按节号引用设计说明的地方改成「文档路径 + 小节标题」（工单 #1411）。

用法：
    uv run python scripts/convert_design_section_refs.py --report .tmp/report.tsv   # 只报告，不改文件
    uv run python scripts/convert_design_section_refs.py --apply                    # 改文件
    uv run python scripts/convert_design_section_refs.py --apply --cache .tmp/cache.json

换算办法见工单 #1411 正文的四步：

1. 定是哪份设计说明。注释里写了名字的按名字（旧叫法见 DOC_ALIASES），写了 `docs/design/`
   路径的按路径；只写「设计说明」或「第 N 节」的，按同一行、同一段注释、文件开头的说明推，
   再按同文件已经定下来的设计说明、同一节号在别的说明里是否存在来核对。
2. 定是哪一节。`git blame` 找到写这条注释的提交，读那个提交里的那份设计说明，第 N 节当时的
   标题就是要写的标题，再对到现在 main 上的名字（改过名的按 `docs/CHANGELOG.md` 的「旧标题 → 新标题」）。
   「第 N 节第 M 项」这类按序号指一项的，写成小节标题加那一项的名字。
3. 指向已经删去的小节的（DELETED 里逐条写明），去掉这一部分引用，注释的其余部分照旧。
4. 写法：`docs/design/<文件>.md「小节标题」`；同一段注释已经写明是哪份设计说明时只写「小节标题」。
   不写节号与行号。

再跑一次没有改动：改完的地方不再有「第 N 节」，剩下的都是写明了是别的文档的引用（原型、
需求记录、ADR、调研、归档、路线图、规则文件与运行配置），脚本跳过这些。

评价材料（`evals/scenarios/` 下的 checks、reference 与 materials）不在扫描范围：它们按摘要
校验，改一个字的注释也让那次评测运行作废，改 checks 还要用户事前批准（SKIP_PREFIXES）。

推不出是哪份设计说明、需要人定的，写进 MAPPING（按文件或「文件:行」）；这些条目在交付说明的
「自定的边界」里逐条说明。
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from collections import Counter, defaultdict
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
    # 别的目录下的文档（需求记录、路线图、ADR、调研、运行配置）：写明了路径的不是设计说明
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

# 对照表：名字、同一行、同一段注释、文件开头都推不出来的，按文件（或「文件:行」）指到设计说明。
MAPPING: dict[str, str] = {
    "harness/api/app.py": "app-and-interface.md",
    "harness/app/application.py": "app-and-interface.md",
    "harness/app/project_commands.py": "app-and-interface.md",
    "harness/app/read_models.py": "app-and-interface.md",
    "harness/app/project_queries.py:1566": "model-management.md",
    "harness/providers/responses.py": "model-management.md",
    "harness/tests/test_responses.py": "model-management.md",
    "evals/": "evaluation-scenarios.md",
    "harness/definitions/rules.json:220": "department-roles.md",
    "harness/definitions/rules.json:572": "department-roles.md",
    ".github/workflows/ci.yml": "browser-and-computer-use.md",
    "harness/submissions.py": "skeleton-and-application.md",
    "harness/tightening.py": "skeleton-and-application.md",
    "client/src/renderer/src/pixel/registry.ts": "visualization.md",
    # 画布与翻译层的文件只讲画面这一份说明（个别页面文件仍按名字与文字定）
    "client/src/renderer/src/pixel/": "visualization.md",
    "client/src/renderer/src/translate/": "visualization.md",
    "client/src/renderer/src/shell/": "web-interface-and-release.md",
    # 守三环的用例：这一处指测试分层「测试按三环留」
    "client/tests/unit/check-methods.test.ts:6": "test-pyramid.md",
    "client/tests/unit/snapshot-view.test.ts:55": "test-pyramid.md",
    "client/tests/unit/translate-coverage.test.ts:6": "test-pyramid.md",
}

# 按文件的对照表：这些模块的注释里只写「设计说明第 N 节」，没点名是哪一份。逐条读模块的职责定的：
# 一个文件的注释都在讲同一份说明时写文件，讲几份的写「文件:行」。
FILE_MAPPING: dict[str, str] = {
    "harness/__main__.py": "web-interface-and-release.md",
    "harness/api/server.py": "web-interface-and-release.md",
    "harness/app/catalog_queries.py": "app-and-interface.md",
    "harness/app/contracts.py": "app-and-interface.md",
    "harness/app/decision_queries.py": "app-and-interface.md",
    "harness/app/form_commands.py": "app-and-interface.md",
    "harness/app/home.py": "app-and-interface.md",
    "harness/app/parameter_commands.py": "app-and-interface.md",
    "harness/app/project_and_work_item_commands.py": "app-and-interface.md",
    "harness/app/registry.py": "app-and-interface.md",
    "harness/app/replay.py": "app-and-interface.md",
    "harness/app/system_queries.py": "app-and-interface.md",
    "harness/browser.py": "browser-and-computer-use.md",
    "harness/context.py": "context-assembly.md",
    "harness/decisions.py": "existing-project-onboarding.md",
    "harness/decision_flow.py": "existing-project-onboarding.md",
    "harness/environment.py": "execution-environment.md",
    "harness/engine.py": "model-management.md",
    "harness/kernel_events.py": "trusted-kernel.md",
    "harness/loops.py": "loops-and-convergence.md",
    "harness/mcp_client.py": "network-and-mcp.md",
    "harness/parameters.py": "rules-and-parameters.md",
    "harness/projection.py": "skeleton-and-application.md",
    "harness/projects.py": "existing-project-onboarding.md",
    "harness/providers/facade.py": "model-management.md",
    "harness/providers/reasoning.py": "model-management.md",
    "harness/providers/selection.py": "model-management.md",
    "harness/providers/suggested.py": "model-management.md",
    "harness/recording.py": "model-management.md",
    "harness/recovery.py": "recovery-contract-and-fault-matrix.md",
    "harness/runtime.py": "app-and-interface.md",
    "harness/snapshot.py": "existing-project-onboarding.md",
    "harness/tightening.py": "independent-verification.md",
    "harness/trial_sessions.py": "browser-and-computer-use.md",
    "harness/tests/layers.toml": "test-pyramid.md",
    "harness/tests/process_kill.py": "existing-project-onboarding.md",
    "harness/tests/test_cli_entry.py": "web-interface-and-release.md",
    "harness/tests/test_data_directory.py": "web-interface-and-release.md",
    "harness/tests/test_event_kind_registration.py": "test-pyramid.md",
    "harness/tests/test_event_sources.py": "app-and-interface.md",
    "harness/tests/test_event_type_fixture.py": "test-pyramid.md",
    "harness/tests/test_interaction_engine.py": "model-management.md",
    "harness/tests/test_issue_89.py": "model-management.md",
    "harness/tests/test_issue_90.py": "model-management.md",
    "harness/tests/test_mcp_lifecycle.py": "network-and-mcp.md",
    "harness/tests/test_message_protocol_contract.py": "model-management.md",
    "harness/tests/test_onboarding_renamed.py": "test-pyramid.md",
    "harness/tests/test_project_loop_organization.py": "department-loop.md",
    "harness/tests/test_project_queries.py": "app-and-interface.md",
    "harness/tests/test_release_waits_for_input.py": "department-guidance.md",
    "harness/tests/test_routing_ask.py": "skeleton-and-application.md",
    "harness/tests/test_routing_per_form.py": "test-pyramid.md",
    "harness/tests/test_startup_reload.py": "web-interface-and-release.md",
    "harness/tests/test_tool_contracts.py": "network-and-mcp.md",
    "harness/tests/test_tools_registry.py": "network-and-mcp.md",
    "harness/tests/test_trial_sessions.py": "execution-environment.md",
    "harness/tests/kernel/test_judge_before_explanation.py:16": "test-pyramid.md",
    "harness/tests/kernel/test_only_grows.py:14": "test-pyramid.md",
    "harness/tests/kernel/test_skeleton_events.py:8": "test-pyramid.md",
    "harness/tests/kernel/test_only_grows.py": "trusted-kernel.md",
    "harness/tests/kernel/test_skeleton_events.py": "trusted-kernel.md",
    "harness/watched_outputs.py": "skeleton-and-application.md",
    "harness/assembly.py": "model-management.md",
    "harness/submissions.py": "skeleton-and-application.md",
    "harness/direct.py": "forms-and-verifier-role.md",
    "harness/definitions/__init__.py": "rules-and-parameters.md",
    "client/src/renderer/src/contract/command-id.ts": "app-and-interface.md",
    "client/src/renderer/src/views/project/floor-screen.tsx": "visualization.md",
    "client/src/renderer/src/views/project/floor-text.ts": "loops-and-convergence.md",
    "client/src/renderer/src/views/project/read-existing.tsx": "existing-project-onboarding.md",
    "client/src/renderer/src/translate/face.ts": "existing-project-onboarding.md",
    "client/tests/e2e/backend.py": "app-and-interface.md",
    "client/tests/e2e/department-settings.spec.ts": "model-management.md",
    "client/tests/e2e/home.spec.ts": "app-and-interface.md",
    "client/tests/e2e/project.spec.ts": "model-management.md",
    "client/tests/e2e/shell.spec.ts": "web-interface-and-release.md",
    "client/tests/unit/translate-tables.test.ts": "test-pyramid.md",
    "client/tests/unit/view-sync.test.js": "test-pyramid.md",
    "evals/tests/test_report.py": "test-pyramid.md",
    "evals/runner/yudao.py:488": "existing-project-onboarding.md",
    "evals/runner/yudao.py:531": "existing-project-onboarding.md",
    # 讲几份说明的文件：逐行定
    "harness/orchestrator.py:528": "existing-project-onboarding.md",
    "harness/orchestrator.py:652": "skeleton-and-application.md",
    "harness/orchestrator.py:957": "loops-and-convergence.md",
    "harness/orchestrator.py:1758": "skeleton-and-application.md",
    "harness/app/project_queries.py:86": "existing-project-onboarding.md",
    "harness/app/project_queries.py:547": "existing-project-onboarding.md",
    "harness/app/project_queries.py:620": "existing-project-onboarding.md",
    "harness/app/project_queries.py:725": "department-loop.md",
    "harness/app/project_queries.py:1120": "model-management.md",
    "harness/app/project_queries.py:1200": "model-management.md",
    "harness/app/project_queries.py:2275": "existing-project-onboarding.md",
    "harness/app/project_queries.py:2286": "existing-project-onboarding.md",
    "harness/app/project_queries.py:2337": "existing-project-onboarding.md",
    "harness/app/project_queries.py:2416": "existing-project-onboarding.md",
    "harness/app/project_queries.py:2448": "existing-project-onboarding.md",
    "harness/app/project_queries.py:2878": "model-management.md",
    "harness/app/payloads.py:916": "independent-verification.md",
    "harness/app/payloads.py:1834": "rules-and-parameters.md",
    "harness/app/catalog_queries.py:220": "app-and-interface.md",
    "harness/definitions/__init__.py:319": "model-management.md",
    "harness/decision_flow.py:178": "skeleton-and-application.md",
    "harness/recovery.py:407": "browser-and-computer-use.md",
    "harness/tightening.py:632": "existing-project-onboarding.md",
    "harness/tightening.py:1433": "execution-environment.md",
    "harness/tests/kernel/test_only_grows.py:132": "trusted-kernel.md",
    "harness/tests/kernel/test_only_grows.py:165": "trusted-kernel.md",
}

# 逐行定的那些（讲几份说明的文件）：这一行指的是哪一份
LINE_MAPPING: dict[str, str] = {
    "harness/__main__.py:44": "web-interface-and-release.md",
    "harness/__main__.py:121": "web-interface-and-release.md",
    "harness/app/catalog_queries.py:220": "app-and-interface.md",
    "harness/app/catalog_queries.py:383": "app-and-interface.md",
    "harness/app/form_commands.py:7": "project-organization.md",
    "harness/context.py:339": "existing-project-onboarding.md",
    "harness/context.py:438": "existing-project-onboarding.md",
    "harness/context.py:666": "existing-project-onboarding.md",
    "harness/decision_flow.py:178": "existing-project-onboarding.md",
    "harness/definitions/__init__.py:202": "model-management.md",
    "harness/definitions/__init__.py:319": "browser-and-computer-use.md",
    "harness/definitions/__init__.py:397": "skeleton-and-application.md",
    "harness/definitions/__init__.py:467": "skeleton-and-application.md",
    "harness/definitions/__init__.py:592": "skeleton-and-application.md",
    "harness/definitions/__init__.py:713": "model-management.md",
    "harness/definitions/__init__.py:745": "model-management.md",
    "harness/definitions/__init__.py:872": "skeleton-and-application.md",
    "harness/definitions/__init__.py:876": "skeleton-and-application.md",
    "harness/definitions/__init__.py:892": "skeleton-and-application.md",
    "harness/definitions/__init__.py:1354": "skeleton-and-application.md",
    "harness/kernel_events.py:84": "existing-project-onboarding.md",
    "harness/kernel_events.py:90": "existing-project-onboarding.md",
    "harness/kernel_events.py:99": "existing-project-onboarding.md",
    "harness/projects.py:1586": "model-management.md",
    "harness/tests/kernel/test_only_grows.py:165": "skeleton-and-application.md",
    "harness/tests/test_startup_reload.py:157": "app-and-interface.md",
    "harness/tests/test_startup_reload.py:312": "model-management.md",
    "harness/tightening.py:254": "skeleton-and-application.md",
    "harness/tightening.py:266": "skeleton-and-application.md",
    "harness/tightening.py:282": "skeleton-and-application.md",
    "harness/tightening.py:288": "skeleton-and-application.md",
    "harness/tightening.py:381": "skeleton-and-application.md",
    "harness/tightening.py:515": "skeleton-and-application.md",
    "harness/tightening.py:556": "skeleton-and-application.md",
    "harness/tightening.py:1433": "browser-and-computer-use.md",
    "harness/app/project_queries.py": "app-and-interface.md",
    # 审查逐条指出的（第 2 轮审查）
    "harness/direct.py:91": "skeleton-and-application.md",
    "harness/direct.py:616": "skeleton-and-application.md",
    "harness/runtime.py:171": "existing-project-onboarding.md",
    "harness/definitions/__init__.py:219": "forms-and-verifier-role.md",
    "harness/definitions/__init__.py:255": "forms-and-verifier-role.md",
    "harness/definitions/__init__.py:827": "forms-and-verifier-role.md",
    "harness/definitions/__init__.py:1156": "forms-and-verifier-role.md",
    "harness/definitions/__init__.py:1181": "forms-and-verifier-role.md",
    "harness/recovery.py:409": "browser-and-computer-use.md",
    "harness/recovery.py:452": "browser-and-computer-use.md",
    "harness/recovery.py:506": "browser-and-computer-use.md",
    "harness/recovery.py:525": "browser-and-computer-use.md",
    "harness/recovery.py:539": "browser-and-computer-use.md",
    "harness/tests/kernel/test_only_grows.py:6": "skeleton-and-application.md",
    "harness/tests/kernel/test_only_grows.py:9": "skeleton-and-application.md",
    "harness/tests/kernel/test_only_grows.py:36": "skeleton-and-application.md",
    "harness/tests/kernel/test_only_grows.py:127": "skeleton-and-application.md",
    "harness/tests/kernel/test_skeleton_events.py:2": "skeleton-and-application.md",
    "harness/tests/kernel/test_skeleton_events.py:85": "skeleton-and-application.md",
    "harness/app/project_queries.py:1566": "model-management.md",
    "harness/orchestrator.py:957": "loops-and-convergence.md",
    "harness/tightening.py:815": "existing-project-onboarding.md",
    "harness/tests/test_event_kind_registration.py:1": "skeleton-and-application.md",
    "harness/tests/test_event_kind_registration.py:27": "skeleton-and-application.md",
    "harness/tests/test_issue_16_recovery.py:256": "recovery-contract-and-fault-matrix.md",
    "harness/tests/test_provider_protocols.py:493": "model-management.md",
}

# 文件级的对照表与「文件:行」的条目一起用：mapping_doc 先查「文件:行」，再查文件，最后查目录。
MAPPING.update(FILE_MAPPING)
# 逐行的条目最后放：同一个键两边都有时以逐行的为准
MAPPING.update(LINE_MAPPING)

# 整份改写、节号对不上的，按内容对上现在的小节（工单 #1411 的「自定的边界」）。
TITLE_OVERRIDES: dict[str, str] = {
    "harness/definitions/rules.json:220": "审查者的上下文",
    "harness/definitions/rules.json:572": "角色清单",
    # 原来的节号在现在这份说明里没有了（那一节改过名或并进了别的一节），按内容对上现在的小节
    "harness/__main__.py:44": "数据目录",
    "harness/__main__.py:121": "数据目录",
    "harness/app/catalog_queries.py:220": "查询清单",
    "harness/app/catalog_queries.py:383": "查询清单",
    "harness/definitions/__init__.py:319": "工具定义的声明",
    "harness/definitions/__init__.py:713": "服务方案预置表与模型能力表",
    "harness/tests/test_startup_reload.py:312": "目录文件重新读取",
    "harness/tests/kernel/test_only_grows.py:6": "骨架事件与应用事件",
    "harness/tests/kernel/test_only_grows.py:9": "骨架事件与应用事件",
    "harness/tests/kernel/test_only_grows.py:36": "骨架事件与应用事件",
    "harness/tests/kernel/test_only_grows.py:127": "骨架事件与应用事件",
    "harness/tests/kernel/test_skeleton_events.py:2": "骨架事件与应用事件",
    "harness/tests/kernel/test_skeleton_events.py:85": "骨架事件与应用事件",
    "harness/app/project_queries.py:1566": "部门工作间",
    "harness/__main__.py:128": "命令行",
    "harness/tests/test_startup_reload.py:157": "命令行",
    "evals/runner/yudao_report.py:545": "Yudao 对单个 agent",
    "harness/orchestrator.py:957": "一定会停",
    "harness/tests/test_event_kind_registration.py:1": "骨架事件与应用事件",
    "harness/tests/test_event_kind_registration.py:27": "骨架事件与应用事件",
    "harness/tests/test_issue_16_recovery.py:256": "执行权与一致边界",
    "harness/tests/test_provider_protocols.py:493": "失败处理",
    "harness/tightening.py:1433": "启动方式",
    "harness/decision_flow.py:178": "用户确认与修改的往返",
    "harness/tests/kernel/test_only_grows.py:165": "可信内核",
    "harness/recovery.py:318": "角色任务的恢复",
    "harness/recovery.py:349": "角色任务的恢复",
}
# 这两处写的是「恢复契约第 5.2 节」：那一份说明现在把恢复讲在第 5 节里，没有 5.2 这样的小节
MAPPING["harness/recovery.py:318"] = "recovery-contract-and-fault-matrix.md"
MAPPING["harness/recovery.py:349"] = "recovery-contract-and-fault-matrix.md"

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

# 工单 #1411 正文第 3 步点名的几行：那里的第 12 节是已删去的「从现有代码过去的路径」，
# 这一部分引用去掉，其余照旧（当时 blame 到的那一版小节名叫「模块交互」，不能按改名换算）。
DROP_SECTIONS: tuple[tuple[str, str], ...] = (
    ("harness/decision_flow.py:1", "12"),
    ("harness/tests/test_decision_flow.py:2", "12"),
    ("harness/tests/test_routing_contract.py:1", "12"),
    ("harness/tests/test_routing_definition.py:1", "12"),
    ("harness/tests/test_second_routing.py:1", "12"),
)

# 已经删去的小节：指向它的那一部分引用去掉，注释的其余部分照旧。

# （工单 #1411 正文第 3 步点名的四处，加上清理时删去的两处。）
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
TAIL_OK = re.compile(r"(设计说明|设计|文档|说明)?[\s）)。，、：:；;]*")
NAME_SUFFIX = re.compile(r"(设计说明|设计|文档|说明)$")
GAP_OK = re.compile(r"(?:[\s）)、，,（(：:；;的]|设计说明|设计|文档|说明)*")
BLAME_LINE_RE = re.compile(r"^([0-9a-f]{40}) \d+ \d+")

# 以下几类推断要在注释里补上文档路径；名字写在同一段注释里的只写「小节标题」。


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
    key = f"blame:{path}"
    if key in _CACHE:
        return tuple(_CACHE[key])  # type: ignore[arg-type]
    out = run(["git", "blame", "--line-porcelain", "--", path])
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


def header_block(lines: tuple[str, ...]) -> str:
    """文件开头的说明：第一段连续的注释或模块文档字符串。"""
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
    # 注释里也有只写文件名或文件名的词干的（`local-tools 第 2 节`、`test-pyramid 第 2 节`）
    for m in re.finditer(r"([\w-]+)\.md", text):
        if f"{m.group(1)}.md" in all_docs():
            hits.append((m.start(), m.end(), f"{m.group(1)}.md"))
    for stem, doc in doc_stems().items():
        for m in re.finditer(rf"(?<![\w./-]){re.escape(stem)}(?![\w-])", text):
            hits.append((m.start(), m.end(), doc))
    # 去掉被更长的名字包住的（「网络与 MCP」包在「网络取回与 MCP」里）
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
    """紧挨在 pos 前面的是设计说明的**文件名**（`local-tools`、`test-pyramid`）时，给出它的起点。

    这种写法要把文件名一起换成路径（工单 #1411 第 4 步的写法），只写「小节标题」会留下
    「local-tools 「工作区」」这种半截的引用。
    """
    for start, end, hit_doc in mentions(text):
        if hit_doc == doc and end <= pos and GAP_OK.fullmatch(text[end:pos]) and text[start:end] == Path(doc).stem:
            return start
    return None


def excluded_before(text: str, pos: int) -> str | None:
    """紧挨在节号前面的「原型 v8」「ADR-0007」「docs/requirements/x.md」这类词。"""
    for pat in EXCLUDED_TOKENS:
        for m in re.finditer(pat, text):
            if m.end() <= pos:
                if GAP_OK.fullmatch(text[m.end() : pos]):
                    return m.group(0)
            elif m.start() < pos <= m.end():
                # 贪婪匹配（「路线图…第 6.1 节」）把节号一起吞掉了：这一处仍然算别的文档
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
    score: float = 0.0
    quote: str = ""
    named: bool = False
    pinned: str | None = None
    pinned_strict: bool = False
    bare: bool = False

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @property
    def dropped(self) -> bool:
        return self.status.startswith("去掉")


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
    """这份文件是照原型的设计做的：客户端文件的**开头**声明了「原型 vN 设计说明第 K 节」。

    工单 #1411 把引用原型的节号排除在外；客户端页面是原型的移植，注释里的无主节号指的是原型，
    不是 docs/design 下的某一份。只在文件开头声明时成立：正文里偶尔提一次原型不再整文件豁免。
    """
    if not path.startswith("client/"):
        return False
    for m in PROTO_RE.finditer(header_block(file_lines(path))):
        head = m.group(0).rsplit("第", 1)[0]
        if "与设计说明" in head or "及设计说明" in head:
            # 「原型 v10 floor.js 的绘制部分与设计说明第 5.2 节」：这一处指的是设计说明本身
            continue
        return True
    return False


def mapping_doc(path: str, line: int | None = None) -> str | None:
    """对照表：先按「文件:行」，再按文件，最后按目录。"""
    if line is not None and f"{path}:{line}" in MAPPING:
        return MAPPING[f"{path}:{line}"]
    if path in MAPPING:
        return MAPPING[path]
    for key, doc in MAPPING.items():
        if key.endswith("/") and path.startswith(key):
            return doc
    return None


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


def title_for(ref: Ref, doc: str) -> tuple[str | None, str]:
    """这一处指向 doc 的哪一节，写成「标题」或「标题」中「项名」；连带状态一起给出。

    先按编号找小节；编号形如「N.M」而 N.M 不是小节时，按第 N 节的第 M 项找（注释里
    带小数点的编号有时指的是「第 N 节的第 M 项」）。
    """

    commit = commit_of(ref)
    hist = doc_at(commit, doc) if commit else None
    if hist is None:
        now = now_headings(doc)
        if ref.sec in now:
            return render_ref(ref, doc, now[ref.sec], hist), "ok"
        return None, f"没有第 {ref.sec} 节"
    headings = dict(doc_headings(hist))
    old = headings.get(ref.sec)
    if old is not None:
        if (doc, old) in DELETED:
            return None, f"去掉（{old} 已删去）"
        title = renamed(doc, old)
        if title:
            return render_ref(ref, doc, title, hist), "ok"
        return None, f"旧标题「{old}」对不到现在的小节"
    base, _dot, last = ref.sec.rpartition(".")
    if base and last.isdigit() and base in headings:
        items = item_texts(hist, base)
        index = int(last)
        if 1 <= index <= len(items):
            name = items[index - 1][1]
            home = item_home(doc, name)
            if home:
                return "「" + home + "」中「" + name + "」", "ok"
            return None, f"第 {base} 节的第 {index} 项「{name}」现在不在说明里"
    return None, f"当时那份说明没有第 {ref.sec} 节"


def item_home(doc: str, name: str) -> str | None:
    """一项现在在哪一节里。"""
    for num, title in now_headings(doc).items():
        if any(item == name for _, item in item_texts(current_doc(doc), num)):
            return title
    return None


def render_ref(ref: Ref, doc: str, title: str, hist: str | None) -> str:
    """一节一处的写法：小节标题；带项号或后面已有引号的，保留那一项的名字。"""
    if ref.items and hist is not None:
        old_items = dict(item_texts(hist, ref.sec))
        names = []
        for n in ref.items:
            name = old_items.get(str(n))
            if not name or item_home(doc, name) is None:
                names = []
                break
            names.append(name)
        if names and all(len(name) <= 30 for name in names):
            return "「" + title + "」中" + "".join("「" + name + "」" for name in names)
    quote = quote_after(ref)
    if quote:
        if quote == title or quote in title:
            ref.end = max(ref.end, quote_end(ref))
        elif quote in body_by_title(doc, title):
            ref.end = max(ref.end, quote_end(ref))
            return "「" + title + "」中「" + quote + "」"
    return "「" + title + "」"


def item_names(ref: Ref, doc: str) -> list[str] | None:
    """第 N 节第 M 项：那一项当时的名字，且现在还在同一节里。"""
    if not ref.items:
        return None
    commit = commit_of(ref)
    hist = doc_at(commit, doc) if commit else None
    if hist is None:
        return None
    old_items = dict(item_texts(hist, ref.sec))
    now_items = {name for _, name in item_texts(current_doc(doc), current_num(doc, ref.title or ""))}
    names = []
    for n in ref.items:
        name = old_items.get(str(n))
        if not name or name not in now_items:
            return None
        names.append(name)
    return names


def current_num(doc: str, title: str) -> str:
    for num, t in now_headings(doc).items():
        if t == title.strip("「」"):
            return num
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
    """一项的名字：去掉加粗与句读，照抄到底，不截断（截断会把标题断在半句上）。"""
    t = re.sub(r"^\*\*(.+?)\*\*\s*", r"\1", text.strip())
    t = re.split(r"[。：:（(]\s*", t, maxsplit=1)[0]
    return t.strip("* 「」")


@lru_cache(maxsize=None)
def body_by_title(doc: str, title: str) -> str:
    """一份设计说明里某一节的正文（到下一节为止），用来与注释的文字比对。"""
    lines = current_doc(doc).splitlines()
    for i, line in enumerate(lines):
        m = HEADING_RE.match(line)
        if m and m.group(3).strip().strip("「」") == title.strip("「」"):
            out = [line]
            for later in lines[i + 1 :]:
                if HEADING_RE.match(later):
                    break
                out.append(later)
            return "\n".join(out)[:8000]
    return ""


def bigrams(text: str) -> set[str]:
    return {text[i : i + 2] for i in range(len(text) - 1) if text[i].strip() and text[i + 1].strip()}


@lru_cache(maxsize=None)
def bigram_df() -> dict[str, int]:
    """每个字符二元组出现在多少节的正文里（越少越有区分度）。"""
    df: Counter[str] = Counter()
    for doc in all_docs():
        for title in now_headings(doc).values():
            df.update(bigrams(body_by_title(doc, title)))
    return dict(df)


def similarity(text: str, doc: str, title: str) -> float:
    """注释的文字覆盖那一节正文的程度：按二元组在全部小节里的常见程度加权。"""
    a = bigrams(text)
    if not a:
        return 0.0
    body = bigrams(body_by_title(doc, title))
    if not body:
        return 0.0
    df = bigram_df()
    n = len(df) + 1
    weight = {b: math.log(n / (1 + df.get(b, 0))) for b in a}
    total = sum(weight.values())
    return sum(weight[b] for b in a & body) / total if total else 0.0


def line_text(ref: Ref) -> str:
    return file_lines(ref.file)[ref.line - 1]


def normalized_line(ref: Ref) -> str:
    """同一句话在别处出现时用来认：去掉空白与行首的注释符号。"""
    return re.sub(r"\s+", "", re.sub(r"^\s*(?:#|//|\*|/\*|--)+", "", line_text(ref)))


def comment_text(ref: Ref) -> str:
    """这一行与同一段注释的上面几行，用来与设计说明比文字。"""
    return block_above(file_lines(ref.file), ref.line) + "\n" + line_text(ref)


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


def consider(ref: Ref, doc: str, how: str) -> bool:
    """按一份候选设计说明换算这一处；成功就记下。"""
    title, status = title_for(ref, doc)
    if title is None:
        ref.status = status
        return False
    ref.doc, ref.how, ref.title, ref.status = doc, how, title, "ok"
    return True


def score_of(ref: Ref, doc: str) -> float:
    """这一处注释与那份说明的那一节有多相符（用于在几个候选里挑一个）。"""
    title, status = title_for(ref, doc)
    if title is None:
        return -1.0
    section = title.split("」")[0].lstrip("「")
    text = comment_text(ref)
    quote = quote_after(ref)
    score = similarity(text, doc, section)
    # 小节的标题里有一两个词就写在注释里（「规则清单」对「装配规则」）
    title_grams = bigrams(section)
    if title_grams:
        score += 0.22 * len(title_grams & bigrams(text)) / len(title_grams)
    if quote and (quote in title or quote in body_by_title(doc, section)):
        score += 0.35
    return round(score, 3)


def rank(ref: Ref, docs: list[str]) -> list[tuple[float, str, str]]:
    """候选设计说明按与注释文字的相符程度排序：((得分, 文件, 写好的标题), ...)。"""
    scored = []
    for doc in dict.fromkeys(docs):
        title, status = title_for(ref, doc)
        if title is None:
            continue
        scored.append((score_of(ref, doc), doc, title))
    return sorted(scored, reverse=True)


def section_by_text(ref: Ref, doc: str) -> tuple[str, float] | None:
    """写明了哪份说明、但节号对不上现在的编号时，在这份说明的小节里按文字挑一节。

    只在人定的或同行点名的说明里找，不跨说明猜；分不开或不明显时返回 None，留给对照表。
    """
    text = comment_text(ref)
    quote = quote_after(ref)
    scored: list[tuple[float, str]] = []
    for title in now_headings(doc).values():
        score = similarity(text, doc, title)
        grams = bigrams(title)
        if grams:
            score += 0.30 * len(grams & bigrams(text)) / len(grams)
        if quote and (quote in title or quote in body_by_title(doc, title)):
            score += 0.40
        scored.append((round(score, 3), title))
    if not scored:
        return None
    scored.sort(reverse=True)
    best, second = scored[0], (scored[1][0] if len(scored) > 1 else 0.0)
    if best[0] >= 0.36 and best[0] >= 1.2 * second:
        return "「" + best[1] + "」", best[0]
    return None


def resolve(groups: list[Group], texts: dict[str, str]) -> None:
    refs = [r for g in groups for r in g.refs]
    file_doc: dict[str, Counter[str]] = {}
    for path in {r.file for r in refs}:
        counter: Counter[str] = Counter()
        for _start, _end, doc in mentions(texts[path]):
            counter[doc] += 1
        file_doc[path] = counter
    by_line: dict[tuple[str, int], list[Ref]] = defaultdict(list)
    for ref in refs:
        by_line[(ref.file, ref.line)].append(ref)
    for items in by_line.values():
        items.sort(key=lambda r: r.start)

    # 第一轮：这一行、这一段注释写明了是哪份说明（确定）。
    # 写明了名字而换算不成的（当时那份说明没有这一节、标题对不上），钉在这份说明上，
    # 不再拿「同文件的多数」或「文字最相近」去改到别的说明——那样改出来的句子自相矛盾。
    for ref in refs:
        line = line_text(ref)
        if (f"{ref.file}:{ref.line}", ref.sec) in DROP_SECTIONS:
            ref.status, ref.how = "去掉（工单点名的已删小节）", "去掉"
            continue
        if kept_as_is(ref.file, line):
            ref.status, ref.how = "排除（只改之外）", "排除"
            continue
        if any(ref.file == p and snippet in line for p, snippet in PROTO_AS_IS):
            ref.status, ref.how = "排除（原型）", "排除"
            continue
        if excluded_before(line, ref.start):
            ref.status, ref.how = "排除（别的文档）", "排除"
            continue
        doc = nearest_before(line, ref.start, mentions(line))
        if doc:
            ref.named = True
            if not consider(ref, doc, "同行名字"):
                ref.doc, ref.pinned, ref.pinned_strict = doc, doc, True
            stem = bare_name_before(line, ref.start, doc)
            if stem is not None:
                # 写的是文件名：换成路径时把文件名一起换掉
                ref.bare = True
                ref.start = stem
            continue
        if proto_file(ref.file):
            # 文件开头声明了照原型的设计做：客户端注释里的无主节号指的是原型（不在本单）
            ref.status, ref.how = "排除（原型）", "排除"
            continue
        above = block_above(file_lines(ref.file), ref.line)
        doc = nearest_before(above + "\n", len(above), mentions(above)) if above else None
        if doc:
            ref.named = True
            if not consider(ref, doc, "同段注释"):
                ref.doc, ref.pinned = doc, doc

    # 同一行的几个节号共用这一行点名的说明：第一个引用定下来的那一份，后面的沿用它，
    # 除非那一处自己写了另一份说明（工单 #1411 审查第 2 条）。
    for items in by_line.values():
        current: str | None = None
        for ref in items:
            if ref.status.startswith("排除") or ref.dropped:
                continue
            if ref.named:
                current = ref.doc
                continue
            if ref.ok:
                current = ref.doc
                continue
            if current:
                if not consider(ref, current, "同一行"):
                    ref.doc, ref.pinned = current, current

    # 同一句话在别处已经写明是哪份说明的，沿用那一份（同一句注释在多处重复，比如
    # 「装配规则的取值（设计说明第 4 节）」）。整行文字相同才算，不用相似度。
    sentence_doc: dict[str, str] = {}
    for ref in refs:
        if ref.named and ref.ok and ref.doc:
            sentence_doc.setdefault(normalized_line(ref), ref.doc)
    for ref in refs:
        if ref.ok or ref.dropped or ref.pinned or ref.status.startswith("排除"):
            continue
        doc = sentence_doc.get(normalized_line(ref))
        if doc:
            if not consider(ref, doc, "同一句话"):
                ref.doc, ref.pinned = doc, doc

    # 第二轮：对照表里人定的那一份（人定的优先于推断；同行点名的不动）
    for ref in refs:
        if ref.dropped or ref.status.startswith("排除"):
            continue
        if ref.ok and ref.named:
            continue
        doc = mapping_doc(ref.file, ref.line)
        if doc:
            if not consider(ref, doc, "对照表"):
                ref.doc, ref.pinned = doc, doc
                # 「文件:行」是逐行定的：不再退到同一份文件点名的说明（按文件的对照表可以退）
                ref.pinned_strict = f"{ref.file}:{ref.line}" in MAPPING


    # 第二轮之半：写明了哪份说明（同行点名或对照表）、节号却对不上现在编号的：
    # 先退到这份文件的注释里点名过的说明（按点名的多少，最多三份），再在这几份里按文字挑一节。
    # 跨说明地猜是不做的（工单 #1411 审查第 5 条）。
    votes: dict[str, Counter[str]] = defaultdict(Counter)
    for ref in refs:
        if ref.ok and ref.doc:
            votes[ref.file][ref.doc] += 1
    for ref in refs:
        if ref.ok or ref.dropped or ref.status.startswith("排除") or not ref.pinned:
            continue
        if not ref.pinned_strict:
            for doc, _count in votes[ref.file].most_common(3):
                if doc != ref.pinned and consider(ref, doc, "同一份文件点名的说明"):
                    break
            if ref.ok:
                continue
        found = section_by_text(ref, ref.pinned)
        if found:
            ref.doc, ref.how, ref.title, ref.status, ref.score = ref.pinned, "指名说明里按文字对节", found[0], "ok", found[1]

    # 第三轮：按注释文字与各说明的小节正文比对，只在候选里取一名；同一份文件里已经定下来的
    # 说明、文件开头写明的那一份、文件里提到过的说明，都只是少许加分。分不开的记为未定，
    # 不替人猜（工单 #1411 审查第 5 条）。
    header_doc = {}
    for path in {r.file for r in refs}:
        header = header_block(file_lines(path))
        found = {doc for _s, _e, doc in mentions(header)}
        header_doc[path] = found.pop() if len(found) == 1 else None
    for ref in refs:
        if ref.ok or ref.dropped or ref.pinned or ref.status.startswith("排除"):
            continue
        total = sum(file_doc[ref.file].values()) or 1
        prior = {doc: 0.06 * count / total for doc, count in file_doc[ref.file].items()}
        counted = sum(votes[ref.file].values()) or 1
        for doc, count in votes[ref.file].items():
            prior[doc] = prior.get(doc, 0.0) + 0.16 * count / counted
        if header_doc.get(ref.file):
            prior[header_doc[ref.file]] = prior.get(header_doc[ref.file], 0.0) + 0.12
        ranked = [
            (round(score_of(ref, doc) + prior.get(doc, 0.0), 3), doc, title)
            for doc in all_docs()
            for title, status in [title_for(ref, doc)]
            if title is not None
        ]
        ranked.sort(reverse=True)
        if not ranked:
            ref.status = "未定：没有一份说明有这个节号"
            continue
        best = ranked[0]
        second = ranked[1][0] if len(ranked) > 1 else 0.0
        if (best[0] >= 0.30 and best[0] >= 1.10 * second) or best[0] >= 0.45:
            ref.doc, ref.how, ref.title, ref.status, ref.score = best[1], "推断", best[2], "ok", best[0]
        else:
            ref.doc, ref.score = best[1], best[0]
            ref.status = "未定：两种读法都可能"

    # 「文件:行」的对照表最后覆盖一次：人定的优先。同一行里已经按名字定下来的另一处（写的是
    # 另一份说明）不动；人定的标题对 section_by_text 已经定下来的那一处也生效。
    for ref in refs:
        if ref.status.startswith("排除") or ref.dropped:
            continue
        key = f"{ref.file}:{ref.line}"
        if key not in MAPPING:
            continue
        doc = MAPPING[key]
        if TITLE_OVERRIDES.get(key):
            if ref.doc and ref.doc != doc:
                continue
            ref.doc, ref.how, ref.status = doc, "对照表", "ok"
            ref.title = "「" + TITLE_OVERRIDES[key] + "」"
            continue
        if ref.ok:
            continue
        consider(ref, doc, "对照表")

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
            for g in sorted(line_groups, key=lambda x: x.start, reverse=True):
                new = g.render()
                if new is None:
                    continue
                doc = next((r.doc for r in g.refs if r.doc), None)
                context = line + "\n" + block_above(file_lines(path), lineno)
                named = bool(doc) and doc in {d for _s, _e, d in mentions(context)}
                if any(r.bare for r in g.refs if r.doc == doc):
                    # 注释里写的是设计说明的文件名：连文件名一起换成路径
                    named = False
                start, end = min([g.start] + [r.start for r in g.refs]), max([g.end] + [r.end for r in g.refs])
                if any(r.dropped for r in g.refs):
                    slice_match = SLICE_RE.match(line, end)
                    if slice_match:
                        end = slice_match.end()
                if new == "":
                    _, start, end = drop_span(line, start, end)
                    line = line[:start] + line[end:]
                else:
                    if not named:
                        if doc:
                            new = f"{DESIGN_DIR}/{doc}" + new
                            suffix = NAME_SUFFIX.search(line[:start])
                            if suffix:
                                start = suffix.start()
                                while start > 0 and line[start - 1] in " \t":
                                    start -= 1
                            elif start > 0 and line[start - 1] == "的":
                                start -= 1
                            if start > 0 and re.match(r"[\w\u4e00-\u9fff]", line[start - 1]):
                                new = " " + new
                    line = line[:start] + new + line[end:]
                touched += 1
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
    if left.endswith(("、", "，", ",")) and right.startswith(("、", "，", ",", "）", ")", "；", ";", "。")):
        start -= 1
    elif right.startswith(("、", "，", ",")):
        # 去掉的那一段在列表末尾：后面多出来的分隔号一并去掉
        end += 1
    while start > 0 and line[start - 1] in " \t":
        start -= 1
    return line, start, end


# ---------------------------------------------------------------- 主流程


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", help="把换算结果写到这个 TSV，不改文件")
    ap.add_argument("--apply", action="store_true", help="改文件")
    ap.add_argument("--only", help="只处理这些文件（逗号分隔）")
    ap.add_argument("--cache", help="历史版本设计说明的缓存（只在开发脚本时用）")
    args = ap.parse_args(argv)

    load_cache(args.cache)
    files = [f for f in run(["git", "ls-files"]).splitlines() if f and in_scope(f)]
    if args.only:
        keep = set(args.only.split(","))
        files = [f for f in files if f in keep]
    groups, texts = collect(files)
    resolve(groups, texts)

    if args.report:
        rows = ["\t".join(("file", "line", "start", "end", "sec", "doc", "how", "title", "status", "score"))]
        for g in groups:
            for r in g.refs:
                rows.append(
                    "\t".join(
                        (r.file, str(r.line), str(g.start), str(g.end), r.sec, r.doc or "", r.how, r.title or "", r.status, f"{r.score:.3f}")
                    )
                )
        Path(args.report).write_text("\n".join(rows), encoding="utf-8")

    if args.apply:
        changed_files, changed_refs = apply_groups(groups, texts)
        print(f"改了 {len(changed_files)} 个文件、{changed_refs} 处")

    refs = [r for g in groups for r in g.refs]
    ok = sum(1 for r in refs if r.ok)
    excluded = sum(1 for r in refs if r.status.startswith("排除"))
    dropped = sum(1 for r in refs if r.dropped)
    undecided = len(refs) - ok - excluded - dropped
    print(f"处数 {len(refs)}，可换算 {ok}，去掉（小节已删）{dropped}，排除（别的文档）{excluded}，未定 {undecided}")
    save_cache()
    return 0


if __name__ == "__main__":
    sys.exit(main())
