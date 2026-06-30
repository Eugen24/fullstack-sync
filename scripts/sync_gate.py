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
