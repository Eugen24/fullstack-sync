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
        assert [(e["method"], e["path"], e["fields"], e["model"]) for e in eps] == [("GET", "/health/ping", [], None)]
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


def test_walk_skips_venv_vcs_and_cache_dirs():
    tmp = tempfile.mkdtemp()
    try:
        _write(tmp, "users.py", ROUTER)
        for skip in (".venv", "node_modules", ".git", "__pycache__", ".worktrees"):
            d = os.path.join(tmp, skip, "lib")
            os.makedirs(d)
            _write(d, "vendored.py", NO_MODEL)
        eps = extract_fastapi.extract([tmp])["endpoints"]
        assert len(eps) == 2  # users only; nothing from the pruned dirs
    finally:
        shutil.rmtree(tmp)


def test_unparseable_file_is_skipped_not_fatal():
    tmp = tempfile.mkdtemp()
    try:
        _write(tmp, "users.py", ROUTER)
        _write(tmp, "broken.py", "def (:\n")
        with open(os.path.join(tmp, "binary.py"), "wb") as f:
            f.write(b"\xff\xfe\x00bad")
        eps = extract_fastapi.extract([tmp])["endpoints"]
        assert len(eps) == 2
    finally:
        shutil.rmtree(tmp)


def test_deadline_exceeded_raises():
    tmp = tempfile.mkdtemp()
    try:
        _write(tmp, "users.py", ROUTER)
        try:
            extract_fastapi.extract([tmp], max_seconds=-1)
        except TimeoutError:
            return
        raise AssertionError("expected TimeoutError")
    finally:
        shutil.rmtree(tmp)


def _tree_dir(files):
    tmp = tempfile.mkdtemp()
    for rel, src in files.items():
        p = os.path.join(tmp, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write(src)
    return tmp


def _by(eps, method, path):
    return next(e for e in eps if e["method"] == method and e["path"] == path)


def test_response_model_resolved_across_files_with_inheritance():
    tmp = _tree_dir({
        "schemas.py": "class Base(BaseModel):\n    id: int\nclass UserOut(Base):\n    email: str\n",
        "routers/users.py": "from schemas import UserOut\nrouter = APIRouter(prefix='/u')\n@router.get('/{id}', response_model=UserOut)\ndef g(): ...\n",
    })
    try:
        e = _by(extract_fastapi.extract([tmp])["endpoints"], "GET", "/u/{id}")
        assert e["fields"] == ["email", "id"] and e["model"] == "UserOut"
    finally:
        shutil.rmtree(tmp)


def test_generic_wrappers_and_return_annotation():
    tmp = _tree_dir({"r.py": (
        "class Item(BaseModel):\n    sku: str\n"
        "router = APIRouter()\n"
        "@router.get('/a', response_model=List[Item])\ndef a(): ...\n"
        "@router.get('/b', response_model=Optional[Item])\ndef b(): ...\n"
        "@router.get('/c')\ndef c() -> Item: ...\n"
        "@router.get('/d')\ndef d() -> list[Item] | None: ...\n"
        "@router.get('/e')\ndef e() -> dict: ...\n")})
    try:
        eps = extract_fastapi.extract([tmp])["endpoints"]
        for path in ("/a", "/b", "/c", "/d"):
            assert _by(eps, "GET", path)["fields"] == ["sku"], path
        assert _by(eps, "GET", "/e")["model"] is None
    finally:
        shutil.rmtree(tmp)


def test_field_alias_is_a_field_name():
    tmp = _tree_dir({"r.py": (
        "class M(BaseModel):\n    vote_count: int = Field(alias='voteCount')\n"
        "router = APIRouter()\n@router.get('/m', response_model=M)\ndef m(): ...\n")})
    try:
        assert _by(extract_fastapi.extract([tmp])["endpoints"], "GET", "/m")["fields"] == ["voteCount", "vote_count"]
    finally:
        shutil.rmtree(tmp)


def test_include_router_prefix_is_applied():
    tmp = _tree_dir({
        "app/routers/users.py": "router = APIRouter(prefix='/users')\n@router.get('/{id}')\ndef g(): ...\n",
        "app/routers/items.py": "router = APIRouter()\n@router.get('/x')\ndef g(): ...\n",
        "app/main.py": ("from app.routers import users\nfrom app.routers.items import router as items_router\n"
                        "app = FastAPI()\napp.include_router(users.router, prefix='/v1')\n"
                        "app.include_router(items_router, prefix='/v2')\n"),
    })
    try:
        paths = {e["path"] for e in extract_fastapi.extract([tmp])["endpoints"]}
        assert paths == {"/v1/users/{id}", "/v2/x"}, paths
    finally:
        shutil.rmtree(tmp)


def test_prefix_rule_from_directory_layout():
    tmp = _tree_dir({
        "routers/v4/tasks.py": "router = APIRouter()\n@router.get('/list')\ndef g(): ...\n",
        "routers/root/health.py": "router = APIRouter()\n@router.get('/ping')\ndef g(): ...\n",
    })
    try:
        rule = {"from_path": "routers", "skip": ["root"]}
        paths = {e["path"] for e in extract_fastapi.extract([tmp], prefix_rule=rule)["endpoints"]}
        assert paths == {"/v4/tasks/list", "/ping"}, paths
    finally:
        shutil.rmtree(tmp)


def test_universe_is_every_name_the_backend_mentions():
    tmp = _tree_dir({"m.py": (
        "class U(Base):\n    name = Column(String)\n    age: int\n"
        "def f(user, row_key):\n    x = user.streak_frozen_until\n"
        "    y = Out(callback_url=1)\n    z = row['plain_key']\n    w = getattr(user, 'dyn_attr')\n"
        "    return {'xp_reward': 1, 'nested': {'deep_key': 2}, 'has space': 3}\n")})
    try:
        u = extract_fastapi.all_model_fields([tmp])
        assert {"name", "age", "streak_frozen_until", "callback_url", "plain_key", "dyn_attr",
                "xp_reward", "nested", "deep_key", "row_key"} <= u
        assert "has space" not in u and "never_mentioned" not in u
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
