# Sync-Level Review Nudge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A drift-gated, suggest-only Stop hook that offers a scoped contract review after contract-affecting changes, with three opt-in levels (off/low/hard).

**Architecture:** The testable drift-gate decision lives in `scripts/sync_gate.py` (pure: glob-match + nudge decision). A bash Stop hook (`hooks/sync-stop.sh`) does the git/extraction IO and calls the gate. A markdown skill+command runs the actual review. Config `sync_level` lives in `.fullstack-sync.json`.

**Tech Stack:** Python 3 stdlib (gate), bash (hook), markdown skills/commands. Reuses `scripts/{fingerprint,extract_fastapi,sync_state}.py` and the `api-contract-sync` skill.

## Global Constraints

- Python 3 stdlib only; tests run with bare `python3`/`bash`, no pytest.
- **Safe by default:** `low`/`off` never edit code and never commit. Tokens spent only when the user accepts the nudge.
- `sync_level` values: `off` | `low` | `hard`. Absent → treat as `low`.
- The Stop hook ALWAYS exits 0 (never blocks the turn) and never edits code.
- Hard-mode autopilot auto-commits/merges **only on a non-default branch**; on `master`/`main` it refuses, reports, and tells the user to branch.
- FastAPI backends get a precise fingerprint gate; other stacks get a coarse "contract-file-changed" gate.
- Hook state file `.fullstack-sync.hook.json` is gitignored.

---

### Task 1: Drift-gate decision (`sync_gate.py`)

**Files:**
- Create: `scripts/sync_gate.py`
- Test: `tests/test_sync_gate.py`

**Interfaces:**
- Produces: `match_contract_files(changed_files: list[str], globs: list[str]) -> list[str]` and `decide(contract_files_changed: bool, current_hash: str|None, last_hash: str|None) -> "NUDGE"|"SILENT"`, both importable. CLI: `match` (globs as `--glob`, files on stdin) and `decide` (`--contract-changed`, `--current-hash`, `--last-hash`; exit 0 NUDGE / 1 SILENT). Task 2's hook calls both.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sync_gate.py`:

```python
import sys, os, traceback
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from sync_gate import match_contract_files, decide

CHANGED = ["routers/users.py", "routers/sub/orders.py", "README.md", "lib/api.dart"]
GLOBS = ["routers/**/*.py", "lib/api.dart"]


def test_match_keeps_glob_and_exact_drops_others():
    got = sorted(match_contract_files(CHANGED, GLOBS))
    assert got == ["lib/api.dart", "routers/sub/orders.py", "routers/users.py"]


def test_match_single_star_not_cross_dir():
    # "routers/*.py" must NOT match a nested file
    assert match_contract_files(["routers/a/b.py"], ["routers/*.py"]) == []
    assert match_contract_files(["routers/b.py"], ["routers/*.py"]) == ["routers/b.py"]


def test_match_ignores_empty_globs():
    assert match_contract_files(["x.py"], ["", None]) == []


def test_decide_silent_when_no_contract_change():
    assert decide(False, "abc", "abc") == "SILENT"


def test_decide_nudge_coarse_when_no_current_hash():
    assert decide(True, None, "abc") == "NUDGE"


def test_decide_nudge_when_hash_moved():
    assert decide(True, "new", "old") == "NUDGE"


def test_decide_silent_when_hash_unchanged():
    # contract file touched (e.g. a comment) but hash identical
    assert decide(True, "same", "same") == "SILENT"


def test_decide_nudge_on_first_run_precise():
    assert decide(True, "abc", None) == "NUDGE"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"PASS {fn.__name__}")
        except AssertionError:
            failed += 1; print(f"FAIL {fn.__name__}"); traceback.print_exc()
    sys.exit(1 if failed else 0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tests/test_sync_gate.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'sync_gate'`.

- [ ] **Step 3: Write the implementation**

Create `scripts/sync_gate.py`:

```python
#!/usr/bin/env python3
"""Pure drift-gate decision for the sync Stop hook (tested apart from IO).

The hook does the git/extraction IO; this module decides whether to nudge.
"""
import re, sys, argparse


def _glob_to_re(glob):
    g = glob.replace("\\", "/")
    out, i = "^", 0
    while i < len(g):
        if g[i:i+2] == "**":
            out += ".*"
            i += 2
            if i < len(g) and g[i] == "/":
                i += 1
        elif g[i] == "*":
            out += "[^/]*"
            i += 1
        elif g[i] == "?":
            out += "."
            i += 1
        else:
            out += re.escape(g[i])
            i += 1
    return re.compile(out + "$")


def match_contract_files(changed_files, globs):
    """Subset of changed_files matching any (non-empty) contract glob."""
    pats = [_glob_to_re(g) for g in globs if g]
    return [f for f in changed_files if any(p.match(f) for p in pats)]


def decide(contract_files_changed, current_hash, last_hash):
    """NUDGE or SILENT.

    current_hash is None in coarse mode (no deterministic extractor): any
    contract-file change nudges. In precise mode, nudge only when the hash moved.
    """
    if not contract_files_changed:
        return "SILENT"
    if current_hash is None:
        return "NUDGE"
    if current_hash != last_hash:
        return "NUDGE"
    return "SILENT"


def _main(argv):
    p = argparse.ArgumentParser(prog="sync_gate")
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("match")
    m.add_argument("--glob", action="append", default=[])
    d = sub.add_parser("decide")
    d.add_argument("--contract-changed", action="store_true")
    d.add_argument("--current-hash", default="")
    d.add_argument("--last-hash", default="")
    a = p.parse_args(argv)
    if a.cmd == "match":
        files = [ln.strip() for ln in sys.stdin if ln.strip()]
        for f in match_contract_files(files, a.glob):
            print(f)
        return 0
    if a.cmd == "decide":
        res = decide(a.contract_changed, a.current_hash or None, a.last_hash or None)
        print(res)
        return 0 if res == "NUDGE" else 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 tests/test_sync_gate.py`
Expected: all 8 `PASS`, exit 0.

- [ ] **Step 5: Verify the CLI**

Run:
```
printf 'routers/users.py\nREADME.md\n' | python3 scripts/sync_gate.py match --glob 'routers/**/*.py'
python3 scripts/sync_gate.py decide --contract-changed --current-hash a --last-hash b; echo "exit=$?"
```
Expected: first prints `routers/users.py`; second prints `NUDGE` then `exit=0`.

- [ ] **Step 6: Commit**

```bash
git add scripts/sync_gate.py tests/test_sync_gate.py
git commit -m "feat: pure drift-gate decision for sync hook"
```

---

### Task 2: Stop hook (`sync-stop.sh`)

**Files:**
- Create: `hooks/sync-stop.sh`
- Test: `tests/test_sync_hook.sh`

**Interfaces:**
- Consumes: `scripts/sync_gate.py` (`match`, `decide`), `scripts/extract_fastapi.py`, `scripts/fingerprint.py`, `.fullstack-sync.json` (`sync_level`, `backend.{stack,root,routers_glob,schemas_glob}`, `app.{endpoints_file,services_glob}`).
- Produces: a Stop hook script that prints a one-line nudge to stdout on drift, silent otherwise, always exit 0. Reads repo root from `$CLAUDE_PROJECT_DIR`, plugin root from `$CLAUDE_PLUGIN_ROOT`. Writes `.fullstack-sync.hook.json` (`{"last_hash": ...}`).

- [ ] **Step 1: Write the failing integration test**

Create `tests/test_sync_hook.sh`:

```bash
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `bash tests/test_sync_hook.sh`
Expected: FAIL (hook script does not exist yet; assertions fail / errors).

- [ ] **Step 3: Write the hook**

Create `hooks/sync-stop.sh`:

```bash
#!/usr/bin/env bash
# Drift-gated, suggest-only contract review nudge. Never edits, never blocks.
set -u
ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
PLUGIN="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
CFG="$ROOT/.fullstack-sync.json"
[ -f "$CFG" ] || exit 0
command -v git >/dev/null 2>&1 || exit 0
git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1 || exit 0

jget(){ python3 -c "import json,sys;d=json.load(open('$CFG'));print(eval(sys.argv[1]) or '')" "$1" 2>/dev/null; }
LEVEL="$(jget "d.get('sync_level','low')")"; [ -n "$LEVEL" ] || LEVEL="low"
[ "$LEVEL" = "off" ] && exit 0

# contract globs
GLOBARGS=()
for expr in "d.get('backend',{}).get('routers_glob','')" \
            "d.get('backend',{}).get('schemas_glob','')" \
            "d.get('app',{}).get('endpoints_file','')" \
            "d.get('app',{}).get('services_glob','')"; do
  v="$(jget "$expr")"; [ -n "$v" ] && GLOBARGS+=(--glob "$v")
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
STACK="$(jget "d.get('backend',{}).get('stack','')")"
CUR=""
if [ "$STACK" = "fastapi" ]; then
  BROOT="$(jget "d.get('backend',{}).get('root','')")"
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
```

- [ ] **Step 4: Make executable + run the test**

Run: `chmod +x hooks/sync-stop.sh && bash tests/test_sync_hook.sh`
Expected: 5 `PASS` lines + `HOOK OK`, exit 0.

- [ ] **Step 5: Commit**

```bash
git add hooks/sync-stop.sh tests/test_sync_hook.sh
git commit -m "feat: drift-gated suggest-only sync Stop hook"
```

---

### Task 3: Review skill + command

**Files:**
- Create: `skills/fullstack-sync-review/SKILL.md`
- Create: `commands/fullstack-sync-review.md`

**Interfaces:**
- Consumes: `.fullstack-sync.json` (`backend.root`, `app.root`, globs, `sync_level`), `api-contract-sync` skill, `git` for branch detection + diff.
- Produces: a model-invoked review. Report-only by default; low = scoped+lens-selected; hard = full both-repos+all-lenses with autopilot guarded off the default branch.

- [ ] **Step 1: Write the skill**

Create `skills/fullstack-sync-review/SKILL.md`:

````markdown
---
name: fullstack-sync-review
description: Review contract-affecting changes between a client app and its backend after an edit. Use when the user says "review the sync", "fullstack review", "review my api changes", "check routes/params/security", accepts the post-change nudge, or runs /fullstack-sync-review. Reports findings one per line (location, problem, fix); does not edit unless asked. A `--hard` / "hard review" pass covers both repos across all lenses and, on a feature branch only, can auto-sync + commit.
---

# Fullstack Sync Review

Review what changed in the contract and report findings. Read `.fullstack-sync.json`
(app root) for `backend.root`, `app.root`, the globs, and `sync_level`. Default is
**report-only** — do not edit unless the user asks (low) or hard autopilot applies.

## 1. Scope

- **low** (default): review the **diff of the contract-affecting change** only —
  `git diff` on the touched routers/schemas (backend) or endpoints/services (app). Do not
  read the whole repo.
- **hard** (`--hard` or "hard review"): review the **full diff across BOTH repos**
  (`backend.root` and `app.root`).

## 2. Lenses

Pick lenses by what changed (low) or use all (hard):

| Change type | Lenses (low) |
|---|---|
| route / path / method | contract, security |
| field / schema / param | contract, params |
| logic only (no contract move) | bugs, best-practice |

**hard** runs every lens: api, routes, params, logic, architecture, bugs, improvements,
best-practice, security. For the **contract** lens, invoke `api-contract-sync` rather than
re-deriving drift here.

## 3. Report

One line per finding, most severe first:

```
<path>:<line>: <BLOCKER|WARN|NIT>: <problem>. <fix>.
```

Collapse "looks fine" areas to a count. End with a one-line summary.

## 4. Fixes

- **low**: report only. Offer to apply fixes; apply only what the user approves.
- **hard autopilot**: after reporting, run the sync fixes (`api-contract-sync`) on both
  sides, then **commit and merge** — but FIRST check the branch:
  `git rev-parse --abbrev-ref HEAD`. If it is `master` or `main`, **refuse** to auto-commit:
  print the findings, say "hard autopilot won't commit on the default branch — create a
  feature branch first", and stop. Otherwise stage + commit the synced changes with a
  message like `sync: reconcile contract (<endpoint>)` and, if on a worktree/feature
  branch, merge per the user's normal flow.

## Output

The findings block + the chosen scope/level + (hard) what was committed or why it was
refused.
````

- [ ] **Step 2: Write the command**

Create `commands/fullstack-sync-review.md`:

```markdown
---
description: Run a contract review of recent changes — scoped (low) or full both-repos (hard). Report-only by default; hard can auto-sync+commit on a feature branch.
argument-hint: "[--hard]"
allowed-tools: Bash(git rev-parse:*), Bash(git diff:*), Bash(git branch:*)
---

# Fullstack Sync Review

Invoke the `fullstack-sync-review` skill. If `$ARGUMENTS` contains `--hard`, run the
**hard** path (full diff across both repos, all lenses, autopilot guarded off the default
branch). Otherwise run the **low** path (scoped diff, lens-selected, report-only).

Current branch: !`git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown`
```

- [ ] **Step 3: Validate**

Run: `head -3 skills/fullstack-sync-review/SKILL.md` → `---`, `name: fullstack-sync-review`, a `description:` starting "Review contract-affecting".
Run: `grep -c 'master\|main' skills/fullstack-sync-review/SKILL.md` → ≥1 (the branch guard).
Run: `grep -c 'report only\|report-only' skills/fullstack-sync-review/SKILL.md` → ≥1.

- [ ] **Step 4: Commit**

```bash
git add skills/fullstack-sync-review/SKILL.md commands/fullstack-sync-review.md
git commit -m "feat: fullstack-sync-review skill + command (low/hard, branch-guarded)"
```

---

### Task 4: Config, hook registration, docs

**Files:**
- Modify: `commands/fullstack-setup.md` (write `sync_level` into config)
- Modify: `.claude-plugin/plugin.json` (register Stop hook + update description)
- Modify: `README.md` (Sync levels section)
- Modify: `.gitignore` (add `.fullstack-sync.hook.json`)
- Modify: `tests/run.sh` (add hook + gate tests)

**Interfaces:**
- Consumes: all prior tasks (hook path, command/skill names, config key).
- Produces: a wired, documented feature; default `sync_level: low`.

- [ ] **Step 1: Add the gate + hook tests to the runner**

In `tests/run.sh`, add these two lines after the `extract_fastapi` line:

```bash
echo "== unit: sync_gate ==";  python3 "$HERE/test_sync_gate.py"  || fail=1
echo "== integration: sync_hook =="; bash "$HERE/test_sync_hook.sh" || fail=1
```

- [ ] **Step 2: Ignore the hook state file**

Append to `.gitignore`:

```
.fullstack-sync.hook.json
```

- [ ] **Step 3: Register the Stop hook + update description**

In `.claude-plugin/plugin.json`, add a `Stop` array inside `hooks` (alongside the existing
`SessionStart`), and append the safety framing to `description`. The `hooks` object becomes:

```json
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash \"${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh\"",
            "timeout": 10,
            "statusMessage": "Checking fullstack-sync config..."
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash \"${CLAUDE_PLUGIN_ROOT}/hooks/sync-stop.sh\"",
            "timeout": 15,
            "statusMessage": "Checking contract drift..."
          }
        ]
      }
    ]
  }
```

And change the `description` value to end with: `Safe by default: asks for the dir, then only nudges on contract drift — no tokens or commits unless you allow; hard mode is opt-in autopilot.`

- [ ] **Step 4: Write `sync_level` in setup**

In `commands/fullstack-setup.md`, in the config shape (Step 4) add `"sync_level": "low"` as a
top-level key, and add one line to the prose: "Set `sync_level` to `low` by default (the
safe, drift-gated nudge); the user can change it to `off` or `hard` later."

- [ ] **Step 5: README Sync levels section**

In `README.md`, after the "Parallel mode" section, add:

```markdown
## Sync levels (safe by default)

`sync_level` in `.fullstack-sync.json` controls the post-change nudge. **Default `low`** —
the plugin asks for your dirs, then stays quiet until a contract file actually changes; it
spends no tokens and touches no code or commits unless you accept the nudge.

| Level | Behaviour |
|-------|-----------|
| `off` | silent, fully manual |
| `low` *(default)* | drift-gated Stop hook prints a one-line "contract moved — review?" suggestion; you decide. `/fullstack-sync-review` runs a scoped, lens-selected, report-only review |
| `hard` | `/fullstack-sync-review --hard` (or the hook in hard mode) reviews both repos across all lenses and can auto-sync + commit — **only on a feature branch; it refuses on master/main** |

FastAPI backends get a precise fingerprint gate; other stacks get a coarser "contract files
changed" gate until more extractors exist. See
`docs/superpowers/specs/2026-06-30-sync-level-review-design.md`.
```

- [ ] **Step 6: Validate everything**

Run: `python3 -c "import json; d=json.load(open('.claude-plugin/plugin.json')); print('Stop' in d['hooks'])"` → `True`.
Run: `bash tests/run.sh` → all sections green (`fingerprint`, `sync_state`, `extract_fastapi`, `sync_gate`, `protocol`, `sync_hook`), `ALL GREEN`.
Run: `git check-ignore .fullstack-sync.hook.json` → prints the path.

- [ ] **Step 7: Commit**

```bash
git add commands/fullstack-setup.md .claude-plugin/plugin.json README.md .gitignore tests/run.sh
git commit -m "feat: register sync Stop hook, sync_level config, docs (safe by default)"
```

---

## Self-Review

**Spec coverage:**
- Three levels + default low → Task 1 (decide), Task 2 (hook reads level), Task 4 (config/setup). ✓
- Cheap pre-gate (glob filter) → Task 1 `match_contract_files` + Task 2 hook. ✓
- FastAPI precise / other coarse → Task 1 `decide` (None=coarse) + Task 2 (extract only when stack==fastapi). ✓
- Suggest-only, never edits/commits in hook → Task 2 (prints only, exit 0). ✓
- Review scoped/lens-selected (low) vs full/all (hard) → Task 3. ✓
- Report-only default, fix on request → Task 3 §4. ✓
- Hard autopilot auto-commit + branch guard (refuse on master/main) → Task 3 §4. ✓
- Reuse api-contract-sync for contract lens → Task 3 §2. ✓
- Config in .fullstack-sync.json → Task 4 Step 4. ✓
- plugin.json Stop registration + description → Task 4 Step 3. ✓
- README safe-by-default + repo description → Task 4 Steps 3, 5. ✓
- hook state gitignored → Task 4 Step 2. ✓
- Tests: hook (Task 2), gate (Task 1), wired into run.sh (Task 4 Step 1). ✓

**Placeholder scan:** No TBD/TODO; full code/content in every step. ✓

**Type consistency:** `match_contract_files`, `decide`, the `match`/`decide` CLI subcommands, `.fullstack-sync.hook.json`, `sync_level`, `/fullstack-sync-review` are used identically across Tasks 1–4. Hook env vars `CLAUDE_PROJECT_DIR` / `CLAUDE_PLUGIN_ROOT` consistent. ✓
