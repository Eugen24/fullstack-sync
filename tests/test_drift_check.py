import sys, os, json, tempfile, shutil, subprocess, traceback
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import drift_check as dc

SCRIPT = os.path.join(HERE, "..", "scripts", "drift_check.py")
ROUTER = '''router = APIRouter(prefix="/v1/users")
class UserOut(BaseModel):
    id: int
    created_at: str
    total_cents: int
@router.get("/{id}", response_model=UserOut)
def get_user(id: int): ...
@router.post("/{id}/orders")
def create_order(id: int): ...
@router.delete("/{id}")
def rm(id: int): ...
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
MODEL_DART = """class U {
  factory U.fromJson(Map<String, dynamic> j) => U(
        id: j['id'],
        createdAt: j['createdAt'],
        total: j['total'],
      );
  Map<String, dynamic> toJson() => {'id': id, 'bogusKey': 1};
  void other() { final z = m['ignored_outside_json']; }
}
"""


def _repo(files, app_cfg=None, backend_src=ROUTER, cfg_extra=None):
    w = tempfile.mkdtemp()
    for rel, src in files.items():
        p = os.path.join(w, "app", rel); os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write(src)
    os.makedirs(os.path.join(w, "be", "routers"))
    open(os.path.join(w, "be", "routers", "users.py"), "w").write(backend_src)
    cfg = {"app": {"root": os.path.join(w, "app"), "endpoints_file": None, "services_glob": "lib/**/*.dart", **(app_cfg or {})},
           "backend": {"root": os.path.join(w, "be")}, **(cfg_extra or {})}
    json.dump(cfg, open(os.path.join(w, "cfg.json"), "w"))
    return w


def _run(w, *args):
    r = subprocess.run([sys.executable, "-I", SCRIPT, "--config", os.path.join(w, "cfg.json"), *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def _calls(w):
    cfg = json.load(open(os.path.join(w, "cfg.json")))
    return dc.app_calls(dc._files(cfg, "api"))


def test_norm():
    assert dc.norm("/V1/Users/$id/") == "/v1/users/{id}"
    assert dc.norm("/v1/users/${u.id}?x=1") == "/v1/users/{id}"
    assert dc.norm("/v1/users/7/orders") == "/v1/users/{id}/orders"
    assert dc.norm("/v2/users") == "/v2/users"  # version segments are not ids


def test_matches_tolerates_prefix_on_either_side():
    assert dc.matches("/auth/login", {"/v1/auth/login": set()})
    assert dc.matches("/v1/auth/login", {"/auth/login": set()})
    assert not dc.matches("/auth/loginx", {"/v1/auth/login": set()})
    assert not dc.matches("/orders", {"/v1/order": set()})


def test_app_calls_paths_verbs_and_filters():
    w = _repo({"lib/api.dart": API_DART, "lib/screen.dart": SCREEN_DART})
    try:
        c = _calls(w)
        assert c["/v1/users/{id}"]["methods"] == {"GET"}
        assert c["/v1/users/{id}/orders"]["methods"] == {"POST"}  # verb on the previous line
        assert not any(p in c for p in ("/home", "/chat", "/assets/x.png"))
    finally:
        shutil.rmtree(w)


def test_verb_does_not_leak_from_an_earlier_statement():
    src = "Future<void> del() => dio.delete('/me');\n\nFuture<User> g() => _social('/auth/google', {});\n"
    w = _repo({"lib/api.dart": src})
    try:
        c = _calls(w)
        assert c["/me"]["methods"] == {"DELETE"}
        assert c["/auth/google"]["methods"] == set()  # wrapper call: verb unknown, not DELETE
    finally:
        shutil.rmtree(w)


def test_endpoints_file_counts_every_literal_without_verb():
    w = _repo({"lib/endpoints.dart": "const login = '/v1/auth/login';\n"})
    try:
        f = os.path.join(w, "app", "lib", "endpoints.dart")
        assert dc.app_calls([f], [f])["/v1/auth/login"]["methods"] == set()
        assert "/v1/auth/login" not in dc.app_calls([f])
    finally:
        shutil.rmtree(w)


def test_check_path_and_method_findings():
    routes = {"/v1/users/{id}": {"GET", "DELETE"}, "/v1/users/{id}/orders": {"POST"}}
    calls = {"/v1/users/{id}": {"loc": "a:1", "methods": {"PUT"}},
             "/v1/users/{id}/orders": {"loc": "a:2", "methods": {"POST"}},
             "/ghost": {"loc": "a:3", "methods": {"GET"}},
             "/v4": {"loc": "a:4", "methods": set()}, "/v4/x": {"loc": "a:5", "methods": set()}}
    routes["/v4/x"] = {"GET"}
    kinds = {(k, p) for k, p, _, _ in dc.check(calls, routes)}
    assert kinds == {("METHOD", "/v1/users/{id}"), ("PATH", "/ghost")}, kinds


def test_check_ignore_list():
    assert dc.check({"/ghost": {"loc": "a:1", "methods": set()}}, {"/x": {"GET"}}, {"/ghost"}) == []


def test_inline_ignore_marker():
    w = _repo({"lib/api.dart": "Future<void> a() => _dio.get('/ghost'); // fss-ignore\n"
                               "Future<void> b() => _dio.get('/v1/users/$id');\n"})
    try:
        c = _calls(w)
        assert "/ghost" not in c and "/v1/users/{id}" in c
    finally:
        shutil.rmtree(w)


def test_app_fields_only_inside_fromjson_tojson():
    w = _repo({"lib/model.dart": MODEL_DART})
    try:
        keys = dc.app_fields([os.path.join(w, "app", "lib", "model.dart")])
        assert set(keys) == {"id", "created_at", "total", "bogus_key"}, keys  # snake-normalised; not 'ignored_outside_json'
    finally:
        shutil.rmtree(w)


def test_field_check_flags_rename_and_uses_coverage_guard():
    fields = {"id", "created_at", "total_cents"}
    f, note = dc.check_fields({"id": "a:1", "created_at": "a:2", "total": "a:3"}, fields)
    assert note is None and [x[1] for x in f] == ["total"]              # 1 of 3 unknown: listed
    f, note = dc.check_fields({"a": "x:1", "b": "x:2", "id": "x:3"}, fields)
    assert f == [] and "cannot see" in note                              # 2 of 3 unknown: skipped
    assert dc.check_fields({}, fields)[0] == []


def test_cli_ok_when_in_sync():
    w = _repo({"lib/api.dart": API_DART})
    try:
        rc, out, _ = _run(w)
        assert rc == 0 and "0 findings" in out, (rc, out)
    finally:
        shutil.rmtree(w)


def test_cli_path_and_method_drift_exit_1_and_warn_0():
    drifted = API_DART + "\nvoid d() => _dio.get('/v1/users/$id/ordres');\nvoid e() => _dio.put('/v1/users/$id');\n"
    w = _repo({"lib/api.dart": drifted})
    try:
        rc, out, _ = _run(w)
        assert rc == 1 and "PATH" in out and "/ordres" in out and "METHOD" in out, (rc, out)
        assert _run(w, "--warn")[0] == 0
        rc, out, _ = _run(w, "--json")
        kinds = {f["kind"] for f in json.loads(out)["findings"]}
        assert rc == 1 and kinds == {"PATH", "METHOD"}, kinds
    finally:
        shutil.rmtree(w)


def test_cli_fields_report_only_unless_strict():
    models = MODEL_DART.replace("total: j['total']", "total: j['total_cents']").replace(", 'bogusKey': 1", "")
    ok = _repo({"lib/api.dart": API_DART, "lib/model.dart": models})
    bad = _repo({"lib/api.dart": API_DART, "lib/model.dart": MODEL_DART.replace("total: j['total'],", "").replace(", 'bogusKey': 1", "")
                 .replace("createdAt: j['createdAt'],", "createdAt: j['createdAt'], nameX: j['nameX'],")})
    try:
        rc, out, err = _run(ok, "--fields")
        assert rc == 0 and "FIELD?" not in out, (out, err)
        rc, out, _ = _run(bad, "--fields")
        assert rc == 0 and "FIELD?" in out and "name_x" in out, out          # reported, not failing
        assert _run(bad, "--strict-fields")[0] == 1                           # opt-in gate
    finally:
        shutil.rmtree(ok); shutil.rmtree(bad)


def test_cli_openapi_methods_and_fields():
    w = _repo({"lib/api.dart": "void a() => _dio.post('/v1/ping');\n", "lib/model.dart": MODEL_DART})
    try:
        spec = os.path.join(w, "spec.json")
        json.dump({"paths": {"/v1/ping": {"post": {}}}, "components": {"schemas": {"U": {"properties": {
            "id": {}, "createdAt": {}, "total": {}, "bogus_key": {}}}}}}, open(spec, "w"))
        rc, out, _ = _run(w, "--openapi", spec, "--strict-fields")
        assert rc == 0, out
        json.dump({"paths": {"/v1/ping": {"get": {}}}}, open(spec, "w"))
        rc, out, _ = _run(w, "--openapi", spec)
        assert rc == 1 and "METHOD" in out, out
        json.dump({"paths": {"/v1/pong": {"post": {}}}}, open(spec, "w"))
        assert _run(w, "--openapi", spec)[0] == 1
    finally:
        shutil.rmtree(w)


def test_app_root_defaults_to_config_dir():
    w = _repo({"lib/api.dart": "void a() => _dio.get('/ghost');\n"})
    try:
        cfg = json.load(open(os.path.join(w, "cfg.json")))
        cfg["app"]["root"] = None
        del cfg["app"]["root"]
        os.rename(os.path.join(w, "app", "lib"), os.path.join(w, "lib"))
        json.dump(cfg, open(os.path.join(w, "cfg.json"), "w"))   # config now sits at the app root
        rc, out, _ = _run(w)
        assert rc == 1 and "/ghost" in out, (rc, out)
    finally:
        shutil.rmtree(w)


def test_cli_config_ignore_and_bad_input():
    w = _repo({"lib/api.dart": "void a() => _dio.get('/ghost');\n"}, cfg_extra={"drift_ignore": ["/ghost"]})
    try:
        assert _run(w)[0] == 0
    finally:
        shutil.rmtree(w)
    w = _repo({"lib/api.dart": "// no calls here\n"})
    try:
        assert _run(w)[0] == 2
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
