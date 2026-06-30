---
name: parallel-sync-status
description: Report whether this parallel session is in sync with the other side, or whether the other side's API contract has moved since the last reconcile. Use in two-session parallel mode when the user asks "am I in sync", "did the backend change", "is my contract stale", "check parallel status", before building against the other side, or before committing. Reads the per-session fingerprint slices under .fullstack-sync/ and reports drift — it does NOT fix drift (use api-contract-sync for that).
---

# Parallel Sync Status

Report drift between the two parallel sessions. Read
`${CLAUDE_PLUGIN_ROOT}/references/parallel-sync.md` for the file shapes. Report only —
never edit code here.

## 0. Locate state

Read `.fullstack-sync/sync.json` (find it via `state_dir_abspath` if this is the backend
session and the app root was added with `/add-dir`). If absent → tell the user to run
`/fullstack-parallel-init`, then stop. Determine which side THIS session is
(backend if the cwd is the backend repo, else app).

## 1. Refresh my own slice

Decide whether re-derivation can be skipped with the tested guard (prints `SKIP`/`DERIVE`,
exit 0/1) — pass `--dirty` when `git status --porcelain` is non-empty:

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/sync_state.py check-fresh \
  --state-dir <state_dir> --side <backend|app> --git-sha "$(git rev-parse HEAD)" \
  $(test -n "$(git status --porcelain)" && echo --dirty)
```

On `SKIP` the contract can't have changed — stop here. On `DERIVE`, re-derive my contract
exactly as `api-contract-sync` does (my routes,
or my calls), build the `{"endpoints":[...]}` input (normalize paths; pass field names
RAW — the helper normalizes camelCase/snake itself). Then write my slice with the tested
helper (it hashes + writes the right keys):

```
echo '<endpoints-json>' | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/sync_state.py \
  write-slice --state-dir <state_dir> --side <backend|app> --git-sha <HEAD> --now <UTC>
```

## 2. Check the other side

Compute staleness with the same helper (exit 0 IN_SYNC, 2 MOVED, 3 NO_RECONCILE):

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/sync_state.py status --state-dir <state_dir> --side <mine>
```

Equivalent rule it applies — `other.contract_hash` vs `sync.json.<other>_hash_at_sync`:
  - equal (or `*_hash_at_sync` is null and the other slice is fresh) → **in sync** on the
    other side.
  - different → **the other side moved** since the last reconcile.

## 3. Report

```
PARALLEL STATUS  (this session: <backend|app>)
  my contract:    <hash[:12]>  @ <git_sha[:7]>
  other side:     <hash[:12]>  @ <git_sha[:7]>   [IN SYNC | MOVED since reconcile | NO SLICE YET]
  last reconcile: <synced_at | never>
```

If the other side MOVED → tell the user to run **api-contract-sync** before building
against it (that skill does the deep diff + fix and is the only thing that should change
code). If both slices are fresh and equal, suggest the user run `/fullstack-reconcile` from
the app session to record the reconcile point (that command is the only writer of
`sync.json.*_hash_at_sync` — this skill never writes it).

## Output

The status block above, plus one next-step line. Never claim "synced" without having
recomputed THIS session's slice in step 1.
