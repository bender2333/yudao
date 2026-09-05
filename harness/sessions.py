"""部门 Session：每个部门独立 session，激活时从投影装配上下文。"""

from __future__ import annotations

from dataclasses import dataclass

from .models import DEPARTMENTS, new_id


@dataclass
class DepartmentSession:
    session_id: str
    run_id: str
    department: str
    status: str = "idle"
    activations: int = 0
    last_activation_id: str | None = None

    def activate(self) -> str:
        self.status = "active"
        self.activations += 1
        self.last_activation_id = new_id("act")
        return self.last_activation_id

    def idle(self) -> None:
        if self.status != "closed":
            self.status = "idle"

    def close(self, status: str = "closed") -> None:
        self.status = status


class SessionFactory:
    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, DepartmentSession]] = {}

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

    def for_run(self, run_id: str) -> dict[str, DepartmentSession]:
        return self._sessions[run_id]

    def abort_run(self, run_id: str) -> None:
        for session in self._sessions.get(run_id, {}).values():
            if session.status == "active":
                session.close("aborted")

    def close_run(self, run_id: str) -> None:
        for session in self._sessions.get(run_id, {}).values():
            session.close("closed")
