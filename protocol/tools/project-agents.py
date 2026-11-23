#!/usr/bin/env python3
"""Checks that a project runs on the agents of the protocol state it points to.

`protocol.md` §6: *a drift between the project and the protocol is visible*. The
mechanism is declared in the project context; here is one, for a project
that attaches the protocol with `link.py` and copies its agents.

A sharpening goes back up to the protocol by construction — it is a commit. Nothing
brings it back down: the project's agents are copies, and a copy
drifts. This script is the way down.

    protocol/tools/project-agents.py          checks, exits with 1 if there is drift
    protocol/tools/project-agents.py --copy   copies again and fixes the links

`INSTALLATION.md` asks for the link at the top of each copy to be fixed: that
difference is intended and is not counted. Any other is.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

LINK_LINK = "(../../protocol.md)"              # as it is in the distribution
LINK_PROJECT = "(../../protocol/protocol.md)"  # as INSTALLATION.md wants it


def project_root() -> Path:
    """The project is two levels above `protocol/tools/`."""
    return Path(__file__).resolve().parent.parent.parent


def pairs(project: Path, link: Path) -> list[tuple[Path, Path]]:
    found = []
    for sub in (".claude/agents", ".claude/commands"):
        for source in sorted((link / sub).glob("*.md")):
            found.append((source, project / sub / source.name))
    return found


def normalise(text: str) -> str:
    """Neutralises the only difference INSTALLATION.md asks for."""
    return text.replace(LINK_PROJECT, LINK_LINK)


def main() -> int:
    project = project_root()
    link = project / "protocol"
    if not (link / "protocol.md").exists():
        print(f"no protocol attached under {link} — nothing to check")
        return 0

    copy = "--copy" in sys.argv
    drifts = []
    for source, target in pairs(project, link):
        expected = source.read_text(encoding="utf-8")
        if not target.exists():
            drifts.append(f"{target.relative_to(project)} — missing, the protocol provides it")
        elif normalise(target.read_text(encoding="utf-8")) != expected:
            drifts.append(f"{target.relative_to(project)} — differs from the pointed state of the protocol")
        else:
            continue
        if copy:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(expected.replace(LINK_LINK, LINK_PROJECT), encoding="utf-8")

    if copy:
        print(f"copied — {len(drifts)} file(s) restored to the pointed state")
        return 0
    if not drifts:
        print(f"up to date — {len(pairs(project, link))} agents and commands")
        return 0
    print(f"{len(drifts)} drift(s) from the pointed state of the protocol:\n")
    for d in drifts:
        print(f"  {d}")
    print("\nA sharpening does not come back down on its own. To apply it:")
    print("  protocol/tools/project-agents.py --copy")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
