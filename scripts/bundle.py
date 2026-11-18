"""Read resolved values (variables, deployed resource IDs) of one bundle target via the Databricks CLI.

    from bundle import summary, value
    s = summary("dev", ["--var", "warehouse_id=abc"])
    value(s, "variables.catalog.value")
"""
import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent


def summary(target, var_args=()):
    cmd = ["databricks", "bundle", "summary", "-t", target, *var_args, "-o", "json"]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"`{' '.join(cmd)}` failed:\n{r.stderr.strip()}")
    return json.loads(r.stdout)


def value(s, path):
    v = s
    for key in path.split("."):
        v = v.get(key) if isinstance(v, dict) else None
    if v in (None, ""):
        raise SystemExit(f"{path} is not set for this target: is the bundle deployed, and are its variables set?")
    return v


def var_args(pairs):
    """['warehouse_id=abc'] -> ['--var', 'warehouse_id=abc']"""
    out = []
    for p in pairs or []:
        out += ["--var", p]
    return out
