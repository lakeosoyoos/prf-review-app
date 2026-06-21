"""Gate 2 — dependency-completeness (static, no Windows needed).

AST-scans the app's own source for every third-party top-level import and asserts each is pinned in
requirements-desktop.txt. Catches the nastiest class of bug: a top-level `import scipy` that works on
the dev machine (scipy happened to be installed) and even passes a boot test there, but dies on a
clean Windows box. Imports guarded by `try/except ImportError` are treated as OPTIONAL.
"""
import os, ast, sys
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# our own modules (never expected in requirements)
LOCAL = {
    "app", "launcher", "run_cli", "core", "pipeline",
    "name_match", "trs_match", "doc_index", "build_grid_sufficiency", "verify_locations",
    "align_to_prior_aip", "set_specificity", "build_location_verified", "spatial", "xlsx_style",
    "parcel_rest", "ingest", "form_templates", "local_extract",
}
# import-name -> distribution (PyPI) name where they differ
DIST = {"yaml": "pyyaml", "PIL": "pillow"}
STDLIB = set(getattr(sys, "stdlib_module_names", set())) | {"__future__"}


def _source_files():
    out = []
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in ("tests", "build", "dist", ".git", "__pycache__", ".github")]
        for f in files:
            if f.endswith(".py"):
                out.append(os.path.join(base, f))
    return out


def _optional_lines(tree):
    """Line numbers of imports inside a try-block that catches ImportError/Exception -> optional."""
    opt = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            names = []
            for h in node.handlers:
                e = h.type
                if e is None:
                    names.append("Exception")
                elif isinstance(e, ast.Name):
                    names.append(e.id)
                elif isinstance(e, ast.Tuple):
                    names += [x.id for x in e.elts if isinstance(x, ast.Name)]
            if any(n in ("ImportError", "ModuleNotFoundError", "Exception") for n in names):
                for stmt in node.body:
                    for sub in ast.walk(stmt):
                        if isinstance(sub, (ast.Import, ast.ImportFrom)):
                            opt.add(sub.lineno)
    return opt


def _required_imports():
    req = set()
    for path in _source_files():
        tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
        optional = _optional_lines(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    if node.lineno not in optional:
                        req.add(n.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                if node.lineno not in optional:
                    req.add(node.module.split(".")[0])
    # drop stdlib + our own modules
    return {m for m in req if m not in STDLIB and m not in LOCAL}


def _pinned_dists():
    reqfile = os.path.join(ROOT, "requirements-desktop.txt")
    dists = set()
    for line in open(reqfile, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = line.split("==")[0].split(">=")[0].split("[")[0].strip().lower()
        dists.add(name)
    return dists


def test_every_thirdparty_import_is_pinned():
    pinned = _pinned_dists()
    missing = []
    for imp in sorted(_required_imports()):
        dist = DIST.get(imp, imp).lower()
        if dist not in pinned:
            missing.append(f"{imp} (dist '{dist}')")
    assert not missing, (
        "These third-party imports are used in the app source but NOT pinned in "
        "requirements-desktop.txt (would die on a clean Windows box):\n  " + "\n  ".join(missing)
    )
