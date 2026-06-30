---
name: fullstack-sync-review
description: Review contract-affecting changes between a client app and its backend after an edit. Use when the user says "review the sync", "fullstack review", "review my api changes", "check routes/params/security", accepts the post-change nudge, or runs /fullstack-sync-review. Reports findings one per line (location, problem, fix); does not edit unless asked. A `--hard` / "hard review" pass covers both repos across all lenses and, on a feature branch only, can auto-sync + commit.
---

# Fullstack Sync Review

Review what changed in the contract and report findings. Read `.fullstack-sync.json`
(app root) for `backend.root`, `app.root`, the globs, and `sync_level`. Default is
**report-only** — do not edit unless the user asks (low) or hard autopilot applies.

## 1. Scope

- **low** (default): review the **diff of the contract-affecting change** only —
  `git diff` on the touched routers/schemas (backend) or endpoints/services (app). Do not
  read the whole repo.
- **hard** (`--hard` or "hard review"): review the **full diff across BOTH repos**
  (`backend.root` and `app.root`).

## 2. Lenses

Pick lenses by what changed (low) or use all (hard):

| Change type | Lenses (low) |
|---|---|
| route / path / method | contract, security |
| field / schema / param | contract, params |
| logic only (no contract move) | bugs, best-practice |

**hard** runs every lens: api, routes, params, logic, architecture, bugs, improvements,
best-practice, security. For the **contract** lens, invoke `api-contract-sync` rather than
re-deriving drift here.

## 3. Report

One line per finding, most severe first:

```
<path>:<line>: <BLOCKER|WARN|NIT>: <problem>. <fix>.
```

Collapse "looks fine" areas to a count. End with a one-line summary.

## 4. Fixes

- **low**: report only. Offer to apply fixes; apply only what the user approves.
- **hard autopilot** — the branch check comes FIRST, before any commit:
  1. **Check the branch:** `git rev-parse --abbrev-ref HEAD`. If it is `master` or `main`,
     **refuse** to auto-commit: print the findings, say "hard autopilot won't commit on the
     default branch — create a feature branch first", and stop. Do NOT run the fixes or
     commit on the default branch.
  2. Only on a non-default branch: run the sync fixes (`api-contract-sync`) on both sides,
     then stage + commit the synced changes with a message like
     `sync: reconcile contract (<endpoint>)`, and merge per the user's normal flow.

## Output

The findings block + the chosen scope/level + (hard) what was committed or why it was
refused.
