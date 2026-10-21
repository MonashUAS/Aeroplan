# Deprecated notebooks

These notebooks are old. They run only on commit `3851d80`, because they import `lab.py`, `rosella.py` and `spec.py`, which are removed ([ADR 24](../../../../docs/decisions/0024-aircraft-models-in-code.md)). They stay for their text and their saved outputs.

| Notebook | What it showed | Replaced by |
|---|---|---|
| `01_geometry_and_mass.ipynb` | Three-view, 3D view with the point masses, mass by subassembly, inertia against flow5 T7, static margin | no replacement yet |
| `02_flow5_vs_aerosandbox.ipynb` | The gap ladder between flow5 and AeroSandbox | no replacement yet |
| `03_gap_study.ipynb` | The causes of the gap (VLM, LiftingLine, AeroBuildup), downwash at the tail, neutral point build-up. The numbers of `../../docs/methods_report.md` | no replacement yet |
| `04_rosella_sizing.ipynb` | The Rosella sizing results and the manual parts window | [../rosella_sizing.ipynb](../rosella_sizing.ipynb) |

A new study makes a new notebook with the classes of `component.py`, `model.py` and `optimise.py`. See [Size a quadplane](../../../../docs/howto/size-a-quadplane.md).
