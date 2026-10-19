"""部门 Session：每个部门独立 session，激活时从投影装配上下文，会话结束时按部门删除检查工作区。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .environment import cleanup_inspection_workspace, stop_jobs_for_run
from .models import DEPARTMENTS, new_id

@dataclass
class DepartmentSession:
    session_id: str
    run_id: str
    department: str
    status: str = "idle"
    activations: int = 0
    last_activation_id: str | None = None
    _jobs: dict[str, Any] = field(default_factory=dict)
    _environments: list[Any] = field(default_factory=list)

    def attach_environment(self, environment: Any) -> None:
        self._environments.append(environment)
        environment.session = self

    def register_job(self, job: Any) -> None:
        self._jobs[job.job_id] = job

    def stop_jobs(self) -> None:
        for job in list(self._jobs.values()):
            if hasattr(job, "stop"):
                job.stop()
        self._jobs.clear()
        for env in self._environments:
            if hasattr(env, "stop_jobs"):
                env.stop_jobs()
        self._environments.clear()

    def activate(self, activation_id: str) -> None:
        self.status = "active"
        self.activations += 1
        self.last_activation_id = activation_id

    def idle(self) -> None:
        if self.status != "closed":
            self.status = "idle"

    def close(self, status: str = "closed") -> None:
        self.status = status
        self.stop_jobs()
class SessionFactory:
    # 会话在内存中按 run 维护；会话结束（DONE / PAUSED / FAILED / 取消）时按部门删除其检查工作区。
    # workspace_root 由编排器在创建时给出，回调在同一线程中执行；回调抛错时把它留在调用方（编排器已经
    # 在 on_commit 内记录错误并继续事务）
    def __init__(self, workspace_root: str | Path | None = None) -> None:
        self._sessions: dict[str, dict[str, DepartmentSession]] = {}
        self._workspace_root = Path(workspace_root) if workspace_root is not None else None

    def create_run_sessions(self, run_id: str, session_ids: dict[str, str] | None = None) -> dict[str, DepartmentSession]:
        ids = session_ids or {department: new_id(f"ses_{department[:3]}") for department in DEPARTMENTS}
        sessions = {
            department: DepartmentSession(session_id=ids[department], run_id=run_id, department=department)
            for department in DEPARTMENTS
        }
        self._sessions[run_id] = sessions
        return sessions

    def get(self, run_id: str, department: str) -> DepartmentSession:
        if run_id not in self._sessions:
            raise KeyError(run_id)
        return self._sessions[run_id][department]

    def cleanup_run(self, run_id: str) -> list[Exception]:
        # 删除 run 的全部会话检查工作区；返回未删除部门的错误清单，由调用方决定如何处理。
        # 没有 workspace_root（纯内存测试）时直接返回空
        stop_jobs_for_run(run_id)
        for session in self._sessions.get(run_id, {}).values():
            session.stop_jobs()
        errors: list[Exception] = []
        if self._workspace_root is None:
            return errors
        for department in DEPARTMENTS:
            try:
                cleanup_inspection_workspace(self._workspace_root / run_id, department)
            except RuntimeError as exc:
                errors.append(exc)
        return errors

    def close_run(self, run_id: str) -> list[Exception]:
        # 关闭 run 的所有会话并清理检查工作区；保留原副作用关闭会话，清理错误作为返回值由编排器写到事件
        stop_jobs_for_run(run_id)
        for session in self._sessions.get(run_id, {}).values():
            session.close("closed")
        return self.cleanup_run(run_id)
