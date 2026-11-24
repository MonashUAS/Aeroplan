# Standards

The standards that AeroPlan builds on. Nothing in this folder is aircraft data.

| Folder | What it holds |
|---|---|
| `adh/upstream/` | The Aircraft Data Hierarchy (ADH) of Boeing, pristine. The commit is in `adh/upstream_commit.txt` |
| `adh/patches/` | The AeroPlan patch series, applied in name order |
| `adh/build_adh.py` | Copies `upstream/src` to `adh/build/src` and applies the patches (git ignores `adh/build/`). `import aeroplan` runs it when the build is missing |
| `adh/EXTENSIONS.md` | The extension register: each `muas` key, what ADH has, and why MUAS adds the key |
| `schema/v<version>/` | The JSON Schema of the MUAS extension types, one folder for each version (`aeroplan schema --out standards/schema`) |
| `spec/dave-ml/2p0/`, `spec/mathml/2p0/` | The DAVE-ML 2.0 DTD and the MathML 2.0 DTD, so the DTD check needs no network |

## The ADH

- Source: [Boeing/aircraft-data-hierarchy](https://github.com/Boeing/aircraft-data-hierarchy), commit `96179ca`
  (2025-10-17). On 2026-10-29 this commit was the head of `main`. The docs site is
  <https://boeing.github.io/aircraft-data-hierarchy/> (an API reference only).
- The design document: R. M. Engelbeck et al., "Model-Based Systems Analysis and Engineering: Aircraft Data Hierarchy",
  NASA/CR-20250007045, NASA Glenn Research Center, 2025-08-01 (<https://ntrs.nasa.gov/citations/20250007045>). No AIAA paper
  or later report exists.
- ADH is a prototype. It has no mass-properties class and no inertia. Its units are free text, and the report lists unit
  conversion as "planned". The extension register shows where MUAS fills these gaps.

### What the report asks for, and where AeroPlan does it

| Practice in NASA/CR-20250007045 | AeroPlan |
|---|---|
| JSON for storage. XML for exchange and archive, YAML for configuration (section 12.4) | The source tree and the package hold JSON. The tool settings are YAML. DAVE-ML is XML |
| A WBS from MIL-STD-881F and SAWE RP A-8 | The WBS comes from upstream only. AeroPlan never adds a WBS number |
| DAVE-ML (ANSI/AIAA S-119) for simulation models | The aero models are ADH `DAVEfunc` documents, checked against the DTD and their checkData |
| Extend by subclass of the Pydantic classes. Validate the data | Each MUAS model is Pydantic with `extra="forbid"`, under the single key `muas`. `adh_doc.validate_document` checks every node against the upstream `Component` |
| A log of design decisions (the digital thread) | `docs/decisions/` (one Nygard ADR for each decision). The build record and the asset register link each value to its source file |
| Units conversion (planned in ADH) | pint, in `aeroplan/muas/units.py`. Every quantity is stored in SI |
| Code-quality tools | `ruff check` in CI (`pyproject.toml` has the rules) |

## Patch policy

- `adh/upstream/` stays pristine. Never edit it.
- A fix goes in a new file `adh/patches/NNNN-<name>.patch` (a `git apply` patch against `upstream/`).
- A patch must not break an upstream ADH test. CI runs them on the patched copy:
  `PYTHONPATH=standards/adh/build/src pytest standards/adh/upstream/tests`.
- To move to a new upstream commit: copy the new upstream into `adh/upstream/`, write its commit into `upstream_commit.txt`,
  run `python standards/adh/build_adh.py`, and run the upstream tests and the AeroPlan tests.

| Patch | What it changes | Why |
|---|---|---|
| 0001 | The schema example of `AsymmetricControl` holds the enum value, not the enum object | The JSON Schema export cannot write an enum object |
| 0002 | The point count check of a spline runs after the degree is known | Upstream always checked for degree 3, so it refused a polyline of 2 points (degree 1) |
| 0003 | `Reference.date` takes DAVE-ML date text | DAVE-ML 2.0 declares the date as text (`1992`, `2013-08-00`) |
| 0004 | The descriptions of `ReferenceData` say m^2 and m, not ft^2 and ft | AeroPlan stores SI (ADR 27). The values and the aliases do not change |

## Known faults of upstream

- `behavior.py` has its own `CommonBaseModel` and `Metadata`, which differ from the ones in `common_base_model.py`. Check which
  one a class imports.
- `ReferenceData` and the other parameter classes take their aliases only (`Sref`, not `reference_area`). With
  `extra="allow"`, a field name passes the validation and the value is lost. `adh_doc.validate_document` refuses it for
  `reference_data`.
- The parameter classes of `airframe_parameters.py` are DATCOM inputs. The upstream file says that they need a refactor.
  `hingeline_chord_ratio` has no clear meaning, so AeroPlan does not use it.

## Other sources to watch

- [alwinw/aircraft-data-hierarchy](https://github.com/alwinw/aircraft-data-hierarchy): a community fork (v0.3.0, 2026-03-18).
  It adds pint units, DAVE-ML document classes, a `tabular` module and a WBS generated from MIL-STD-881F. Its changelog has
  no mass or inertia. It overlaps `aeroplan/muas/units.py` and `aeroplan/daveml_adh.py`. AeroPlan stays on the Boeing
  release (decision of 2026-10-29).
- CPACS (DLR): `massDescription` (mass, location, `massInertia`) is the model for the MUAS mass fields.
