# 通用命令行客户端的模块层测试（docs/design/external-ops-agent.md「连接、认证与请求头规则」「零维护的单项合同自省」「查询读取与幂等命令提交」「验收」）。
# 使用 httpx.ASGITransport 对接真实 FastAPI 与 Application 实例，网络异常使用自定义 httpx.BaseTransport 触发。

from __future__ import annotations

import io
import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx

from harness.__main__ import main as cli_main
from harness.api.app import contract_digest, create_app
from harness.app.access_tokens import AccessTokenStore
from harness.app.application import Application
from harness.app.contracts import AccessMode
from harness.event_store import catalog_stream
from harness.models import utc_now
from harness.runtime import LoopSystem, SINGLE_ROLE_DIRECT


@contextmanager
def _open_asgi_service(
    tmp_path: Path,
    *,
    access: AccessMode = "local",
    tokens: AccessTokenStore | None = None,
    with_dotenv: bool = False,
) -> Iterator[tuple[Application, httpx.ASGITransport]]:
    data_dir = tmp_path / f"data-{access}"
    if with_dotenv:
        dotenv_path = tmp_path / ".env"
        dotenv_path.write_text("", encoding="utf-8")
        system = LoopSystem(data_dir, provider_config_path=None, dotenv_path=dotenv_path)
    else:
        system = LoopSystem.for_testing(data_dir, None, resume_on_startup=False)
    application = Application(system)
    api = create_app(
        lambda: application,
        access=access,
        pages=tmp_path / "no-pages",
        tokens=tokens,
    )
    api.state.application = application
    api.state.contract_digest = contract_digest(api)
    try:
        yield application, httpx.ASGITransport(app=api)
    finally:
        application.close()


def _invoke(
    argv: list[str],
    *,
    transport: httpx.BaseTransport | httpx.AsyncBaseTransport | None = None,
    stdin_text: str = "",
    environ: Mapping[str, str] | None = None,
) -> tuple[int, str, str]:
    stdin = io.StringIO(stdin_text)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = cli_main(
        argv,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        environ={} if environ is None else dict(environ),
        transport=transport,
    )
    return code, stdout.getvalue(), stderr.getvalue()


class _FailingSyncTransport(httpx.BaseTransport):
    def __init__(self, kind: str) -> None:
        self._kind = kind

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if self._kind == "timeout":
            raise httpx.ReadTimeout("timed out waiting for response", request=request)
        raise httpx.ConnectError("connection refused", request=request)


class _HeaderInspectingTransport(httpx.AsyncBaseTransport):
    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self._inner = inner
        self.seen_requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.seen_requests.append(request)
        return await self._inner.handle_async_request(request)


def test_capabilities_and_loopback_host_rules_in_local_mode(tmp_path: Path) -> None:
    # 守 R2/R3：能力清单结构与接口层一致，回环主机保持目标 Host 头、不附带 Origin 头且绕过环境变量代理
    with _open_asgi_service(tmp_path, access="local") as (_app, asgi_transport):
        inspector = _HeaderInspectingTransport(asgi_transport)
        proxy_env = {
            "HTTP_PROXY": "http://127.0.0.1:1",
            "HTTPS_PROXY": "http://127.0.0.1:1",
        }
        code, out, err = _invoke(["capabilities"], transport=inspector, environ=proxy_env)
        assert code == 0, err
        assert err == ""
        payload = json.loads(out)
        assert payload["deployment"]["access"] == "local"
        assert isinstance(payload["deployment"]["api_version"], int)
        assert payload["deployment"]["log_id"]
        assert any(item["name"] == "project.overview" for item in payload["queries"])
        assert any(item["name"] == "project.create" for item in payload["commands"])

        first_req = inspector.seen_requests[-1]
        assert first_req.headers["host"] == "127.0.0.1:8765"
        assert "origin" not in first_req.headers

        for loopback_url, expected_host in (
            ("http://localhost:9000", "localhost:9000"),
            ("http://[::1]:9001", "[::1]:9001"),
        ):
            code_lb, out_lb, err_lb = _invoke(
                ["--url", loopback_url, "capabilities"],
                transport=inspector,
                environ=proxy_env,
            )
            assert code_lb == 0, err_lb
            assert json.loads(out_lb)["deployment"]["access"] == "local"
            assert inspector.seen_requests[-1].headers["host"] == expected_host
            assert "origin" not in inspector.seen_requests[-1].headers

        code_forbidden, _out_f, err_f = _invoke(
            ["capabilities", "--url", "http://192.168.1.20:8765"],
            transport=inspector,
        )
        assert code_forbidden == 3
        assert "403" in err_f


def test_lan_authentication_token_sources_and_connection_errors(tmp_path: Path) -> None:
    # 守 R1/R3：局域网访问方式核对访问令牌，有效令牌把提出者 user:<令牌名称> 记入事件，连接异常返回退出码 3
    token_store = AccessTokenStore(tmp_path / "tokens")
    _entry, valid_token = token_store.create("ops-agent", now=utc_now())

    with _open_asgi_service(tmp_path, access="lan", tokens=token_store) as (application, transport):
        code_missing, _out_m, err_m = _invoke(
            ["capabilities", "--url", "http://192.168.10.5:8765"],
            transport=transport,
        )
        assert code_missing == 3
        assert "401" in err_m

        code_invalid, _out_i, err_i = _invoke(
            ["capabilities", "--url", "http://192.168.10.5:8765", "--token", "wrong-token"],
            transport=transport,
        )
        assert code_invalid == 3
        assert "401" in err_i

        code_env, out_env, err_env = _invoke(
            ["capabilities"],
            transport=transport,
            environ={
                "YUDAO_URL": "http://192.168.10.5:8765",
                "YUDAO_TOKEN": valid_token,
            },
        )
        assert code_env == 0, err_env
        assert json.loads(out_env)["deployment"]["access"] == "lan"

        code_stdin_tok, out_stdin_tok, err_stdin_tok = _invoke(
            ["capabilities", "--url", "http://192.168.10.5:8765", "--token-stdin"],
            transport=transport,
            stdin_text=f"{valid_token}\n",
        )
        assert code_stdin_tok == 0, err_stdin_tok
        assert json.loads(out_stdin_tok)["deployment"]["access"] == "lan"

        # 命令行 --token 优先于环境变量 YUDAO_TOKEN
        code_cmd, out_cmd, err_cmd = _invoke(
            [
                "command",
                "project.create",
                "--url",
                "http://192.168.10.5:8765",
                "--token",
                valid_token,
                "--param",
                "name=局域网项目",
            ],
            transport=transport,
            environ={"YUDAO_TOKEN": "stale-env-token"},
        )
        assert code_cmd == 0, err_cmd
        created = json.loads(out_cmd)
        project_id = created["refs"]["project_id"]
        events = application.system.store.list_project_events(project_id)
        assert events[0].actor == "user:ops-agent"

    for failure_kind in ("connect", "timeout"):
        code_net, _out_net, err_net = _invoke(
            ["capabilities", "--url", "http://127.0.0.1:9999"],
            transport=_FailingSyncTransport(failure_kind),
        )
        assert code_net == 3
        assert "http://127.0.0.1:9999" in err_net


def test_describe_extracts_command_and_query_contracts_and_hints_unknown_names(tmp_path: Path) -> None:
    # 守 R2：单项合同说明从能力清单与 OpenAPI 展开字段约束、返回结构摘要、拒绝原因或刷新事件与回放标记
    with _open_asgi_service(tmp_path) as (_app, transport):
        _cap_code, cap_out, _cap_err = _invoke(["capabilities"], transport=transport)
        capabilities = json.loads(cap_out)
        cmd_reasons = {item["name"]: item["reasons"] for item in capabilities["commands"]}
        qry_meta = {item["name"]: item for item in capabilities["queries"]}

        code_pc, out_pc, err_pc = _invoke(["describe", "project.create"], transport=transport)
        assert code_pc == 0, err_pc
        desc_pc = json.loads(out_pc)
        assert desc_pc["kind"] == "command"
        assert desc_pc["name"] == "project.create"
        assert desc_pc["rejections"] == cmd_reasons["project.create"]
        fields_pc = {field["name"]: field for field in desc_pc["request"]}
        assert fields_pc["command_id"]["required"] is True
        assert fields_pc["name"]["required"] is True
        assert fields_pc["goal"]["required"] is False
        resp_fields_pc = {field["name"]: field for field in desc_pc["response"]["fields"]}
        assert "position" in resp_fields_pc
        refs_subfields = {field["name"] for field in resp_fields_pc["refs"]["fields"]}
        assert "project_id" in refs_subfields

        code_ps, out_ps, err_ps = _invoke(["describe", "parameter.set"], transport=transport)
        assert code_ps == 0, err_ps
        desc_ps = json.loads(out_ps)
        assert desc_ps["kind"] == "command"
        assert set(desc_ps["rejections"]) == set(cmd_reasons["parameter.set"])
        fields_ps = {field["name"]: field for field in desc_ps["request"]}
        for req_field in ("command_id", "name", "value", "reason"):
            assert fields_ps[req_field]["required"] is True
        assert fields_ps["base_version"]["required"] is False

        # 验证嵌套对象引用展开与默认值、枚举提取
        code_cc, out_cc, err_cc = _invoke(["describe", "catalog.connection.save"], transport=transport)
        assert code_cc == 0, err_cc
        desc_cc = json.loads(out_cc)
        fields_cc = {field["name"]: field for field in desc_cc["request"]}
        assert any(sub["name"] == "base_url" for sub in fields_cc["provider"]["fields"])
        assert fields_cc["models"]["default"] == []
        assert any(sub["name"] == "protocol" for sub in fields_cc["models"]["fields"])

        code_po, out_po, err_po = _invoke(["describe", "project.overview"], transport=transport)
        assert code_po == 0, err_po
        desc_po = json.loads(out_po)
        assert desc_po["kind"] == "query"
        assert desc_po["name"] == "project.overview"
        assert desc_po["refresh_on"] == qry_meta["project.overview"]["changed_by"]
        assert desc_po["replayable"] is False
        fields_po = {field["name"]: field for field in desc_po["request"]}
        assert fields_po["project_id"]["required"] is True
        assert fields_po["work_item"]["required"] is False

        code_dl, out_dl, err_dl = _invoke(["describe", "decisions.list"], transport=transport)
        assert code_dl == 0, err_dl
        desc_dl = json.loads(out_dl)
        assert desc_dl["kind"] == "query"
        assert desc_dl["replayable"] is True
        fields_dl = {field["name"]: field for field in desc_dl["request"]}
        assert set(fields_dl["status"]["enum"]) == {"open", "answered", "withdrawn"}

        code_np, out_np, err_np = _invoke(["describe", "forms.list"], transport=transport)
        assert code_np == 0, err_np
        desc_np = json.loads(out_np)
        assert desc_np["kind"] == "query"
        assert desc_np["request"] == []

        code_unk1, _out_u1, err_u1 = _invoke(["describe", "project.nonexistent"], transport=transport)
        assert code_unk1 == 2
        assert "project.create" in err_u1
        assert "project.overview" in err_u1

        code_unk2, _out_u2, err_u2 = _invoke(["describe", "totally.unknown"], transport=transport)
        assert code_unk2 == 2
        assert "project.create" in err_u2


def test_roundtrip_operations_idempotency_and_rejection_exit_codes(tmp_path: Path) -> None:
    # 守 R1/R3：仅经命令行客户端完成新建项目、切换组织、修改与撤回参数、读取概览与回放查询；验证命令去重与过期版本拒绝
    with _open_asgi_service(tmp_path) as (_app, transport):
        code_init, out_init, err_init = _invoke(["query", "projects.list"], transport=transport)
        assert code_init == 0, err_init
        pos_before_project = json.loads(out_init)["position"]

        # 1. 新建项目：缺省自动填充 command_id，--string-param 保持前导零字符串
        code_create, out_create, err_create = _invoke(
            [
                "command",
                "project.create",
                "--param",
                "name=命令行往返项目",
                "--string-param",
                "goal=0042",
            ],
            transport=transport,
        )
        assert code_create == 0, err_create
        accepted_create = json.loads(out_create)
        assert accepted_create["duplicate"] is False
        assert len(accepted_create["command_id"]) == 36
        project_id = accepted_create["refs"]["project_id"]

        # 2. 显式 --command-id 幂等重发与身份重用冲突
        fixed_cid = "11111111-2222-4333-8444-555555555555"
        code_dup1, out_dup1, err_dup1 = _invoke(
            [
                "command",
                "project.create",
                "--command-id",
                fixed_cid,
                "--json",
                json.dumps({"name": "幂等项目"}),
            ],
            transport=transport,
        )
        assert code_dup1 == 0, err_dup1
        first_dup_res = json.loads(out_dup1)
        assert first_dup_res["duplicate"] is False

        code_dup2, out_dup2, err_dup2 = _invoke(
            [
                "command",
                "project.create",
                "--command-id",
                fixed_cid,
                "--json",
                json.dumps({"name": "幂等项目"}),
            ],
            transport=transport,
        )
        assert code_dup2 == 0, err_dup2
        second_dup_res = json.loads(out_dup2)
        assert second_dup_res["duplicate"] is True
        assert second_dup_res["refs"]["project_id"] == first_dup_res["refs"]["project_id"]

        code_reuse, out_reuse, _err_reuse = _invoke(
            [
                "command",
                "project.create",
                "--command-id",
                fixed_cid,
                "--json",
                json.dumps({"name": "另一个名字"}),
            ],
            transport=transport,
        )
        assert code_reuse == 1
        reuse_rejected = json.loads(out_reuse)
        assert reuse_rejected["reason"] == "command_id_reused"
        assert reuse_rejected["message"]

        # 3. 读取项目组织并采用新形态；验证过期 base_version 返回退出码 1 并打印拒绝 JSON
        code_org_q, out_org_q, err_org_q = _invoke(
            ["query", "project.organization", "--param", f"project_id={project_id}"],
            transport=transport,
        )
        assert code_org_q == 0, err_org_q
        org_version = json.loads(out_org_q)["data"]["version"]

        code_adopt, out_adopt, err_adopt = _invoke(
            [
                "command",
                "organization.adopt",
                "--param",
                f"project_id={project_id}",
                "--param",
                f"form={SINGLE_ROLE_DIRECT}",
                "--param",
                "changes={}",
                "--param",
                f"base_version={org_version}",
            ],
            transport=transport,
        )
        assert code_adopt == 0, err_adopt

        code_stale, out_stale, _err_stale = _invoke(
            [
                "command",
                "organization.adopt",
                "--param",
                f"project_id={project_id}",
                "--param",
                f"form={SINGLE_ROLE_DIRECT}",
                "--param",
                "changes={}",
                "--param",
                f"base_version={org_version}",
            ],
            transport=transport,
        )
        assert code_stale == 1
        stale_json = json.loads(out_stale)
        assert stale_json["reason"] == "stale_base"
        assert stale_json["message"]

        # 4. 读取规则登记，修改界内参数并撤回恢复原值
        code_rules1, out_rules1, err_rules1 = _invoke(["query", "rules.registry"], transport=transport)
        assert code_rules1 == 0, err_rules1
        rules_snap1 = json.loads(out_rules1)["data"]
        param_ver1 = rules_snap1["parameters_version"]
        entry1 = next(item for item in rules_snap1["rules"] if item["name"] == "run_time_limit_sec")
        original_limit = entry1["value"]

        code_pset, _out_pset, err_pset = _invoke(
            [
                "command",
                "parameter.set",
                "--param",
                "name=run_time_limit_sec",
                "--param",
                "value=3600",
                "--param",
                "reason=命令行调整运行上限",
                "--param",
                f"base_version={param_ver1}",
            ],
            transport=transport,
        )
        assert code_pset == 0, err_pset

        code_rules2, out_rules2, err_rules2 = _invoke(["query", "rules.registry"], transport=transport)
        assert code_rules2 == 0, err_rules2
        rules_snap2 = json.loads(out_rules2)["data"]
        param_ver2 = rules_snap2["parameters_version"]
        entry2 = next(item for item in rules_snap2["rules"] if item["name"] == "run_time_limit_sec")
        assert entry2["value"] == 3600
        change_id = entry2["changes"][-1]["event_id"]

        code_pwithdraw, _out_pw, err_pw = _invoke(
            [
                "command",
                "parameter.withdraw",
                "--param",
                "name=run_time_limit_sec",
                "--param",
                f"expected_change_id={change_id}",
                "--param",
                "reason=撤回：命令行调整运行上限",
                "--param",
                f"base_version={param_ver2}",
            ],
            transport=transport,
        )
        assert code_pwithdraw == 0, err_pw

        code_rules3, out_rules3, _err_r3 = _invoke(["query", "rules.registry"], transport=transport)
        assert code_rules3 == 0
        entry3 = next(
            item for item in json.loads(out_rules3)["data"]["rules"] if item["name"] == "run_time_limit_sec"
        )
        assert entry3["value"] == original_limit

        # 5. 查询项目概览（核对前导零字符串目标）、多值筛选参数与 --at 历史回放
        code_ov, out_ov, err_ov = _invoke(
            ["query", "project.overview", "--json", json.dumps({"project_id": project_id})],
            transport=transport,
        )
        assert code_ov == 0, err_ov
        overview = json.loads(out_ov)
        assert overview["position"] > pos_before_project
        assert overview["data"]["goal"] == "0042"
        assert overview["data"]["name"] == "命令行往返项目"

        code_multi, out_multi, err_multi = _invoke(
            [
                "query",
                "decisions.list",
                "--param",
                "status=open",
                "--param",
                "status=answered",
            ],
            transport=transport,
        )
        assert code_multi == 0, err_multi
        assert "decisions" in json.loads(out_multi)["data"]

        code_at, out_at, err_at = _invoke(
            ["query", "projects.list", "--at", str(pos_before_project)],
            transport=transport,
        )
        assert code_at == 0, err_at
        at_snap = json.loads(out_at)
        assert at_snap["position"] == pos_before_project
        assert at_snap["data"]["projects"] == []


def test_validation_errors_parameter_conflicts_and_timeout_bounds(tmp_path: Path) -> None:
    # 守 R2：未知命令或查询、请求校验错误（422）、超界 --timeout 与命令行参数冲突统一返回退出码 2
    with _open_asgi_service(tmp_path) as (_app, transport):
        # 422 请求体校验失败（缺少必填字段 name）
        code_422, _out_422, err_422 = _invoke(
            ["command", "project.create", "--json", "{}"],
            transport=transport,
        )
        assert code_422 == 2
        assert err_422.strip()

        # 422 查询位置超界
        code_q422, _out_q422, err_q422 = _invoke(
            ["query", "projects.list", "--at", "999999"],
            transport=transport,
        )
        assert code_q422 == 2
        assert err_q422.strip()

        # 404 未知命令与未知查询
        code_c404, _out_c404, err_c404 = _invoke(["command", "no.such.command"], transport=transport)
        assert code_c404 == 2
        assert "no.such.command" in err_c404

        code_q404, _out_q404, err_q404 = _invoke(["query", "no.such.query"], transport=transport)
        assert code_q404 == 2
        assert "no.such.query" in err_q404

        # --timeout 超出 5–600 秒范围或非数字
        for bad_timeout in ("4", "4.9", "601", "0", "-10", "not-a-number"):
            code_to, _out_to, err_to = _invoke(
                ["capabilities", "--timeout", bad_timeout],
                transport=transport,
            )
            assert code_to == 2, bad_timeout
            assert err_to.strip()

        # 参数冲突：--token 与 --token-stdin、--token-stdin 与 --stdin、--json 与 --stdin
        for conflict_argv in (
            ["capabilities", "--token", "abc", "--token-stdin"],
            ["command", "project.create", "--token-stdin", "--stdin"],
            ["command", "project.create", "--json", "{}", "--stdin"],
        ):
            code_cf, _out_cf, err_cf = _invoke(conflict_argv, transport=transport, stdin_text="{}")
            assert code_cf == 2, conflict_argv
            assert err_cf.strip()


def test_credential_secret_via_stdin_never_leaks_to_output_or_event_log(tmp_path: Path) -> None:
    # 守 R1/R3：经标准输入向 credential.set 传入密钥后，明文密钥不出现在标准输出、标准错误与事件日志中
    secret_value = "sk-ops-ultra-secret-never-appear-88271"
    with _open_asgi_service(tmp_path, with_dotenv=True) as (application, transport):
        stdin_payload = json.dumps(
            {
                "base_version": 0,
                "ref": "OPS_PROVIDER_KEY",
                "secret": secret_value,
                "persist": True,
            }
        )
        code, out, err = _invoke(
            ["command", "credential.set", "--stdin"],
            transport=transport,
            stdin_text=stdin_payload,
        )
        assert code == 0, err
        assert secret_value not in out
        assert secret_value not in err

        accepted = json.loads(out)
        assert accepted["position"] >= 1

        catalog_events = application.system.store.stream_events(catalog_stream())
        serialized_events = json.dumps(
            [
                {"type": ev.type, "actor": ev.actor, "payload": ev.payload}
                for ev in catalog_events
            ],
            ensure_ascii=False,
        )
        assert secret_value not in serialized_events
        cred_events = [ev for ev in catalog_events if ev.type == "credential_changed"]
        assert len(cred_events) == 1
        assert cred_events[0].payload["ref"] == "OPS_PROVIDER_KEY"
        assert (tmp_path / ".env").read_text(encoding="utf-8").strip() == f"OPS_PROVIDER_KEY={secret_value}"

        code_bad, out_bad, err_bad = _invoke(
            ["command", "credential.set", "--stdin"],
            transport=transport,
            stdin_text=f'{{"secret": "{secret_value}", broken_json',
        )
        assert code_bad == 2
        assert secret_value not in out_bad
        assert secret_value not in err_bad
