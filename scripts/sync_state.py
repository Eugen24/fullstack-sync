#!/usr/bin/env python3
"""Mechanical state operations for parallel contract sync.

Encapsulates the .fullstack-sync/ file protocol so the coordination logic is
tested CODE, not skill prose. The skills invoke these subcommands for the
mechanical steps (write a slice, reconcile, check drift); the model still does
the contract EXTRACTION (parsing routes/calls into the endpoints JSON).

Subcommands:
  write-slice --state-dir D --side backend|app --git-sha S [--now T]  (contract on stdin)
  reconcile   --state-dir D --side app [--now T]
  status      --state-dir D --side backend|app

Single-writer invariant: only the app session may run `reconcile` (it owns the
state dir → sole writer of sync.json). Running it from backend is refused.

Exit codes for `status`: 0 IN_SYNC, 2 MOVED, 3 NO_RECONCILE.
"""
import sys, os, json, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fingerprint import fingerprint

SLICE = {"backend": "backend.fp.json", "app": "app.fp.json"}
OTHER = {"backend": "app", "app": "backend"}
HASH_KEY = {"backend": "backend_hash_at_sync", "app": "app_hash_at_sync"}
DIGEST_KEY = {"backend": "routes_digest", "app": "calls_digest"}
STATUS_EXIT = {"IN_SYNC": 0, "MOVED": 2, "NO_RECONCILE": 3}


def _load(path):
    with open(path) as f:
        return json.load(f)


def _dump(path, data):
    with open(path, "w") as f:
        json.dump(data, f)


def write_slice(state_dir, side, git_sha, contract, now):
    """Compute the contract hash and write this side's fingerprint slice."""
    h = fingerprint(contract)
    _dump(os.path.join(state_dir, SLICE[side]), {
        "git_sha": git_sha,
        "contract_hash": h,
        DIGEST_KEY[side]: contract.get("endpoints", []),
        "updated_at": now,
    })
    return h


def reconcile(state_dir, side, now):
    """Record the reconcile baseline. App session only (single writer)."""
    if side != "app":
        raise SystemExit(
            "reconcile must run from the app session (single writer of sync.json)")
    be = _load(os.path.join(state_dir, SLICE["backend"]))
    app = _load(os.path.join(state_dir, SLICE["app"]))
    for name, slc in (("backend", be), ("app", app)):
        if "contract_hash" not in slc:
            raise SystemExit(
                f"{name} slice not fresh yet — run parallel-sync-status in the "
                f"{name} session first")
    sync_path = os.path.join(state_dir, "sync.json")
    d = _load(sync_path)
    d["backend_hash_at_sync"] = be["contract_hash"]
    d["app_hash_at_sync"] = app["contract_hash"]
    d["synced_at"] = now
    _dump(sync_path, d)
    return d


def check_fresh(state_dir, side, current_sha, dirty):
    """Decide whether re-derivation can be skipped (cheap-skip guard).

    SKIP only when my slice's git_sha equals the current worktree HEAD AND the
    tree is clean — an uncommitted edit doesn't move HEAD, so a dirty tree must
    re-derive. The caller supplies `dirty` (e.g. `git status --porcelain`
    non-empty) since the git context lives in the session, not here.
    """
    slc = _load(os.path.join(state_dir, SLICE[side]))
    if not dirty and slc.get("git_sha") == current_sha and "contract_hash" in slc:
        return "SKIP"
    return "DERIVE"


def status(state_dir, side):
    """Has the OTHER side moved since the last reconcile?

    Returns (state, other_hash) where state is IN_SYNC | MOVED | NO_RECONCILE.
    """
    other = OTHER[side]
    sync = _load(os.path.join(state_dir, "sync.json"))
    other_slice = _load(os.path.join(state_dir, SLICE[other]))
    other_hash = other_slice.get("contract_hash")
    baseline = sync.get(HASH_KEY[other])
    if baseline is None:
        return ("NO_RECONCILE", other_hash)
    if other_hash != baseline:
        return ("MOVED", other_hash)
    return ("IN_SYNC", other_hash)


def _main(argv):
    p = argparse.ArgumentParser(prog="sync_state")
    sub = p.add_subparsers(dest="cmd", required=True)

    ws = sub.add_parser("write-slice")
    ws.add_argument("--state-dir", required=True)
    ws.add_argument("--side", required=True, choices=("backend", "app"))
    ws.add_argument("--git-sha", required=True)
    ws.add_argument("--now", default="")

    rc = sub.add_parser("reconcile")
    rc.add_argument("--state-dir", required=True)
    rc.add_argument("--side", required=True, choices=("backend", "app"))
    rc.add_argument("--now", default="")

    st = sub.add_parser("status")
    st.add_argument("--state-dir", required=True)
    st.add_argument("--side", required=True, choices=("backend", "app"))

    cf = sub.add_parser("check-fresh")
    cf.add_argument("--state-dir", required=True)
    cf.add_argument("--side", required=True, choices=("backend", "app"))
    cf.add_argument("--git-sha", required=True)
    cf.add_argument("--dirty", action="store_true",
                    help="pass when `git status --porcelain` is non-empty")

    a = p.parse_args(argv)
    if a.cmd == "write-slice":
        contract = json.load(sys.stdin)
        h = write_slice(a.state_dir, a.side, a.git_sha, contract, a.now)
        print(h)
        return 0
    if a.cmd == "reconcile":
        d = reconcile(a.state_dir, a.side, a.now)
        print(f"reconciled backend={d['backend_hash_at_sync'][:12]} "
              f"app={d['app_hash_at_sync'][:12]}")
        return 0
    if a.cmd == "status":
        state, other_hash = status(a.state_dir, a.side)
        oh = (other_hash or "none")[:12]
        print(f"{state} other={oh}")
        return STATUS_EXIT[state]
    if a.cmd == "check-fresh":
        decision = check_fresh(a.state_dir, a.side, a.git_sha, a.dirty)
        print(decision)
        return 0 if decision == "SKIP" else 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
