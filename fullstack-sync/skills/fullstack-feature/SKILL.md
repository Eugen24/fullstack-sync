---
name: fullstack-feature
description: Scaffold a new API endpoint (or change an existing one) across BOTH the backend and the client app in one pass, so the contract can't drift. Use when the user wants to add an endpoint, wire a new API call end-to-end, "add this on backend and app", build a feature that needs a new route, or expose backend data to the app. Creates the backend route + schema AND the app constant + service method + model together, with matching field names.
---

# Fullstack Feature

Add or change one endpoint on both sides at once. The contract is decided first,
then implemented identically on backend and app.

## 0. Load config

Read `.fullstack-sync.json` (app root). If missing → run `/fullstack-setup`
first. Use it to locate routers/schemas (backend) and constants/services (app).

## 1. Pin the contract FIRST

Before writing code, write the contract down and confirm it with the user:

```
METHOD  /vN/resource/{id}/action
auth:   <public | user | admin>
request (data wrapper if the project uses one):
  { "field_snake": type, ... }
response:
  { "field_snake": type, ... }
errors: <status + detail string the app should branch on>
```

Match the project's existing envelope (e.g. body under `data`, response under
`{"data": ...}`) — detect it from neighboring routes, don't impose a new one.

## 2. Backend side

Following the existing router/schema conventions in `backend.routers_glob`:
- add the route to the correct versioned router (reuse the router prefix)
- **ensure the route is registered** — a new router silently 404s unless it's
  `include_router`-ed into the root/versioned aggregator (or auto-mounted). Verify
  the mount, don't just define the handler.
- add/extend request + response schemas (Pydantic/serializer/etc.)
- wire auth dependency + error responses matching step 1
- if the backend uses migrations (e.g. alembic) and a model changed, generate
  the migration — do NOT hand-edit schema without one

## 3. App side

Following the app's conventions:
- add the URL constant to `app.endpoints_file` (reuse `$basePath`/prefix helper)
- add the service method (correct verb, body wrapper, return parsing)
- add/extend the model using the EXACT backend field names (handle
  snake_case→camelCase in the model, not by renaming the API). **If the app uses
  codegen** (`json_serializable`/`freezed`, retrofit), edit the annotated model
  and run `dart run build_runner build --delete-conflicting-outputs` rather than
  hand-writing `fromJson`/`toJson`.
- wire the provider/state if the user asked for UI

## 4. Keep names identical

The #1 drift source is field-name skew. The model's JSON keys MUST equal the
backend schema keys verbatim. List them side by side before finishing.

## 5. Verify both

Run the **fullstack-verify** checks on the touched files (app analyze + backend
import/tests + migration drift + contract recheck) rather than restating them
here. Show the output. Then hand the user a one-paragraph "what to test" note.

## Output

Print the final contract block + the files changed on each side. Confirm field
names match.
