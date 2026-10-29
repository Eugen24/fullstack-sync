# Changelog

## 0.4.0
- New `scripts/drift_check.py`: a CI drift gate that needs no Claude. Fails when the app calls a path the backend does not serve; backend from the FastAPI extractor or an OpenAPI file (`--openapi`). Exit 0/1/2, `--json`, `--warn`.
- Example GitHub Actions workflow in `docs/examples/drift-gate.yml`.
- Tests for path normalisation, prefix tolerance, call-context filtering and the CLI exit codes.

## 0.3.1
- Fix: the drift-check Stop hook no longer walks `.venv`, `.git`, `node_modules`, caches or worktrees. On real FastAPI backends this took 8 to 14 s and often hit the hook timeout; it now takes about 0.1 to 1 s with identical output.
- Extractor skips files it cannot parse instead of failing, and takes a `--max-seconds` budget (the hook uses 6 s and falls back to a coarse nudge).
- Hook passes the state path and hash as arguments, so project paths containing quotes work.
- Stop hook timeout 15 s to 10 s.
- Tests: pruning, unparseable files, time budget, quote-in-path.

## 0.3.0
- Sync levels (`off` / `low` / `hard`), drift-gated Stop hook, `/fullstack-sync-review`.

## 0.2.0
- Parallel two-session contract sync (fingerprint slices, drift detection).

## 0.1.0
- Setup, `api-contract-sync`, `fullstack-feature`, `fullstack-run`, `fullstack-verify`.
