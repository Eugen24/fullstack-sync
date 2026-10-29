#!/usr/bin/env bash
# Integration test for the drift-gated Stop hook over a fixture FastAPI repo.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$ROOT/hooks/sync-stop.sh"
W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT
FAIL=0
ok(){ echo "PASS $1"; }; bad(){ echo "FAIL $1"; FAIL=1; }
g(){ git -C "$W" -c user.email=t@t -c user.name=t "$@"; }

mkdir -p "$W/routers"
cat > "$W/routers/users.py" <<'PY'
router = APIRouter(prefix="/v3/users")
class UserOut(BaseModel):
    id: int
    email: str
@router.get("/{id}", response_model=UserOut)
def get_user(id: int): ...
PY
cat > "$W/.fullstack-sync.json" <<JSON
{"sync_level":"low","backend":{"stack":"fastapi","root":"$W","routers_glob":"routers/**/*.py","schemas_glob":"routers/**/*.py"},"app":{"endpoints_file":"lib/api.dart","services_glob":"lib/**/*.dart"}}
JSON
g init -q; g add -A; g commit -qm v1

run(){ CLAUDE_PROJECT_DIR="$W" CLAUDE_PLUGIN_ROOT="$ROOT" bash "$HOOK" 2>/dev/null; }

# clean tree → silent
[ -z "$(run)" ] && ok "silent_when_clean" || bad "silent_when_clean"

# change a non-contract file → silent
echo "hi" > "$W/README.md"
[ -z "$(run)" ] && ok "silent_on_non_contract_change" || bad "silent_on_non_contract_change"

# change a router (add a field) → nudge
cat >> "$W/routers/users.py" <<'PY'
class OrderOut(BaseModel):
    order_id: int
@router.post("/{id}/orders", response_model=OrderOut)
def create_order(id: int): ...
PY
OUT="$(run)"
echo "$OUT" | grep -qi "contract moved" && ok "nudge_on_contract_change" || bad "nudge_on_contract_change"

# run again with no further change → silent (hash recorded)
[ -z "$(run)" ] && ok "silent_after_recorded" || bad "silent_after_recorded"

# unparseable vendored file under the backend root must not break precise mode
mkdir -p "$W/.venv/lib"; printf 'def (:\n' > "$W/.venv/lib/bad.py"
cat >> "$W/routers/users.py" <<'PY'
@router.get("/{id}/venvcheck")
def venvcheck(id: int): ...
PY
OUT="$(run)"
echo "$OUT" | grep -qi "contract moved" && ok "nudge_with_venv_present" || bad "nudge_with_venv_present"
[ -z "$(run)" ] && ok "silent_after_recorded_with_venv" || bad "silent_after_recorded_with_venv"

# nudge carries concrete path drift when the app calls a path the backend does not serve
mkdir -p "$W/lib"; printf "const gone = '/v3/users/{id}/missing';\n" > "$W/lib/api.dart"
cat >> "$W/routers/users.py" <<'PY'
@router.get("/{id}/drifted")
def drifted(id: int): ...
PY
python3 - "$W/.fullstack-sync.json" <<'PY'
import json,sys
p=sys.argv[1]; d=json.load(open(p)); d["sync_level"]="low"; json.dump(d,open(p,"w"))
PY
OUT="$(run)"
echo "$OUT" | grep -q "PATH .*missing" && ok "nudge_lists_path_drift" || bad "nudge_lists_path_drift"
rm -rf "$W/lib"

# off level → silent even with a change
python3 - "$W/.fullstack-sync.json" <<'PY'
import json,sys
p=sys.argv[1]; d=json.load(open(p)); d["sync_level"]="off"; json.dump(d,open(p,"w"))
PY
cat >> "$W/routers/users.py" <<'PY'
@router.get("/{id}/extra")
def extra(id: int): ...
PY
[ -z "$(run)" ] && ok "silent_when_off" || bad "silent_when_off"

# project path containing a quote must not break state handling
Q="$(mktemp -d)/o'brien"; mkdir -p "$Q/routers"
cp "$W/routers/users.py" "$Q/routers/users.py"
sed "s#$W#$Q#g" "$W/.fullstack-sync.json" > "$Q/.fullstack-sync.json"
python3 - "$Q/.fullstack-sync.json" <<'PY'
import json,sys
p=sys.argv[1]; d=json.load(open(p)); d["sync_level"]="low"; json.dump(d,open(p,"w"))
PY
git -C "$Q" init -q; git -C "$Q" -c user.email=t@t -c user.name=t add -A; git -C "$Q" -c user.email=t@t -c user.name=t commit -qm v1
echo "# x" >> "$Q/routers/users.py"
runq(){ CLAUDE_PROJECT_DIR="$Q" CLAUDE_PLUGIN_ROOT="$ROOT" bash "$HOOK" 2>/dev/null; }
runq >/dev/null; [ -z "$(runq)" ] && ok "quote_in_path_state_ok" || bad "quote_in_path_state_ok"
rm -rf "$(dirname "$Q")"

echo "----"; [ "$FAIL" -eq 0 ] && echo "HOOK OK" || echo "HOOK FAILED"
exit "$FAIL"
