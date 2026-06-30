#!/usr/bin/env python3
"""Tested contract extractor for the common FastAPI case.

Parses FastAPI router source with the `ast` module (deterministic — no regex
guessing) into the `{"endpoints":[{"method","path","fields"}]}` shape consumed
by fingerprint.py / sync_state.py. Covers the common pattern:

  - module-level `router = APIRouter(prefix="...")`
  - `@router.<method>("<path>", response_model=Model)` decorators
  - `class Model(BaseModel): name: type` field names (top-level annotations)

Field names come from the `response_model` class only. Paths get their params
normalized to `{id}` and are lowercased, matching the fingerprint path rule.

Documented limits (these fall back to the model-driven api-contract-sync skill):
  - does NOT follow `include_router(...)` mounting chains across files
  - does NOT read request-body parameter models (response_model only)
  - does NOT resolve nested / inherited Pydantic models or `Field(alias=...)`
  - assumes one `APIRouter` prefix per file
"""
import ast, os, sys, json, re

METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}
_PARAM = re.compile(r"\{[^}]+\}")


def _norm_path(path):
    return _PARAM.sub("{id}", path).lower()


def _model_fields(tree):
    """Map each class name -> its top-level annotated field names."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            out[node.name] = [
                n.target.id for n in node.body
                if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
            ]
    return out


def _router_prefix(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            call = node.value
            if isinstance(call.func, ast.Name) and call.func.id == "APIRouter":
                for kw in call.keywords:
                    if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                        return kw.value.value
    return ""


def extract_file(path):
    tree = ast.parse(open(path).read())
    models = _model_fields(tree)
    prefix = _router_prefix(tree)
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
            model = None
            for kw in dec.keywords:
                if kw.arg == "response_model" and isinstance(kw.value, ast.Name):
                    model = kw.value.id
            eps.append({
                "method": dec.func.attr.upper(),
                "path": _norm_path(prefix + sub_path),
                "fields": sorted(models.get(model, [])),
            })
    return eps


def extract(paths):
    files = []
    for p in paths:
        if os.path.isdir(p):
            for root, _, names in os.walk(p):
                files += [os.path.join(root, n) for n in names if n.endswith(".py")]
        else:
            files.append(p)
    eps = []
    for f in sorted(files):
        eps += extract_file(f)
    return {"endpoints": eps}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: extract_fastapi.py <routers-dir-or-file> [...]")
    print(json.dumps(extract(sys.argv[1:]), separators=(",", ":")))
