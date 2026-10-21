# AeroPlan documents

The documents follow the Diataxis split.

| Kind | Use it to | Files |
|---|---|---|
| Tutorials | learn by doing | [First day](tutorials/first-day.md) |
| How-to guides | do one job | [Change the aircraft with your tool](howto/change-the-aircraft.md), [Fly it in Aerolink](howto/fly-in-aerolink.md), [Add a multirotor](howto/add-a-multirotor.md), [Size a quadplane](howto/size-a-quadplane.md) |
| Reference | look up a fact | [Commands](reference/commands.md), [Folders](reference/folders.md), [Source tree](reference/source-tree.md), [Package format](reference/package-format.md), [Multirotor contract](reference/multirotor_contract.md), [Aircraft summaries](reference/aircraft/) |
| Explanation | understand why | [Architecture](explanation/architecture.md) |
| Decisions | see what was decided | [Decision records](decisions/README.md) |

## By aircraft

| Aircraft | Summary | Reports and studies | Notebook | Model and settings |
|---|---|---|---|---|
| Currawong (fixed wing) | [summary](reference/aircraft/currawong.md) | [AeroSandbox methods report](../tools/aerosandbox/docs/methods_report.md) | [deprecated notebooks](../tools/aerosandbox/notebooks/deprecated/README.md) | [settings](../tools/aerosandbox/settings/currawong.yaml), `aircraft/currawong/` |
| Redback (multirotor) | [summary](reference/aircraft/redback.md) | [Redback twin report](reports/redback_twin/README.md) | none | [settings](../tools/aerosandbox/settings/redback.yaml), `aircraft/redback/` |
| Rosella (VTOL quadplane) | [summary](reference/aircraft/rosella.md) | [Sizing method report](reports/rosella_sizing/README.md), [COTS candidates](reports/rosella_sizing/cots_candidates.md) | [rosella_sizing.ipynb](../tools/aerosandbox/notebooks/rosella_sizing.ipynb) | [rosella.json](../tools/aerosandbox/settings/rosella.json), `aircraft/rosella/` |
| F-16 | [summary](reference/aircraft/f16.md) | none | none | `aircraft/f16/` |

A notebook is committed with its outputs, so GitHub shows it. Clone the repository and run `python -m aeroplan setup AeroSandbox` to run it and to use its window ([ADR 24](decisions/0024-aircraft-models-in-code.md)).
