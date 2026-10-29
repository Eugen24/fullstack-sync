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
  static const base = '/v1';
  Future<void> a() => _dio.get('/v1/users/$id');
  Future<void> b() => _dio.post(
    '/v1/users/${user.id}/orders',
    data: {});
  Future<void> c() => http.get(Uri.parse('$apiBase/v1/users/7?x=1'));
  Future<User> me() async => User.fromJson(_m(await _dio.get('$base/users/$id')));
}
"""
USER_DART = """class User {
  factory User.fromJson(Map<String, dynamic> j) => User(
        id: j['id'] as int,
        createdAt: j['createdAt'] as String,
        total: j['total'] as int,
        note: j['note'] as String? ?? '',
        extra: _i(j['extra']),
        nested: (j['id'] as Map)['inner'],
      );
  Map<String, dynamic> toJson() => {'id': id, 'bogusKey': 1};
  void other(m) { final z = m['ignored_outside_json']; }
}
"""
SCREEN_DART = """void go(c) { c.go('/home'); c.push('/chat'); Image.asset('/assets/x.png'); }"""


def _repo(files, app_cfg=None, backend_src=ROUTER, cfg_extra=None, backend_cfg=None):
    w = tempfile.mkdtemp()
    for rel, src in files.items():
        p = os.path.join(w, "app", rel); os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write(src)
    os.makedirs(os.path.join(w, "be", "routers"))
    open(os.path.join(w, "be", "routers", "users.py"), "w").write(backend_src)
    cfg = {"app": {"root": os.path.join(w, "app"), "endpoints_file": None, "services_glob": "lib/**/*.dart", **(app_cfg or {})},
           "backend": {"root": os.path.join(w, "be"), **(backend_cfg or {})}, **(cfg_extra or {})}
    json.dump(cfg, open(os.path.join(w, "cfg.json"), "w"))
    return w


def _run(w, *args):
    r = subprocess.run([sys.executable, "-I", SCRIPT, "--config", os.path.join(w, "cfg.json"), *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def _cfg(w):
    return json.load(open(os.path.join(w, "cfg.json")))


def _calls(w, consts=None):
    cfg = _cfg(w)
    files = dc._files(cfg, "api")
    return dc.app_calls(files, [], consts)


def op(fields=None, model=None):
    return {"fields": fields, "model": model}


def test_norm():
    assert dc.norm("/V1/Users/$id/") == "/v1/users/{id}"
    assert dc.norm("/v1/users/${u.id}?x=1") == "/v1/users/{id}"
    assert dc.norm("/v1/users/7/orders") == "/v1/users/{id}/orders"
    assert dc.norm("/v2/users") == "/v2/users"  # version segments are not ids


def test_matches_tolerates_prefix_on_either_side():
    assert dc.matches("/auth/login", {"/v1/auth/login": {}})
    assert dc.matches("/v1/auth/login", {"/auth/login": {}})
    assert not dc.matches("/auth/loginx", {"/v1/auth/login": {}})
    assert not dc.matches("/orders", {"/v1/order": {}})


def test_dart_consts_are_resolved_into_paths():
    consts = {"v4": "/v4", "feedback": "$v4/app_feedback"}
    assert dc.expand("$v4/tasks", consts) == "/v4/tasks"
    assert dc.expand("${feedback}", consts) == "/v4/app_feedback"      # nested
    assert dc._literal_path("$apiBase/v1/x", {}) == ("/v1/x", False)   # unresolved host var is dropped
    assert dc._literal_path("$v4/tasks/", consts) == ("/v4/tasks/", False)


def test_dynamic_remainder_variable():
    assert dc._literal_path("$apiBase/v4/remo/$path", {}) == ("/v4/remo", True)
    assert dc._literal_path("/v1/users/$id", {}) == ("/v1/users/$id", False)   # an id stays a param
    assert dc._literal_path("/assets/a.png", {}) is None
    assert dc._literal_path("hello world", {}) is None


def test_app_calls_paths_verbs_filters_and_model():
    w = _repo({"lib/api.dart": API_DART, "lib/screen.dart": SCREEN_DART})
    try:
        cfg = _cfg(w)
        files = dc._files(cfg, "api")
        c = dc.app_calls(files, [], dc.dart_consts(files))
        assert c["/v1/users/{id}"]["methods"] == {"GET"}
        assert c["/v1/users/{id}/orders"]["methods"] == {"POST"}  # verb on the previous line
        assert c["/v1/users/{id}"]["model"] == "User"             # '$base/users/$id' resolved, fromJson on the line
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


def test_inline_ignore_marker():
    w = _repo({"lib/api.dart": "Future<void> a() => _dio.get('/ghost'); // fss-ignore\n"
                               "Future<void> b() => _dio.get('/v1/users/$id');\n"})
    try:
        c = _calls(w)
        assert "/ghost" not in c and "/v1/users/{id}" in c
    finally:
        shutil.rmtree(w)


def test_app_models_required_only_for_nonnull_casts():
    w = _repo({"lib/user.dart": USER_DART})
    try:
        m = dc.app_models([os.path.join(w, "app", "lib", "user.dart")])["User"]
        assert {k for k, i in m.items() if i["required"]} == {"id", "created_at", "total"}
        assert not m["note"]["required"]       # as String? ?? ''
        assert not m["extra"]["required"]      # wrapper call: unprovable
        assert "inner" not in m and "ignored_outside_json" not in m   # nested / outside fromJson
    finally:
        shutil.rmtree(w)


def _model(**keys):
    return {"User": {k: {"loc": "u:1", "required": r} for k, r in keys.items()}}


def test_check_path_method_and_dynamic():
    routes = {"/v1/users/{id}": {"GET": op(), "DELETE": op()}, "/v1/users/{id}/orders": {"POST": op()},
              "/v4/x": {"GET": op()}, "/v4/remo/{id}": {"GET": op()}}
    calls = {"/v1/users/{id}": {"loc": "a:1", "methods": {"PUT"}, "model": None, "dynamic": False},
             "/v1/users/{id}/orders": {"loc": "a:2", "methods": {"POST"}, "model": None, "dynamic": False},
             "/ghost": {"loc": "a:3", "methods": {"GET"}, "model": None, "dynamic": False},
             "/v4": {"loc": "a:4", "methods": set(), "model": None, "dynamic": False},
             "/v4/x": {"loc": "a:5", "methods": set(), "model": None, "dynamic": False},
             "/v4/remo": {"loc": "a:6", "methods": {"POST"}, "model": None, "dynamic": True},
             "/nowhere": {"loc": "a:7", "methods": set(), "model": None, "dynamic": True}}
    kinds = {(k, p) for k, p, _, _ in dc.check(calls, routes)}
    assert kinds == {("METHOD", "/v1/users/{id}"), ("PATH", "/ghost"), ("DYNAMIC", "/v4/remo"), ("PATH", "/nowhere")}, kinds


def test_check_ignore_list():
    c = {"/ghost": {"loc": "a:1", "methods": set(), "model": None, "dynamic": False}}
    assert dc.check(c, {"/x": {"GET": op()}}, {"/ghost"}) == []


def test_check_endpoint_fields_hard_vs_review():
    call = lambda: {"/users/{id}": {"loc": "a:1", "methods": {"GET"}, "model": "User", "dynamic": False}}
    routes = {"/users/{id}": {"GET": op({"id", "created_at"}, "UserOut")}}
    out = dc.check(call(), routes, models=_model(id=True, created_at=True, total=True, note=False))
    assert [(k, "total" in d, "note" in d) for k, _, d, _ in out] == [("FIELD", True, False), ("FIELD?", False, True)]
    assert "UserOut" in out[0][2]
    # dict response (fields unknown): nothing is guessed
    assert dc.check(call(), {"/users/{id}": {"GET": op(None)}}, models=_model(total=True)) == []
    # no model parsed in the app: nothing to compare
    assert dc.check(call(), routes, models={}) == []


def test_loose_field_check_and_coverage_guard():
    fields = {"id", "created_at", "total_cents"}
    f, note = dc.check_fields({"id": "a:1", "created_at": "a:2", "total": "a:3"}, fields)
    assert note is None and [x[1] for x in f] == ["total"] and f[0][0] == "FIELD?"
    f, note = dc.check_fields({"a": "x:1", "b": "x:2", "id": "x:3"}, fields)
    assert f == [] and "cannot see" in note
    assert dc.check_fields({}, fields)[0] == []


def test_openapi_response_fields_ref_array_allof():
    w = tempfile.mkdtemp()
    try:
        spec = {"paths": {
            "/a": {"get": {"responses": {"200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/A"}}}}}}},
            "/b": {"get": {"responses": {"200": {"content": {"application/json": {"schema": {"type": "array", "items": {"$ref": "#/components/schemas/A"}}}}}}}},
            "/c": {"post": {"responses": {"201": {"content": {"application/json": {"schema": {"allOf": [{"$ref": "#/components/schemas/A"}, {"properties": {"extraKey": {}}}]}}}}}}},
            "/d": {"get": {"responses": {"200": {"description": "no schema"}}}}},
            "components": {"schemas": {"A": {"properties": {"createdAt": {}, "id": {}}}}}}
        p = os.path.join(w, "s.json"); json.dump(spec, open(p, "w"))
        routes, universe = dc.backend_from_openapi(p)
        assert routes["/a"]["GET"]["fields"] == {"created_at", "id"} == routes["/b"]["GET"]["fields"]
        assert routes["/c"]["POST"]["fields"] == {"created_at", "id", "extra_key"}
        assert routes["/d"]["GET"]["fields"] is None and "created_at" in universe
    finally:
        shutil.rmtree(w)


def test_cli_ok_when_in_sync():
    w = _repo({"lib/api.dart": API_DART, "lib/user.dart": USER_DART.replace("total: j['total'] as int,", "total: j['total_cents'] as int,")})
    try:
        rc, out, _ = _run(w)
        assert rc == 0 and "0 findings" in out, (rc, out)
    finally:
        shutil.rmtree(w)


def test_cli_path_method_drift_and_warn():
    drifted = API_DART + "\nvoid d() => _dio.get('/v1/users/$id/ordres');\nvoid e() => _dio.put('/v1/users/$id');\n"
    w = _repo({"lib/api.dart": drifted})
    try:
        rc, out, _ = _run(w)
        assert rc == 1 and "PATH" in out and "/ordres" in out and "METHOD" in out, (rc, out)
        assert _run(w, "--warn")[0] == 0
        rc, out, _ = _run(w, "--json")
        assert rc == 1 and {f["kind"] for f in json.loads(out)["findings"]} >= {"PATH", "METHOD"}
    finally:
        shutil.rmtree(w)


def test_cli_endpoint_field_drift_fails_and_can_be_disabled():
    w = _repo({"lib/api.dart": API_DART, "lib/user.dart": USER_DART})   # reads required 'total'; backend has total_cents
    try:
        rc, out, _ = _run(w)
        assert rc == 1 and "FIELD " in out and "total" in out, (rc, out)
        assert "FIELD?" not in out                       # review items stay hidden without --fields
        assert _run(w, "--no-endpoint-fields")[0] == 0
        rc, out, _ = _run(w, "--fields")
        assert rc == 1 and "FIELD?" in out               # note / extra now listed for review
    finally:
        shutil.rmtree(w)


def test_cli_strict_fields_gate():
    user = USER_DART.replace("total: j['total'] as int,", "total: j['total_cents'] as int,").replace("id: j['id'] as int,", "id: j['id'] as int, mood: _s(j['mood']),")
    w = _repo({"lib/api.dart": API_DART, "lib/user.dart": user})
    try:
        rc, out, _ = _run(w, "--fields")
        assert rc == 0 and "FIELD?" in out and "mood" in out, (rc, out)    # review only
        assert _run(w, "--strict-fields")[0] == 1
    finally:
        shutil.rmtree(w)



def test_body_keys_parser_real_world_shapes():
    # shapes taken from real apps: ternary values must not become keys (a bug found auditing mystartup)
    t = ("post(uri('/v1/auth/anonymous'), body: jsonEncode({'installation_id': id, 'platform': Platform.isIOS ? 'ios' : "
         "Platform.isMacOS ? 'macos' : 'x', if (att != null) 'attestation': att}))")
    b = dc.body_keys(t)
    assert b == {"keys": {"installation_id", "platform", "attestation"}, "conditional": {"attestation"}, "complete": True}, b
    b = dc.body_keys("_dio.post('/x', data: {'a': 1, 'b': {'c': 2}, 'l': [1, 2], 'f': foo(1, 'z': 3), 'createdAt': now})")
    assert b["keys"] == {"a", "b", "l", "f", "created_at"} and b["complete"]      # nested keys excluded, snake-normalised
    assert dc.body_keys("_dio.post('/x', data: {...base, 'a': 1})")["complete"] is False
    assert dc.body_keys("_dio.post('/x', data: payload.toJson())") is None
    assert dc.body_keys("_dio.get('/x')") is None
    assert dc.body_keys("_dio.post('/x', data: {'a': 1") is None                    # unbalanced: never guess


def _bop(fields, required=(), model="OrderIn"):
    return {"fields": None, "model": None, "req_fields": set(fields), "req_required": [list(r) for r in required], "req_model": model}


def _bcall(keys, cond=(), complete=True):
    return {"loc": "a:1", "methods": {"POST"}, "model": None, "dynamic": False,
            "body": {"keys": set(keys), "conditional": set(cond), "complete": complete}}


def test_check_body_extra_and_missing_required():
    routes = {"/o": {"POST": _bop({"qty", "note"}, [["qty"]])}}
    ok = dc.check({"/o": _bcall({"qty", "note"})}, routes)
    assert ok == []
    extra = dc.check({"/o": _bcall({"qty", "qtty"})}, routes)
    assert [(k, "qtty" in d and "dropped" in d) for k, _, d, _ in extra] == [("BODY", True)]
    missing = dc.check({"/o": _bcall({"note"})}, routes)
    assert [(k, "qty" in d and "requires" in d) for k, _, d, _ in missing] == [("BODY", True)]
    assert dc.check({"/o": _bcall({"note"}, complete=False)}, routes) == []          # spread: missing not judged
    assert dc.check({"/o": _bcall({"qty"}, cond={"qty"})}, routes) == []              # conditional key counts as sent
    assert dc.check({"/o": _bcall({"qty", "qtty"})}, routes, body=False) == []
    # alias pair satisfied by either spelling
    r2 = {"/o": {"POST": _bop({"code", "promo_code"}, [["code", "promo_code"]])}}
    assert dc.check({"/o": _bcall({"promo_code"})}, r2) == []
    # unknown request schema, GET, and ambiguous multi-op matches are never judged
    assert dc.check({"/o": _bcall({"zzz"})}, {"/o": {"POST": {"fields": None, "model": None, "req_fields": None}}}) == []
    get = _bcall({"zzz"}); get["methods"] = {"GET"}
    assert dc.check({"/o": get}, {"/o": {"GET": _bop({"a"})}}) == []


def test_cli_body_drift_end_to_end():
    be = ("class OrderIn(BaseModel):\n    qty: int\n    note: str | None = None\n"
          "router = APIRouter(prefix='/v1')\n@router.post('/orders')\ndef c(body: OrderIn): ...\n")
    good = "Future<void> c() => _dio.post('/v1/orders', data: {'qty': 1, 'note': n});\n"
    typo = "Future<void> c() => _dio.post('/v1/orders', data: {'quantity': 1});\n"
    w = _repo({"lib/api.dart": good}, backend_src=be)
    try:
        assert _run(w)[0] == 0
    finally:
        shutil.rmtree(w)
    w = _repo({"lib/api.dart": typo}, backend_src=be)
    try:
        rc, out, _ = _run(w)
        assert rc == 1 and out.count("BODY") == 2 and "quantity" in out and "requires" in out, out
        assert _run(w, "--no-body")[0] == 0
        assert _run(w, "--warn")[0] == 0
    finally:
        shutil.rmtree(w)


def test_openapi_request_body_fields_and_required():
    w = tempfile.mkdtemp()
    try:
        spec = {"paths": {"/o": {"post": {"requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/In"}}}},
                                          "responses": {"200": {"description": "ok"}}}}},
                "components": {"schemas": {"In": {"properties": {"qty": {}, "noteText": {}}, "required": ["qty"]}}}}
        p = os.path.join(w, "s.json"); json.dump(spec, open(p, "w"))
        routes, _ = dc.backend_from_openapi(p)
        info = routes["/o"]["POST"]
        assert info["req_fields"] == {"qty", "note_text"} and info["req_required"] == [["qty"]]
        assert [k for k, *_ in dc.check({"/o": _bcall({"qty", "nope"})}, routes)] == ["BODY"]
    finally:
        shutil.rmtree(w)



def test_one_path_many_verbs_keeps_model_and_body_per_call_site():
    # real shape from a mutation audit: GET /me parsed as User, PATCH /me sends a body, DELETE /me plain
    dart = ("Future<User> me() async => User.fromJson(_m(await dio.get('/me')));\n"
            "Future<void> upd() => dio.patch('/me', data: {'name': n, 'bogus': 1});\n"
            "Future<void> del() => dio.delete('/me');\n")
    user = "class User {\n  factory User.fromJson(Map<String, dynamic> j) => User(id: j['idd'] as String);\n}\n"
    w = _repo({"lib/api.dart": dart, "lib/user.dart": user},
              backend_src=("class UserOut(BaseModel):\n    id: str\nclass UserPatch(BaseModel):\n    name: str | None = None\n"
                           "router = APIRouter()\n@router.get('/me', response_model=UserOut)\ndef g(): ...\n"
                           "@router.patch('/me')\ndef u(b: UserPatch): ...\n@router.delete('/me')\ndef d(): ...\n"))
    try:
        rc, out, _ = _run(w)
        assert rc == 1, out
        assert "FIELD " in out and "idd" in out and "GET User.fromJson" in out, out     # GET site keeps its model
        assert "BODY" in out and "bogus" in out and "PATCH" in out, out                 # PATCH site keeps its body
        assert out.count("METHOD") == 0
    finally:
        shutil.rmtree(w)


def test_cli_openapi_source():
    w = _repo({"lib/api.dart": "void a() => _dio.post('/v1/ping');\n"})
    try:
        spec = os.path.join(w, "spec.json")
        json.dump({"paths": {"/v1/ping": {"post": {}}}}, open(spec, "w"))
        assert _run(w, "--openapi", spec)[0] == 0
        json.dump({"paths": {"/v1/ping": {"get": {}}}}, open(spec, "w"))
        rc, out, _ = _run(w, "--openapi", spec)
        assert rc == 1 and "METHOD" in out, out
        json.dump({"paths": {"/v1/pong": {"post": {}}}}, open(spec, "w"))
        assert _run(w, "--openapi", spec)[0] == 1
    finally:
        shutil.rmtree(w)


def test_cli_prefix_rule_from_config():
    be = "router = APIRouter()\n@router.get('/list')\ndef g(): ...\n"
    rule = {"prefix_rule": {"from_path": "routers", "skip": ["root"]}}
    # without the rule the backend path is just '/list': the app's longer path is tolerated
    w = _repo({"lib/api.dart": "void a() => _dio.get('/v4/users/list');\n"}, backend_src=be)
    try:
        assert _run(w)[0] == 0
    finally:
        shutil.rmtree(w)
    # with the rule the backend path is '/users/list', so a typo is caught and the right call passes
    w = _repo({"lib/api.dart": "void a() => _dio.get('/users/lisst');\n"}, backend_src=be, backend_cfg=rule)
    try:
        rc, out, _ = _run(w)
        assert rc == 1 and "lisst" in out, out
    finally:
        shutil.rmtree(w)
    w = _repo({"lib/api.dart": "void a() => _dio.get('/v4/users/list');\n"}, backend_src=be, backend_cfg=rule)
    try:
        assert _run(w)[0] == 0
    finally:
        shutil.rmtree(w)


def test_app_root_defaults_to_config_dir():
    w = _repo({"lib/api.dart": "void a() => _dio.get('/ghost');\n"})
    try:
        cfg = _cfg(w); del cfg["app"]["root"]
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
