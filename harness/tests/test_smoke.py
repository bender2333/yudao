from harness.smoke import smoke_exit_code


def test_smoke_requires_host_receipts_and_rejects_fake():
    base = {
        "phase": "DONE",
        "stop_reason": "released",
        "replay_consistent": True,
        "context_isolated": True,
        "check_receipts": [{"name": "smoke", "exit_code": 0}],
        "fake_used": False,
        "ask_count": 1,
    }
    assert smoke_exit_code({"available": True, "scenarios": {"happy": base, "ask": base}}) == 0
    assert smoke_exit_code({"available": False, "scenarios": {}}) == 2
    assert smoke_exit_code({"available": True, "scenarios": {"happy": dict(base, fake_used=True)}}) == 2
    assert smoke_exit_code({"available": True, "scenarios": {"happy": dict(base, check_receipts=[])}}) == 1
    assert smoke_exit_code({"available": True, "scenarios": {"ask": dict(base, ask_count=0)}}) == 1
