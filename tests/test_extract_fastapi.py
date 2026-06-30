import sys, os, json, tempfile, shutil, traceback
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import extract_fastapi
from fingerprint import fingerprint

ROUTER = '''
router = APIRouter(prefix="/v3/users")

class UserOut(BaseModel):
    id: int
    email: str
    created_at: datetime

class OrderOut(BaseModel):
    order_id: int
    total_cents: int
    created_at: datetime

@router.get("/{id}", response_model=UserOut)
def get_user(id: int): ...

@router.post("/{id}/orders", response_model=OrderOut)
def create_order(id: int): ...
'''

NO_MODEL = '''
router = APIRouter(prefix="/health")

@router.get("/ping")
def ping(): ...
'''


def _write(tmp, name, src):
    p = os.path.join(tmp, name)
    with open(p, "w") as f:
        f.write(src)
    return p


def test_extracts_method_path_with_prefix():
    tmp = tempfile.mkdtemp()
    try:
        p = _write(tmp, "users.py", ROUTER)
        eps = extract_fastapi.extract([p])["endpoints"]
        paths = {(e["method"], e["path"]) for e in eps}
        assert ("GET", "/v3/users/{id}") in paths
        assert ("POST", "/v3/users/{id}/orders") in paths
    finally:
        shutil.rmtree(tmp)


def test_path_params_normalized_to_id():
    tmp = tempfile.mkdtemp()
    try:
        src = 'router = APIRouter(prefix="/v3")\n@router.get("/items/{item_id}")\ndef f(): ...\n'
        p = _write(tmp, "r.py", src)
        eps = extract_fastapi.extract([p])["endpoints"]
        assert eps[0]["path"] == "/v3/items/{id}"
    finally:
        shutil.rmtree(tmp)


def test_response_model_fields_extracted():
    tmp = tempfile.mkdtemp()
    try:
        p = _write(tmp, "users.py", ROUTER)
        eps = extract_fastapi.extract([p])["endpoints"]
        get = next(e for e in eps if e["method"] == "GET")
        assert get["fields"] == ["created_at", "email", "id"]  # sorted
        post = next(e for e in eps if e["method"] == "POST")
        assert post["fields"] == ["created_at", "order_id", "total_cents"]
    finally:
        shutil.rmtree(tmp)


def test_endpoint_without_response_model_has_empty_fields():
    tmp = tempfile.mkdtemp()
    try:
        p = _write(tmp, "health.py", NO_MODEL)
        eps = extract_fastapi.extract([p])["endpoints"]
        assert eps == [{"method": "GET", "path": "/health/ping", "fields": []}]
    finally:
        shutil.rmtree(tmp)


def test_directory_walk_collects_all_files():
    tmp = tempfile.mkdtemp()
    try:
        sub = os.path.join(tmp, "routers")
        os.makedirs(sub)
        _write(sub, "users.py", ROUTER)
        _write(sub, "health.py", NO_MODEL)
        eps = extract_fastapi.extract([sub])["endpoints"]
        assert len(eps) == 3  # 2 from users + 1 from health
    finally:
        shutil.rmtree(tmp)


def test_output_feeds_fingerprint():
    tmp = tempfile.mkdtemp()
    try:
        p = _write(tmp, "users.py", ROUTER)
        contract = extract_fastapi.extract([p])
        h = fingerprint(contract)
        assert len(h) == 64  # extractor output is a valid contract for the hasher
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"PASS {fn.__name__}")
        except AssertionError:
            failed += 1; print(f"FAIL {fn.__name__}"); traceback.print_exc()
    sys.exit(1 if failed else 0)
