#!/usr/bin/env bash
# End-to-end protocol integration test: two real git repos driven through the
# full parallel-sync flow via the sync_state CLI. Asserts in-sync (camel==snake),
# reconcile baseline, drift detection, AND no-false-drift. CI regression net.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FP="$ROOT/scripts/fingerprint.py"
SS="$ROOT/scripts/sync_state.py"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
FAIL=0
ok()   { echo "PASS $1"; }
bad()  { echo "FAIL $1"; FAIL=1; }

git_q() { git -C "$1" -c user.email=t@t -c user.name=t "${@:2}"; }

# --- build two disjoint repos ---
BE="$WORK/backend"; APP="$WORK/app"; mkdir -p "$BE" "$APP"
git_q "$BE" init -q; echo "routes v1" > "$BE/routes.py"; git_q "$BE" add -A; git_q "$BE" commit -qm v1
git_q "$APP" init -q; echo "constants v1" > "$APP/api.dart"; git_q "$APP" add -A; git_q "$APP" commit -qm v1
SD="$APP/.fullstack-sync"; mkdir -p "$SD"
printf '{"backend_hash_at_sync":null,"app_hash_at_sync":null,"synced_at":null,"state_dir_abspath":"%s","owned_files":{}}\n' "$SD" > "$SD/sync.json"
echo '{}' > "$SD/backend.fp.json"; echo '{}' > "$SD/app.fp.json"

BE_SHA="$(git_q "$BE" rev-parse HEAD)"
APP_SHA="$(git_q "$APP" rev-parse HEAD)"

# backend = snake_case, app = camelCase: SAME logical contract
BE_C='{"endpoints":[{"method":"GET","path":"/v3/users/{id}","fields":["created_at","email","id"]}]}'
APP_C='{"endpoints":[{"method":"GET","path":"/v3/users/{id}","fields":["createdAt","email","id"]}]}'

# --- refresh both slices ---
HB="$(echo "$BE_C"  | python3 "$SS" write-slice --state-dir "$SD" --side backend --git-sha "$BE_SHA" --now t0)"
HA="$(echo "$APP_C" | python3 "$SS" write-slice --state-dir "$SD" --side app     --git-sha "$APP_SHA" --now t0)"
[ "$HB" = "$HA" ] && ok "camel_equals_snake_in_sync" || bad "camel_equals_snake_in_sync ($HB != $HA)"

# --- status before reconcile: NO_RECONCILE (exit 3) ---
python3 "$SS" status --state-dir "$SD" --side app >/dev/null; [ $? -eq 3 ] && ok "no_reconcile_before_baseline" || bad "no_reconcile_before_baseline"

# --- reconcile from backend: refused (non-zero) ---
if python3 "$SS" reconcile --state-dir "$SD" --side backend --now t1 >/dev/null 2>&1; then bad "backend_reconcile_refused"; else ok "backend_reconcile_refused"; fi

# --- reconcile from app: records baseline ---
python3 "$SS" reconcile --state-dir "$SD" --side app --now t1 >/dev/null && ok "app_reconcile_ok" || bad "app_reconcile_ok"

# --- status after reconcile, nothing changed: IN_SYNC (exit 0), no false drift ---
python3 "$SS" status --state-dir "$SD" --side app >/dev/null; [ $? -eq 0 ] && ok "no_false_drift_when_unchanged" || bad "no_false_drift_when_unchanged"

# --- backend changes a field + commits, refresh slice ---
git_q "$BE" commit -q --allow-empty -m "rename created_at->created_ts"
BE_SHA2="$(git_q "$BE" rev-parse HEAD)"
BE_C2='{"endpoints":[{"method":"GET","path":"/v3/users/{id}","fields":["created_ts","email","id"]}]}'
echo "$BE_C2" | python3 "$SS" write-slice --state-dir "$SD" --side backend --git-sha "$BE_SHA2" --now t2 >/dev/null

# --- status now: MOVED (exit 2) ---
python3 "$SS" status --state-dir "$SD" --side app >/dev/null; [ $? -eq 2 ] && ok "drift_detected_after_change" || bad "drift_detected_after_change"

echo "----"
[ "$FAIL" -eq 0 ] && echo "PROTOCOL OK" || echo "PROTOCOL FAILED"
exit "$FAIL"
