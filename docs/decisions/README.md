# Decisions

One short file for each decision (Nygard format, ADR 0031). A new decision gets the next number. A changed decision gets a
new file that names the old one in its front matter (`supersedes`, `amends`).

Each file starts with YAML front matter (`id`, `title`, `date`, `status`, `kind`, the links, `applies_to`). An accepted
`architecture` or `data` decision ends with a `## Rules` section: one rule for each line, with its kind (`APnnn` for a
check in `tests/architecture/`, `check`, `ci` or `process`).

- Print the rules for a file: `python -m aeroplan rules <path>`.
- Update the table below after a change: `python -m aeroplan rules --index --write`. A check compares the table with the
  front matter.

<!-- index:start -->
| ADR | Date | Status | Kind | Decision |
|---|---|---|---|---|
| [0001](0001-ssot-inside-aeroplan.md) | 2026-10-08 | accepted | data | SSOT lives inside AeroPlan |
| [0002](0002-source-tree-in-git-package-in-dist.md) | 2026-10-10 | accepted (amended by 0026) | architecture | Git holds the source tree, dist holds the package |
| [0003](0003-only-adh-data-in-the-source-tree.md) | 2026-10-10 | accepted | data | Only small, sourced data goes into the source tree |
| [0004](0004-asset-register-and-packing-profiles.md) | 2026-10-10 | accepted | data | Asset register, storage tiers and packing profiles |
| [0005](0005-gltf-for-the-3d-view.md) | 2026-10-10 | accepted | architecture | glTF for the 3D view, no STL output |
| [0006](0006-one-folder-per-tool.md) | 2026-10-10 | superseded (superseded by 0025) | architecture | One spoke folder for each tool |
| [0007](0007-how-an-aircraft-starts.md) | 2026-10-10 | superseded (superseded by 0037) | process | How a new aircraft starts |
| [0008](0008-manual-changes-only-through-a-spoke.md) | 2026-10-10 | accepted | data | Manual changes come in through a spoke, by script only |
| [0009](0009-changed-file-wins.md) | 2026-10-08 | accepted | data | The changed file wins |
| [0010](0010-aerosandbox-in-its-own-python.md) | 2026-10-14 | superseded (superseded by 0030) | architecture | AeroSandbox runs in its own Python |
| [0011](0011-openvsp-in-its-own-python.md) | 2026-10-10 | accepted | architecture | OpenVSP runs in its own Python |
| [0012](0012-specsheet-owns-the-mass-model.md) | 2026-10-15 | accepted | data | The Master Specification Sheet owns the mass model |
| [0013](0013-mrp-stays-the-t7-cog.md) | 2026-10-15 | superseded (superseded by 0033) | data | The MRP stays the CoG of the flow5 T7 analysis |
| [0014](0014-notebooks-without-outputs.md) | 2026-10-14 | superseded (superseded by 0024) | process | Notebooks without outputs |
| [0015](0015-wing-root-leading-edge-at-x-zero.md) | 2026-10-15 | superseded (superseded by 0023) | data | The wing root leading edge sits at x = 0.000 |
| [0016](0016-fuselage-body-fit-from-the-skin.md) | 2026-10-15 | accepted | data | The fuselage body is a fit of the Creo skin |
| [0017](0017-flight-files-as-datasets.md) | 2026-10-16 | accepted | data | Flight files are datasets of the autopilot node |
| [0018](0018-multirotor-path.md) | 2026-10-16 | accepted (amended by 0032, 0036) | data | Multirotor path |
| [0019](0019-web-editor-shelved.md) | 2026-10-10 | accepted | process | The web editor and viewer are shelved |
| [0020](0020-repository-layout-a.md) | 2026-10-17 | superseded (superseded by 0025) | architecture | Repository layout A |
| [0021](0021-merge-ardupilot-and-missionplanner.md) | 2026-10-17 | accepted | architecture | One ArduPilot spoke for flight events and flight files |
| [0022](0022-quadplane-path.md) | 2026-10-17 | accepted | data | Quadplane path |
| [0023](0023-design-frame-origin-at-the-wing-le.md) | 2026-10-17 | accepted (supersedes 0015; amended by 0029) | data | The design frame starts at the root leading edge of the main wing |
| [0024](0024-aircraft-models-in-code.md) | 2026-10-21 | accepted (supersedes 0014; amended by 0028, 0030) | architecture | Aircraft models are made in code, saved in one JSON file, and shown in evaluated notebooks |
| [0025](0025-one-package-with-tool-subpackages.md) | 2026-10-30 | accepted (supersedes 0006, 0020; amended by 0030) | architecture | One package, with a subpackage for each tool |
| [0026](0026-flat-aircraft-folder.md) | 2026-10-30 | accepted (amends 0002) | data | A flat aircraft folder |
| [0027](0027-store-each-fact-once.md) | 2026-10-30 | accepted (amended by 0032) | data | Store each fact once: ADH fields first |
| [0028](0028-aerosandbox-stays-in-aeroplan.md) | 2026-10-30 | accepted (amends 0024) | architecture | The AeroSandbox model stays in AeroPlan, with one seam |
| [0029](0029-design-frame-is-frd.md) | 2026-10-21 | accepted (amends 0023) | data | The design frame is FRD |
| [0030](0030-one-python-for-aeroplan-and-aerosandbox.md) | 2026-11-26 | accepted (supersedes 0010; amends 0024, 0025) | architecture | One Python for AeroPlan and AeroSandbox |
| [0031](0031-rules-are-code.md) | 2026-11-26 | accepted | architecture | Rules are code |
| [0032](0032-units-angles-and-sign-conventions.md) | 2026-11-26 | accepted (amends 0018, 0027) | data | Units, angles and sign conventions |
| [0033](0033-the-mrp.md) | 2026-11-26 | accepted (supersedes 0013) | data | The MRP |
| [0034](0034-vendored-adh-and-patches.md) | 2026-11-26 | accepted | architecture | Vendored ADH and patches |
| [0035](0035-test-data.md) | 2026-11-26 | accepted | data | Test data |
| [0036](0036-aerolink-owns-the-contract.md) | 2026-11-26 | accepted (amends 0018) | architecture | Aerolink owns the contract and keeps a hand copy of the reader |
| [0037](0037-how-an-aircraft-starts-by-kind.md) | 2026-11-26 | accepted (supersedes 0007) | process | How an aircraft starts, by kind |
<!-- index:end -->
