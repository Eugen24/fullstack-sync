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
