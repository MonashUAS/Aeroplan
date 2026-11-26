# First day (about 15 minutes)

You need Python 3.12 or newer, git and a network connection. One Python, the repository `.venv`, runs AeroPlan, the
AeroSandbox sizing models and the notebooks ([ADR 30](../decisions/0030-one-python-for-aeroplan-and-aerosandbox.md)).

Proptimiser, the propeller code of the sizing, is in a **private** GitHub repository. Ask for read access to
`MonashUAS/Propcalc-2_prop-er_faster_stronger`. Then sign git in once, for example with `gh auth login`.

1. Clone the repository:
   ```
   git clone <AeroPlan repository URL>
   cd Aeroplan
   ```
2. Make the `.venv` and activate it:
   ```
   python -m venv .venv
   source .venv/bin/activate          # Linux and macOS
   .venv\Scripts\activate             # Windows
   ```
3. Install AeroPlan with all extras (about 5 minutes):
   ```
   pip install -e ".[all]"
   ```
   With no access to Proptimiser, run `pip install -e ".[sizing,dev]"`. All works but the propeller models and the
   sizing notebook.
4. Check the computer: `python -m aeroplan doctor`. Each `FAIL` line gives its fix. A `--` line is an optional tool
   (Proptimiser, OpenVSP, flow5, Graphviz).
5. Check the aircraft: `python -m aeroplan check currawong`. The last line says "All checks pass."
6. Run the tests: `python -m pytest`.
7. Open `aeroplan/aerosandbox/notebooks/rosella_sizing.ipynb` in VS Code or Jupyter. Select the `.venv` Python as the
   kernel. Run all cells. The notebook needs the 4 blade files of
   [Size a quadplane](../howto/size-a-quadplane.md#before-you-start).

The first `import aeroplan` builds the patched ADH package in `standards/adh/build/` (git ignores it).

Next: read the [quadplane modelling report](../reports/quadplane_model/README.md), or a tool README in
`aeroplan/<tool>/README.md`. Before you change code, read `CLAUDE.md`.

## OpenVSP (only for the OpenVSP spoke)

OpenVSP needs its own Python, because its compiled module fixes the Python version ([ADR 11](../decisions/0011-openvsp-in-its-own-python.md)).

1. Download OpenVSP 3.54 and unpack it.
2. In the activated `.venv`, run `python -m aeroplan setup OpenVSP`. If the search does not find OpenVSP, add
   `--vsp <the OpenVSP folder>`.
