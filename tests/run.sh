#!/usr/bin/env bash
# Run the whole fullstack-sync test suite. Zero deps beyond python3 + git.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
fail=0
echo "== unit: fingerprint =="; python3 "$HERE/test_fingerprint.py" || fail=1
echo "== unit: sync_state ==";  python3 "$HERE/test_sync_state.py"  || fail=1
echo "== unit: extract_fastapi =="; python3 "$HERE/test_extract_fastapi.py" || fail=1
echo "== unit: sync_gate ==";  python3 "$HERE/test_sync_gate.py"  || fail=1
echo "== integration: sync_hook =="; bash "$HERE/test_sync_hook.sh" || fail=1
echo "== integration: protocol =="; bash "$HERE/test_protocol.sh"  || fail=1
echo "----"
[ "$fail" -eq 0 ] && echo "ALL GREEN" || echo "SUITE FAILED"
exit "$fail"
