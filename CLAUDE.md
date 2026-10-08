# AeroPlan

AeroPlan is the ADH-based single source of truth (SSOT) for aircraft data. It validates, assembles, composes and exports an immutable aircraft export package. Aerolink consumes the package.

## Context files

- `docs/source/design/decisions.md`: user answers, MRP evaluation, uncertainty design, test method, roadmap status.
- `docs/source/design/interfaces.md`: interface to Proptimiser, Propalyser and Aerolink.
- `docs/source/design/references.md`: sources and the assumptions register.
- `docs/ADH SSOT implementation plan.md`: the implementation brief.
- `docs/source/currawong/`: Currawong integration guide, data map, procedure and the **missing data register** (M-01 to M-21).
- Docs are Sphinx (`cd docs; sphinx-build -M html ./source ./_build`). Install with `pip install .[test,docs]`.

## Rules

- ADH decides the design. Add a MUAS extension only where ADH is silent or broken. Put it under the `muas` key, with `extra="forbid"` (D03).
- Never invent a WBS number. `adh_wbs_numbers()` reads them from upstream.
- `packages/muas_adh/upstream/` stays pristine. Fixes go in `packages/muas_adh/patches/`. Run `python scripts/build_adh.py` before the tests.
- Store SI. Angles are radians. Every quantity carries units (D04).
- MRP is the nominal-configuration CG, a fixed point in the design frame.
- Every uncertainty has a status, a scope and a basis (NASA-STD-7009B).
- Hand config is YAML. Machine files are canonical JSON.
- Copy data by hand between repos. No symlinks. No hard-coded cross-repo paths. AeroPlan imports no sibling repo.
- Proptimiser reaches AeroPlan only through Propalyser. Propulsion reaches Aerolink only through the package.
- Currawong data lives in the `muas-fleet-data` repo (sibling folder). Read `docs/source/currawong/procedure.md` before you change it. Never write a value that no source gives: use `unknown`, `placeholder` or `unverified` and add the gap to the missing data register.
- Never type an unsourced number. Use `<placeholder>`, or add a row to `docs/source/design/references.md`.
- CI is allowed here (not in Aerolink). Workflows mirror the ADH workflows. Do not add a step ADH has no equivalent for without a reason in `docs/source/design/decisions.md`.
- DAVE-ML must pass the vendored 2.0 DTD (`spec/dave-ml/2p0`). Use the `/DTDs/2p0/` file, not the 1.4 file.
- Do not integrate team data until the Phase 1 exit in the brief.
- Write prose in ASD-STE100 style.
- Legacy repos (Proptimiser, Propalyser, Aerolink) are not edited from here.

## Commands

```
python scripts/build_adh.py                 # build patched ADH
set PYTHONPATH=src;packages/muas_adh/build/src
python -m pytest                            # T0 tests (pyproject sets the paths)
python -m aeroplan.cli schema --out schema  # re-export JSON Schema after a model change
python -m aeroplan.cli package synthetic <dir>   # also: verify, pack, unpack
python -m aeroplan.cli integrate currawong <fleet-data>/aircraft/currawong   # path is an argument
python -m aeroplan.cli validate <node.json>
python -m aeroplan.cli compile-config <in.yaml> <out.json>
```

## Status

P0 mostly done. Currawong integration started 2026-10-08: raw data copied, 6 flow5 datasets and 1 Ct/Cp dataset ingested, export package blocked by M-01, M-02, M-07, M-10. Open: first CI run on GitHub, geometry nodes, rate derivatives. Aero sizing (AeroSandbox) is out of scope until later.
