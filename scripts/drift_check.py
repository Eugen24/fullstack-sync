#!/usr/bin/env python3
"""CI drift gate: do the endpoint paths the app calls exist in the backend?

  drift_check.py [--config .fullstack-sync.json] [--openapi spec.json] [--json] [--warn]

App side: string-literal paths ('/v1/auth/login') in app.endpoints_file / app.services_glob
(Dart/TS/JS/Kotlin/Swift style string constants). Backend side: the FastAPI extractor over
backend.root, or an OpenAPI JSON file (--openapi) when you have one.

Exit 0 = every app path is served, 1 = drift (unless --warn), 2 = bad input.
Path-level only: method and fields are the model-driven api-contract-sync's job.
Known limits: no include_router prefix chasing and no dynamic path building. A prefix the
backend mounts but the extractor can't see is tolerated by segment-suffix matching, so the
gate can miss a drift but should not invent one.
"""
import argparse, glob, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_fastapi

# optional leading $base / ${base} (Dart/Kotlin string interpolation of the API host)
_LIT = re.compile(r"""(['"])(?:\$\{?[A-Za-z_]\w*\}?)?(/[A-Za-z0-9_\-./{}$:]*)(?:\?[^'"]*)?\1""")
_ASSET = re.compile(r"\.(png|jpe?g|gif|svg|webp|ico|json|js|css|html|ttf|otf|mp[34]|pdf|txt|md)$", re.I)
_PARAM = re.compile(r"\$\{[^}]*\}|\$[A-Za-z_]\w*|\{[^}]*\}|:[A-Za-z_]\w*")


def norm(path):
    p = _PARAM.sub("{id}", path.split("?", 1)[0]).lower().rstrip("/")
    p = re.sub(r"/\d+(?=/|$)", "/{id}", p)  # literal ids (/users/7) are params too
    return p or "/"


# A literal in a services/screens file only counts when an HTTP call opens within the
# previous 2 lines; this keeps UI routes (context.go('/home')) out. The endpoints file
# is dedicated to API paths, so every literal there counts.
_CALL = re.compile(r"\.(get|post|put|patch|delete|head|request|getUri)\s*[<(]|Uri\.(parse|https?)\(|http\.\w+\(|fetch\(|axios", re.I)


def app_paths(files, strict_files=()):
    """{normalized path: 'file:line'} for API-looking string literals."""
    out = {}
    strict = set(strict_files)
    for f in files:
        try:
            lines = open(f, errors="ignore").read().splitlines()
        except OSError:
            continue
        for n, line in enumerate(lines, 1):
            if f not in strict and not any(_CALL.search(l) for l in lines[max(0, n - 3):n]):
                continue
            for m in _LIT.finditer(line):
                raw = m.group(2)
                if len(raw) < 2 or _ASSET.search(raw) or raw.startswith("/assets") or raw.startswith("//"):
                    continue
                if not re.search(r"[a-z]", raw, re.I):
                    continue
                out.setdefault(norm(raw), f"{f}:{n}")
    return out


def _segs(p):
    return [s for s in p.split("/") if s]


def served(app_path, backend):
    """Tolerates a base/prefix present on only one side: dio baseUrl makes the backend path
    longer, an include_router prefix the extractor can't see makes it shorter."""
    a = _segs(app_path)
    for b in backend:
        bs = _segs(b)
        if a and bs and (a[-len(bs):] == bs or bs[-len(a):] == a):
            return True
    return False


def backend_from_openapi(path):
    spec = json.load(open(path))
    return {norm(p) for p in spec.get("paths", {})}


def backend_from_fastapi(root, max_seconds=30):
    eps = extract_fastapi.extract([root], max_seconds=max_seconds)["endpoints"]
    return {norm(e["path"]) for e in eps}


def check(app, backend):
    """App paths the backend does not serve. A path that is a segment-prefix of another app
    path ('/v4' next to '/v4/tasks') is a base constant, not a call, so it is not checked."""
    segs = {p: _segs(p) for p in app}
    def is_base(p):
        return any(q != p and len(segs[q]) > len(segs[p]) and segs[q][:len(segs[p])] == segs[p] for q in app)
    return sorted((p, loc) for p, loc in app.items() if not is_base(p) and not served(p, backend))


def _files(cfg):
    root = cfg["app"]["root"]
    pats = [cfg["app"].get("endpoints_file"), cfg["app"].get("services_glob")]
    out = []
    for pat in pats:
        if pat:
            out += glob.glob(os.path.join(root, pat), recursive=True)
    return sorted(set(f for f in out if os.path.isfile(f)))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="drift_check")
    ap.add_argument("--config", default=".fullstack-sync.json")
    ap.add_argument("--openapi")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--warn", action="store_true", help="report drift but exit 0")
    a = ap.parse_args(argv)
    try:
        cfg = json.load(open(a.config))
        files = _files(cfg)
        ep = cfg["app"].get("endpoints_file")
        app = app_paths(files, [os.path.join(cfg["app"]["root"], ep)] if ep else [])
        backend = (backend_from_openapi(a.openapi) if a.openapi
                   else backend_from_fastapi(cfg["backend"]["root"]))
    except (OSError, ValueError, KeyError, TimeoutError) as e:
        print(f"drift_check: {e}", file=sys.stderr)
        return 2
    if not files or not app:
        print("drift_check: no app endpoint paths found; check app.endpoints_file/services_glob", file=sys.stderr)
        return 2
    if not backend:
        print("drift_check: backend exposes no endpoints; check backend.root or --openapi", file=sys.stderr)
        return 2
    missing = check(app, backend)
    if a.json:
        print(json.dumps({"app_paths": len(app), "backend_paths": len(backend),
                          "missing": [{"path": p, "at": loc} for p, loc in missing]}))
    else:
        for p, loc in missing:
            print(f"DRIFT {p}  (app: {loc}) not served by backend")
        print(f"{len(app)} app paths, {len(backend)} backend paths, {len(missing)} not served")
    return 0 if (not missing or a.warn) else 1


if __name__ == "__main__":
    sys.exit(main())
