#!/usr/bin/env bash
# fullstack-sync SessionStart hook.
# - If a .fullstack-sync.json exists at the project root, inject its paths so the
#   skills use the correct app/backend locations automatically.
# - If absent but the repo looks like a client app, gently nudge /fullstack-setup.
# - Otherwise stay silent (don't nag in unrelated repos).
# Output on stdout becomes additional session context.

set -euo pipefail

root="${CLAUDE_PROJECT_DIR:-$PWD}"
cfg="$root/.fullstack-sync.json"

if [[ -f "$cfg" ]]; then
  # Summarize the config (python3 is available on macOS; fall back to raw cat).
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$cfg" <<'PY'
import json, sys
try:
    c = json.load(open(sys.argv[1]))
except Exception:
    print("fullstack-sync: config present but unreadable; run /fullstack-setup to repair.")
    sys.exit(0)
app = c.get("app", {}); be = c.get("backend", {})
print("fullstack-sync ACTIVE — use these paths for any app↔backend work:")
print(f"  app:     {app.get('root','?')} [{app.get('stack','?')}/{app.get('client_pattern','?')}] endpoints={app.get('endpoints_file','?')}")
print(f"  backend: {be.get('root','?')} [{be.get('stack','?')}/{be.get('api_style','?')}] spec={be.get('spec_format','?')} routers={be.get('routers_glob','?')}")
extra = c.get("extra_dirs") or []
if extra: print(f"  extra:   {', '.join(extra)}")
docs = c.get("docs") or []
if docs: print(f"  docs:    {len(docs)} contract file(s) tracked")
print("Skills available: api-contract-sync (drift), fullstack-feature (add endpoint both sides), fullstack-run, fullstack-verify.")
print("If the backend root is not a working dir yet, suggest: /add-dir " + be.get('root','<backend>'))
PY
  else
    echo "fullstack-sync ACTIVE — config at $cfg (install python3 for a full summary)."
  fi
  exit 0
fi

# No config — only nudge if this looks like a client app repo.
if [[ -f "$root/pubspec.yaml" || -f "$root/package.json" ]]; then
  echo "fullstack-sync: no .fullstack-sync.json in this repo. If it talks to a backend API, run /fullstack-setup once to capture the backend path and enable app↔backend drift sync."
fi
exit 0
