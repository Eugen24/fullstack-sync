---
description: Record a reconcile point — write the current backend + app contract hashes into sync.json so drift-since-reconcile can be detected. Run from the APP session only (it owns the state dir → single writer).
allowed-tools: Bash(git rev-parse:*), Bash(git status:*), Bash(date:*)
---

# Fullstack Sync — Reconcile

Record that the two parallel sessions agree RIGHT NOW, so later drift is measured
against this point. Read `${CLAUDE_PLUGIN_ROOT}/references/parallel-sync.md` for the
file shapes.

**Run this from the APP session only.** The app session owns the state dir, so it is
the single writer of `sync.json` — running reconcile from the backend session too would
reintroduce a two-writer file. If this is the backend session, stop and tell the user.

## 0. Load state

Read `.fullstack-sync/sync.json` (find it via `state_dir_abspath`). If missing → tell
the user to run `/fullstack-parallel-init`, then stop. Read both slices
`.fullstack-sync/backend.fp.json` and `.fullstack-sync/app.fp.json`.

## 1. Require both slices fresh

A slice is **fresh** when its `git_sha` equals that worktree's current HEAD and the tree
is clean. Verify the app side directly: `git rev-parse HEAD` must equal
`app.fp.json.git_sha`, and `git status --porcelain` must be empty. If not → tell the user
to run `parallel-sync-status` in the app session first (to refresh its slice), then stop.
For the backend side, trust `backend.fp.json` — the backend session is responsible for
having refreshed it via `parallel-sync-status`. If `backend.fp.json` is empty (`{}`) or
absent → tell the user the backend session hasn't run `parallel-sync-status` yet, stop.

## 2. Confirm

Show the user what will be recorded and confirm before writing:

```
RECONCILE
  backend: <backend.fp.json.contract_hash[:12]>  @ <backend.fp.json.git_sha[:7]>
  app:     <app.fp.json.contract_hash[:12]>      @ <app.fp.json.git_sha[:7]>
```

## 3. Write sync.json (single writer = this app session)

Update `.fullstack-sync/sync.json`, preserving `state_dir_abspath` and `owned_files`:
- `backend_hash_at_sync` = `backend.fp.json.contract_hash`
- `app_hash_at_sync`     = `app.fp.json.contract_hash`
- `synced_at`            = current UTC (`date -u +%Y-%m-%dT%H:%M:%SZ`)

## 4. Confirm

Print the new reconcile point. From now, `parallel-sync-status` reports the other side as
MOVED whenever its `contract_hash` differs from the value just recorded.
