"""Copy the pristine upstream ADH source to packages/muas_adh/build and apply the patch series.

Upstream stays untouched (brief D01). Run this before the tests.
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "packages" / "muas_adh"
UP, BUILD, PATCHES = ROOT / "upstream" / "src", ROOT / "build" / "src", ROOT / "patches"


def main() -> int:
    if BUILD.parent.exists():
        shutil.rmtree(BUILD.parent)
    shutil.copytree(UP, BUILD, ignore=shutil.ignore_patterns("__pycache__"))
    for patch in sorted(PATCHES.glob("*.patch")):
        r = subprocess.run(
            ["git", "apply", "--unsafe-paths", "--directory", str(BUILD.parent), str(patch)],
            capture_output=True, text=True,
        )
        if r.returncode:
            print(f"patch failed: {patch.name}\n{r.stderr}", file=sys.stderr)
            return 1
        print(f"applied {patch.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
