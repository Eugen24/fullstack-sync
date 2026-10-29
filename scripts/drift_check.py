#!/usr/bin/env python3
"""Contract drift gate for CI and the Stop hook: paths, HTTP methods, response fields.

  drift_check.py [--config .fullstack-sync.json] [--openapi spec.json] [--fields]
                 [--strict-fields] [--no-endpoint-fields] [--json] [--warn] [--max-seconds N]

App side (string-constant clients): API literals in app.endpoints_file (every literal) and
app.services_glob (only literals inside an HTTP call, so UI routes are ignored). Dart string
constants are resolved ('$v4BasePath/x' -> '/v4/x'). Backend side: the FastAPI extractor over
backend.root (cross-file response models, inheritance, include_router, prefix_rule), or OpenAPI.

Findings
  PATH    the app calls a path no backend route serves
  METHOD  the path exists but not with the verb the app uses
  FIELD   per endpoint: the app parses the response with Model.fromJson and reads a key
          with a non-nullable cast (`j['id'] as String`, which throws when absent) that the backend's
          response model for that endpoint does not declare. Only when both sides resolve; dict
          responses are skipped, never guessed. Reads the scan cannot prove required (`?? x`,
          wrappers, `final r = j['k']`) are reported as FIELD? instead
  FIELD?  (--fields) loose review list: an app key that no backend model/dict declares anywhere
  DYNAMIC (info) a path built from a runtime variable ('$base/v4/$path'); checked only as a prefix

Exit 0 clean, 1 drift (PATH/METHOD/FIELD; FIELD? only with --strict-fields), 2 bad input.
--warn: report but exit 0. Opt-outs: `// fss-ignore` on a call line (or alone on the line above),
or "drift_ignore": ["/v4/remo/{id}"] in the config. Config may set backend.prefix_rule
({"from_path": "routers", "skip": ["root"]}) for backends that mount routers by directory.
Limits: nested response fields are not flattened; no multi-level router chains; request bodies
are not compared per endpoint.
"""
import argparse, glob, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_fastapi
from fingerprint import normalize_field

HTTP = {"get", "post", "put", "patch", "delete", "head", "options"}
DYNAMIC_VARS = {"path", "url", "uri", "endpoint", "route", "suffix", "rest", "tail", "subpath"}
_STR = re.compile(r"""(['"])((?:\\.|(?!\1).)*)\1""")
_ASSET = re.compile(r"\.(png|jpe?g|gif|svg|webp|ico|json|js|css|html|ttf|otf|mp[34]|pdf|txt|md)$", re.I)
_PARAM = re.compile(r"\$\{[^}]*\}|\$[A-Za-z_]\w*|\{[^}]*\}|:[A-Za-z_]\w*")
_VAR = re.compile(r"\$\{(\w+)\}|\$(\w+)")
_CONST = re.compile(r"""(?:const|final)\s+(?:String\s+)?(\w+)\s*=\s*(['"])([^'"]*)\2\s*;""")
_CALL = re.compile(r"\.(get|post|put|patch|delete|head|request|getUri)\s*[<(]|Uri\.(parse|https?)\(|http\.\w+\(|fetch\(|axios", re.I)
_VERB = re.compile(r"\.(get|post|put|patch|delete|head)\s*[<(]", re.I)
_MAPKEY = re.compile(r"""['"]([A-Za-z0-9_]+)['"]\s*:""")
_FROMJSON_DEF = re.compile(r"\b([A-Z]\w*)\.fromJson\s*\(\s*(?:final\s+)?(?:Map\s*<[^>]*>|Map|dynamic|Object\??)\s+(\w+)")
# A read is provably required only as a non-nullable cast (`j['id'] as String`), which throws
# when the key is absent. Anything else (`?? x`, `_i(j['k'])`, `final r = j['k']; if (r is ..)`)
# may be handled in ways a text scan cannot see, so it is only ever a review item.
_REQUIRED_CAST = re.compile(r"\s+as\s+([A-Za-z_][\w<>, ]*?)(\??)(?=[\s,;)\]}]|$)")
_FROMJSON_USE = re.compile(r"\b([A-Z]\w*)\.fromJson\s*\(")


def norm(path):
    p = _PARAM.sub("{id}", path.split("?", 1)[0]).lower().rstrip("/")
    p = re.sub(r"/\d+(?=/|$)", "/{id}", p)  # literal ids (/users/7) are params too
    return p or "/"


def _segs(p):
    return [s for s in p.split("/") if s]


def _read(f):
    try:
        return open(f, errors="ignore").read().splitlines()
    except OSError:
        return []


# ---------------------------------------------------------------- app side
def dart_consts(files):
    """{name: '/v4'} for `const|final [String] name = '...';` in the scanned files."""
    out = {}
    for f in files:
        for line in _read(f):
            for m in _CONST.finditer(line):
                out[m.group(1)] = m.group(3)
    return out


def expand(text, consts):
    """Substitute known $name / ${name}, up to 3 levels deep."""
    for _ in range(3):
        new = _VAR.sub(lambda m: consts.get(m.group(1) or m.group(2), m.group(0)), text)
        if new == text:
            break
        text = new
    return text


def _literal_path(content, consts):
    """(path, dynamic) for an API-looking string literal, else None."""
    text = expand(content, consts)
    m = re.match(r"^(?:\$\{?[A-Za-z_]\w*\}?)(/.*)$", text)  # unresolved leading host var: $apiBase/...
    text = m.group(1) if m else text
    if not text.startswith("/") or text.startswith("//") or len(text) < 2:
        return None
    text = text.split("?", 1)[0]
    if _ASSET.search(text) or text.startswith("/assets") or not re.search(r"[a-z]", text, re.I):
        return None
    if re.search(r"[^A-Za-z0-9_\-./{}$:]", text):
        return None
    dyn = re.search(r"/(?:\$\{?(\w+)\}?)$", text)
    if dyn and dyn.group(1).lower() in DYNAMIC_VARS:
        return text[:dyn.start()] or "/", True
    return text, False


def app_models(files):
    """{Class: {snake_key: {"loc": 'file:line', "required": bool}}} for keys read as <param>['k']
    inside Class.fromJson(Map p). required = some read is a non-nullable cast with no `??` after."""
    out = {}
    for f in files:
        lines = _read(f)
        for i, line in enumerate(lines):
            m = _FROMJSON_DEF.search(line)
            if not m:
                continue
            cls, param = m.groups()
            body = _call_body(lines, i)
            rx = re.compile(r"\b%s\s*\[\s*['\"]([A-Za-z0-9_]+)['\"]\s*\]" % re.escape(param))
            keys = out.setdefault(cls, {})
            for km in rx.finditer(body):
                k = normalize_field(km.group(1))
                tail = body[km.end():km.end() + 80]
                c = _REQUIRED_CAST.match(tail)
                req = bool(c and not c.group(2) and not re.match(r"\s*\?\?", tail[c.end():]))
                cur = keys.setdefault(k, {"loc": f"{f}:{i + 1}", "required": req})
                cur["required"] = cur["required"] or req
    return out


def app_calls(files, strict_files=(), consts=None):
    """{normalized path: {"loc", "methods": {...}, "model": Class|None, "dynamic": bool}}."""
    consts = consts if consts is not None else dart_consts(files)
    out, strict = {}, set(strict_files)
    for f in files:
        lines = _read(f)
        for n, line in enumerate(lines, 1):
            window = lines[max(0, n - 3):n]
            prev = lines[n - 2].strip() if n > 1 else ""
            if "fss-ignore" in line or (prev.startswith(("//", "#")) and "fss-ignore" in prev):
                continue  # inline opt-out: // fss-ignore
            if f not in strict and not any(_CALL.search(l) for l in window):
                continue
            for m in _STR.finditer(line):
                lit = _literal_path(m.group(2), consts)
                if not lit:
                    continue
                path, dynamic = lit
                e = out.setdefault(norm(path), {"loc": f"{f}:{n}", "methods": set(), "model": None, "dynamic": dynamic})
                e["dynamic"] = e["dynamic"] and dynamic
                same = line[:m.start()].rsplit(";", 1)[-1]
                found = _VERB.findall(same)
                if not found and ";" not in line[:m.start()]:
                    for chunk in lines[max(0, n - 3):n - 1][::-1]:
                        if ";" in chunk:  # that line ends an earlier statement: stop looking back
                            break
                        found = _VERB.findall(chunk)
                        if found:
                            break
                if found:
                    e["methods"].add(found[-1].upper())
                if e["model"] is None:
                    stmt = "\n".join(lines[n - 1:n + 5]).split(";", 1)[0]
                    u = _FROMJSON_USE.search(same + " " + stmt) or _FROMJSON_USE.search(" ".join(window))
                    if u:
                        e["model"] = u.group(1)
    return out


def _call_body(lines, i):
    """Text of the function starting at lines[i], until its brackets balance (max 80 lines)."""
    depth, started, buf = 0, False, []
    for l in lines[i:i + 80]:
        buf.append(l)
        for ch in l:
            if ch in "({[":
                depth += 1; started = True
            elif ch in ")}]":
                depth -= 1
        if started and depth <= 0:
            break
    return "\n".join(buf)


def app_fields(files, models=None):
    """{snake_case key: 'file:line'}: every fromJson key plus every key written in toJson."""
    out = {}
    for keys in (models if models is not None else app_models(files)).values():
        for k, info in keys.items():
            out.setdefault(k, info["loc"])
    for f in files:
        lines = _read(f)
        for i, line in enumerate(lines):
            if "toJson" in line and "(" in line:
                for k in _MAPKEY.findall(_call_body(lines, i)):
                    out.setdefault(normalize_field(k), f"{f}:{i + 1}")
    return out


# ---------------------------------------------------------------- backend side
# routes: {normalized path: {METHOD: {"fields": set[str] | None, "model": str | None}}}
def _schema_fields(schema, spec, depth=0):
    """Top-level property names of an OpenAPI response schema ($ref/allOf/array unwrapped)."""
    if not isinstance(schema, dict) or depth > 6:
        return None
    if "$ref" in schema:
        node = spec
        for part in schema["$ref"].lstrip("#/").split("/"):
            node = node.get(part, {}) if isinstance(node, dict) else {}
        return _schema_fields(node, spec, depth + 1)
    if schema.get("type") == "array":
        return _schema_fields(schema.get("items"), spec, depth + 1)
    out, found = set(), False
    for sub in schema.get("allOf", []) + schema.get("anyOf", []) + schema.get("oneOf", []):
        f = _schema_fields(sub, spec, depth + 1)
        if f is not None:
            out |= f; found = True
    if "properties" in schema:
        out |= {normalize_field(k) for k in schema["properties"]}; found = True
    return out if found else None


def backend_from_openapi(path):
    spec = json.load(open(path))
    routes = {}
    for p, item in spec.get("paths", {}).items():
        for m, op in item.items():
            if m.lower() not in HTTP or not isinstance(op, dict):
                continue
            fields = None
            for status, resp in op.get("responses", {}).items():
                if status.startswith("2") and isinstance(resp, dict):
                    sch = resp.get("content", {}).get("application/json", {}).get("schema")
                    fields = _schema_fields(sch, spec) if sch else None
                    break
            routes.setdefault(norm(p), {})[m.upper()] = {"fields": fields, "model": None}
    universe = set()
    for sch in spec.get("components", {}).get("schemas", {}).values():
        universe.update(normalize_field(k) for k in sch.get("properties", {}))
    return routes, universe


def backend_from_fastapi(root, max_seconds, want_universe, prefix_rule=None):
    routes = {}
    for e in extract_fastapi.extract([root], max_seconds=max_seconds, prefix_rule=prefix_rule)["endpoints"]:
        fields = {normalize_field(f) for f in e["fields"]} if e.get("model") else None
        routes.setdefault(norm(e["path"]), {})[e["method"]] = {"fields": fields, "model": e.get("model")}
    universe = ({normalize_field(f) for f in extract_fastapi.all_model_fields([root], max_seconds=max_seconds)}
                if want_universe else set())
    return routes, universe


# ---------------------------------------------------------------- comparison
def matches(app_path, routes):
    """Backend paths that serve app_path. Tolerates a prefix present on only one side:
    dio baseUrl makes the backend path longer, an unseen include_router prefix shorter."""
    a = _segs(app_path)
    return [b for b in routes
            if a and _segs(b) and (a[-len(_segs(b)):] == _segs(b) or _segs(b)[-len(a):] == a)]


def _under(prefix, routes):
    """Backend paths containing prefix as a run of whole segments (for dynamic app paths)."""
    needle = "/" + "/".join(_segs(prefix)) + "/"
    return [b for b in routes if needle in "/" + "/".join(_segs(b)) + "/"]


def check(calls, routes, ignore=(), models=None):
    """[(kind, path, detail, loc)] for PATH / METHOD / FIELD drift (+ DYNAMIC info)."""
    segs = {p: _segs(p) for p in calls}
    def is_base(p):
        return any(q != p and len(segs[q]) > len(segs[p]) and segs[q][:len(segs[p])] == segs[p] for q in calls)
    out = []
    for p, e in sorted(calls.items()):
        if p in ignore:
            continue
        if e.get("dynamic"):
            if not _under(p, routes):
                out.append(("PATH", p, "no backend route under this dynamic prefix", e["loc"]))
            else:
                out.append(("DYNAMIC", p, "built from a runtime variable; checked as a prefix only", e["loc"]))
            continue
        hit = matches(p, routes)
        if not hit:
            if not is_base(p):  # an unserved prefix of another call is a base constant, not a call
                out.append(("PATH", p, "not served by backend", e["loc"]))
            continue
        ops = {}
        for b in hit:
            ops.update(routes[b])
        served = set(ops)
        bad = e["methods"] - served
        if bad and served:
            out.append(("METHOD", p, f"app uses {'/'.join(sorted(bad))}, backend serves {'/'.join(sorted(served))}", e["loc"]))
            continue
        model = e.get("model")
        if model and models and models.get(model) and len(e["methods"]) == 1:
            verb = next(iter(e["methods"]))
            infos = [routes[b][verb] for b in hit if verb in routes[b]]
            if infos and all(i["fields"] is not None for i in infos):
                known = set().union(*(i["fields"] for i in infos))
                bm = "/".join(sorted({i["model"] for i in infos if i["model"]})) or "its response"
                for req, kind, note in ((True, "FIELD", "declares no such field"),
                                        (False, "FIELD?", "declares no such field (the app may tolerate its absence: not a plain non-null cast)")):
                    miss = sorted(k for k, i in models[model].items() if k not in known and i["required"] == req)
                    if miss:
                        out.append((kind, p, f"{verb} {model}.fromJson reads {', '.join(miss)}; {bm} {note}", e["loc"]))
    return out


# If more than this share of the app's keys is unknown, the extractor can't see this backend's
# models (dict responses, dataclasses, ...) and a per-key list would be noise, not signal.
MAX_UNKNOWN_SHARE = 0.4


def check_fields(app_keys, universe):
    """(findings, note). note explains why the loose FIELD? check was skipped, else None."""
    if not app_keys:
        return [], "no fromJson/toJson keys found in the app; FIELD? checks skipped"
    unknown = [(k, loc) for k, loc in sorted(app_keys.items()) if k not in universe]
    share = len(unknown) / len(app_keys)
    if share > MAX_UNKNOWN_SHARE:
        return [], (f"{share:.0%} of {len(app_keys)} app keys are unknown to the {len(universe)} backend "
                    "names found; the extractor cannot see this backend's models, FIELD? checks skipped")
    return [("FIELD?", k, "no backend model declares it (review: may be client-only or a dict response)", loc)
            for k, loc in unknown], None


def _files(cfg, key, default=None):
    root = cfg["app"]["root"]
    pats = [cfg["app"].get("endpoints_file"), cfg["app"].get("services_glob")] if key == "api" \
        else [cfg["app"].get("models_glob") or default]
    out = []
    for pat in pats:
        if pat:
            out += glob.glob(os.path.join(root, pat), recursive=True)
    return sorted(set(f for f in out if os.path.isfile(f)))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="drift_check")
    ap.add_argument("--config", default=".fullstack-sync.json")
    ap.add_argument("--openapi")
    ap.add_argument("--fields", action="store_true", help="also print the loose FIELD? review list")
    ap.add_argument("--strict-fields", action="store_true", help="FIELD? findings fail the run (implies --fields)")
    ap.add_argument("--no-endpoint-fields", action="store_true", help="skip the per-endpoint FIELD check")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--warn", action="store_true", help="report drift but exit 0")
    ap.add_argument("--max-seconds", type=float, default=30)
    a = ap.parse_args(argv)
    loose = a.fields or a.strict_fields
    try:
        cfg = json.load(open(a.config))
        # the config lives at the app root by definition; app.root is only an override
        cfg["app"].setdefault("root", os.path.dirname(os.path.abspath(a.config)))
        ep = cfg["app"].get("endpoints_file")
        api_files = _files(cfg, "api")
        model_files = _files(cfg, "models", "lib/**/*.dart")
        consts = dart_consts(sorted(set(api_files) | set(model_files)))
        calls = app_calls(api_files, [os.path.join(cfg["app"]["root"], ep)] if ep else [], consts)
        rule = cfg["backend"].get("prefix_rule")
        routes, universe = (backend_from_openapi(a.openapi) if a.openapi else
                            backend_from_fastapi(cfg["backend"]["root"], a.max_seconds, loose, rule))
        models = app_models(model_files) if not a.no_endpoint_fields or loose else {}
        keys = app_fields(model_files, models) if loose else {}
    except (OSError, ValueError, KeyError, TimeoutError) as e:
        print(f"drift_check: {e}", file=sys.stderr)
        return 2
    if not calls:
        print("drift_check: no app endpoint paths found; check app.endpoints_file/services_glob", file=sys.stderr)
        return 2
    if not routes:
        print("drift_check: backend exposes no endpoints; check backend.root or --openapi", file=sys.stderr)
        return 2
    findings = check(calls, routes, {norm(x) for x in cfg.get("drift_ignore", [])},
                     None if a.no_endpoint_fields else models)
    if loose:
        extra, note = check_fields(keys, universe) if universe else ([], "no backend names found; FIELD? checks skipped")
        findings += extra
        if note:
            print(f"drift_check: {note}", file=sys.stderr)
    shown = [f for f in findings if f[0] != "FIELD?" or loose]
    hard = [f for f in shown if f[0] in ("PATH", "METHOD", "FIELD") or (f[0] == "FIELD?" and a.strict_fields)]
    if a.json:
        print(json.dumps({"app_paths": len(calls), "backend_paths": len(routes), "app_fields": len(keys),
                          "findings": [{"kind": k, "path": p, "detail": d, "at": l} for k, p, d, l in shown]}))
    else:
        for k, p, d, l in shown:
            print(f"{k:7} {p}  {d}  ({l})")
        print(f"{len(calls)} app paths, {len(routes)} backend paths"
              + (f", {len(keys)} app fields" if loose else "") + f": {len(shown)} findings")
    return 0 if (not hard or a.warn) else 1


if __name__ == "__main__":
    sys.exit(main())
