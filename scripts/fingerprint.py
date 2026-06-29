#!/usr/bin/env python3
"""Deterministic structural fingerprint of an API contract.

Reads {"endpoints": [{"method","path","fields"}]} on stdin, prints sha256 hex.
Sorts endpoints and fields internally so ordering never affects the hash.
Scope is structural ONLY (method/path/fields) — never auth/errors/envelopes.
"""
import sys, json, hashlib


def canonical(contract):
    eps = []
    for ep in contract.get("endpoints", []):
        eps.append({
            "method": ep["method"].upper(),
            "path": ep["path"],
            "fields": sorted(ep.get("fields", [])),
        })
    eps.sort(key=lambda e: (e["method"], e["path"]))
    return json.dumps({"endpoints": eps}, sort_keys=True, separators=(",", ":"))


def fingerprint(contract):
    return hashlib.sha256(canonical(contract).encode("utf-8")).hexdigest()


if __name__ == "__main__":
    print(fingerprint(json.load(sys.stdin)))
