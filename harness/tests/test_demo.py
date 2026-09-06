from harness.demo import run_demo


def test_demo_fills_four_views(data_dir):
    system, run_id = run_demo(data_dir)
    projection = system.project(run_id)
    assert projection.phase == "DONE"
    assert projection.request_count == 3
    assert projection.rework_count == 1
    assert projection.product_spec.revision >= 2
    assert projection.reviews[0].checks[0]["name"] == "usage"
    assert projection.reviews[0].checks[0]["exit_code"] != 0
    assert {item["name"] for item in projection.last_review.checks} == {"echo", "flags", "usage"}
    assert all(item["exit_code"] == 0 for item in projection.last_review.checks)
    assert projection.delivery_specs
    assert projection.manifests
    assert any(event.type == "collaboration_requested" for event in system.store.list_events(run_id))
    assert any(event.type == "collaboration_responded" for event in system.store.list_events(run_id))
    from harness.views import run_payload

    payload = run_payload(system.store, run_id)
    assert payload["board"]["phase"] == "DONE"
    assert payload["timeline"]["requests"]
    assert payload["timeline"]["responses"]
    assert payload["evidence"]["reviews"]
    assert payload["context"]["manifests"]
