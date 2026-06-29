import sys, os, traceback
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from fingerprint import fingerprint

base = {"endpoints": [
    {"method": "GET",  "path": "/users/{id}", "fields": ["email", "id"]},
    {"method": "POST", "path": "/users",      "fields": ["email", "name"]},
]}

def test_deterministic():
    assert fingerprint(base) == fingerprint(base)

def test_endpoint_order_invariant():
    reordered = {"endpoints": list(reversed(base["endpoints"]))}
    assert fingerprint(base) == fingerprint(reordered)

def test_field_order_invariant():
    swapped = {"endpoints": [
        {"method": "GET",  "path": "/users/{id}", "fields": ["id", "email"]},
        {"method": "POST", "path": "/users",      "fields": ["name", "email"]},
    ]}
    assert fingerprint(base) == fingerprint(swapped)

def test_method_case_invariant():
    lowered = {"endpoints": [
        {"method": "get",  "path": "/users/{id}", "fields": ["email", "id"]},
        {"method": "post", "path": "/users",      "fields": ["email", "name"]},
    ]}
    assert fingerprint(base) == fingerprint(lowered)

def test_field_rename_changes_hash():
    renamed = {"endpoints": [
        {"method": "GET",  "path": "/users/{id}", "fields": ["email", "userId"]},
        {"method": "POST", "path": "/users",      "fields": ["email", "name"]},
    ]}
    assert fingerprint(base) != fingerprint(renamed)

def test_returns_64_char_hex():
    h = fingerprint(base)
    assert len(h) == 64 and all(c in "0123456789abcdef" for c in h)

if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"PASS {fn.__name__}")
        except AssertionError:
            failed += 1; print(f"FAIL {fn.__name__}"); traceback.print_exc()
    sys.exit(1 if failed else 0)
