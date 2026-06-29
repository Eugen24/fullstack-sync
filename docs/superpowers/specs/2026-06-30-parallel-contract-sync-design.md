# fullstack-sync v0.2 — Parallel-Safe Contract Coordination

**Date:** 2026-06-30
**Status:** Approved design, pre-implementation
**Builds on:** fullstack-sync v0.1 (`.fullstack-sync.json`, `api-contract-sync`, `fullstack-feature`)

## Goal

Let **two Claude sessions** work a fullstack feature in parallel — backend session in
one git worktree, app session in another — without (a) drifting the API contract or
(b) clobbering each other's files. Achieve this with **on-demand fingerprint
comparison**, not a live orchestrator or process supervisor.

## Non-goals (YAGNI ledger)

Deliberately NOT built, with reason:

- **No event log** — git history already is an append-only, ordered, audited event log.
  A parallel `events.jsonl` reinvents git, worse.
- **No live orchestrator / process supervisor** — a plugin is skills + commands + hooks.
  It cannot spawn and babysit long-lived parallel `claude` sessions. The human runs the
  two terminals; the plugin supplies the coordination *protocol*.
- **No locks / vector clocks** — single-writer-per-file partitioning removes the need.
- **No auto-spawned sessions** — out of scope for a plugin; documented as a manual step.
- **No custom merge engine** — `git merge` is the reconciliation backstop.

## Drivers

1. **Parallel-edit correctness** — two agents editing at once must not corrupt the
   contract or lose each other's writes.
2. **Token efficiency** — agents read a small derived contract summary, not whole repos;
   re-scan only when the git SHA moved.

## Distributed-systems framing

Two sessions on one filesystem = two processes, no shared memory, no DB. Available
primitives: atomic `rename()`, atomic small-record `O_APPEND`, advisory `flock()`,
mtime/content-hash, git 3-way merge. Two collision models:

- **Model A — logical conflict:** disjoint files, shared contract. Backend renames a
  route; app still calls the old one. Nothing crashes; the contract drifted. This is a
  *coordination* problem → solved by staleness detection, no locks.
- **Model B — physical conflict:** both write the same shared file (`openapi.yaml`,
  `shared/types`). Real lost update → solved by *ownership partition* + git-merge backstop.

The subtle trap: a single shared `context.json` written by both agents is **Model B on
the coordination layer itself**. The design avoids it by giving each agent its own
write-only slice.

## Architecture

### State directory

`.fullstack-sync/` at the app repo root (gitignored). Three files:

| File | Writer | Contents |
|---|---|---|
| `backend.fp.json` | backend session ONLY | `{ git_sha, contract_hash, routes_digest, updated_at }` |
| `app.fp.json` | app session ONLY | `{ git_sha, contract_hash, calls_digest, updated_at }` |
| `sync.json` | whichever runs reconcile | `{ backend_hash_at_sync, app_hash_at_sync, synced_at, owned_files, state_dir_abspath }` |

**One writer per file → no lost update, no locks, no event log.** This single-writer
partition is the entire concurrency-control story.

### Drift / staleness detection (Model A)

On demand — at work start, before building against the other side, and before commit:

1. Session re-derives **its own** contract (reuse `api-contract-sync` extraction logic).
2. Writes its own `*.fp.json` slice.
3. **"Am I stale?"** = read the *other* slice; compare `other.contract_hash` to
   `sync.json.{other}_hash_at_sync`. If changed → the other side moved → run
   `api-contract-sync` before proceeding.
4. **Cheap skip:** if `git_sha` is unchanged since the last slice write, skip
   re-derivation entirely (the contract cannot have changed).

### Shared-file safety (Model B)

`sync.json.owned_files`: a map of glob → owner (`"backend"` | `"app"`), e.g.
`openapi.yaml → backend`, `shared/types/** → backend`. Before writing any file matching
a glob it does **not** own, the agent refuses and tells the user
("`openapi.yaml` is backend-owned; make that change in the backend session").

Backstop: each session works on a branch (its worktree). Integration is `git merge`. If
the partition is ever violated, git surfaces the conflict markers and the agent resolves
them semantically. No bespoke merge code.

### Worktree layout

- Backend session → a git worktree/branch of the backend repo.
- App session → a git worktree/branch of the app repo.
- App and backend are already separate repos in v1, so file sets are naturally disjoint;
  worktrees add per-feature branch isolation and avoid a shared-index race.
- The `.fullstack-sync/` state dir lives at the app root. The app session reaches it
  natively; the backend session reaches it via its absolute path, recorded in
  `sync.json.state_dir_abspath` (and added with `/add-dir` if needed).

### Fingerprint algorithm (content-addressing)

```
contract       = sorted list of { method, normalized_path, sorted field_names per schema }
normalize_path = lowercase, {id} placeholder, strip base-path
canonical_json = deterministic JSON of the sorted contract
contract_hash  = sha256(canonical_json)
```

Deterministic: reordering routes → identical hash; renaming a field → different hash →
drift caught. The hash doubles as the **cache key** for the derived contract summary
(token-efficiency layer).

## Components to build

1. **`references/parallel-sync.md`** — the protocol spec: state-file formats, ownership
   rules, the fingerprint algorithm, worktree setup. Single source of truth that the
   skills read (mirrors how v1 skills read `references/spec-detection.md`).
2. **Skill `parallel-sync-status`** (model-invoked) — answers "am I in sync? is the other
   side stale?" Reads both slices + `sync.json`, reports drift. Reports only — does NOT
   auto-fix (defers to `api-contract-sync`).
3. **Extend `fullstack-feature`** — parallel mode: edit only the side this session owns,
   write this session's `*.fp.json` slice, warn if the other side's slice is stale.
4. **Command `/fullstack-parallel-init`** — creates `.fullstack-sync/`, prompts the
   ownership partition, prints the `git worktree add` commands for both repos, records
   `state_dir_abspath` in `sync.json`, adds `.fullstack-sync/` to `.gitignore`.
5. **Fingerprint helper** — a deterministic hash via a documented `jq`/`sha256sum`
   snippet, or a tiny script under the plugin if the snippet proves fragile.

## Token efficiency

The derived contract summary is cached in the `*.fp.json` slice (small), keyed by
`contract_hash`. Agents read slices + summary and re-scan the repos only when `git_sha`
moved. The fingerprint is the cache invalidator.

## Error handling

- **Missing state dir** → tell user to run `/fullstack-parallel-init`, then stop.
- **Stale other-side slice** → `parallel-sync-status` flags it; `fullstack-feature` warns
  and suggests `api-contract-sync` before continuing.
- **Ownership violation** → refuse the write, name the owning side.
- **Slice from a different `git_sha` than the working tree** → re-derive (do not trust
  the cached summary).

## Testing

- **Fingerprint determinism** — same contract → same hash; route reorder → same hash;
  field rename → different hash.
- **Staleness** — backend renames a route → app's view of backend slice flags stale.
- **Ownership** — app session attempts to write a backend-owned file → refused.
- **Disjoint happy path** — both edit their own sides → both slices update, `sync.json`
  reconciles, no conflict.

## What the user learns (patterns, surfaced for the learning goal)

Content-addressing (fingerprint), derived-vs-stored state (recompute, don't persist),
optimistic coordination (check-before-act, no locks), ownership partitioning (dodging
consensus), idempotency (re-running sync is safe).
