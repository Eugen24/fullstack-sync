#!/usr/bin/env python3
"""Deterministic structural fingerprint of an API contract.

Reads {"endpoints": [{"method","path","fields"}]} on stdin, prints sha256 hex.
Sorts endpoints and fields internally so ordering never affects the hash.
Field names are normalized to snake_case so the app side's camelCase and the
backend's snake_case produce the SAME hash when the contract agrees.
Scope is structural ONLY (method/path/fields) — never auth/errors/envelopes.
"""
import sys, re, json, hashlib

# camelCase / PascalCase -> snake_case. Idempotent on snake_case input.
_CAMEL_WORD = re.compile(r"(.)([A-Z][a-z]+)")     # ...dAt   -> ...d_At
_CAMEL_TAIL = re.compile(r"([a-z0-9])([A-Z])")    # userID   -> user_ID
_DASH_SPACE = re.compile(r"[-\s]+")
_MULTI_US = re.compile(r"_+")


def normalize_field(name):
    """Collapse a field name to snake_case deterministically.

    createdAt/userId -> created_at/user_id; userID -> user_id; HTTPStatus ->
    http_status. Already-snake names pass through unchanged (idempotent).
    Caveat: an embedded acronym is split at the case boundary only, so
    "OAuth2Token" -> "o_auth2_token" (NOT "oauth2_token"); both sides must
    agree on the snake spelling of acronyms.
    """
    s = _CAMEL_WORD.sub(r"\1_\2", name)
    s = _CAMEL_TAIL.sub(r"\1_\2", s)
    s = _DASH_SPACE.sub("_", s)
    s = _MULTI_US.sub("_", s).strip("_")
    return s.lower()


def canonical(contract):
    eps = []
    for ep in contract.get("endpoints", []):
        eps.append({
            "method": ep["method"].upper(),
            "path": ep["path"],
            "fields": sorted(normalize_field(f) for f in ep.get("fields", [])),
        })
    eps.sort(key=lambda e: (e["method"], e["path"]))
    return json.dumps({"endpoints": eps}, sort_keys=True, separators=(",", ":"))


def fingerprint(contract):
    return hashlib.sha256(canonical(contract).encode("utf-8")).hexdigest()


if __name__ == "__main__":
    print(fingerprint(json.load(sys.stdin)))
