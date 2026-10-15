"""Run AeroSandbox jobs in the AeroSandbox Python, and make that Python (`aeroplan setup AeroSandbox`).

AeroPlan runs on its own Python and does not import aerosandbox or proptimiser. The spoke sends each job to
AeroSandbox/asb_worker.py in a separate Python: AeroSandbox/.venv (git ignores it). The job goes in as a JSON file and
the result comes back as a JSON file, the same way as the OpenVSP worker.

`setup()` makes the venv with uv. It installs the packages in WORKER_NEEDS, JupyterLab for the notebooks
(AeroSandbox/notebooks), AeroPlan itself (editable, so a notebook reads the source tree live) and Proptimiser.
Proptimiser comes from a local checkout (`--proptimiser <folder>`) or from the git URL and revision in the spoke
settings. It is optional: without it the airframe jobs and the notebooks work, and the propeller jobs say what is
missing. The worker needs only the CasADi path of Proptimiser, so the install has no JAX.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
VENV = HERE / ".venv"
WORKER = HERE / "asb_worker.py"
PYTHON = "3.12"
WORKER_NEEDS = ("aerosandbox==4.2.9", "matplotlib", "plotly", "h5py", "PyYAML")
NOTEBOOK_NEEDS = ("jupyterlab", "ipykernel", "ipywidgets", "nbformat", "pandas")
KERNEL = "aeroplan-asb"


class AeroSandboxError(RuntimeError):
    pass


def python() -> Path:
    """The AeroSandbox Python: AEROSANDBOX_PYTHON, else AeroSandbox/.venv."""
    env = os.environ.get("AEROSANDBOX_PYTHON")
    if env:
        return Path(env)
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def available() -> bool:
    return python().is_file() and WORKER.is_file()


def run(job: Dict[str, Any], timeout: float = 1800) -> Dict[str, Any]:
    """Run one worker job. Raises AeroSandboxError with the worker error text."""
    if not available():
        raise AeroSandboxError("the AeroSandbox Python is not set up: run `python -m aeroplan setup AeroSandbox`")
    with tempfile.TemporaryDirectory(prefix="aeroplan_asb_") as tmp:
        jf, rf = Path(tmp) / "job.json", Path(tmp) / "result.json"
        jf.write_text(json.dumps(job), encoding="utf-8")
        p = subprocess.run([str(python()), "-I", str(WORKER), str(jf), str(rf)], capture_output=True, text=True,
                           timeout=timeout, cwd=tmp)
        if not rf.is_file():
            raise AeroSandboxError(f"the AeroSandbox worker stopped (exit {p.returncode}): {(p.stderr or p.stdout)[-2000:]}")
        res = json.loads(rf.read_text(encoding="utf-8"))
    if not res.get("ok"):
        raise AeroSandboxError(f"AeroSandbox job {job.get('job')}: {res.get('error')}\n{res.get('trace', '')}")
    return res


def _uv() -> List[str]:
    """The uv command: the `uv` program on the PATH, else the uv module of this Python (installed when it is missing)."""
    found = shutil.which("uv")
    if found:
        return [found]
    try:
        subprocess.run([sys.executable, "-m", "uv", "--version"], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "uv"], check=True)
    return [sys.executable, "-m", "uv"]


def setup(proptimiser: Optional[str] = None, git: Optional[Dict[str, str]] = None,
          log=lambda m: print(m, flush=True)) -> Dict[str, str]:
    """Make AeroSandbox/.venv. `proptimiser` is a checkout folder. Without it, `git` ({url, rev}) names the source.
    A Proptimiser that cannot be installed is a warning: the airframe jobs and the notebooks still work.
    Returns {folder, python, version}."""
    src = None
    if proptimiser:
        src = str(Path(proptimiser).resolve())
        if not (Path(src) / "pyproject.toml").is_file():
            raise AeroSandboxError(f"{src} is not a Proptimiser folder (no pyproject.toml)")
    elif git and git.get("url") and git.get("rev"):
        src = f"git+{git['url']}@{git['rev']}"
    uv = _uv()
    log(f"Make {VENV} with Python {PYTHON}")
    subprocess.run(uv + ["venv", "--clear", "--python", PYTHON, str(VENV)], check=True)
    vpy = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(uv + ["pip", "install", "--quiet", "--python", str(vpy), *WORKER_NEEDS, *NOTEBOOK_NEEDS], check=True)
    log(f"Install AeroPlan from {REPO} (editable, for the notebooks)")
    subprocess.run(uv + ["pip", "install", "--quiet", "--python", str(vpy), "-e", str(REPO)], check=True)
    subprocess.run([str(vpy), "-m", "ipykernel", "install", "--sys-prefix", "--name", KERNEL,
                    "--display-name", "AeroPlan AeroSandbox"], check=True, capture_output=True)
    if src is None:
        log("WARNING: no Proptimiser source (--proptimiser <folder>, or url and rev in the settings): "
            "the propeller jobs (cruise_trim, static_check) do not work")
    else:
        log(f"Install Proptimiser from {src} (no JAX)")
        r = subprocess.run(uv + ["pip", "install", "--quiet", "--python", str(vpy), src], capture_output=True, text=True)
        if r.returncode:
            log(f"WARNING: Proptimiser did not install, the propeller jobs do not work:\n{r.stderr[-800:]}")
    version = run({"job": "version"}, timeout=300)["version"]
    log(f"Check: {version}")
    return {"folder": str(VENV), "python": str(vpy), "version": version}


def describe() -> str:
    """One line for `aeroplan spokes`: the worker versions, or the setup command."""
    if not available():
        return "AeroSandbox Python not set up: run `python -m aeroplan setup AeroSandbox`"
    try:
        return run({"job": "version"}, timeout=120)["version"]
    except AeroSandboxError as e:
        return f"AeroSandbox Python does not work: {e}"
