# AeroPlan

AeroPlan is the single source of truth (SSOT) for MUAS aircraft data. It is built on the NASA/Boeing
Aircraft Data Hierarchy (ADH). It checks the data, composes it, and exports an immutable aircraft
package. Aerolink reads the package and runs the simulation.

Start here:

- Engineer who integrates Currawong data: [](currawong/index.md), then [](currawong/missing_data.md).
- Engineer who adds a new tool or aircraft: [](overview.md), then [](api/index.md).
- Reviewer: [](design/decisions.md).

```{toctree}
:maxdepth: 2
:caption: Start

overview
```

```{toctree}
:maxdepth: 2
:caption: Currawong integration

currawong/index
currawong/data_map
currawong/procedure
currawong/missing_data
```

```{toctree}
:maxdepth: 2
:caption: Design

design/decisions
design/exchange
design/aero_methods
design/uncertainty
design/interfaces
design/references
aerolink
brief
```

```{toctree}
:maxdepth: 2
:caption: Reference

api/index
```
