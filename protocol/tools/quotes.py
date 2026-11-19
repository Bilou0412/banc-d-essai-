#!/usr/bin/env python3
"""Checks the quotations of the theoretical layer (`protocol.md` §1).

The cheapest check goes first: before any model reads a dossier, a proposal or
a spec, every quotation it carries must be found, word for word, where it
claims to come from. This script reads no meaning — a real source quoted for
what it does not say passes here, and is the cold judge's to catch.

    tools/quotes.py <dossier-dir>                 checks the dossier's extracts
    tools/quotes.py <dossier-dir> <file> [...]    also checks the quotations of each file

Layout of the dossier directory:

    intent.md            the arbiter's words, verbatim, never edited
    facts.md             the facts the driver injects about the setting (optional)
    dossier.md           the searcher's entries:  id: S<n>  …  extract: "<text>"  (one or more)
    sources/S<n>.txt     the text fetched for each entry

A quotation in a proposal or a spec is "<text>" — S<n> | arbiter | facts
(or the same origin in parentheses), wherever it stands: on a quote: line, as the
second quotation of one, or in an answer. Every one is checked, and the count is
printed — a file whose quotations the pattern misses holds with 0, and shows it.
Exits with 1 if anything does not match.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ENTRY_ID = re.compile(r"^id:\s*(S\d+)\s*$", re.M)
EXTRACT = re.compile(r'^extract:\s*"(.*)"\s*$')
CONTINUED = re.compile(r'^\s+"(.*)"\s*$')
OUTSIDE = re.compile(r'^(essence|holds if|fails if):\s*(.*)$')
QUOTED = re.compile(r'["“]([^"”]+)["”]')
QUOTE = re.compile(r'["“]([^"”]+)["”]\s*(?:[—-]+\s*|\()(S\d+|arbiter|facts)\)?', re.I)


def norm(text: str) -> str:
    """Whitespace, typographic quotes, emphasis marks and a quote escaped inside a
    quotation (\\") do not make a quotation different."""
    text = text.replace('\\"', '"').replace("*", "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return " ".join(text.split()).casefold()


def outside(dossier: Path) -> list[str]:
    """A quotation written on an essence, holds-if or fails-if line is held to
    its source like an extract: one not found there is a recall presented as
    a reading. A proposal still cites only extracts."""
    text = (dossier / "dossier.md").read_text(encoding="utf-8")
    found, ident = [], "?"
    for line in text.splitlines():
        head = ENTRY_ID.match(line)
        if head:
            ident = head.group(1)
            continue
        field = OUTSIDE.match(line)
        if not field:
            continue
        source = dossier / "sources" / f"{ident}.txt"
        fetched = norm(source.read_text(encoding="utf-8")) if source.exists() else ""
        for quoted in QUOTED.findall(field.group(2)):
            if len(quoted.split()) >= 4 and norm(quoted) not in fetched:
                found.append(f"{ident} — quotation on its {field.group(1)} line not found in its source: "
                             f"\"{quoted[:50]}\" — drop it, never repair it from memory")
    return found


def entries(dossier: Path) -> dict[str, list[str]]:
    """Maps each entry id to its extracts: an entry may carry several,
    each on its own `extract:` line or on an indented quoted line below it."""
    text = (dossier / "dossier.md").read_text(encoding="utf-8")
    found = {}
    bounds = [(m.group(1), m.start()) for m in ENTRY_ID.finditer(text)]
    for i, (ident, start) in enumerate(bounds):
        end = bounds[i + 1][1] if i + 1 < len(bounds) else len(text)
        extracts, inside = [], False
        for line in text[start:end].splitlines():
            first = EXTRACT.match(line)
            more = CONTINUED.match(line) if inside else None
            if first or more:
                extracts.append((first or more).group(1))
                inside = True
            else:
                inside = False
        found[ident] = extracts
    return found


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    dossier = Path(sys.argv[1])
    defects = []

    intent_file = dossier / "intent.md"
    if not (dossier / "dossier.md").exists() or not intent_file.exists():
        print(f"no dossier to check against: {dossier} needs intent.md (the arbiter's words, verbatim) "
              "and dossier.md — write them before any quotation is checked")
        return 1

    extracts = entries(dossier)
    defects.extend(outside(dossier))
    for ident, found in extracts.items():
        source = dossier / "sources" / f"{ident}.txt"
        if not found:
            continue  # "not retrieved" entries carry no extract
        if not source.exists():
            defects.append(f"{ident} — extract without its fetched source ({source})")
            continue
        fetched = norm(source.read_text(encoding="utf-8"))
        for extract in found:
            if norm(extract) not in fetched:
                defects.append(f"{ident} — extract not found in its source: drop it, never repair it from memory")

    intent = norm(intent_file.read_text(encoding="utf-8"))
    facts_file = dossier / "facts.md"
    facts = norm(facts_file.read_text(encoding="utf-8")) if facts_file.exists() else ""
    checked = 0
    for name in sys.argv[2:]:
        for text, origin in QUOTE.findall(Path(name).read_text(encoding="utf-8")):
            if origin.lower() == "arbiter":
                ok = norm(text) in intent
            elif origin.lower() == "facts":
                ok = norm(text) in facts
            else:
                ok = any(norm(text) in norm(e) for e in extracts.get(origin, []))
            checked += 1
            if not ok:
                defects.append(f"{name} — \"{text[:60]}\" not found in {origin}: own choice, not a quotation")

    if not defects:
        print(f"quotations hold — {len(extracts)} entries, {len(sys.argv) - 2} file(s), {checked} quotation(s)")
        return 0
    print(f"{len(defects)} quotation defect(s):\n")
    for d in defects:
        print(f"  {d}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
