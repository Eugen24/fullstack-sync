#!/usr/bin/env python3
"""Tested contract extractor for the common FastAPI case.

Parses FastAPI router source with the `ast` module (deterministic — no regex
guessing) into the `{"endpoints":[{"method","path","fields"}]}` shape consumed
by fingerprint.py / sync_state.py. Covers the common pattern:

  - module-level `router = APIRouter(prefix="...")`
  - `@router.<method>("<path>", response_model=Model)` decorators
  - `class Model(BaseModel): name: type` field names (top-level annotations)

Field names come from the response model (response_model=..., or the return annotation), resolved across files with inheritance and Field(alias=...). Paths get their params
normalized to `{id}` and are lowercased, matching the fingerprint path rule.

Documented limits (these fall back to the model-driven api-contract-sync skill):
  - follows static `include_router(mod.router, prefix=...)` one level; runtime-computed prefixes
    need `prefix_rule`; no multi-level router-in-router chains
  - does NOT read request-body parameter models (response model / return annotation only)
  - response fields are top-level only (nested model fields are not flattened)
  - assumes one `APIRouter` prefix per file
"""
import ast, os, sys, json, re, time

METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}
_PARAM = re.compile(r"\{[^}]+\}")
# Never descend into these: virtualenvs, VCS metadata, caches, vendored deps. Walking them
# made the Stop hook take 8-14s on real backends (and hit its timeout).
SKIP_DIRS = {".git", ".venv", "venv", "env", "node_modules", "__pycache__", ".mypy_cache",
             ".pytest_cache", ".ruff_cache", ".tox", ".worktrees", "site-packages",
             "build", "dist", ".claude", ".superpowers"}


def _norm_path(path):
    return _PARAM.sub("{id}", path).lower()


_WRAPPERS = {"List", "list", "Optional", "Sequence", "Set", "set", "Union", "Page", "Paginated",
             "Dict", "dict", "Tuple", "tuple", "Iterable", "Annotated"}
_ALIAS_KW = {"alias", "validation_alias", "serialization_alias"}


def _field_names(cls):
    """Annotated field names of a class body, plus any Field(alias=...) spelling."""
    out = []
    for n in cls.body:
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            out.append(n.target.id)
            if isinstance(n.value, ast.Call):
                out += [kw.value.value for kw in n.value.keywords
                        if kw.arg in _ALIAS_KW and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str)]
    return out


def _model_fields(tree):
    """Map each class name -> its top-level annotated field names."""
    return {n.name: _field_names(n) for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}


def _base_names(cls):
    return [b.id if isinstance(b, ast.Name) else b.attr for b in cls.bases
            if isinstance(b, (ast.Name, ast.Attribute))]


def registry(trees):
    """{class name: {"bases": [...], "fields": [...]}} across every parsed file."""
    reg = {}
    for tree in trees:
        for n in ast.walk(tree):
            if isinstance(n, ast.ClassDef):
                reg[n.name] = {"bases": _base_names(n), "fields": _field_names(n)}
    return reg


def resolve_fields(name, reg, _seen=None):
    """Fields of a model including everything inherited from bases known in reg."""
    seen = _seen if _seen is not None else set()
    if name in seen or name not in reg:
        return set()
    seen.add(name)
    out = set(reg[name]["fields"])
    for b in reg[name]["bases"]:
        out |= resolve_fields(b, reg, seen)
    return out


def _model_in(expr, reg):
    """Model class name behind a response_model / return annotation: unwraps List[X],
    Optional[X], X | None, Page[X]. None when it names no class we can see."""
    if isinstance(expr, ast.Name):
        return expr.id if expr.id in reg else None
    if isinstance(expr, ast.Attribute):
        return expr.attr if expr.attr in reg else None
    if isinstance(expr, ast.Subscript):
        sl = expr.slice
        for e in (sl.elts if isinstance(sl, ast.Tuple) else [sl]):
            m = _model_in(e, reg)
            if m:
                return m
    if isinstance(expr, ast.BinOp):  # X | None
        return _model_in(expr.left, reg) or _model_in(expr.right, reg)
    return None


def _router_prefix(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            call = node.value
            if isinstance(call.func, ast.Name) and call.func.id == "APIRouter":
                for kw in call.keywords:
                    if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                        return kw.value.value
    return ""


def _tree(path):
    return ast.parse(open(path).read())


def extract_file(path, reg=None, mount=""):
    """Endpoints of one file. reg resolves response models declared in other files; mount is
    the prefix the router is included under."""
    tree = _tree(path)
    reg = reg if reg is not None else registry([tree])
    prefix = mount + _router_prefix(tree)
    eps = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                    and dec.func.attr in METHODS):
                continue
            sub_path = dec.args[0].value if (
                dec.args and isinstance(dec.args[0], ast.Constant)) else ""
            expr = next((kw.value for kw in dec.keywords if kw.arg == "response_model"), None)
            model = _model_in(expr, reg) if expr is not None else (
                _model_in(node.returns, reg) if node.returns is not None else None)
            eps.append({
                "method": dec.func.attr.upper(),
                "path": _norm_path(prefix + sub_path),
                "fields": sorted(resolve_fields(model, reg)) if model else [],
                "model": model,
                "file": path,
            })
    return eps


def _module_files(files):
    """{dotted module path: file} for suffix matching ('app.routers.users' -> .../app/routers/users.py)."""
    out = {}
    for f in files:
        parts = os.path.normpath(f)[:-3].split(os.sep)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        out[tuple(parts)] = f
    return out


def _find_module(dotted, modules):
    want = tuple(dotted.split("."))
    hits = [f for parts, f in modules.items() if parts[-len(want):] == want]
    return hits[0] if len(hits) == 1 else None


def include_mounts(trees_by_file):
    """{file: prefix} from static `x.include_router(mod.router, prefix="/p")` calls.

    Handles `from pkg import mod`, `from pkg.mod import router` and `import pkg.mod as mod`.
    Dynamic prefixes (computed at runtime) are not resolvable; use prefix_rule for those."""
    modules = _module_files(trees_by_file)
    mounts = {}
    for f, tree in trees_by_file.items():
        names = {}  # local name -> dotted module it refers to
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom):
                base = n.module or ""
                for a in n.names:
                    names[a.asname or a.name] = (base + "." + a.name).strip(".")
                    names["@router:" + (a.asname or a.name)] = base
            elif isinstance(n, ast.Import):
                for a in n.names:
                    names[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "include_router" and n.args):
                continue
            prefix = next((kw.value.value for kw in n.keywords
                           if kw.arg == "prefix" and isinstance(kw.value, ast.Constant)), "")
            arg = n.args[0]
            dotted = None
            if isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name):   # mod.router
                dotted = names.get(arg.value.id)
            elif isinstance(arg, ast.Name):                                          # router (from pkg.mod import router)
                dotted = names.get("@router:" + arg.id)
            target = _find_module(dotted, modules) if dotted else None
            if target and prefix:
                mounts[target] = prefix
    return mounts


def path_prefix(file, rule):
    """Prefix derived from a file's location, for backends that mount routers by directory:
    rule = {"from_path": "routers", "skip": ["root"]}: routers/v4/tasks.py -> /v4/tasks,
    routers/root/x.py -> '' (a part containing a skip token right under the dir disables it)."""
    parts = os.path.normpath(file).split(os.sep)
    if rule["from_path"] not in parts:
        return ""
    rel = parts[parts.index(rule["from_path"]) + 1:]
    if not rel or any(t in rel[0] for t in rule.get("skip", [])):
        return ""
    return "".join("/" + (x[:-3] if x.endswith(".py") else x) for x in rel if "__" not in x)


def _py_files(paths):
    files = []
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, names in os.walk(p):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                files += [os.path.join(root, n) for n in names if n.endswith(".py")]
        else:
            files.append(p)
    return sorted(files)


def _deadline(max_seconds):
    return None if max_seconds is None else time.monotonic() + max_seconds


def _check(deadline):
    if deadline is not None and time.monotonic() > deadline:
        raise TimeoutError("extract_fastapi: time budget exceeded")


def _parse_all(paths, deadline):
    trees = {}
    for f in _py_files(paths):
        _check(deadline)
        try:
            trees[f] = _tree(f)
        except (SyntaxError, UnicodeDecodeError, ValueError):
            continue
    return trees


def extract(paths, max_seconds=None, prefix_rule=None):
    """Endpoints for every .py under paths. Unparseable files are skipped.

    Response models resolve across files (with inheritance, List[X]/Optional[X] unwrapping and
    Field(alias=...)); static include_router prefixes are applied; prefix_rule adds the
    directory-derived prefix some backends use. max_seconds raises TimeoutError once exceeded.
    """
    deadline = _deadline(max_seconds)
    trees = _parse_all(paths, deadline)
    reg = registry(trees.values())
    mounts = include_mounts(trees)
    eps = []
    for f in trees:
        _check(deadline)
        mount = mounts.get(f, "") + (path_prefix(f, prefix_rule) if prefix_rule else "")
        try:
            eps += extract_file(f, reg, mount)
        except (SyntaxError, UnicodeDecodeError, ValueError):
            continue
    return {"endpoints": eps}


_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def all_model_fields(paths, max_seconds=None):
    """Every field-like name the backend mentions anywhere: class fields (and aliases), assignment
    targets, keyword-argument and attribute names, function parameters and identifier-like string
    literals (dict keys, getattr names). Used for the loose FIELD? check, where 'the backend never
    mentions this name' is the signal, so over-inclusion only ever errs toward silence."""
    deadline, out = _deadline(max_seconds), set()
    for tree in _parse_all(paths, deadline).values():
        for n in ast.walk(tree):
            if isinstance(n, ast.ClassDef):
                out.update(_field_names(n))
            elif isinstance(n, ast.Name):
                out.add(n.id)
            elif isinstance(n, ast.Attribute):
                out.add(n.attr)
            elif isinstance(n, ast.keyword) and n.arg:
                out.add(n.arg)
            elif isinstance(n, ast.arg):
                out.add(n.arg)
            elif isinstance(n, ast.Constant) and isinstance(n.value, str) and _IDENT.match(n.value):
                out.add(n.value)
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    budget = None
    if args[:1] == ["--max-seconds"] and len(args) > 2:
        budget, args = float(args[1]), args[2:]
    if not args:
        sys.exit("usage: extract_fastapi.py [--max-seconds N] <routers-dir-or-file> [...]")
    try:
        print(json.dumps(extract(args, budget), separators=(",", ":")))
    except TimeoutError as e:
        sys.exit(str(e))
