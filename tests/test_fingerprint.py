import sys, os, traceback
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from fingerprint import fingerprint, normalize_field

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

# --- field normalization (M-2): camel/snake collapse to one form ---

def test_normalize_camel_to_snake():
    assert normalize_field("createdAt") == "created_at"
    assert normalize_field("userId") == "user_id"
    assert normalize_field("firstName") == "first_name"

def test_normalize_snake_is_idempotent():
    # backend names are already snake_case — must pass through unchanged
    for f in ("created_at", "user_id", "id", "email", "oauth2_token"):
        assert normalize_field(f) == f

def test_normalize_trailing_acronym():
    # userID / userId both collapse to user_id
    assert normalize_field("userID") == "user_id"
    assert normalize_field("userId") == "user_id"

def test_normalize_pascal_and_separators():
    assert normalize_field("HTTPStatus") == "http_status"
    assert normalize_field("first-name") == "first_name"
    assert normalize_field("first name") == "first_name"

def test_app_camel_equals_backend_snake():
    # THE point: app's camelCase contract hashes identical to backend's snake_case
    backend = {"endpoints": [
        {"method": "GET", "path": "/users/{id}", "fields": ["created_at", "user_id"]},
    ]}
    app = {"endpoints": [
        {"method": "GET", "path": "/users/{id}", "fields": ["createdAt", "userId"]},
    ]}
    assert fingerprint(backend) == fingerprint(app)

def test_acronym_boundary_caveat():
    # Documented limit: a leading/embedded acronym does NOT round-trip to a
    # single-letter-split snake form. "OAuth2Token" -> "o_auth2_token", which
    # only matches a backend field literally named "o_auth2_token" (NOT
    # "oauth2_token"). Both sides must agree on the snake spelling of acronyms.
    assert normalize_field("OAuth2Token") == "o_auth2_token"
    assert normalize_field("OAuth2Token") != normalize_field("oauth2_token")

if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"PASS {fn.__name__}")
        except AssertionError:
            failed += 1; print(f"FAIL {fn.__name__}"); traceback.print_exc()
    sys.exit(1 if failed else 0)
