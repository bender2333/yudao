import argparse
import json
from pathlib import Path

from harness.models import EventType
from harness.tests.helpers import FAST_RETRIES
from harness.tests.protocol_helpers import provider_system

# 由测试在新进程中启动：经真实 Provider 模块运行产品部门的一次激活，其中的模型请求是这个进程内的第一次请求。
# 用法：python -m harness.tests.first_request <服务地址> <协议> <请求时限秒数> <数据目录>
# 结果以一行 JSON 打印：运行阶段、停止原因与每次失败尝试的原因


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("base")
    parser.add_argument("protocol")
    parser.add_argument("timeout_sec", type=float)
    parser.add_argument("data_dir", type=Path)
    args = parser.parse_args()
    system, run_id = provider_system(args.data_dir, args.base, args.protocol, timeout_sec=args.timeout_sec,
                                     step_limits=FAST_RETRIES)
    try:
        result = system.activate_once(run_id)
        failed = [event.payload["reason"] for event in system.store.list_events(run_id)
                  if event.type == EventType.MODEL_ATTEMPT_FAILED]
        print(json.dumps({"status": result.status, "stop_reason": result.stop_reason, "failed": failed}))
    finally:
        system.close()


if __name__ == "__main__":
    main()
