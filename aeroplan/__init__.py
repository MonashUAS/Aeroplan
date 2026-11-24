"""AeroPlan: the ADH-based single source of truth for aircraft data (the .muas file)."""
import sys as _sys
from pathlib import Path as _Path

MUAS_SCHEMA_VERSION = "0.6.0"

#: The repository root (this file is aeroplan/__init__.py)
REPO_ROOT = _Path(__file__).resolve().parents[1]


def _ensure_adh() -> None:
    """Make the patched upstream ADH importable: build standards/adh/build once, then put it on sys.path."""
    root = REPO_ROOT
    build = root / "standards" / "adh" / "build" / "src"
    if not build.is_dir() and (root / "standards" / "adh" / "build_adh.py").is_file():
        import runpy

        if runpy.run_path(str(root / "standards" / "adh" / "build_adh.py"))["main"]():
            raise RuntimeError("standards/adh/build_adh.py failed: the patched ADH package is not available")
    if build.is_dir() and str(build) not in _sys.path:
        _sys.path.insert(0, str(build))


_ensure_adh()
