import sys, os, json, tempfile, shutil, traceback
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from fingerprint import fingerprint
import sync_state

BE = {"endpoints": [{"method": "GET", "path": "/users/{id}", "fields": ["created_at", "id"]}]}
APP = {"endpoints": [{"method": "GET", "path": "/users/{id}", "fields": ["createdAt", "id"]}]}


def _fresh_state():
    d = tempfile.mkdtemp()
    json.dump({"backend_hash_at_sync": None, "app_hash_at_sync": None,
               "synced_at": None, "state_dir_abspath": d, "owned_files": {}},
              open(os.path.join(d, "sync.json"), "w"))
    json.dump({}, open(os.path.join(d, "backend.fp.json"), "w"))
    json.dump({}, open(os.path.join(d, "app.fp.json"), "w"))
    return d


def test_write_slice_writes_hash_and_keys():
    d = _fresh_state()
    try:
        h = sync_state.write_slice(d, "backend", "sha1", BE, "t0")
        slc = json.load(open(os.path.join(d, "backend.fp.json")))
        assert h == fingerprint(BE)
        assert slc["git_sha"] == "sha1"
        assert slc["contract_hash"] == h
        assert "routes_digest" in slc and slc["updated_at"] == "t0"
    finally:
        shutil.rmtree(d)


def test_app_slice_uses_calls_digest():
    d = _fresh_state()
    try:
        sync_state.write_slice(d, "app", "sha1", APP, "t0")
        slc = json.load(open(os.path.join(d, "app.fp.json")))
        assert "calls_digest" in slc and "routes_digest" not in slc
    finally:
        shutil.rmtree(d)


def test_camel_and_snake_slices_hash_equal():
    d = _fresh_state()
    try:
        hb = sync_state.write_slice(d, "backend", "s", BE, "t0")
        ha = sync_state.write_slice(d, "app", "s", APP, "t0")
        assert hb == ha  # camelCase app contract == snake_case backend contract
    finally:
        shutil.rmtree(d)


def test_reconcile_from_app_writes_baselines():
    d = _fresh_state()
    try:
        hb = sync_state.write_slice(d, "backend", "s", BE, "t0")
        ha = sync_state.write_slice(d, "app", "s", APP, "t0")
        sync_state.reconcile(d, "app", "t1")
        sync = json.load(open(os.path.join(d, "sync.json")))
        assert sync["backend_hash_at_sync"] == hb
        assert sync["app_hash_at_sync"] == ha
        assert sync["synced_at"] == "t1"
        # preserved
        assert sync["owned_files"] == {} and sync["state_dir_abspath"] == d
    finally:
        shutil.rmtree(d)


def test_reconcile_from_backend_refused():
    d = _fresh_state()
    try:
        sync_state.write_slice(d, "backend", "s", BE, "t0")
        sync_state.write_slice(d, "app", "s", APP, "t0")
        try:
            sync_state.reconcile(d, "backend", "t1")
            assert False, "backend reconcile should raise (single-writer invariant)"
        except SystemExit:
            pass
    finally:
        shutil.rmtree(d)


def test_reconcile_refused_when_slice_not_fresh():
    d = _fresh_state()
    try:
        sync_state.write_slice(d, "app", "s", APP, "t0")  # backend slice still {}
        try:
            sync_state.reconcile(d, "app", "t1")
            assert False, "reconcile should raise when a slice is not fresh"
        except SystemExit:
            pass
    finally:
        shutil.rmtree(d)


def test_status_no_reconcile_before_baseline():
    d = _fresh_state()
    try:
        sync_state.write_slice(d, "backend", "s", BE, "t0")
        state, _ = sync_state.status(d, "app")
        assert state == "NO_RECONCILE"
    finally:
        shutil.rmtree(d)


def test_status_in_sync_after_reconcile():
    d = _fresh_state()
    try:
        sync_state.write_slice(d, "backend", "s", BE, "t0")
        sync_state.write_slice(d, "app", "s", APP, "t0")
        sync_state.reconcile(d, "app", "t1")
        state, _ = sync_state.status(d, "app")
        assert state == "IN_SYNC"
    finally:
        shutil.rmtree(d)


def test_status_moved_after_backend_changes():
    d = _fresh_state()
    try:
        sync_state.write_slice(d, "backend", "s", BE, "t0")
        sync_state.write_slice(d, "app", "s", APP, "t0")
        sync_state.reconcile(d, "app", "t1")
        changed = {"endpoints": [{"method": "GET", "path": "/users/{id}",
                                  "fields": ["created_ts", "id"]}]}
        sync_state.write_slice(d, "backend", "s2", changed, "t2")
        state, _ = sync_state.status(d, "app")
        assert state == "MOVED"
    finally:
        shutil.rmtree(d)


def test_check_fresh_skip_when_sha_matches_and_clean():
    d = _fresh_state()
    try:
        sync_state.write_slice(d, "backend", "sha1", BE, "t0")
        assert sync_state.check_fresh(d, "backend", "sha1", dirty=False) == "SKIP"
    finally:
        shutil.rmtree(d)


def test_check_fresh_derive_when_dirty():
    d = _fresh_state()
    try:
        sync_state.write_slice(d, "backend", "sha1", BE, "t0")
        assert sync_state.check_fresh(d, "backend", "sha1", dirty=True) == "DERIVE"
    finally:
        shutil.rmtree(d)


def test_check_fresh_derive_when_sha_differs():
    d = _fresh_state()
    try:
        sync_state.write_slice(d, "backend", "sha1", BE, "t0")
        assert sync_state.check_fresh(d, "backend", "sha2", dirty=False) == "DERIVE"
    finally:
        shutil.rmtree(d)


def test_check_fresh_derive_when_no_slice():
    d = _fresh_state()  # slices are {}
    try:
        assert sync_state.check_fresh(d, "backend", "sha1", dirty=False) == "DERIVE"
    finally:
        shutil.rmtree(d)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"PASS {fn.__name__}")
        except AssertionError:
            failed += 1; print(f"FAIL {fn.__name__}"); traceback.print_exc()
    sys.exit(1 if failed else 0)
