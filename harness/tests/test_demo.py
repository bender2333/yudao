from harness.demo import run_demo


def test_demo_fills_four_views(data_dir):
    system, run_id = run_demo(data_dir)
    projection = system.project(run_id)
    assert projection.phase == "DONE"
    assert projection.ask_count == 1
    assert projection.rework_count == 1
    assert projection.product_spec.revision >= 2
    assert projection.delivery_specs
    assert projection.manifests
    assert any(event.type == "ask_submitted" for event in system.store.list_events(run_id))
    assert any(event.type == "react_submitted" for event in system.store.list_events(run_id))
    from harness.views import run_payload

    payload = run_payload(system.store, run_id)
    assert payload["board"]["phase"] == "DONE"
    assert payload["timeline"]["asks"]
    assert payload["timeline"]["reactions"]
    assert payload["evidence"]["reviews"]
    assert payload["context"]["manifests"]
