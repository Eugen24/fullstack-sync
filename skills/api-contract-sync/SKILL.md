---
name: api-contract-sync
description: Detect and fix API contract drift between a client app and its backend. Use when the user mentions an endpoint mismatch, "sync app and backend", "check API contracts", a missing route/constant, a 404/405/422 from the app, a response the app can't parse, a field that's null or missing in the app, snake_case vs camelCase skew, "does the backend have this endpoint", or wants to confirm an existing endpoint still matches after a change. Cross-references the app's URL constants + service calls against the backend's routes + schemas (OpenAPI, GraphQL SDL, .proto, or raw route files) and reports every mismatch with the exact fix on each side.
---

# API Contract Sync

Find every place the app and backend disagree about the contract, then fix the
named side. Drift types: missing route, missing app constant, path/method
mismatch, request/response shape mismatch, field-name skew (snake↔camel),
pagination-envelope mismatch, auth/gate mismatch, error-string mismatch.

## 0. Load config + detection

Read `.fullstack-sync.json` (app root). If absent → tell the user to run
`/fullstack-setup`, then stop. Read `${CLAUDE_PLUGIN_ROOT}/references/spec-detection.md`.
Use the config's `backend.spec_format` to pick the backend truth source — do NOT
assume OpenAPI.

If the backend root isn't a working dir, suggest `/add-dir <backend.root>`.

## 1. App-side endpoint table

From `app.endpoints_file` extract every endpoint: constant name, resolved path
(expand base-path vars, normalize `{id}`/`$id`/`:id`), and — from
`app.services_glob` — the HTTP method each is called with and the request body
shape + the response keys the app reads. For `client_pattern: generated`, diff
the SPEC instead (the client can't drift from it). For `graphql`/`trpc`, extract
operation/procedure names + selected fields, not URL paths.

Produce: `app_endpoints[] = { name, method, path, body_keys, response_keys }`.

## 2. Backend-side route table — by spec_format

- **openapi** → parse the spec file; or, if the server is runnable (FastAPI/Nest
  auto-generate), prefer the live `/openapi.json` — it's the cheapest exact truth.
- **route-files** (common) → parse the route source per `references/spec-detection.md`
  (FastAPI `@router.*` + prefix rule; Express `router.*`; Django `urlpatterns`;
  Go/Rails/Laravel equivalents). Pull request/response schemas + error detail
  strings (e.g. 429/422 details) + auth deps. Read markdown `docs` as extra truth.
- **graphql** → parse SDL types/operations. **grpc** → parse `.proto` services.

Produce: `backend_routes[] = { method, path, req_schema, resp_schema, errors, auth }`.

## 3. Diff

Match by (method, normalized path) — or operation name for GraphQL,
`service.Method` for gRPC. Account for **list/pagination envelopes**
(`{"data":[...], "page":...}`) — a wrapper the app doesn't unwrap is silent drift.
One line per finding:

```
DRIFT  <method> <path>
  app:     <constant|MISSING>  body={...}
  backend: <route|MISSING>     req=<schema>
  fix:     <which side, exact edit>
```

Classify: **app-missing** (add constant + service method) · **backend-missing**
(implement route + schema) · **path/method mismatch** (align the app — cheap, no
deploy) · **shape/field mismatch** (reconcile keys; backend names are source of
truth; handle snake↔camel in the app model) · **error/gate mismatch** (app
branches on a status/detail the backend doesn't emit, or vice-versa).

## 4. Apply fixes (only what the user approves)

Bias: align the app for path/method nits; implement backend only when the route
truly doesn't exist; for shapes prefer backend field names. Always edit BOTH
sides when a contract changes — never leave one half.

## 5. App-side improvement audit

Beyond drift, flag (report; fix only if asked) per `references/spec-detection.md`:
scattered URL literals (centralize), hand-written client while backend has a spec
(suggest codegen), inconsistent snake↔camel mapping, unhandled documented errors,
request bodies the route ignores / missing required fields, hardcoded base URL
with no dev override.

## 6. Verify

App: analyzer/typecheck the touched files. Backend: import-check / scoped tests.
Show the output — never claim synced without it.

## Output

Collapse OK (matched) rows to a count; list DRIFT rows in full with the chosen
fix + side. End with the app-improvement flags as a short bullet list.
