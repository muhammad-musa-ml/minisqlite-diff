"""Clone cursor/minisqlite at the pinned commit into vendor/minisqlite.

The source is not copied into this repository: cursor/minisqlite carries no licence
file, so this project fetches it from GitHub at build time instead of redistributing it.

Usage: python scripts/fetch_minisqlite.py [commit]
"""

import subprocess
import sys
from pathlib import Path

PINNED = "4a5c1341fdde38beaf438e0241c9f45833c4b870"
URL = "https://github.com/cursor/minisqlite"

root = Path(__file__).resolve().parent.parent
dest = root / "vendor" / "minisqlite"
commit = sys.argv[1] if len(sys.argv) > 1 else PINNED


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


if not dest.exists():
    dest.parent.mkdir(parents=True, exist_ok=True)
    git("clone", "--quiet", URL, str(dest))
git("fetch", "--quiet", "origin", cwd=dest)
git("checkout", "--quiet", "--detach", commit, cwd=dest)
head = git("rev-parse", "HEAD", cwd=dest)
print(f"vendor/minisqlite at {head}")
if head != commit:
    sys.exit(f"expected {commit}, got {head}")
