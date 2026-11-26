# AeroPlan documents

The documents follow the Diataxis split.

| Kind | Use it to | Files |
|---|---|---|
| Tutorials | learn by doing | [First day](tutorials/first-day.md) |
| Reference | look up a fact | [Aircraft summaries](reference/aircraft/) |
| Reports | read a study and its method | [Quadplane modelling report](reports/quadplane_model/README.md), [Currawong AeroSandbox methods](reports/currawong_aero_methods/README.md), [Redback twin](reports/redback_twin/README.md), [Rosella propulsion selection](reports/rosella_propulsion/README.md) |
| Decisions | see what was decided | [Decision records](decisions/README.md) |

## By aircraft

| Aircraft | Summary | Reports and studies | Notebook | Model and settings |
|---|---|---|---|---|
| Currawong (fixed wing) | [summary](reference/aircraft/currawong.md) | [AeroSandbox methods report](reports/currawong_aero_methods/README.md) | deprecated notebooks (git history, commit 3851d80) | [settings](../aeroplan/aerosandbox/settings/currawong.yaml), `aircraft/currawong/` |
| Redback (multirotor) | [summary](reference/aircraft/redback.md) | [Redback twin report](reports/redback_twin/README.md) | none | [settings](../aeroplan/aerosandbox/settings/redback.yaml), `aircraft/redback/` |
| Rosella (VTOL quadplane) | [summary](reference/aircraft/rosella.md) | [Quadplane modelling report](reports/quadplane_model/README.md) | [rosella_sizing.ipynb](../aeroplan/aerosandbox/notebooks/rosella_sizing.ipynb) | [rosella.json](../aeroplan/aerosandbox/settings/rosella.json), `aircraft/rosella/` |
| F-16 | [summary](reference/aircraft/f16.md) | none | none | `aircraft/f16/` |

A notebook is committed with its outputs, so GitHub shows it. Do the install of [First day](tutorials/first-day.md) to run it and to use its window ([ADR 24](decisions/0024-aircraft-models-in-code.md), [ADR 30](decisions/0030-one-python-for-aeroplan-and-aerosandbox.md)).
