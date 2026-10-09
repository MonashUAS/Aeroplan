"""Run OpenVSP jobs in the OpenVSP Python, and make that Python (`aeroplan setup OpenVSP`).

The OpenVSP Python module is built for one Python version (OpenVSP 3.54: Python 3.13). AeroPlan runs on its own
Python, so the spoke sends each job to OpenVSP/vsp_worker.py in a separate Python: OpenVSP/.venv (git ignores it).

`setup()` makes that venv on a member's machine, from a clean OpenVSP download:
  1. find the OpenVSP folder (`--vsp`, OPENVSP_DIR, or a search of the usual folders for OpenVSP-*/vsp.exe),
  2. read the Python version that the module needs (the python3NN.dll name in _vsp.pyd),
  3. make the venv with uv, which downloads that Python into the user profile (no admin rights),
  4. install numpy and six, and write openvsp.pth, which points to the Python packages of the OpenVSP folder.
Nothing is written into the OpenVSP folder. For a new OpenVSP version, unzip it and run the setup again.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
VENV = HERE / ".venv"
WORKER = HERE / "vsp_worker.py"
PACKAGES = ("openvsp", "degen_geom", "utilities", "openvsp_config")
WORKER_NEEDS = ("numpy", "six")


class OpenVSPError(RuntimeError):
    pass


def python() -> Path:
    """The OpenVSP Python: OPENVSP_PYTHON, else OpenVSP/.venv."""
    env = os.environ.get("OPENVSP_PYTHON")
    if env:
        return Path(env)
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def available() -> bool:
    return python().is_file() and WORKER.is_file()


def run(job: Dict[str, Any], timeout: float = 600) -> Dict[str, Any]:
    """Run one worker job. Raises OpenVSPError with the worker error text."""
    if not available():
        raise OpenVSPError("the OpenVSP Python is not set up: run `python -m aeroplan setup OpenVSP`")
    job = {k: (str(Path(v).resolve()) if k in ("path", "out") else v) for k, v in job.items()}
    with tempfile.TemporaryDirectory(prefix="aeroplan_vsp_") as tmp:
        jf, rf = Path(tmp) / "job.json", Path(tmp) / "result.json"
        jf.write_text(json.dumps(job), encoding="utf-8")
        p = subprocess.run([str(python()), "-I", str(WORKER), str(jf), str(rf)], capture_output=True, text=True,
                           timeout=timeout, cwd=tmp)
        if not rf.is_file():
            raise OpenVSPError(f"the OpenVSP worker stopped (exit {p.returncode}): {(p.stderr or p.stdout)[-2000:]}")
        res = json.loads(rf.read_text(encoding="utf-8"))
    if not res.get("ok"):
        raise OpenVSPError(f"OpenVSP job {job['job']}: {res.get('error')}\n{res.get('trace', '')}")
    return res


# ------------------------------------------------------------------------------------------------------------ setup
def _version_key(path: Path):
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", path.name)
    return tuple(int(v) for v in m.groups()) if m else (0, 0, 0)


def find_openvsp(given: Optional[str] = None) -> Path:
    """The OpenVSP folder (the folder of vsp.exe)."""
    for cand in (given, os.environ.get("OPENVSP_DIR")):
        if cand:
            p = Path(cand)
            if (p / "python" / "openvsp" / "openvsp").is_dir():
                return p
            raise OpenVSPError(f"{p} is not an OpenVSP folder (no python/openvsp/openvsp in it)")
    home = Path.home()
    roots = [Path(os.environ.get("ProgramFiles", r"C:\Program Files")), home / "Downloads", home / "Desktop", home,
             home / "Applications", Path("/Applications"), Path("/opt")]
    found = []
    for r in roots:
        if r.is_dir():
            found += [p for p in r.glob("OpenVSP*") if (p / "python" / "openvsp" / "openvsp").is_dir()]
            found += [p for p in r.glob("OpenVSP*/OpenVSP*") if (p / "python" / "openvsp" / "openvsp").is_dir()]
    if not found:
        raise OpenVSPError("no OpenVSP folder found. Download OpenVSP from openvsp.org, unzip it, and give the folder "
                           "with --vsp <folder>")
    return sorted(found, key=_version_key)[-1]


def needed_python(vsp_dir: Path) -> str:
    """The Python version of the OpenVSP module, for example "3.13"."""
    mod = vsp_dir / "python" / "openvsp" / "openvsp"
    libs = list(mod.glob("_vsp.*.pyd")) + list(mod.glob("_vsp.pyd")) + list(mod.glob("_vsp*.so"))
    if not libs:
        raise OpenVSPError(f"{mod} holds no _vsp module")
    lib = libs[0]
    m = re.search(r"cpython-3(\d+)", lib.name) or re.search(rb"python3(\d+)\.dll", lib.read_bytes())
    if not m:
        m = re.search(rb"libpython3\.(\d+)", lib.read_bytes())
    if not m:
        raise OpenVSPError(f"the Python version of {lib.name} is not known")
    minor = m.group(1).decode() if isinstance(m.group(1), bytes) else m.group(1)
    return f"3.{minor}"


def _uv() -> List[str]:
    try:
        subprocess.run([sys.executable, "-m", "uv", "--version"], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "uv"], check=True)
    return [sys.executable, "-m", "uv"]


def setup(vsp: Optional[str] = None, expected: Optional[str] = None, log=lambda m: print(m, flush=True)) -> Dict[str, str]:
    """Make OpenVSP/.venv for the OpenVSP folder. Returns {folder, python, version}."""
    vsp_dir = find_openvsp(vsp)
    py = needed_python(vsp_dir)
    log(f"OpenVSP folder: {vsp_dir}")
    log(f"The OpenVSP module needs Python {py}")
    uv = _uv()
    subprocess.run(uv + ["venv", "--clear", "--python", py, str(VENV)], check=True)
    vpy = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(uv + ["pip", "install", "--quiet", "--python", str(vpy), *WORKER_NEEDS], check=True)
    site = subprocess.run([str(vpy), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                          check=True, capture_output=True, text=True).stdout.strip()
    pth = Path(site) / "openvsp.pth"
    pth.write_text("".join(f"{vsp_dir / 'python' / p}\n" for p in PACKAGES), encoding="utf-8")
    version = run({"job": "version"})["version"]
    log(f"Check: {version} loads in {vpy}")
    if expected and expected not in version:
        log(f"WARNING: the spoke settings name OpenVSP {expected}. The tests ran with that version.")
    return {"folder": str(vsp_dir), "python": str(vpy), "version": version}


def describe() -> str:
    """One line for `aeroplan spokes`: the OpenVSP version, or the setup command."""
    if not available():
        return "OpenVSP Python not set up: run `python -m aeroplan setup OpenVSP`"
    try:
        return run({"job": "version"}, timeout=60)["version"]
    except OpenVSPError as e:
        return f"OpenVSP Python does not work: {e}"
