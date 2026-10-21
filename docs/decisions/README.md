# Decisions

One short file for each decision (Nygard format). A new decision gets the next number. A changed decision gets a new file that names the old one.

| ADR | Date | Decision |
|---|---|---|
| [0001](0001-ssot-inside-aeroplan.md) | 2026-10-08 | SSOT lives inside AeroPlan |
| [0002](0002-source-tree-in-git-package-in-dist.md) | 2026-10-10 | Git holds the source tree, dist holds the package |
| [0003](0003-only-adh-data-in-the-source-tree.md) | 2026-10-10 | Only ADH data goes into the source tree |
| [0004](0004-asset-register-and-packing-profiles.md) | 2026-10-10 | Asset register, storage tiers and packing profiles |
| [0005](0005-gltf-for-the-3d-view.md) | 2026-10-10 | glTF for the 3D view, no STL output |
| [0006](0006-one-folder-per-tool.md) | 2026-10-10 | One spoke folder for each tool |
| [0007](0007-how-an-aircraft-starts.md) | 2026-10-10 | How a new aircraft starts |
| [0008](0008-manual-changes-only-through-a-spoke.md) | 2026-10-10 | Manual changes come in through a spoke, by script only |
| [0009](0009-changed-file-wins.md) | 2026-10-08 | The changed file wins |
| [0010](0010-aerosandbox-in-its-own-python.md) | 2026-10-14 | AeroSandbox runs in its own Python |
| [0011](0011-openvsp-in-its-own-python.md) | 2026-10-10 | OpenVSP runs in its own Python |
| [0012](0012-specsheet-owns-the-mass-model.md) | 2026-10-15 | The Master Specification Sheet owns the mass model |
| [0013](0013-mrp-stays-the-t7-cog.md) | 2026-10-15 | The MRP stays the CoG of the flow5 T7 analysis |
| [0015](0015-wing-root-leading-edge-at-x-zero.md) | 2026-10-15 | The wing root leading edge sits at x = 0.000 |
| [0016](0016-fuselage-body-fit-from-the-skin.md) | 2026-10-15 | The fuselage body is a fit of the Creo skin |
| [0017](0017-flight-files-as-datasets.md) | 2026-10-16 | Flight files are datasets of the autopilot node |
| [0018](0018-multirotor-path.md) | 2026-10-16 | Multirotor path |
| [0019](0019-web-editor-shelved.md) | 2026-10-10 | The web editor and viewer are shelved |
| [0020](0020-repository-layout-a.md) | 2026-10-17 | Repository layout A |
| [0021](0021-merge-ardupilot-and-missionplanner.md) | 2026-10-17 | One ArduPilot spoke for flight events and flight files |
| [0022](0022-quadplane-path.md) | 2026-10-17 | Quadplane path |
| [0023](0023-design-frame-origin-at-the-wing-le.md) | 2026-10-17 | The design frame starts at the root leading edge of the main wing |
| [0024](0024-aircraft-models-in-code.md) | 2026-10-21 | Aircraft models are made in code, saved in one JSON file, and shown in evaluated notebooks |
