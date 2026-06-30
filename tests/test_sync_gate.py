import sys, os, traceback
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from sync_gate import match_contract_files, decide

CHANGED = ["routers/users.py", "routers/sub/orders.py", "README.md", "lib/api.dart"]
GLOBS = ["routers/**/*.py", "lib/api.dart"]


def test_match_keeps_glob_and_exact_drops_others():
    got = sorted(match_contract_files(CHANGED, GLOBS))
    assert got == ["lib/api.dart", "routers/sub/orders.py", "routers/users.py"]


def test_match_single_star_not_cross_dir():
    # "routers/*.py" must NOT match a nested file
    assert match_contract_files(["routers/a/b.py"], ["routers/*.py"]) == []
    assert match_contract_files(["routers/b.py"], ["routers/*.py"]) == ["routers/b.py"]


def test_match_ignores_empty_globs():
    assert match_contract_files(["x.py"], ["", None]) == []


def test_decide_silent_when_no_contract_change():
    assert decide(False, "abc", "abc") == "SILENT"


def test_decide_nudge_coarse_when_no_current_hash():
    assert decide(True, None, "abc") == "NUDGE"


def test_decide_nudge_when_hash_moved():
    assert decide(True, "new", "old") == "NUDGE"


def test_decide_silent_when_hash_unchanged():
    # contract file touched (e.g. a comment) but hash identical
    assert decide(True, "same", "same") == "SILENT"


def test_decide_nudge_on_first_run_precise():
    assert decide(True, "abc", None) == "NUDGE"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"PASS {fn.__name__}")
        except AssertionError:
            failed += 1; print(f"FAIL {fn.__name__}"); traceback.print_exc()
    sys.exit(1 if failed else 0)
