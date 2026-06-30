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

echo "----"; [ "$FAIL" -eq 0 ] && echo "HOOK OK" || echo "HOOK FAILED"
exit "$FAIL"
