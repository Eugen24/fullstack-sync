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

Get this worktree's HEAD: `git rev-parse HEAD`. If it equals the `git_sha` already in my
slice (`backend.fp.json` or `app.fp.json`) AND `git status --porcelain` is empty, skip
re-derivation — the contract can't have changed. If the tree is dirty, re-derive (an
uncommitted edit doesn't move HEAD). Otherwise re-derive my contract exactly as `api-contract-sync` does (my routes,
or my calls), build the `{"endpoints":[...]}` input (normalize paths, snake_case fields;
on the app side map camelCase→snake), pipe it through
`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/fingerprint.py`, and write my slice
(`git_sha`, `contract_hash`, `routes_digest`/`calls_digest`, `updated_at`).

## 2. Check the other side

Read the OTHER slice. Compute staleness:
- `other.contract_hash` vs `sync.json.<other>_hash_at_sync`:
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
