"""部门适配器：fake 与 OMP 共用同一调用接口。"""

from .base import AdapterResult, Availability, DepartmentAdapter, InvokeRequest, ProviderError
from .fake import FakeAdapter, FakeTurn
from .omp import OmpConfig, OmpRpcAdapter

__all__ = [
    "AdapterResult",
    "Availability",
    "DepartmentAdapter",
    "FakeAdapter",
    "FakeTurn",
    "InvokeRequest",
    "OmpConfig",
    "OmpRpcAdapter",
    "ProviderError",
]
