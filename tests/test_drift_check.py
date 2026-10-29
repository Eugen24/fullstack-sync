import sys, os, json, tempfile, shutil, subprocess, traceback
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import drift_check as dc

SCRIPT = os.path.join(HERE, "..", "scripts", "drift_check.py")
ROUTER = '''router = APIRouter(prefix="/v1/users")
@router.get("/{id}")
def get_user(id: int): ...
@router.post("/{id}/orders")
def create_order(id: int): ...
'''
API_DART = """class Api {
  Future<void> a() => _dio.get('/v1/users/$id');
  Future<void> b() => _dio.post(
    '/v1/users/${user.id}/orders',
    data: {});
  Future<void> c() => http.get(Uri.parse('$apiBase/v1/users/7?x=1'));
}
"""
SCREEN_DART = """void go(c) { c.go('/home'); c.push('/chat'); Image.asset('/assets/x.png'); }"""


def _repo(files, app_cfg=None, backend_src=ROUTER):
    w = tempfile.mkdtemp()
    for rel, src in files.items():
        p = os.path.join(w, "app", rel); os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write(src)
    os.makedirs(os.path.join(w, "be", "routers"))
    open(os.path.join(w, "be", "routers", "users.py"), "w").write(backend_src)
    cfg = {"app": {"root": os.path.join(w, "app"), "endpoints_file": None, "services_glob": "lib/**/*.dart", **(app_cfg or {})},
           "backend": {"root": os.path.join(w, "be")}}
    json.dump(cfg, open(os.path.join(w, "cfg.json"), "w"))
    return w


def _run(w, *args):
    r = subprocess.run([sys.executable, "-I", SCRIPT, "--config", os.path.join(w, "cfg.json"), *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def test_norm_params_query_case_and_slash():
    assert dc.norm("/V1/Users/$id/") == "/v1/users/{id}"
    assert dc.norm("/v1/users/${u.id}?x=1") == "/v1/users/{id}"
    assert dc.norm("/v1/items/{item_id}") == "/v1/items/{id}"
    assert dc.norm("/v1/users/7/orders") == "/v1/users/{id}/orders"
    assert dc.norm("/v2/users") == "/v2/users"  # version segments are not ids


def test_served_tolerates_prefix_on_either_side():
    assert dc.served("/auth/login", {"/v1/auth/login"})      # dio baseUrl supplies /v1
    assert dc.served("/v1/auth/login", {"/auth/login"})      # extractor missed include_router prefix
    assert not dc.served("/auth/loginx", {"/v1/auth/login"})
    assert not dc.served("/orders", {"/v1/order"})


def test_base_prefix_constants_are_not_checked():
    app = {"/v4": "a:1", "/v4/tasks": "a:2", "/ghost": "a:3"}
    assert dc.check(app, {"/v4/tasks"}) == [("/ghost", "a:3")]


def test_app_paths_only_in_call_context_and_skips_assets():
    w = _repo({"lib/api.dart": API_DART, "lib/screen.dart": SCREEN_DART})
    try:
        files = dc._files(json.load(open(os.path.join(w, "cfg.json"))))
        paths = dc.app_paths(files)
        assert "/v1/users/{id}" in paths and "/v1/users/{id}/orders" in paths
        assert not any(p in paths for p in ("/home", "/chat", "/assets/x.png"))
    finally:
        shutil.rmtree(w)


def test_endpoints_file_counts_every_literal():
    w = _repo({"lib/endpoints.dart": "const login = '/v1/auth/login';\n"})
    try:
        f = os.path.join(w, "app", "lib", "endpoints.dart")
        assert "/v1/auth/login" in dc.app_paths([f], [f])
        assert "/v1/auth/login" not in dc.app_paths([f])
    finally:
        shutil.rmtree(w)


def test_cli_ok_when_in_sync():
    w = _repo({"lib/api.dart": API_DART})
    try:
        rc, out, _ = _run(w)
        assert rc == 0 and "0 not served" in out, (rc, out)
    finally:
        shutil.rmtree(w)


def test_cli_exit_1_on_drift_and_warn_exits_0():
    drifted = API_DART + "\nvoid d() => _dio.get('/v1/users/$id/ordres');\n"
    w = _repo({"lib/api.dart": drifted})
    try:
        rc, out, _ = _run(w)
        assert rc == 1 and "/v1/users/{id}/ordres" in out, (rc, out)
        rc, _, _ = _run(w, "--warn")
        assert rc == 0
        rc, out, _ = _run(w, "--json")
        assert rc == 1 and json.loads(out)["missing"][0]["path"] == "/v1/users/{id}/ordres"
    finally:
        shutil.rmtree(w)


def test_cli_openapi_source():
    w = _repo({"lib/api.dart": "void a() => _dio.get('/v1/ping');\n"})
    try:
        spec = os.path.join(w, "spec.json")
        json.dump({"paths": {"/v1/ping": {}}}, open(spec, "w"))
        assert _run(w, "--openapi", spec)[0] == 0
        json.dump({"paths": {"/v1/pong": {}}}, open(spec, "w"))
        assert _run(w, "--openapi", spec)[0] == 1
    finally:
        shutil.rmtree(w)


def test_cli_exit_2_on_bad_input():
    w = _repo({"lib/api.dart": "// no calls here\n"})
    try:
        assert _run(w)[0] == 2                      # no app paths found
        assert _run(w, "--openapi", "/nonexistent.json")[0] == 2
        assert subprocess.run([sys.executable, "-I", SCRIPT, "--config", "/nonexistent"],
                              capture_output=True).returncode == 2
    finally:
        shutil.rmtree(w)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"PASS {fn.__name__}")
        except AssertionError:
            failed += 1; print(f"FAIL {fn.__name__}"); traceback.print_exc()
    sys.exit(1 if failed else 0)
