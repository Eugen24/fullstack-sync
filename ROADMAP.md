# fullstack-sync — Roadmap

## v0.1.0 (shipped)
- `/fullstack-setup` — detect stacks + spec format (OpenAPI/GraphQL/proto/route-files), scan docs, write `.fullstack-sync.json`
- `api-contract-sync` — drift detection + fix (app constants/services ↔ backend routes/schemas)
- `fullstack-feature` — scaffold an endpoint across both repos with matching field names
- `fullstack-run` — boot backend + point app at it (per-device host resolution)
- `fullstack-verify` — app analyze + backend tests + migration drift + contract recheck
- SessionStart hook — auto-load config paths, or nudge `/fullstack-setup`
- `references/spec-detection.md` — stack → spec-format → route-file-fallback matrix
- `/fullstack-parallel-init` + `parallel-sync-status` — two-session parallel mode via per-session contract fingerprints (`references/parallel-sync.md`)

## v0.2 — candidate features (build when the pain is real)

### Scoped subagents + parallel contract sync  (shipped in v0.2)
Per-session fingerprint slices under `.fullstack-sync/` + on-demand drift detection,
instead of a live orchestrator. Single-writer partition removes lost-update without
locks or an event log (git is the log). Shared-file conflict handled by auto-detected
ownership + git-merge backstop. See `references/parallel-sync.md`.

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
First real run on a private app↔API pair found 4 contract bugs the analyzer
couldn't see, plus several unused/unwired routes — all of the classes this
plugin targets:
- a constant pointing at a non-existent route (live 404) → repointed to the real one
- a collection path missing its trailing slash → 307 redirect risk on POST → fixed
- a constant referenced in code but never declared (route existed) → constant added
- a constant for a route the backend never implemented (latent) → removed
~60 endpoints matched clean; also surfaced backend routes the app hadn't wired yet.
