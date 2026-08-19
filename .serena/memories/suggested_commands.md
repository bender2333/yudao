Targeted test: python -m pytest harness/tests/test_work_order_loop.py -q
Full harness tests: python -m pytest harness/tests -q
CLI smoke: python -m harness.run_solo --help; python -m harness.run_multi --help
Git: git status --short --branch; git add <explicit paths>; git commit -m <message>