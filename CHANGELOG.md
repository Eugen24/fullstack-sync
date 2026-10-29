# Changelog

## 0.7.0
- **Request-body check (`BODY`):** for POST/PUT/PATCH calls with an inline JSON map, fails when the app sends a key the backend's request model does not declare (Pydantic drops it silently) or omits a field the model requires. Request models resolve like response models (inheritance, `Optional[X]`, `Field(alias=...)`; `Depends/Query/Path/...` params are not bodies; list bodies are not judged). OpenAPI `requestBody` is supported. `--no-body` turns it off.
- Findings are now per call site: one path used with several verbs keeps each verb's model and body, and a `METHOD` finding no longer hides the other sites' `FIELD`/`BODY` findings.
- Fixed in audits on real apps: ternary values (`'platform': isIOS ? 'ios' : ...`) were read as body keys; `if (x) 'k': v` entries lost their `if`.
- Mutation-tested on copies of real apps (renamed body key, path typo, verb change, renamed model key): each is reported with the exact call site; unmutated apps stay at 0 findings.

## 0.6.0
- **Per-endpoint field check (`FIELD`):** links each HTTP call to the `Model.fromJson` that parses it and to the backend response model for that endpoint. Fails only for a non-null cast the backend does not declare; reads the scan cannot prove required are `FIELD?` review items. Dict-returning endpoints are skipped, never guessed.
- **Dart constants resolved** (`'$v4/x'` with `const v4 = '/v4'`), and trailing `$path`-style dynamic segments are checked as a prefix (`DYNAMIC`).
- **FastAPI extractor:** response models resolve across files with inheritance, `List/Optional/X | None` unwrapping, return annotations and `Field(alias=...)`; static `include_router` prefixes are applied; `backend.prefix_rule` handles directory-derived mounting.
- Loose `FIELD?` now means "the backend never mentions this name" (class fields, attributes, keyword args, parameters, dict keys, identifier-like strings), a far stronger signal than before.
- Stop hook also lists `FIELD` findings. `--no-endpoint-fields` turns the per-endpoint check off.
- On the author's apps this removed every false `PATH` finding (4 on one app) and exposed the real ones; 40+ tests.

## 0.5.0
- `drift_check.py` now checks HTTP methods (`METHOD`) as well as paths, and with `--fields` JSON field names (`FIELD?`: keys read in `fromJson` / written in `toJson` that no backend model declares). OpenAPI source also supplies methods and schema fields.
- Honest field check: coverage guard skips FIELD output when the extractor cannot see the backend's models; `--strict-fields` makes it fail the run.
- The Stop hook now runs the check and lists concrete `PATH`/`METHOD` findings in its nudge.
- Opt-outs: `// fss-ignore` and `drift_ignore` in the config. `app.root` defaults to the config's directory.
- Fixed: a verb from an earlier statement leaked into a later wrapper call (false `METHOD`); an unserved-prefix rule hid real endpoints that were also a prefix of another path.
- 15 drift tests, plus a hook test for concrete nudges.

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
