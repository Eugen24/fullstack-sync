# fullstack-sync

Keep a client app and its backend API in lockstep. Catches the exact class of
bug where the app calls an endpoint the backend doesn't expose (or vice-versa),
field names drift, or a method/path disagrees — and fixes the named side.

Stack-agnostic; tuned for **Flutter + FastAPI** (the layout it was built
against) but detects Node/Django/Go/Rails on the backend and Flutter/RN/web on
the client.

## Install

```
claude plugin marketplace add /Users/neogenius24/Work1/claude-plugins
claude plugin install fullstack-sync
```

(Or point your marketplace at the parent `claude-plugins` folder.)

## First run

From inside the **app** repo:

```
/fullstack-setup
```

It asks for the backend path + any extra folders, scans both repos for
OpenAPI / markdown route docs / endpoint constants, and writes
`.fullstack-sync.json` at the app root. Then `/add-dir <backend-root>` so both
repos are first-class in the session.

## Skills (model-invoked — just ask)

| Skill | Use it for |
|-------|-----------|
| `api-contract-sync` | "check API contracts", endpoint mismatch, 404/405 from app, after changing a route — diffs app constants/services ↔ backend routes/schemas and fixes the drift |
| `fullstack-feature` | "add this endpoint on backend and app" — scaffolds route+schema AND constant+service+model with identical field names |
| `fullstack-run` | "run backend and app together" — boots the API, health-checks it, points the app at local |
| `fullstack-verify` | "verify before commit" — app analyze + backend tests + migration drift + contract recheck |

## Config: `.fullstack-sync.json`

Lives at the app repo root, written by `/fullstack-setup`, read by every skill.
Records app/backend roots + stacks, the endpoints file, router/schema globs, the
doc/spec files to treat as contract truth, and version base-paths.

## Why it exists

Real drift caught on day one of dogfooding: app called `/v4/tasks/custom`
(backend had `/v4/tasks/`), and three app URL constants + a consent route were
missing entirely. Each was a silent runtime 404 the analyzer couldn't see.
This plugin makes that visible before it ships.
