---
description: Set up parallel-mode contract sync — create the .fullstack-sync/ state dir, auto-detect shared-file ownership, print the git worktree commands for both repos
allowed-tools: Bash(git rev-parse:*), Bash(pwd:*), Bash(ls:*), Bash(mkdir:*), Bash(date:*)
---

# Fullstack Sync — Parallel Init

Set up two-session parallel mode. Read `${CLAUDE_PLUGIN_ROOT}/references/parallel-sync.md`
first — it defines every file shape you write here.

App repo root: !`git rev-parse --show-toplevel 2>/dev/null || pwd`

## Step 1 — Require v1 config

Read `.fullstack-sync.json` at the app root. If missing → tell the user to run
`/fullstack-setup` first, then stop. Pull `app.root`, `backend.root`, `extra_dirs`.

## Step 2 — Create the state dir

```
mkdir -p .fullstack-sync
```

## Step 3 — Auto-detect shared-file ownership

Model B (two sessions writing the same file) is impossible across two separate repos.
It only applies if a THIRD shared surface exists. Inspect `extra_dirs` and the repo roots
for a dir both sides import (shared types/proto/openapi). 
- If NONE → `owned_files` is `{}` (dormant — the common case).
- If FOUND → propose a glob→owner map with **AskUserQuestion**, defaulting each shared
  glob to `backend` (backend names are the contract source of truth).

## Step 4 — Write sync.json

Write `.fullstack-sync/sync.json` using the shape in the reference. Set
`state_dir_abspath` to the absolute path of `.fullstack-sync`, `synced_at` to
!`date -u +%Y-%m-%dT%H:%M:%SZ`, both `*_hash_at_sync` to `null` (no reconcile yet),
and `owned_files` from Step 3. Also create empty `backend.fp.json` and `app.fp.json`
as `{}` placeholders.

## Step 5 — Print worktree commands

Print, for the user to run (do NOT run them — the user chooses branch names):

```
git -C <backend.root> worktree add ../backend-<feature> -b <feature>
git -C <app.root>     worktree add ../app-<feature>     -b <feature>
```

Tell them: open one `claude` session in each worktree. In the backend session,
`/add-dir <app.root>` so it can read `.fullstack-sync/`. Then each session uses
`parallel-sync-status` to check drift and `fullstack-feature` to build its side.
