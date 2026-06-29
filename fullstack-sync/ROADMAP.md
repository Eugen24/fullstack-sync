# fullstack-sync — Roadmap

## v0.1.0 (shipped)
- `/fullstack-setup` — detect stacks + spec format (OpenAPI/GraphQL/proto/route-files), scan docs, write `.fullstack-sync.json`
- `api-contract-sync` — drift detection + fix (app constants/services ↔ backend routes/schemas)
- `fullstack-feature` — scaffold an endpoint across both repos with matching field names
- `fullstack-run` — boot backend + point app at it (per-device host resolution)
- `fullstack-verify` — app analyze + backend tests + migration drift + contract recheck
- SessionStart hook — auto-load config paths, or nudge `/fullstack-setup`
- `references/spec-detection.md` — stack → spec-format → route-file-fallback matrix

## v0.2 — candidate features (build when the pain is real)

### Scoped subagents + write-back reconcile  (deferred — see note)
`/backend` + `/frontend` slash commands that open subagents scoped to one repo,
each reading `.fullstack-sync.json`, writing changes back, with a master `/sync`
reconciling. **Deferred on purpose**: adds state-reconciliation + agent-lifecycle
+ write-conflict complexity. Core value (drift detect + both-sides scaffold)
doesn't need it — `fullstack-feature` already edits both sides in one pass, and
`Agent` + `/add-dir` already give scoped exploration. Build only when two agents
must edit both repos in parallel.

### Other candidates
- **OpenAPI/GraphQL codegen integration** — when the app uses a generated client,
  drive `fullstack-feature` through the generator (openapi-generator / orval /
  hey-api) instead of hand-editing models.
- **CI drift gate** — a `fullstack-verify --ci` mode that exits non-zero on any
  contract drift, for a pre-merge GitHub Action.
- **Live `/openapi.json` diff** — when the backend is runnable, diff against the
  live spec instead of static route parsing (already noted in `api-contract-sync`).
- **Budget/feature-flag style cross-cutting checks** — generalize the "is field X
  honored on both sides" pattern beyond endpoints.

## Dogfood proof (v0.1, Flutter + FastAPI)
First real run found 4 contract bugs the analyzer couldn't see:
- `userValidate` → `/v3/user/validate` (no route, live 404) → repointed to `/v3/auth/validate`
- `savedMeals` missing trailing slash → 307 redirect risk on POST → fixed
- `userConsentAccept` referenced but undeclared (backend route existed) → constant added
- `userSuggestions` → no backend route (latent) → constant removed
~61 endpoints matched clean. Also surfaced backend routes the app hadn't wired
yet (`/v4/groceries/ingredient-lists`, `/v4/groceries/inventory`).
