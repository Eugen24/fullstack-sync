---
name: fullstack-verify
description: Verify a fullstack change is sound before committing — typecheck/analyze the app, import-check and test the backend, and confirm DB migrations match the models. Use when the user says "verify", "is this ready", before a commit/PR touching both repos, after a fullstack-feature change, or to check alembic/migration drift. Runs the real checks on each side and reports pass/fail with output.
---

# Fullstack Verify

Prove a cross-repo change is consistent. Never claim "done" without showing the
command output for each check.

## 0. Load config

Read `.fullstack-sync.json` for both repo roots + stacks. If missing →
`/fullstack-setup`.

## 1. App side

Run the app's static check on the touched files (cheap + fast):
- Flutter: `flutter analyze <changed files>` — expect `No issues found`.
- TS/JS: `tsc --noEmit` / `eslint` / the project's lint script.
Report errors only; collapse a clean run to one line.

**Also: no stray local base-URL override.** `fullstack-run` rewrites the app's
base URL to the local backend. Confirm that change was reverted — a committed
`localhost`/`10.0.2.2` base URL must not ship. Grep the base-URL config; flag it
as a FAIL if a local override remains.

## 2. Backend side

- Import/syntax check the touched modules (e.g. `python -c "import routers.v4.x"`
  or the project's lint/typecheck).
- Run tests scoped to the touched area if a test suite exists (`pytest path`,
  `npm test -- path`). If no tests, say so plainly.

## 3. Migration / schema drift (if backend uses migrations)

When a backend model changed:
- alembic: check for an autogenerate diff —
  `alembic revision --autogenerate --sql` (or `check`) — a NON-empty diff means
  a migration is missing. Flag it; offer to generate.
- Prisma/TypeORM/Django: the equivalent `migrate diff` / `makemigrations --check`.
A model change with no migration is a FAIL.

## 4. Contract recheck

Quickly re-run the heart of **api-contract-sync** for the touched endpoint(s):
confirm the app constant/method and backend route/schema still match (path,
verb, field names). One line per endpoint: `OK` or `DRIFT + fix`.

## 5. Verdict

Print a checklist:
```
app analyze      : PASS / FAIL (n issues)
backend tests    : PASS / FAIL / none
migrations       : OK / MISSING / n-a
contract         : OK / DRIFT
```
If anything failed, do NOT say it's ready — list the exact remaining fix.
