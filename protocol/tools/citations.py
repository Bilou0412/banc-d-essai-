#!/usr/bin/env python3
"""Checks that every test name cites what the spec carries (`protocol.md` §2, §3).

A test that cites no rule is a phantom: the green's silence lets it through. A
behaviour or an invariant that no test cites is uncited. This script reads test
names only, never bodies (D5), through patterns the project declares (D1), and
compares what they cite with what the spec and the decision log carry. It reads
no meaning: a name citing the wrong rule for the right reason passes here.

    tools/citations.py --format <declaration.json> [--log <decision-log>] <spec.md> <test-file> [...]

The declaration is one JSON object (specs/citations/interface.md):
`tests` (its first group is the test name), `rule` and `invariant` (two groups,
giving `<a>.<b>`), `decision` (one group, giving `D<n>`), `outside` (optional
list). An identifier is carried when a list item of its own field — 4, 5 or 6 —
opens with it, or a line or table row of the log does, and the next word is not
`retired` (5.3, G2). Matching is by identity, never by rank nor substring (5.2).

Prints, sorted: `phantom <name> <file>`, `uncited <id>`, `outside <name> <file>`;
on success, `ok <n> test names, <m> identifiers`. Writes nothing (5.1).
Exits with 0 when nothing is phantom nor uncited (4.3), 1 otherwise (4.1, 4.2),
2 on unusable input or no test name at all, naming the file on stderr (4.7, 4.8).
"""

from __future__ import annotations

import argparse
import json
import re
import sys

HEADING = re.compile(r"^##\s+(\d+)\b")
ITEM = re.compile(r"^\s*-\s+(?:\*\*)?(\d+\.\d+|D\d+)(?:\*\*)?(?=\s|$)(\s+retired\b)?")
LOG_ENTRY = re.compile(r"^(?:\|\s*|-\s+)?(?:\*\*)?(D\d+)(?:\*\*)?(?=\s|\||$)(\s+retired\b)?", re.M)
GROUPS = {"tests": None, "rule": 2, "invariant": 2, "decision": 1}


class Unusable(Exception):
    def __init__(self, path: str, reason: str):
        super().__init__(f"{path}: {reason}")


def read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError as e:
        raise Unusable(path, e.strerror or type(e).__name__)


def compile_(path: str, key: str, pattern: object) -> re.Pattern:
    if not isinstance(pattern, str):
        raise Unusable(path, f"{key}: a pattern must be a string")
    try:
        return re.compile(pattern)
    except re.error as e:
        raise Unusable(path, f"{key}: {e}")


def declaration(path: str) -> dict:
    try:
        decl = json.loads(read(path))
    except ValueError as e:
        raise Unusable(path, f"not JSON: {e}")
    if not isinstance(decl, dict):
        raise Unusable(path, "the declaration must be one JSON object")
    out = {}
    for key, groups in GROUPS.items():
        if key not in decl:
            raise Unusable(path, f"missing {key}")
        out[key] = compile_(path, key, decl[key])
        found = out[key].groups
        if (groups is None and found < 1) or (groups is not None and found != groups):
            raise Unusable(path, f"{key}: {found} groups, expected {groups or 'at least 1'}")
    outside = decl.get("outside", [])
    if not isinstance(outside, list):
        raise Unusable(path, "outside: must be a list")
    out["outside"] = [compile_(path, "outside", p) for p in outside]
    return out


def carried_by_spec(path: str) -> dict[str, set[str]]:
    fields: dict[str, set[str]] = {"4": set(), "5": set(), "6": set()}
    retired: set[str] = set()
    field = None
    for line in read(path).splitlines():
        heading = HEADING.match(line)
        if heading:
            field = heading.group(1)
            continue
        item = ITEM.match(line)
        if field in fields and item:
            ident = item.group(1)
            own = ident.startswith("D") if field == "6" else ident.startswith(field + ".")
            if own:
                (retired if item.group(2) else fields[field]).add(ident)
    for ids in fields.values():
        ids -= retired
    if not fields["4"]:
        raise Unusable(path, "field 4 carries no identifier")
    return fields


def carried_by_log(path: str) -> set[str]:
    entries = LOG_ENTRY.findall(read(path))
    retired = {ident for ident, mark in entries if mark}
    return {ident for ident, mark in entries if not mark} - retired


def cites(decl: dict, name: str) -> dict[str, set[str]]:
    return {
        "4": {f"{m.group(1)}.{m.group(2)}" for m in decl["rule"].finditer(name)},
        "5": {f"{m.group(1)}.{m.group(2)}" for m in decl["invariant"].finditer(name)},
        "6": {f"D{m.group(1)}" for m in decl["decision"].finditer(name)},
    }


def check(args: argparse.Namespace) -> tuple[list[str], bool]:
    decl = declaration(args.format)
    carried = carried_by_spec(args.spec)
    if args.log is not None:
        carried["6"] |= carried_by_log(args.log)
    names = set()
    for path in args.tests:
        for m in decl["tests"].finditer(read(path)):
            if m.group(1):
                names.add((m.group(1), path))
    if not names:
        raise Unusable(" ".join(args.tests), "the tests pattern yields no test name")

    lines, cited = [], {"4": set(), "5": set()}
    for name, path in names:
        if any(p.search(name) for p in decl["outside"]):
            lines.append(f"outside {name} {path}")
            continue
        found = cites(decl, name)
        if not any(found[f] & carried[f] for f in found):
            lines.append(f"phantom {name} {path}")
        for f in cited:
            cited[f] |= found[f] & carried[f]
    for f in cited:
        lines += [f"uncited {ident}" for ident in carried[f] - cited[f]]
    lines.sort()
    clean = not any(line.startswith(("phantom ", "uncited ")) for line in lines)
    if clean:
        count = len(carried["4"]) + len(carried["5"])
        lines.append(f"ok {len(names)} test names, {count} identifiers")
    return lines, clean


def main() -> int:
    parser = argparse.ArgumentParser(description="Checks the citations of test names.")
    parser.add_argument("--format", required=True)
    parser.add_argument("--log")
    parser.add_argument("spec")
    parser.add_argument("tests", nargs="+")
    args = parser.parse_args()
    try:
        lines, clean = check(args)
    except Unusable as e:
        print(f"citations: {e}", file=sys.stderr)
        return 2
    print("\n".join(lines))
    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(main())
