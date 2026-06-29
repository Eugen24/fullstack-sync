---
description: Set up fullstack-sync — capture backend path(s), extra dirs, detect stacks/spec formats, scan docs/specs into a shared config
allowed-tools: Bash(git rev-parse:*), Bash(pwd:*), Bash(ls:*)
---

# Fullstack Sync — Setup

Goal: produce a `.fullstack-sync.json` config at the **app repo root** (current
working directory) recording where the app + backend live, their stacks, their
contract format (OpenAPI / GraphQL / proto / route-files / …), and the docs to
sync against. Every other fullstack-sync skill reads this config — do it first.

App repo root (pre-resolved): !`git rev-parse --show-toplevel 2>/dev/null || pwd`

Read the detection reference before scanning:
`${CLAUDE_PLUGIN_ROOT}/references/spec-detection.md` — the stack → spec-format →
route-file-fallback matrix. **Do not assume OpenAPI** — most repos have no spec
and you must fall back to reading route source.

## Step 1 — Ask the user for backend + extra folders

Use **AskUserQuestion** (never guess paths). First detect candidate siblings to
offer as options — run this via the Bash tool:

```
ls -d ../*/ ../../*/ 2>/dev/null | head -20
```
Flag any candidate that contains `requirements.txt`, `pyproject.toml`,
`package.json`, `go.mod`, `Gemfile`, `composer.json`, `manage.py`, `asgi.py`,
or a `routers/`/`src/routes` dir as a likely backend.

Ask, in one AskUserQuestion call:
1. **Backend path** — absolute path to the backend/API repo root (offer detected
   candidates + Other).
2. **Extra folders** (multiSelect) — shared types, infra, a second service, a
   design/spec folder, or None.

## Step 2 — Detect stack + contract format (per repo)

For the backend and each extra dir, run the Bash tool to inspect the root and
apply `references/spec-detection.md`:

```
for p in "<backend>" "<extra...>"; do echo "== $p =="; ls "$p"; done
```

Determine, per repo: **stack** (FastAPI/Express/NestJS/Django/Rails/Go/…),
**api_style** (rest|graphql|grpc|event|json-rpc|soap), and **spec_format**:
- explicit spec file if present (`openapi.*`, `schema.graphql`, `*.proto`,
  `asyncapi.*`, `*.wsdl`, `openrpc.json`), else
- `route-files` + the glob where routes live (the fallback — most common).

Detect the **app** stack + client pattern too (Flutter `pubspec.yaml` →
constants/retrofit/generated; JS `package.json` → axios/trpc/graphql/codegen;
iOS/Android → Alamofire/Retrofit). Note if the client is **generated from a
spec** (then diffs run against the spec, not the client).

## Step 3 — Locate the contract surface on both sides

- **Backend:** the route source (e.g. FastAPI `routers/**/*.py`) + any spec file
  + markdown route docs (`routers/**/*.md`, `specs/**`, `docs/**`).
- **App:** the endpoints registry (e.g. `**/api_constants.dart`, `**/endpoints.*`)
  + the services/client glob + any `*.graphql` operations.

Run real scans via the Bash tool, e.g.:
```
cd "<backend>" && find . -maxdepth 4 \( -name 'openapi*' -o -name 'schema.graphql' -o -name '*.proto' -o -name '*.md' \) 2>/dev/null | head -40
cd "<app-root>" && grep -rl --include=*.dart 'static const String' lib 2>/dev/null | head
```

## Step 4 — Write the config

Write `.fullstack-sync.json` at the app repo root from what Step 2–3 ACTUALLY
found (never invent paths). Shape:

```jsonc
{
  "version": 1,
  "app": {
    "root": "/abs/app", "stack": "flutter",
    "client_pattern": "string-constants",      // or retrofit | generated | trpc | graphql
    "endpoints_file": "lib/core/constants/api_constants.dart",
    "services_glob": "lib/features/**/services/*.dart"
  },
  "backend": {
    "root": "/abs/api", "stack": "fastapi",
    "api_style": "rest",
    "spec_format": "route-files",              // or openapi | graphql | grpc | asyncapi
    "spec_file": null,                          // path when spec_format != route-files
    "routers_glob": "routers/**/*.py",
    "schemas_glob": "schemas/**/*.py",
    "route_prefix_rule": "<how prefixes resolve>",
    "migrations": "alembic"
  },
  "extra_dirs": [],
  "docs": ["routers/v3/meal_plans.md", "..."],
  "base_paths": { "v3": "/v3", "v4": "/v4" }
}
```

## Step 5 — Confirm + next steps

Print a summary: app stack+pattern, backend stack+api_style+spec_format, extra
dirs, # docs, endpoints file. Then tell the user:
- run **api-contract-sync** to sweep for drift,
- **fullstack-feature** to add an endpoint across both repos,
- and `/add-dir <backend-root>` so both repos are first-class in the session.
