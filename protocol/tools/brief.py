#!/usr/bin/env python3
"""Assembles the material an agent of the theoretical layer receives (`protocol.md` §1).

An agent with no read tool receives its material pasted into its prompt. Pasted
by hand, it diverges from what is recorded: a fact given to the green but not
written in facts.md makes a true quotation fail the check, and a placeholder
left unfilled sends the agent to work on nothing. This script builds the
material from the files only, so what an agent is given is what the quotation
check reads.

    tools/brief.py <dossier-dir> [file ...]
    tools/brief.py --hook        (a pre-tool hook: reads the call on stdin)

Prints, fenced and verbatim: the arbiter's words (intent.md), the facts
(facts.md, when present), the dossier (dossier.md) — or, before the searcher
has written it, the question it is to answer (question.md) —, then each file named — a
proposal, objections. Paste the output whole. Writes nothing.
Exits with 1 if a required file is missing or empty.

As a hook before an agent is launched, it refuses (exit 2) to launch a role
that has no read tool of its own — searcher, green-spec, red, judge — with a
prompt that carries no material built here: the convention "paste the brief"
gave way three times; the hook makes it hold where hooks run.
"""

from __future__ import annotations

import sys
from pathlib import Path


def block(title: str, path: Path) -> str:
    return f"## {title} — verbatim from {path}\n\n\"\"\"\n{path.read_text(encoding='utf-8').strip()}\n\"\"\"\n"


PASTED_ROLES = {"searcher", "green-spec", "red", "judge"}
MARK = "— verbatim from "


def hook() -> int:
    import json
    call = json.load(sys.stdin)
    tool = call.get("tool_input", {})
    import re
    relay = call.get("tool_name") == "SendMessage"
    if not relay and (call.get("tool_name") != "Agent" or tool.get("subagent_type") not in PASTED_ROLES):
        return 0
    prompt = tool.get("message" if relay else "prompt", "")
    blocks = re.findall(r'— verbatim from (\S+)\n\n"""\n(.*?)\n"""', prompt, re.S)
    if relay and not blocks:
        return 0  # a relay to a running agent may carry no material; when it does, it is checked
    if not blocks:
        print(f"{tool.get('subagent_type')} has no material built by tools/brief.py: "
              "run `tools/brief.py <dossier> [file ...]` and paste its output whole", file=sys.stderr)
        return 2
    for name, text in blocks:
        path = Path(name)
        if not path.exists() or path.read_text(encoding="utf-8").strip() != text.strip():
            print(f"the block said to be verbatim from {name} is not that file: "
                  "paste the output of tools/brief.py whole, never a condensed copy", file=sys.stderr)
            return 2
    return 0


def main() -> int:
    if sys.argv[1:] == ["--hook"]:
        return hook()
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    dossier = Path(sys.argv[1])
    parts, missing = [], []

    # Before the searcher runs, the question stands in for the dossier: the
    # searcher writes dossier.md, and a file already there blocks it from
    # writing — it has no read tool, so it cannot overwrite what it never read.
    second = ("dossier.md", "Dossier") if (dossier / "dossier.md").exists() else ("question.md", "Question")
    for name, title, required in (
        ("intent.md", "The arbiter's words", True),
        ("facts.md", "Facts", False),
        (*second, True),
    ):
        path = dossier / name
        if path.exists() and path.read_text(encoding="utf-8").strip():
            parts.append(block(title, path))
        elif required:
            missing.append(str(path))

    for name in sys.argv[2:]:
        path = Path(name)
        if path.exists() and path.read_text(encoding="utf-8").strip():
            parts.append(block(path.stem, path))
        else:
            missing.append(name)

    if missing:
        print("no brief: missing or empty — " + ", ".join(missing))
        return 1
    print("\n".join(parts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
