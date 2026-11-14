# 随包分发的进程外运维技能模块层测试（docs/design/external-ops-agent.md「随包运维技能」「三条改动通道与失败处理」「验收」）。

from __future__ import annotations

import io
from pathlib import Path

import yaml

from harness.__main__ import main as cli_main
from harness.ops_skill import SKILL_FILENAME, install_skill, read_skill_text


def _invoke_skill(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = cli_main(argv, stdin=io.StringIO(""), stdout=stdout, stderr=stderr, environ={})
    return code, stdout.getvalue(), stderr.getvalue()


def test_skill_show_outputs_complete_yaml_frontmatter_and_operational_protocols(tmp_path: Path) -> None:
    # 守 R2/R3：yudao skill show 原样输出带 YAML 头的完整技能文档，覆盖基准版本、凭据隔离、三条改动通道、决定请求用户拍板与常见运维序列，且不接触数据目录
    unused_data_dir = tmp_path / "untouched-data-dir"
    code, out, err = _invoke_skill(["--data-dir", str(unused_data_dir), "skill", "show"])
    assert code == 0, err
    assert err == ""
    assert not unused_data_dir.exists()
    assert out == read_skill_text()

    assert out.startswith("---\n")
    parts = out.split("---\n", 2)
    assert len(parts) == 3
    frontmatter = yaml.safe_load(parts[1])
    assert isinstance(frontmatter, dict)
    assert frontmatter["name"] == "yudao-ops"
    assert isinstance(frontmatter.get("description"), str) and frontmatter["description"].strip()

    body = parts[2]
    # 1. 先读取后修改与基准版本规程及全部退出码
    for token in (
        "capabilities",
        "describe",
        "query",
        "command",
        "events",
        "base_version",
        "--command-id",
        "退出码 `0`",
        "退出码 `1`",
        "退出码 `2`",
        "退出码 `3`",
        "退出码 `4`",
        "退出码 `5`",
    ):
        assert token in body, token

    # 2. 凭据安全与隔离规程
    for token in (".env", "--stdin", "--token-stdin", "YUDAO_TOKEN", "credential.set", "catalog.connect"):
        assert token in body, token

    # 3. 三条改动通道分流规程
    for token in (
        "第一条通道：数据定义与参数命令",
        "第二条通道：隔离动作与外部工具",
        "第三条通道：修改 Yudao 自身代码",
        "organization.adopt",
        "parameter.set",
        "parameter.withdraw",
        "tool_server.probe",
        "mcp_servers.save",
        "kernel_modification",
        "runtime.start_drain",
        "release-check",
    ):
        assert token in body, token

    # 4. 决定请求用户拍板确认规程与常见运维序列
    for token in ("decisions.list", "decision.answer", "只有在用户明确给出具体选择之后", "常见运维操作序列"):
        assert token in body, token


def test_skill_install_creates_parent_directories_and_enforces_overwrite_guard(tmp_path: Path) -> None:
    # 守 R2/R3：yudao skill install 自动建立缺失父目录并写入 SKILL.md；已存在时未传 --force 返回退出码 1 并保留原文件，传 --force 正常覆盖
    target_dir = tmp_path / "external-agent" / "skills" / "yudao-ops"
    expected_file = target_dir / SKILL_FILENAME

    code_new, out_new, err_new = _invoke_skill(["skill", "install", str(target_dir)])
    assert code_new == 0, err_new
    assert err_new == ""
    assert Path(out_new.strip()) == expected_file
    assert expected_file.is_file()
    assert expected_file.read_text(encoding="utf-8") == read_skill_text()

    sentinel_text = "用户本地改过的旧版技能内容\n"
    expected_file.write_text(sentinel_text, encoding="utf-8")

    code_refused, out_refused, err_refused = _invoke_skill(["skill", "install", str(target_dir)])
    assert code_refused == 1
    assert out_refused == ""
    assert "--force" in err_refused
    assert expected_file.read_text(encoding="utf-8") == sentinel_text

    code_forced, out_forced, err_forced = _invoke_skill(["skill", "install", str(target_dir), "--force"])
    assert code_forced == 0, err_forced
    assert err_forced == ""
    assert Path(out_forced.strip()) == expected_file
    assert expected_file.read_text(encoding="utf-8") == read_skill_text()

    # 函数入口同样遵守覆盖守卫
    direct_dir = tmp_path / "direct-install"
    written = install_skill(direct_dir)
    assert written == direct_dir / SKILL_FILENAME
    try:
        install_skill(direct_dir, force=False)
    except FileExistsError:
        pass
    else:
        raise AssertionError("install_skill without force must raise FileExistsError when SKILL.md exists")
