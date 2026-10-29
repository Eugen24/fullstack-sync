#!/usr/bin/env python3
"""Contract drift gate for CI and the Stop hook: paths, HTTP methods and field names.

  drift_check.py [--config .fullstack-sync.json] [--openapi spec.json] [--fields]
                 [--strict-fields] [--json] [--warn] [--max-seconds N]

App side (string-constant clients): API literals in app.endpoints_file (every literal) and
app.services_glob (only literals inside an HTTP call, so UI routes are ignored). Backend side:
the FastAPI extractor over backend.root, or OpenAPI JSON (--openapi).

Findings
  PATH    the app calls a path no backend route serves
  METHOD  the path exists but not with the verb the app uses (verb known from .get/.post/... calls)
  FIELD?  (--fields) a JSON key the app reads in fromJson, or writes in toJson, that no backend
          model declares. App keys are compared snake_case-normalised against the union of all
          backend model fields, so a rename (e.g. total -> total_cents) is caught, but a field
          that exists on a *different* model is not: precise per-endpoint field checking needs
          the model-driven api-contract-sync skill.

Opt-outs: `// fss-ignore` on a call line (or alone on the line above it), or "drift_ignore": ["/v4/remo/{id}"] in
the config, for paths the scan cannot judge (dynamic wrappers like '$base/v4/$path').

Exit 0 clean, 1 drift (PATH/METHOD; FIELD? only with --strict-fields), 2 bad input. --warn: exit 0.
Limits: no include_router prefix chasing (a prefix on one side only is tolerated, so a drift can
be missed but is not invented), dynamically built paths are not seen.
"""
import argparse, glob, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_fastapi
from fingerprint import normalize_field

HTTP = {"get", "post", "put", "patch", "delete", "head", "options"}
# optional leading $base / ${base} (Dart/Kotlin string interpolation of the API host)
_LIT = re.compile(r"""(['"])(?:\$\{?[A-Za-z_]\w*\}?)?(/[A-Za-z0-9_\-./{}$:]*)(?:\?[^'"]*)?\1""")
_ASSET = re.compile(r"\.(png|jpe?g|gif|svg|webp|ico|json|js|css|html|ttf|otf|mp[34]|pdf|txt|md)$", re.I)
_PARAM = re.compile(r"\$\{[^}]*\}|\$[A-Za-z_]\w*|\{[^}]*\}|:[A-Za-z_]\w*")
_CALL = re.compile(r"\.(get|post|put|patch|delete|head|request|getUri)\s*[<(]|Uri\.(parse|https?)\(|http\.\w+\(|fetch\(|axios", re.I)
_VERB = re.compile(r"\.(get|post|put|patch|delete|head)\s*[<(]", re.I)
_KEY = re.compile(r"""\[\s*['"]([A-Za-z0-9_]+)['"]\s*\]""")
_MAPKEY = re.compile(r"""['"]([A-Za-z0-9_]+)['"]\s*:""")


def norm(path):
    p = _PARAM.sub("{id}", path.split("?", 1)[0]).lower().rstrip("/")
    p = re.sub(r"/\d+(?=/|$)", "/{id}", p)  # literal ids (/users/7) are params too
    return p or "/"


def _segs(p):
    return [s for s in p.split("/") if s]


# ---------------------------------------------------------------- app side
def app_calls(files, strict_files=()):
    """{normalized path: {"loc": 'file:line', "methods": {'POST', ...}}}."""
    out, strict = {}, set(strict_files)
    for f in files:
        try:
            lines = open(f, errors="ignore").read().splitlines()
        except OSError:
            continue
        for n, line in enumerate(lines, 1):
            window = lines[max(0, n - 3):n]
            prev = lines[n - 2].strip() if n > 1 else ""
            if "fss-ignore" in line or (prev.startswith(("//", "#")) and "fss-ignore" in prev):
                continue  # inline opt-out: // fss-ignore
            if f not in strict and not any(_CALL.search(l) for l in window):
                continue
            for m in _LIT.finditer(line):
                raw = m.group(2)
                if len(raw) < 2 or _ASSET.search(raw) or raw.startswith(("/assets", "//")):
                    continue
                if not re.search(r"[a-z]", raw, re.I):
                    continue
                e = out.setdefault(norm(raw), {"loc": f"{f}:{n}", "methods": set()})
                verb = None
                same = line[:m.start()].rsplit(";", 1)[-1]
                found = _VERB.findall(same)
                if found:
                    verb = found[-1].upper()
                elif ";" not in line[:m.start()]:
                    for chunk in lines[max(0, n - 3):n - 1][::-1]:
                        if ";" in chunk:  # that line ends an earlier statement: stop looking back
                            break
                        found = _VERB.findall(chunk)
                        if found:
                            verb = found[-1].upper()
                            break
                if verb:
                    e["methods"].add(verb)
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


def app_fields(files):
    """{snake_case key: 'file:line'} read in fromJson (x['k']) or written in toJson ({'k': v})."""
    out = {}
    for f in files:
        try:
            lines = open(f, errors="ignore").read().splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines):
            if "fromJson" in line and "(" in line:
                rx = _KEY
            elif "toJson" in line and "(" in line:
                rx = _MAPKEY
            else:
                continue
            body = _call_body(lines, i)
            for k in rx.findall(body):
                out.setdefault(normalize_field(k), f"{f}:{i + 1}")
    return out


# ---------------------------------------------------------------- backend side
def backend_from_openapi(path):
    """({normalized path: {METHODS}}, {snake field names})."""
    spec = json.load(open(path))
    routes = {}
    for p, item in spec.get("paths", {}).items():
        routes[norm(p)] = {m.upper() for m in item if m.lower() in HTTP}
    fields = set()
    for sch in spec.get("components", {}).get("schemas", {}).values():
        fields.update(normalize_field(k) for k in sch.get("properties", {}))
    return routes, fields


def backend_from_fastapi(root, max_seconds, want_fields):
    routes = {}
    for e in extract_fastapi.extract([root], max_seconds=max_seconds)["endpoints"]:
        routes.setdefault(norm(e["path"]), set()).add(e["method"])
    fields = ({normalize_field(f) for f in extract_fastapi.all_model_fields([root], max_seconds=max_seconds)}
              if want_fields else set())
    return routes, fields


# ---------------------------------------------------------------- comparison
def matches(app_path, routes):
    """Backend paths that serve app_path. Tolerates a prefix present on only one side:
    dio baseUrl makes the backend path longer, an unseen include_router prefix shorter."""
    a = _segs(app_path)
    return [b for b in routes
            if a and _segs(b) and (a[-len(_segs(b)):] == _segs(b) or _segs(b)[-len(a):] == a)]


def check(calls, routes, ignore=()):
    """[(kind, path, detail, loc)] for PATH and METHOD drift. An unserved path that is a segment-prefix
    of another app path ('/v4' next to '/v4/tasks') is a base constant, not a call."""
    segs = {p: _segs(p) for p in calls}
    def is_base(p):
        return any(q != p and len(segs[q]) > len(segs[p]) and segs[q][:len(segs[p])] == segs[p] for q in calls)
    out = []
    for p, e in sorted(calls.items()):
        if p in ignore:
            continue
        hit = matches(p, routes)
        if not hit and is_base(p):
            continue
        if not hit:
            out.append(("PATH", p, "not served by backend", e["loc"]))
            continue
        served = set().union(*(routes[b] for b in hit))
        bad = e["methods"] - served
        if bad and served:
            out.append(("METHOD", p, f"app uses {'/'.join(sorted(bad))}, backend serves {'/'.join(sorted(served))}", e["loc"]))
    return out


# If more than this share of the app's keys is unknown, the extractor can't see this backend's
# models (dict responses, dataclasses, ...) and a per-key list would be noise, not signal.
MAX_UNKNOWN_SHARE = 0.4


def check_fields(app_keys, backend_fields):
    """(findings, note). note explains why FIELD checks were skipped, else None."""
    if not app_keys:
        return [], "no fromJson/toJson keys found in the app; FIELD checks skipped"
    unknown = [(k, loc) for k, loc in sorted(app_keys.items()) if k not in backend_fields]
    share = len(unknown) / len(app_keys)
    if share > MAX_UNKNOWN_SHARE:
        return [], (f"{share:.0%} of {len(app_keys)} app keys are unknown to the {len(backend_fields)} backend "
                    "model fields found; the extractor cannot see this backend's models, FIELD checks skipped")
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
    ap.add_argument("--fields", action="store_true", help="also compare JSON field names")
    ap.add_argument("--strict-fields", action="store_true", help="FIELD findings fail the run (implies --fields)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--warn", action="store_true", help="report drift but exit 0")
    ap.add_argument("--max-seconds", type=float, default=30)
    a = ap.parse_args(argv)
    want_fields = a.fields or a.strict_fields
    try:
        cfg = json.load(open(a.config))
        # the config lives at the app root by definition; app.root is only an override
        cfg["app"].setdefault("root", os.path.dirname(os.path.abspath(a.config)))
        ep = cfg["app"].get("endpoints_file")
        calls = app_calls(_files(cfg, "api"), [os.path.join(cfg["app"]["root"], ep)] if ep else [])
        routes, bfields = (backend_from_openapi(a.openapi) if a.openapi
                           else backend_from_fastapi(cfg["backend"]["root"], a.max_seconds, want_fields))
        keys = app_fields(_files(cfg, "models", "lib/**/*.dart")) if want_fields else {}
    except (OSError, ValueError, KeyError, TimeoutError) as e:
        print(f"drift_check: {e}", file=sys.stderr)
        return 2
    if not calls:
        print("drift_check: no app endpoint paths found; check app.endpoints_file/services_glob", file=sys.stderr)
        return 2
    if not routes:
        print("drift_check: backend exposes no endpoints; check backend.root or --openapi", file=sys.stderr)
        return 2
    findings = check(calls, routes, {norm(x) for x in cfg.get("drift_ignore", [])})
    if want_fields:
        extra, note = check_fields(keys, bfields) if bfields else ([], "no backend model fields found; FIELD checks skipped")
        findings += extra
        if note:
            print(f"drift_check: {note}", file=sys.stderr)
    hard = [f for f in findings if f[0] != "FIELD?" or a.strict_fields]
    if a.json:
        print(json.dumps({"app_paths": len(calls), "backend_paths": len(routes), "app_fields": len(keys),
                          "findings": [{"kind": k, "path": p, "detail": d, "at": l} for k, p, d, l in findings]}))
    else:
        for k, p, d, l in findings:
            print(f"{k:7} {p}  {d}  ({l})")
        print(f"{len(calls)} app paths, {len(routes)} backend paths"
              + (f", {len(keys)} app fields" if want_fields else "") + f": {len(findings)} findings")
    return 0 if (not hard or a.warn) else 1


if __name__ == "__main__":
    sys.exit(main())
