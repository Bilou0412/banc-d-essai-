#!/usr/bin/env python3
"""Attaches the protocol to a project as a stamped copy, and checks that copy.

`protocol.md` §6, "The link", asks three things of whatever tool carries it:
the project runs on a known state of the protocol, a drift is visible, a
sharpening goes back up. A submodule makes them true only where submodules
are fetched; a runtime that clones the project alone finds an empty folder.
This tool carries the link as plain files instead:

    <protocol>/tools/link.py <project>     writes or refreshes the link
    <project>/protocol/tools/link.py       checks it, exits with 1 on drift

`<project>` is a git repository, or a folder of one when the project lives\nbeside others in the same repository. The link is `<project>/protocol/`, a copy of the distribution, plus
`protocol/STATE`: the commit it was taken from and a seal over its files.
The known state is that commit. An edit made from the project breaks the
seal — so a sharpening cannot stay in the project: it has to go up.

The agents and commands are copied into `<project>/.claude/` with the one
link fix `INSTALLATION.md` asks for; `project-agents.py` keeps checking them.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

DISTRIBUTION = ["protocol.md", "protocol-product-spec.md", "history.md",
                "INSTALLATION.md", "templates", ".claude/agents",
                ".claude/commands", "tools/link.py", "tools/project-agents.py",
                "tools/quotes.py", "tools/brief.py", "tools/citations.py",
                "tools/mutate.py"]
STATE = "STATE"
LINK_LINK = "(../../protocol.md)"
LINK_PROJECT = "(../../protocol/protocol.md)"


def files(root: Path) -> list[Path]:
    """Every file of the link, in a stable order, the state file aside."""
    found = [p for p in root.rglob("*")
             if p.is_file() and p.name != STATE and "__pycache__" not in p.parts]
    return sorted(found, key=lambda p: p.relative_to(root).as_posix())


def seal(root: Path) -> str:
    digest = hashlib.sha256()
    for path in files(root):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def commit_of(source: Path) -> str:
    out = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"{source} is not a git checkout of the protocol")
    dirty = subprocess.run(["git", "-C", str(source), "status", "--porcelain"],
                           capture_output=True, text=True).stdout.strip()
    if dirty:
        raise SystemExit("the protocol checkout has uncommitted changes — "
                         "a link taken from it would name no known state")
    return out.stdout.strip()


def read_state(link: Path) -> dict[str, str]:
    pairs = (line.split(": ", 1) for line in
             (link / STATE).read_text(encoding="utf-8").splitlines() if ": " in line)
    return dict(pairs)


def write(source: Path, project: Path) -> int:
    inside = subprocess.run(["git", "-C", str(project), "rev-parse", "--is-inside-work-tree"],
                            capture_output=True, text=True).stdout.strip()
    if inside != "true":
        raise SystemExit(f"{project} is not in a git repository")
    commit = commit_of(source)
    link = project / "protocol"
    if link.exists():
        shutil.rmtree(link)
    for item in DISTRIBUTION:
        origin, target = source / item, link / item
        target.parent.mkdir(parents=True, exist_ok=True)
        if origin.is_dir():
            shutil.copytree(origin, target)
        else:
            shutil.copy2(origin, target)
    (link / STATE).write_text(f"commit: {commit}\nseal: {seal(link)}\n",
                              encoding="utf-8")
    copied = 0
    for sub in (".claude/agents", ".claude/commands"):
        for origin in sorted((link / sub).glob("*.md")):
            target = project / sub / origin.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(origin.read_text(encoding="utf-8")
                              .replace(LINK_LINK, LINK_PROJECT), encoding="utf-8")
            copied += 1
    print(f"linked — protocol at {commit[:7]}, {len(files(link))} files, "
          f"{copied} agents and commands")
    return 0


def check(link: Path) -> int:
    if not (link / STATE).exists():
        print(f"{link} carries no {STATE} — this is not a link written by link.py")
        return 1
    state = read_state(link)
    actual = seal(link)
    if actual != state.get("seal"):
        print(f"the link was edited from the project — seal {actual}, "
              f"recorded {state.get('seal')}.\n"
              "A sharpening goes up to the protocol repository, then comes "
              "back down through link.py; it never starts here.")
        return 1
    print(f"link intact — protocol at {state.get('commit', '?')[:7]}")
    return 0


def main() -> int:
    here = Path(__file__).resolve()
    if len(sys.argv) == 2:
        return write(here.parent.parent, Path(sys.argv[1]).resolve())
    if len(sys.argv) == 1:
        return check(here.parent.parent)
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
