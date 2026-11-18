"""Pull edits made in the Genie UI back into the agent's resource file.

Tune your dev copy of the agent in the UI, then run (or `make pull`):
    python scripts/pull_agent.py --target dev
The agent ID, catalog and schema come from the bundle target; pass --space-id, --catalog or --schema to override.

It downloads the agent definition, turns the catalog and schema back into ${var.catalog} and ${var.schema},
and replaces serialized_space in the resource file. Title, description, warehouse and permissions stay as they
are in Git. Review the diff, deploy to dev, run the gate, then open a pull request. Needs CAN EDIT on the agent.
"""
import argparse
import json
import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent


class Dumper(yaml.SafeDumper):
    """Block style for structure, inline lists for short values, | for multi-line text, like the hand-written file."""


def _str(dumper, value):
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


Dumper.add_representer(str, _str)


def catalog_pattern(catalog, schema):
    """Matches `catalog.schema.` with optional backticks, but not inside a longer name (xdev.genie_sales.)."""
    return rf"(?<![\w.`])`?{re.escape(catalog)}`?\.`?{re.escape(schema)}`?\."


def normalize(value):
    """Undo API formatting so that an unchanged agent pulls back as no change:
    sort id-, table- and column-keyed lists (the API returns some in reverse), join instruction text split into lines,
    and drop enable_format_assistance: true (the default)."""
    if isinstance(value, dict):
        value = {k: normalize(v) for k, v in value.items()}
        if value.get("enable_format_assistance") is True:
            del value["enable_format_assistance"]
        if "text_instructions" in value:
            for t in value["text_instructions"]:
                t["content"] = ["".join(t.get("content", []))]
        return value
    if isinstance(value, list):
        value = [normalize(v) for v in value]
        for key in ("id", "identifier", "column_name"):  # the API sorts by these; keep Git in the same order
            if value and all(isinstance(v, dict) and key in v for v in value):
                value.sort(key=lambda v: v[key])
                break
        return value
    return value


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--target", default="dev", help="bundle target whose agent you edited (default dev)")
    p.add_argument("--var", action="append", help="bundle variable, for example warehouse_id=abc (repeatable)")
    p.add_argument("--space-id", help="default: the agent deployed by the bundle target")
    p.add_argument("--catalog", help="default: the target's catalog variable")
    p.add_argument("--schema", help="default: the target's schema variable")
    p.add_argument("--file", default="resources/sales_agent.genie.yml", help="resource file to update")
    p.add_argument("--agent", default="sales_agent", help="resource key of the agent in that file")
    p.add_argument("--out", help="write here instead of overwriting --file (for a dry run)")
    a = p.parse_args()

    if not (a.space_id and a.catalog and a.schema):
        from bundle import summary, value, var_args
        b = summary(a.target, var_args(a.var))
        a.space_id = a.space_id or value(b, f"resources.genie_spaces.{a.agent}.id")
        a.catalog = a.catalog or value(b, "variables.catalog.value")
        a.schema = a.schema or value(b, "variables.schema.value")
    print(f"Pulling agent {a.space_id} ({a.target}: {a.catalog}.{a.schema})")

    from databricks.sdk import WorkspaceClient  # imported here so the unit tests do not need the SDK

    src = ROOT / a.file
    w = WorkspaceClient()
    space = w.api_client.do("GET", f"/api/2.0/genie/spaces/{a.space_id}", query={"include_serialized_space": "true"})
    raw = space.get("serialized_space")
    if not raw:
        raise SystemExit("The agent definition came back empty: you need CAN EDIT on the agent.")

    pattern = catalog_pattern(a.catalog, a.schema)
    raw, n = re.subn(pattern, "${var.catalog}.${var.schema}.", raw)
    ss = normalize(json.loads(raw))

    text = src.read_text()
    header = "".join(line for line in text.splitlines(keepends=True) if line.startswith("#"))
    doc = yaml.safe_load(text)
    agent = doc["resources"]["genie_spaces"][a.agent]
    changed = agent.get("serialized_space") != ss
    agent["serialized_space"] = ss

    if not changed and not a.out:
        print(f"No changes in {a.file}: the agent matches Git, file left as is")
        return
    out = pathlib.Path(a.out) if a.out else src
    out.write_text(header + yaml.dump(doc, Dumper=Dumper, sort_keys=False, width=200, allow_unicode=True,
                                      default_flow_style=None, indent=2))
    print(f"{'Updated' if changed else 'No changes in'} {out if a.out else a.file}: {n} table references mapped to "
          f"${{var.catalog}}.${{var.schema}}")
    if changed and not a.out:
        print("Next: review with git diff, deploy to dev, run the benchmark gate, open a pull request.")


if __name__ == "__main__":
    main()
