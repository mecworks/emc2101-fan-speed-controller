"""MicroPython-subset lint gate for shared (platform-neutral) modules.

Checks (per AGENTS.md ground rules):
  - compiles under CPython (syntax valid)
  - no CPython-only imports (os/sys/json/struct/logging/subprocess/...)
  - type annotations restricted to bare built-in names from the whitelist
    {int, float, bytes, str, bool}; subscripted/container generics,
    Optional, typing-module imports and AnnAssign remain banned
  - no async/await or walrus operator
(f-strings ARE allowed: MicroPython supports PEP 498 from v1.17; the
project baseline is v1.29.0. @property is likewise allowed.)
Shared files: _regs.py, _core.py, _faults.py, _tables.py, _persist.py,
_transport_mp.py, mp.py, __init__.py, plus every examples/*.py script
(they run on MicroPython). Exempt (CPython-only by design):
_transport_cp.py, cp.py.

Note on the import ban: it targets CPython-only stdlib. `json`, `time`,
`os` and `sys` ARE allowed because they ship with MicroPython v1.29.0 on
both target ports (Pico W / ESP32-S3); M4's persistence layer uses
json/time in _persist.py and os (guarded, function-level) for the
atomic-rename file glue in _core.py, degrading to a plain overwrite where
unsupported, and the examples use sys.platform/os.uname() for board-aware
pin selection.
"""
import ast
import py_compile
import sys

SHARED = [
    "emc2101/_regs.py",
    "emc2101/_core.py",
    "emc2101/_faults.py",
    "emc2101/_tables.py",
    "emc2101/_persist.py",
    "emc2101/_transport_mp.py",
    "emc2101/mp.py",
    "emc2101/__init__.py",
    "examples/_fan_curve_math.py",
    "examples/pico_demo.py",
    "examples/esp32_demo.py",
    "examples/rpi_demo.py",
    "examples/hw_smoke_test.py",
    "examples/e2e_hardware_test.py",
]
BAD_MODULES = {
    "struct", "logging", "subprocess", "threading",
    "socket", "urllib", "http", "sqlite3", "smbus", "smbus2", "ctypes",
    "multiprocessing", "queue", "select", "signal", "typing",
}

# Only these bare built-in names may appear as annotations.
ALLOWED_ANNOTATIONS = {"int", "float", "bytes", "str", "bool"}


def _ok_annotation(node):
    return isinstance(node, ast.Name) and node.id in ALLOWED_ANNOTATIONS


def check(path):
    problems = []
    src = open(path, encoding="utf-8").read()
    try:
        py_compile.compile(path, doraise=True)
    except Exception as e:
        return ["compile: %s" % e]
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                top = a.name.split(".")[0]
                if top in BAD_MODULES:
                    problems.append("bad import %r at line %d"
                                    % (a.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if top in BAD_MODULES:
                problems.append("bad from-import %r at line %d"
                                % (node.module, node.lineno))
        elif isinstance(node, ast.FunctionDef):
            params = (list(getattr(node.args, "posonlyargs", []))
                      + list(node.args.args)
                      + list(node.args.kwonlyargs))
            if node.args.vararg is not None:
                params.append(node.args.vararg)
            if node.args.kwarg is not None:
                params.append(node.args.kwarg)
            if any(p.annotation is not None and not _ok_annotation(p.annotation)
                   for p in params):
                problems.append("disallowed arg annotation in %s line %d"
                                % (node.name, node.lineno))
            if node.returns is not None and not _ok_annotation(node.returns):
                problems.append("disallowed return annotation in %s line %d"
                                % (node.name, node.lineno))
        elif isinstance(node, ast.AnnAssign):
            problems.append("annotation at line %d" % node.lineno)
        elif isinstance(node, ast.JoinedStr):
            pass  # f-strings allowed: MicroPython >= 1.17 supports PEP 498
        elif isinstance(node, ast.AsyncFunctionDef):
            problems.append("async def at line %d" % node.lineno)
        elif isinstance(node, ast.NamedExpr):
            problems.append("walrus operator at line %d" % node.lineno)
    return problems


ok = True
for path in SHARED:
    probs = check(path)
    if probs:
        ok = False
        print("%s : FAIL" % path)
        for p in probs:
            print("   - %s" % p)
    else:
        print("%s : CLEAN" % path)
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
