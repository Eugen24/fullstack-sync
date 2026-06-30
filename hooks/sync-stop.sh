#!/usr/bin/env bash
# Drift-gated, suggest-only contract review nudge. Never edits, never blocks.
set -u
ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
PLUGIN="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
CFG="$ROOT/.fullstack-sync.json"
[ -f "$CFG" ] || exit 0
command -v git >/dev/null 2>&1 || exit 0
git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1 || exit 0

# Safe dotted-path lookup into JSON config — no eval(), no code execution from data.
# Usage: jget "section.key"  or  jget "key"
jget(){
  python3 - "$CFG" "$1" 2>/dev/null <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
keys = sys.argv[2].split('.')
r = d
for k in keys[:-1]:
    r = r.get(k, {}) if isinstance(r, dict) else {}
print((r.get(keys[-1], '') if isinstance(r, dict) else '') or '')
PYEOF
}
LEVEL="$(jget "sync_level")"; [ -n "$LEVEL" ] || LEVEL="low"
[ "$LEVEL" = "off" ] && exit 0

# contract globs
GLOBARGS=()
for key in "backend.routers_glob" "backend.schemas_glob" \
           "app.endpoints_file"   "app.services_glob"; do
  v="$(jget "$key")"; [ -n "$v" ] && GLOBARGS+=(--glob "$v")
done
[ "${#GLOBARGS[@]}" -gt 0 ] || exit 0

CHANGED="$( { git -C "$ROOT" diff --name-only HEAD; \
              git -C "$ROOT" ls-files --others --exclude-standard; } 2>/dev/null )"
[ -n "$CHANGED" ] || exit 0

MATCHED="$(printf '%s\n' "$CHANGED" | python3 "$PLUGIN/scripts/sync_gate.py" match "${GLOBARGS[@]}")"
[ -n "$MATCHED" ] || exit 0

# precise (FastAPI) vs coarse
STATE="$ROOT/.fullstack-sync.hook.json"
LAST="$(python3 -c "import json,os;p='$STATE';print(json.load(open(p)).get('last_hash','') if os.path.exists(p) else '')" 2>/dev/null)"
STACK="$(jget "backend.stack")"
CUR=""
if [ "$STACK" = "fastapi" ]; then
  BROOT="$(jget "backend.root")"
  CUR="$(python3 "$PLUGIN/scripts/extract_fastapi.py" "$BROOT" 2>/dev/null | python3 "$PLUGIN/scripts/fingerprint.py" 2>/dev/null)"
fi

if [ -n "$CUR" ]; then
  if python3 "$PLUGIN/scripts/sync_gate.py" decide --contract-changed --current-hash "$CUR" --last-hash "$LAST" >/dev/null; then DEC="NUDGE"; else DEC="SILENT"; fi
  python3 -c "import json;json.dump({'last_hash':'$CUR'},open('$STATE','w'))" 2>/dev/null
else
  if python3 "$PLUGIN/scripts/sync_gate.py" decide --contract-changed >/dev/null; then DEC="NUDGE"; else DEC="SILENT"; fi
fi
[ "$DEC" = "NUDGE" ] || exit 0

FILES="$(printf '%s' "$MATCHED" | tr '\n' ' ')"
if [ "$LEVEL" = "hard" ]; then
  echo "fullstack-sync: contract moved ($FILES) — hard mode: run /fullstack-sync-review --hard (auto sync+commit, feature branch only)."
else
  echo "fullstack-sync: contract moved ($FILES) — review? run /fullstack-sync-review or api-contract-sync."
fi
exit 0
