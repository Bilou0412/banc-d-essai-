"""Minimal AST mutation runner: one mutant at a time, tests run as subprocesses (§3).

    tools/mutate.py <tools/x.py> <tools/x_tests> <workers> <out.json>

Each mutant is written as tools/<name of the source> beside a copy of the tests
directory, under its own name, in a scratch directory next to <out.json>; the
tests run there. The unmutated source runs first: if the suite does not pass on
it, nothing is counted and the exit is 2 — a suite that fails for every mutant
kills them all, and a score of 100 % would then measure nothing.
Exits 0 when the run completes; the score is printed and written to <out.json>."""
import ast, copy, json, os, shutil, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor

SRC, TESTS, WORKERS, OUT = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
tree = ast.parse(open(SRC).read())
CMP = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt, ast.Eq: ast.NotEq, ast.NotEq: ast.Eq,
       ast.In: ast.NotIn, ast.NotIn: ast.In, ast.Is: ast.IsNot, ast.IsNot: ast.Is}
BIN = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.FloorDiv, ast.FloorDiv: ast.Mult, ast.Div: ast.Mult, ast.Mod: ast.Mult}
BOOL = {ast.And: ast.Or, ast.Or: ast.And}

def sites():
    out = []
    for i, n in enumerate(ast.walk(tree)):
        if isinstance(n, ast.Compare):
            for j, op in enumerate(n.ops):
                if type(op) in CMP: out.append((i, "cmp", j))
        elif isinstance(n, ast.BinOp) and type(n.op) in BIN: out.append((i, "bin", 0))
        elif isinstance(n, ast.BoolOp) and type(n.op) in BOOL: out.append((i, "bool", 0))
        elif isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not): out.append((i, "not", 0))
        elif isinstance(n, ast.Constant) and type(n.value) is int and not isinstance(n.value, bool): out.append((i, "int", 0))
        elif isinstance(n, ast.Constant) and type(n.value) is bool: out.append((i, "bool_const", 0))
        elif isinstance(n, ast.Return) and n.value is not None: out.append((i, "ret_none", 0))
        elif isinstance(n, (ast.If, ast.While)): out.append((i, "cond_neg", 0))
    return out

def mutant(site):
    t = copy.deepcopy(tree); i, kind, j = site
    n = list(ast.walk(t))[i]
    if kind == "cmp": n.ops[j] = CMP[type(n.ops[j])]()
    elif kind == "bin": n.op = BIN[type(n.op)]()
    elif kind == "bool": n.op = BOOL[type(n.op)]()
    elif kind == "not":
        return None if not hasattr(n, "operand") else _replace(t, n, n.operand)
    elif kind == "int": n.value = n.value + 1
    elif kind == "bool_const": n.value = not n.value
    elif kind == "ret_none": n.value = ast.Constant(None)
    elif kind == "cond_neg": n.test = ast.UnaryOp(ast.Not(), n.test)
    return ast.unparse(ast.fix_missing_locations(t))

def _replace(t, old, new):
    for p in ast.walk(t):
        for f, v in ast.iter_fields(p):
            if v is old: setattr(p, f, new); return ast.unparse(ast.fix_missing_locations(t))
            if isinstance(v, list) and old in v: v[v.index(old)] = new; return ast.unparse(ast.fix_missing_locations(t))

NAME, SUITE = os.path.basename(SRC), os.path.basename(os.path.normpath(TESTS))

def run(args):
    k, site = args
    code = mutant(site) if site is not None else open(SRC).read()
    if code is None: return k, site, "skipped"
    d = tempfile.mkdtemp(dir=os.path.dirname(os.path.abspath(OUT)))
    os.makedirs(f"{d}/tools"); open(f"{d}/tools/{NAME}", "w").write(code)
    shutil.copytree(TESTS, f"{d}/tools/{SUITE}", ignore=shutil.ignore_patterns("__pycache__"))
    try:
        p = subprocess.run([sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", f"tools/{SUITE}"],
                           cwd=d, capture_output=True, timeout=180)
        res = "survived" if p.returncode == 0 else "killed"
    except subprocess.TimeoutExpired:
        res = "timeout"
    shutil.rmtree(d, ignore_errors=True)
    return k, site, res

if run((-1, None))[2] != "survived":
    print(f"the suite does not pass on the unmutated {SRC}: no score", file=sys.stderr)
    sys.exit(2)
ss = sites()
print(len(ss), "mutants", flush=True)
results = []
with ThreadPoolExecutor(WORKERS) as ex:
    for k, site, res in ex.map(run, enumerate(ss)):
        results.append({"k": k, "site": site, "result": res, "line": getattr(list(ast.walk(tree))[site[0]], "lineno", None)})
json.dump(results, open(OUT, "w"), indent=0)
from collections import Counter; c = Counter(r["result"] for r in results); print(c)
counted = c["killed"] + c["survived"] + c["timeout"]
print(f"score {100 * (c['killed'] + c['timeout']) / counted:.1f} % of {counted}" if counted else "no mutant counted")
