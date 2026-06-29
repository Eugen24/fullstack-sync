# Parallel-Safe Contract Coordination Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let two Claude sessions (backend worktree + app worktree) build a fullstack feature in parallel without drifting the API contract or clobbering each other, via on-demand fingerprint comparison.

**Architecture:** Each session owns a single write-only fingerprint slice under a gitignored `.fullstack-sync/` dir. Drift = comparing the other side's structural contract hash to the last reconciled hash in `sync.json`. No event log (git is the log), no locks (single-writer partition), no orchestrator (the human runs the terminals). Shared-file conflict (only possible with a third shared package) is killed by auto-detected ownership + git-merge backstop.

**Tech Stack:** Claude Code plugin (markdown skills/commands + a `references/` protocol doc) + one Python 3 fingerprint helper (stdlib only). Existing v1: `.fullstack-sync.json`, `api-contract-sync`, `fullstack-feature`.

## Global Constraints

- Fingerprint helper: **Python 3 stdlib only** — no pip deps. Tests run with bare `python3`, no pytest.
- Fingerprint scope is **structural only**: `method`, normalized `path`, sorted `field-names`. Never hash auth gates, error strings, or envelopes.
- State dir `.fullstack-sync/` lives at the **app repo root**; must be gitignored.
- One writer per state file: backend session writes ONLY `backend.fp.json`; app session writes ONLY `app.fp.json`; `sync.json` written only by whichever session runs reconcile/init.
- Plugin manifest version bumps to **0.2.0** on completion.
- Markdown deliverables (skills/commands/reference) are not unit-testable; their "test" step is a concrete validation procedure with expected file contents, not a unit test.

---

### Task 1: Protocol reference doc

**Files:**
- Create: `references/parallel-sync.md`

**Interfaces:**
- Produces: the canonical definitions every later task reads — the three state-file shapes, the `endpoints` contract-input shape consumed by the fingerprint helper (Task 2), ownership rules, and worktree setup. Exact field names defined here are reused verbatim in Tasks 2–5.

- [ ] **Step 1: Write the reference doc**

Create `references/parallel-sync.md` with this exact content:

````markdown
# Parallel Contract Sync — Protocol

How two Claude sessions coordinate a fullstack feature without drifting the
contract or clobbering each other. Read this before using `parallel-sync-status`,
`/fullstack-parallel-init`, or `fullstack-feature` in parallel mode.

## State directory

`.fullstack-sync/` at the app repo root, gitignored. One writer per file.

### `backend.fp.json` — written ONLY by the backend session
```json
{ "git_sha": "<HEAD sha of backend worktree>",
  "contract_hash": "<sha256 from fingerprint helper>",
  "routes_digest": [ { "method": "GET", "path": "/v3/users/{id}", "fields": ["created_at","email","id"] } ],
  "updated_at": "<ISO-8601 UTC>" }
```

### `app.fp.json` — written ONLY by the app session
```json
{ "git_sha": "<HEAD sha of app worktree>",
  "contract_hash": "<sha256 from fingerprint helper>",
  "calls_digest": [ { "method": "GET", "path": "/v3/users/{id}", "fields": ["createdAt","email","id"] } ],
  "updated_at": "<ISO-8601 UTC>" }
```

### `sync.json` — written only by init / reconcile
```json
{ "backend_hash_at_sync": "<contract_hash at last reconcile>",
  "app_hash_at_sync": "<contract_hash at last reconcile>",
  "synced_at": "<ISO-8601 UTC>",
  "state_dir_abspath": "/abs/path/to/app/.fullstack-sync",
  "owned_files": {} }
```

## Contract-input shape (fed to the fingerprint helper)

The helper at `scripts/fingerprint.py` reads this JSON on stdin and prints a hash:
```json
{ "endpoints": [ { "method": "GET", "path": "/v3/users/{id}", "fields": ["created_at","email","id"] } ] }
```
- `method` — uppercase HTTP verb (or operation name for GraphQL/gRPC).
- `path` — normalized: lowercase, `{id}` placeholder for any path param, base-path stripped.
- `fields` — request + response field names, snake_case (canonical backend names);
  the app side maps camelCase→snake before hashing so both sides hash equal when in sync.

The helper sorts endpoints and fields internally, so ordering never affects the hash.

## Staleness detection (logical drift)

A session, on demand (work start / before building against the other side / before commit):
1. Re-derive ITS OWN contract (reuse `api-contract-sync` extraction). Cheap skip: if the
   worktree `git_sha` is unchanged since the last slice write, the contract cannot have
   changed — skip re-derivation.
2. Write its own `*.fp.json` slice (hash via `scripts/fingerprint.py`).
3. "Am I stale?" = read the OTHER slice; if `other.contract_hash != sync.json.<other>_hash_at_sync`,
   the other side moved → run `api-contract-sync` before proceeding.

## Ownership (physical drift — only with a shared package)

Two separate repos cannot write the same file, so ownership is dormant unless a third
shared surface exists (a shared types/proto dir both sides edit). When present,
`sync.json.owned_files` maps glob → owner (`"backend"` | `"app"`). Before writing a file
matching a glob it does NOT own, a session refuses and names the owning side.
Backstop: each session is on a branch; integration is `git merge`, which surfaces any
real conflict for semantic resolution. No custom merge logic.

## Worktree setup

```bash
# backend session
git -C <backend-root> worktree add ../backend-<feature> -b <feature>
# app session
git -C <app-root> worktree add ../app-<feature> -b <feature>
```
Both sessions reach `.fullstack-sync/` via `sync.json.state_dir_abspath` (the backend
session may need `/add-dir <app-root>` to read it).
````

- [ ] **Step 2: Validate the doc is self-consistent**

Run: `grep -c 'contract_hash' references/parallel-sync.md`
Expected: count ≥ 5 (appears in all three file shapes + staleness section).

Confirm by reading: the three state-file field names (`git_sha`, `contract_hash`, `routes_digest`/`calls_digest`, `updated_at`; and `sync.json`'s `backend_hash_at_sync`, `app_hash_at_sync`, `synced_at`, `state_dir_abspath`, `owned_files`) match exactly what Tasks 2–5 will reference. No "TBD" present: `grep -i 'tbd\|todo' references/parallel-sync.md` → no output.

- [ ] **Step 3: Commit**

```bash
git add references/parallel-sync.md
git commit -m "feat: add parallel-sync protocol reference"
```

---

### Task 2: Fingerprint helper + tests (TDD)

**Files:**
- Create: `scripts/fingerprint.py`
- Test: `tests/test_fingerprint.py`

**Interfaces:**
- Consumes: the contract-input shape defined in `references/parallel-sync.md` (Task 1) — `{ "endpoints": [ { "method", "path", "fields" } ] }`.
- Produces: `fingerprint(contract: dict) -> str` (64-char sha256 hex) importable from `scripts/fingerprint.py`; and a CLI that reads that JSON on stdin and prints the hash. Tasks 3–5 invoke the CLI as `python3 scripts/fingerprint.py < contract.json`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_fingerprint.py`:

```python
import sys, os, traceback
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from fingerprint import fingerprint

base = {"endpoints": [
    {"method": "GET",  "path": "/users/{id}", "fields": ["email", "id"]},
    {"method": "POST", "path": "/users",      "fields": ["email", "name"]},
]}

def test_deterministic():
    assert fingerprint(base) == fingerprint(base)

def test_endpoint_order_invariant():
    reordered = {"endpoints": list(reversed(base["endpoints"]))}
    assert fingerprint(base) == fingerprint(reordered)

def test_field_order_invariant():
    swapped = {"endpoints": [
        {"method": "GET",  "path": "/users/{id}", "fields": ["id", "email"]},
        {"method": "POST", "path": "/users",      "fields": ["name", "email"]},
    ]}
    assert fingerprint(base) == fingerprint(swapped)

def test_method_case_invariant():
    lowered = {"endpoints": [
        {"method": "get",  "path": "/users/{id}", "fields": ["email", "id"]},
        {"method": "post", "path": "/users",      "fields": ["email", "name"]},
    ]}
    assert fingerprint(base) == fingerprint(lowered)

def test_field_rename_changes_hash():
    renamed = {"endpoints": [
        {"method": "GET",  "path": "/users/{id}", "fields": ["email", "userId"]},
        {"method": "POST", "path": "/users",      "fields": ["email", "name"]},
    ]}
    assert fingerprint(base) != fingerprint(renamed)

def test_returns_64_char_hex():
    h = fingerprint(base)
    assert len(h) == 64 and all(c in "0123456789abcdef" for c in h)

if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"PASS {fn.__name__}")
        except AssertionError:
            failed += 1; print(f"FAIL {fn.__name__}"); traceback.print_exc()
    sys.exit(1 if failed else 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_fingerprint.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'fingerprint'`.

- [ ] **Step 3: Write minimal implementation**

Create `scripts/fingerprint.py`:

```python
#!/usr/bin/env python3
"""Deterministic structural fingerprint of an API contract.

Reads {"endpoints": [{"method","path","fields"}]} on stdin, prints sha256 hex.
Sorts endpoints and fields internally so ordering never affects the hash.
Scope is structural ONLY (method/path/fields) — never auth/errors/envelopes.
"""
import sys, json, hashlib


def canonical(contract):
    eps = []
    for ep in contract.get("endpoints", []):
        eps.append({
            "method": ep["method"].upper(),
            "path": ep["path"],
            "fields": sorted(ep.get("fields", [])),
        })
    eps.sort(key=lambda e: (e["method"], e["path"]))
    return json.dumps({"endpoints": eps}, sort_keys=True, separators=(",", ":"))


def fingerprint(contract):
    return hashlib.sha256(canonical(contract).encode("utf-8")).hexdigest()


if __name__ == "__main__":
    print(fingerprint(json.load(sys.stdin)))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_fingerprint.py`
Expected: all six lines `PASS ...`, exit 0.

- [ ] **Step 5: Verify the CLI path**

Run: `echo '{"endpoints":[{"method":"get","path":"/users/{id}","fields":["id","email"]}]}' | python3 scripts/fingerprint.py`
Expected: a 64-char hex string. Run it twice → identical output.

- [ ] **Step 6: Commit**

```bash
git add scripts/fingerprint.py tests/test_fingerprint.py
git commit -m "feat: add deterministic contract fingerprint helper + tests"
```

---

### Task 3: `/fullstack-parallel-init` command

**Files:**
- Create: `commands/fullstack-parallel-init.md`
- Modify: `.gitignore` (append `.fullstack-sync/`)

**Interfaces:**
- Consumes: `references/parallel-sync.md` (state-file shapes), existing `.fullstack-sync.json` (for `app.root`, `backend.root`, `extra_dirs`).
- Produces: a populated `.fullstack-sync/` dir with `sync.json` (and empty `backend.fp.json`/`app.fp.json` placeholders), used by Tasks 4–5.

- [ ] **Step 1: Add the state dir to .gitignore**

Append a line to `.gitignore` so the whole repo ignores the state dir:

```
.fullstack-sync/
```

- [ ] **Step 2: Write the command**

Create `commands/fullstack-parallel-init.md`:

````markdown
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
````

- [ ] **Step 3: Validate**

Run: `grep -n 'allowed-tools' commands/fullstack-parallel-init.md`
Expected: one frontmatter line listing the Bash tools.

Run: `git check-ignore .fullstack-sync/sync.json`
Expected: prints `.fullstack-sync/sync.json` (confirms it's ignored).

- [ ] **Step 4: Commit**

```bash
git add commands/fullstack-parallel-init.md .gitignore
git commit -m "feat: add /fullstack-parallel-init command"
```

---

### Task 4: `parallel-sync-status` skill

**Files:**
- Create: `skills/parallel-sync-status/SKILL.md`

**Interfaces:**
- Consumes: `references/parallel-sync.md`, `.fullstack-sync/{backend,app}.fp.json`, `.fullstack-sync/sync.json`, `scripts/fingerprint.py`.
- Produces: nothing on disk beyond refreshing THIS session's own `*.fp.json` slice; reports drift to the user. Does NOT auto-fix (defers to `api-contract-sync`).

- [ ] **Step 1: Write the skill**

Create `skills/parallel-sync-status/SKILL.md`:

````markdown
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
slice (`backend.fp.json` or `app.fp.json`), skip re-derivation — the contract can't have
changed. Otherwise re-derive my contract exactly as `api-contract-sync` does (my routes,
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
code). If both slices are fresh and equal, suggest they're safe to reconcile (update
`sync.json.*_hash_at_sync` to the current hashes + `synced_at`).

## Output

The status block above, plus one next-step line. Never claim "synced" without having
recomputed THIS session's slice in step 1.
````

- [ ] **Step 2: Validate the skill frontmatter + trigger surface**

Run: `head -3 skills/parallel-sync-status/SKILL.md`
Expected: `---`, then `name: parallel-sync-status`, then a `description:` starting with "Report whether".

Manual check: the description contains concrete trigger phrases ("am I in sync", "did the backend change", "is my contract stale") so the model invokes it. Confirm it says report-only and points fixes to `api-contract-sync`.

- [ ] **Step 3: Commit**

```bash
git add skills/parallel-sync-status/SKILL.md
git commit -m "feat: add parallel-sync-status skill"
```

---

### Task 5: Extend `fullstack-feature` for parallel mode

**Files:**
- Modify: `skills/fullstack-feature/SKILL.md` (insert a parallel-mode section after section 0)

**Interfaces:**
- Consumes: `.fullstack-sync/sync.json` (`owned_files`, side detection), `references/parallel-sync.md`, `scripts/fingerprint.py`.
- Produces: when in parallel mode, edits only the side this session owns and refreshes this session's `*.fp.json` slice after the change.

- [ ] **Step 1: Insert the parallel-mode section**

In `skills/fullstack-feature/SKILL.md`, immediately after the `## 0. Load config`
section (after its paragraph, before `## 1. Pin the contract FIRST`), insert:

```markdown
## 0b. Parallel mode (only if `.fullstack-sync/` exists)

If a `.fullstack-sync/` dir exists (set up by `/fullstack-parallel-init`), this is a
two-session run — read `${CLAUDE_PLUGIN_ROOT}/references/parallel-sync.md`. Then:

- **Scope to my side.** Determine if this session is backend or app (from cwd vs the
  config roots). Edit ONLY that side's files. Do NOT touch the other side — the other
  session owns it. (Single-pass both-sides editing is for non-parallel mode only.)
- **Respect ownership.** If `sync.json.owned_files` maps a file you're about to write to
  the OTHER side, refuse that edit and tell the user to make it in the owning session.
- **Check staleness first.** Run the `parallel-sync-status` logic; if the other side has
  MOVED since the last reconcile, run `api-contract-sync` before building against it.
- **Refresh my slice after editing.** Once my side is changed, re-derive my contract,
  hash it via `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/fingerprint.py`, and write my
  `*.fp.json` slice (`git_sha`, `contract_hash`, digest, `updated_at`). Tell the user to
  reconcile (`parallel-sync-status`) once both sessions have updated their slices.
```

- [ ] **Step 2: Validate the insertion**

Run: `grep -n '0b. Parallel mode' skills/fullstack-feature/SKILL.md`
Expected: one match, located between the `## 0. Load config` and `## 1. Pin the contract FIRST` headings.

Run: `grep -n '^## ' skills/fullstack-feature/SKILL.md`
Expected ordering: `## 0. Load config`, `## 0b. Parallel mode ...`, `## 1. Pin the contract FIRST`, ... (no heading reordered).

- [ ] **Step 3: Commit**

```bash
git add skills/fullstack-feature/SKILL.md
git commit -m "feat: add parallel-mode handling to fullstack-feature"
```

---

### Task 6: Docs + version bump

**Files:**
- Modify: `.claude-plugin/plugin.json` (version → 0.2.0)
- Modify: `README.md` (skills table + a parallel-mode subsection)
- Modify: `ROADMAP.md` (move the deferred item to shipped)

**Interfaces:**
- Consumes: all prior tasks (their final command/skill names).
- Produces: user-facing docs that match what was built.

- [ ] **Step 1: Bump the plugin version**

In `.claude-plugin/plugin.json`, change `"version": "0.1.0"` to `"version": "0.2.0"`.

- [ ] **Step 2: Add the skill to the README table + a parallel section**

In `README.md`, add a row to the skills table:

```
| `parallel-sync-status` | two-session parallel mode — "am I in sync", "did the backend change", report contract drift between the backend and app sessions (report-only; fixes go through `api-contract-sync`) |
```

And add this subsection after the config section:

```markdown
## Parallel mode (two sessions)

For building a feature with one session per side at the same time:

1. `/fullstack-parallel-init` — creates `.fullstack-sync/`, auto-detects shared-file
   ownership, prints the `git worktree` commands.
2. Open one `claude` session per worktree (backend / app).
3. Each session: `parallel-sync-status` to check drift, `fullstack-feature` to build its
   side. Drift is caught by comparing a structural contract fingerprint — no event log,
   no locks, no orchestrator. See `references/parallel-sync.md`.
```

- [ ] **Step 3: Mark the roadmap item shipped**

In `ROADMAP.md`, under `## v0.1.0 (shipped)` add:

```
- `/fullstack-parallel-init` + `parallel-sync-status` — two-session parallel mode via per-session contract fingerprints (`references/parallel-sync.md`)
```

And in the v0.2 section, replace the `### Scoped subagents + write-back reconcile (deferred — see note)` paragraph's deferral note with:

```
### Scoped subagents + parallel contract sync  (shipped in v0.2)
Per-session fingerprint slices under `.fullstack-sync/` + on-demand drift detection,
instead of a live orchestrator. Single-writer partition removes lost-update without
locks or an event log (git is the log). Shared-file conflict handled by auto-detected
ownership + git-merge backstop. See `references/parallel-sync.md`.
```

- [ ] **Step 4: Validate docs**

Run: `python3 -c "import json; print(json.load(open('.claude-plugin/plugin.json'))['version'])"`
Expected: `0.2.0`.

Run: `grep -c 'parallel-sync-status' README.md ROADMAP.md`
Expected: ≥1 in each.

- [ ] **Step 5: Final full-suite check**

Run: `python3 tests/test_fingerprint.py`
Expected: all `PASS`, exit 0.

- [ ] **Step 6: Commit**

```bash
git add .claude-plugin/plugin.json README.md ROADMAP.md
git commit -m "docs: v0.2.0 — parallel contract sync (version bump + README + roadmap)"
```

---

## Self-Review

**Spec coverage:**
- State dir + three single-writer files → Task 1 (defined), Tasks 3–5 (written/read). ✓
- Fingerprint algorithm (structural, deterministic) → Task 2. ✓
- Drift/staleness detection → Task 4. ✓
- Ownership auto-detect + dormant when disjoint → Task 3 Step 3. ✓
- Git-merge backstop / worktree layout → Task 1 (reference). ✓
- `/fullstack-parallel-init`, `parallel-sync-status`, `fullstack-feature` extension → Tasks 3, 4, 5. ✓
- Token efficiency (cheap-skip on unchanged `git_sha`) → Task 1 + Task 4 Step 1. ✓
- Non-goals (no event log/locks/orchestrator) → enforced by single-writer design, not code. ✓
- Testing scenarios from spec: fingerprint determinism → Task 2 tests ✓; staleness flag, ownership refusal, disjoint happy path → these are skill-behavior scenarios, validated manually per the Global Constraint that markdown deliverables aren't unit-tested. ✓

**Placeholder scan:** No TBD/TODO; every code/content step shows full content. ✓

**Type consistency:** `contract_hash`, `git_sha`, `routes_digest`/`calls_digest`, `updated_at`, `backend_hash_at_sync`/`app_hash_at_sync`, `state_dir_abspath`, `owned_files`, and the `{"endpoints":[{"method","path","fields"}]}` input shape are identical across Tasks 1–5. `fingerprint()` name matches between `scripts/fingerprint.py` and `tests/test_fingerprint.py`. ✓
