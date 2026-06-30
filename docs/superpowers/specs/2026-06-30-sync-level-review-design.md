# Sync-Level Review Nudge — Design

**Date:** 2026-06-30
**Status:** Approved design, pre-implementation
**Builds on:** v0.2 parallel contract sync — `scripts/fingerprint.py`, `scripts/extract_fastapi.py`, `scripts/sync_state.py`, `.fullstack-sync.json`, `api-contract-sync`.

## Goal

After a contract-affecting change, a quiet Stop hook offers a scoped review so drift
never ships unreviewed — without nagging the user into muting it. Three opt-in levels
trade safety for automation. **Safe by default:** the plugin asks for the dir, then uses
it; it spends no tokens and touches no code or commits unless the user permits.

## Levels (`sync_level` in `.fullstack-sync.json`, default `low`)

| Level | Tokens / edits | Commits |
|---|---|---|
| **off** | none | never |
| **low** *(default)* | only when the user accepts the nudge | never — review is report-only, user commits |
| **hard** *(opt-in autopilot)* | auto: sync + full review | auto-commit + merge, **feature branch only (refuses on master/main)** |

- **off** — silent, fully manual.
- **low** — Stop hook, drift-gated, prints a one-line **suggest-only** nudge for a scoped
  review of the moved contract. Never blocks, never auto-runs, never edits.
- **hard** — when the user opts in, detected drift triggers automatic `api-contract-sync`
  (applies fixes both sides) + the full cross-side review, then **auto-commits and merges**.
  Available as `/fullstack-sync-review --hard` and as a hook mode.

## Components

### 1. Stop hook — `hooks/sync-stop.sh`

Fires when the model finishes a turn. Cheap by construction:

1. No `.fullstack-sync.json`, or `sync_level: off`, or not a git repo → **exit 0 silent**.
2. **Cheap pre-gate:** `git diff --name-only HEAD` + untracked, filtered by the contract
   globs (`routers_glob`, `endpoints_file`, `services_glob`, `schemas_glob`). No contract
   file touched → **exit 0 silent** (the ~95% case, near-zero cost).
3. Contract files touched → determine drift:
   - **FastAPI backend** → run `extract_fastapi.py` + `fingerprint.py`, compare to the last
     hash in `.fullstack-sync.hook.json` (gitignored, hook-owned state). Different → MOVED.
   - **Other stacks** → coarse: "contract files changed" = MOVED (no deterministic
     extractor yet). Documented limit.
   - Update `.fullstack-sync.hook.json`.
4. On MOVED:
   - **low** → print one-line suggest-only nudge pointing at `/fullstack-sync-review` /
     `api-contract-sync`. Exit 0 (non-blocking).
   - **hard** → emit a follow-up instruction that triggers the autopilot review+sync (the
     hook injects the run; it does not itself edit code). The branch guard (below) is
     enforced by the review skill, not the hook.

The hook never edits code and never commits. Always exits 0.

### 2. Review — `fullstack-sync-review` skill + `/fullstack-sync-review` command

Report-only by default; fixes on request (low) or automatic (hard). Reads
`.fullstack-sync.json` for `backend.root`, `app.root`, and globs.

- **low scope** = the diff of the moved contract. **Lenses auto-picked by change type:**
  - route/path/method change → `contract`, `security`
  - field/schema change → `contract`, `params`
  - logic-only change → `bugs`, `best-practice`
- **hard scope** = full diff across **both** repos. **All lenses:** api, routes, params,
  logic, architecture, bugs, improvements, best-practice, security.
- **Output:** one line per finding — `path:line: <severity>: <problem>. <fix>.`
- Reuses `api-contract-sync` for the contract dimension (no duplication).
- **hard autopilot:** after reporting, apply the sync fixes, then commit + merge — but
  **only if the current branch is not the default branch** (`master`/`main`). On the
  default branch, hard refuses to auto-commit, prints the findings, and tells the user to
  branch first. This guard prevents automatic rewrites of mainline history.

### 3. Config

`.fullstack-sync.json` gains `"sync_level"` (`off` | `low` | `hard`). `/fullstack-setup`
writes it (default `low`). Absent → treated as `low`.

### 4. Registration & docs

- `.claude-plugin/plugin.json` — register the Stop hook; update `description` with the
  "safe by default; hard mode is opt-in autopilot" framing.
- `README.md` — a "Sync levels" section stating safe-by-default (asks for the dir, never
  spends tokens or touches commits unless permitted) and the hard-mode guard.
- `.gitignore` already ignores `.fullstack-sync/`; add `.fullstack-sync.hook.json`.

## Error handling

- No config / not a git repo / no git → hook exits silent.
- `extract_fastapi` parse error → fall back to the coarse gate (file-touched), never crash
  the turn.
- hard on default branch → refuse auto-commit, report only, instruct to branch.

## Testing

- **Hook** (`tests/test_sync_hook.sh`, bash, like `test_protocol.sh`): in a fixture repo —
  no change → silent (no nudge); non-contract file changed → silent; route/field changed →
  nudge printed. Asserts the cheap-gate and FastAPI drift detection.
- **Review skill** — markdown, validated by inspection (lens table present, report-only
  default, hard branch-guard wording) — not unit-tested, consistent with the other skills.
- Full suite (`tests/run.sh`) gains the hook test.

## Honest limits

- Non-FastAPI stacks get the **coarse** gate (file-touched, not hash-confirmed) until more
  extractors exist.
- The hook surfaces a nudge; it cannot run an interactive menu. By design.
- hard-mode autopilot edits and commits automatically — opt-in only, and fenced off the
  default branch by the guard.
