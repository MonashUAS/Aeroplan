# Exchange contracts

Three files cross a repository boundary. AeroPlan owns all three layouts. Each tool keeps a hand copy of the part
it writes or reads, in its own `docs/`. A copy names this page as its source and the contract version.

Rules for all three:

- One `.h5` file (or, for C, a folder with an optional `.h5` wrapper). No other cross-repo file.
- SI units. Every dataset carries an attribute `units` (`nd` for a dimensionless value). An angle column says `deg` or `rad`.
- Unit spelling in an `.h5` attribute (`units` on a dataset, an uncertainty item or a result): the pint spelling,
  for example `m/s`, `kg/m^3`, `N*m`, `rad/s`, `rpm`, `ohm`. A reader parses it with pint and refuses a spelling that
  pint does not know. Unit spelling inside a DAVE-ML file: the S-119 spelling (`m_s`, `kg_m3`, `N_m`), as the standard asks.
  Do not mix the two. The round trip of 2026-10-08 found `m/s` against `m_s` and stopped on it.
- Every uncertainty item has the fields of the AeroPlan uncertainty schema ([](uncertainty.md)): `status`, `scope`,
  `basis`, and, when quantitative, `method`, `distribution`, `effect`, and `num_sigmas` or `coverage`.
- `author` is a person, never a program name.
- A writer refuses to write from a dirty git tree. There is no override that hides it.
- A reader refuses a file with an unknown `schema` or `schema_version`. There is no migration and no legacy reader.
- No value is invented. A field that the writer does not know is absent, and the matching reader reports it.
- `generator` is a group `/generator` with attributes `name`, `commit`, `dirty`. Each uncertainty item is a group
  `/uncertainty/<item>` whose attributes are the uncertainty fields. Each scalar result is a group `/results/<name>`.
- Strings are UTF-8 variable-length. Lists of strings (`/warnings`) are 1-D string datasets.

```
Proptimiser --(A: prop-performance .h5)--> Propalyser --(B: propulsion-system .h5)--> AeroPlan --(C: package)--> Aerolink
```

## A. `prop-performance` v1 (Proptimiser to Propalyser)

Root attributes: `schema = "prop-performance"`, `schema_version = 1`, `prop_id`, `design_sha256` (hash of the design
YAML and the solved state JSON, canonical form), `created_utc`, `author`, `generator` (`name`, `commit`, `dirty = false`),
`placeholder` (bool).

| Path | Content | Units |
|---|---|---|
| `/geometry` attrs | `diameter_m`, `blades`, `hub_radius_m`, `frame` (blade frame text), `twist_sign`, `rotation` (`cw_from_behind`, `ccw_from_behind` or absent) | m |
| `/geometry/stations` | table: `r_m`, `chord_m`, `twist_deg` | as named |
| `/performance` | table, one row for each operating point: `J`, `rpm`, `V_mps`, `CT`, `CP`, `CQ`, `eta`, `tip_mach`, `reynolds_75`, `converged` | `units` attr on each column |
| `/performance` attrs | `rho_kgpm3`, `nu_m2ps`, `J_range`, `rpm_values` | |
| `/uncertainty/<item>` | one group for each item (for example `CT`, `CP`): the uncertainty fields. Optional columns `CT_sigma`, `CP_sigma` in `/performance` | |

Definitions: `J = V/(n D)`, `CT = T/(rho n^2 D^4)`, `CP = P/(rho n^3 D^5)`, `CQ = Q/(rho n^2 D^5)`, `n` in rev/s.
Not in the file: motor values, off-axis inflow (`V_yz`), installation (hub position, thrust axis). AeroPlan holds the installation.

## B. `propulsion-system` v2 (Propalyser to AeroPlan)

Root attributes: `schema = "propulsion-system"`, `schema_version = 2`, `system_id`, `basis` (`stand`, `vendor`, `mixed`),
`placeholder`, `created_utc`, `author`, `data_sha256`, `generator` (`name`, `commit`, `dirty = false`).

| Path | Content |
|---|---|
| `/prop_ctcp` | table: `J`, `CT`, `CP`, `CT_sigma`, `CP_sigma`, `source_id`. Sigma columns are absolute 1-sigma in coefficient units. Group attrs: `valid_J`, `selected_source` |
| `/throttle_map` | table: `esc_command_norm` (0 to 1) against `power_fraction`, with the band columns `power_fraction_lo`, `power_fraction_hi`. `units` on each column. Group attr `p_max_W`: the shaft power at full command, the scale of the power fraction |
| `/propeller` attrs | `model`, `diameter_m`, `blades`, and when known `ixx_kgm2` (moment of inertia about the shaft) and `design_ref` (`prop_id` and `design_sha256` of contract A, when the propeller is a Proptimiser design) |
| `/motor`, `/esc`, `/battery` attrs | parameters with the unit in the name (`kv_rpm_per_V`, `r_ohm`, `i0_A`, `cells_s`, `capacity_Ah`, `v_nominal_V`) |
| `/uncertainty/<item>` | uncertainty fields for each item. The item `prop_ctcp` says how the sigma columns were made. A model-relative value (for example `u_model`) is converted to absolute sigma, and the basis says so |
| `/results/<name>` attrs | scalar results with an interval: `median`, `lower`, `upper`, `coverage`, `units`, `method`. Names, all at full command and J = 0: `ct0`, `cp0`, `fom`, `tip_mach`, `thrust`, `torque`, `rpm`, `power` (shaft power), `current` |
| `/gates` | Propalyser gates only (D, V, P, R): `id`, `name`, `status` (`pass`, `fail`, `skip`, `inconclusive`), `value`, `limit` |
| `/components`, `/warnings`, `/references` | as in v1 |
| root attr `data_sha256` | the writer's own content hash (Propalyser: `tree_sha256` without `data_sha256` and `created_utc`). A reader does not check it. The package manifest sha256 is the integrity check |
| `/daveml/propulsion.dml` | DAVE-ML 2.0, valid against the 2.0 DTD, author a person |

Not in the file: JSBSim property names, Aerolink gates, aircraft blocks, flight-log results.

## C. Export package `muas-export/1.0.0` (AeroPlan to Aerolink)

The manifest field `package_spec` holds the version. Aerolink accepts only `muas-export/1.0.0`. The version changes
when a file becomes required. Content: the base content (see [](decisions.md)) plus:

| Path | Content | State (Currawong) |
|---|---|---|
| `missions/<name>.json` | one mission (AeroPlan `Mission` model, below) | filled |
| `propulsion/<system_id>.h5` | the contract B file, unchanged | filled (`currawongcustom`) |
| `visual/parts/*.stl` and `visual/parts.json` | parts and their transforms to the design frame: `units`, and `parts` with `file`, `transform` (`axes`, `origin_m`), `hinge` (two points, m) for each moving part, optional `units`, `material`, `source` | filled: 9 CAD parts, the fin, the boom |
| `mass/mass_items.json` | `items`: `name`, `mass`, `cg`, `inertia` (kg*m^2, parallel_to_design, +integral(xy dm)), `source`, `placeholder`. The roll-up CG equals the MRP | filled: one item (whole aircraft) |
| `dml/aero.dml` | the aero build-up in DAVE-ML 2.0 with the variable names of the Aerolink model (Aerolink `docs/package_contract.md`), check-cases in `checkData` | filled |
| `checks/datum.json` | the datum checks of the build (AeroPlan `datum.py`) | filled |

Aerolink refuses a package that lacks a file it needs and names the missing item. It never uses a default in its place.

## MUAS keys of the ADH tree (contract C)

Grouped for later analyses: control systems, structures, requirements. Each key sits under a node's `muas`.

| Key | Node (ADH WBS) | Content | Group |
|---|---|---|---|
| `control_surface` | 1.2.2.3.3 Ailerons, 1.2.2.4 Empennage | `parent`, `eta_span`, `hinge_x_over_c`, `limit_min_rad`, `limit_max_rad`, `positive_sign`, `s119_name`, `jsbsim_property` | control systems |
| `actuator` | same node as `control_surface` | `tau_s`, `rate_limit_rad_s`, `model`, `source`, `placeholder` | control systems |
| `autopilot` | 1.2.5.10 AutomaticFlightControl | `firmware`, `board`, `outputs` (`channel`, `function`, `targets`, `sign`, `reversed`, `pwm_min_us`, `pwm_trim_us`, `pwm_max_us`, `source`, `placeholder`) | control systems |
| `propeller` | 1.2.3.9 PropellerOrFanInstallation | `role`, `hub`, `thrust_axis`, `spin`, `diameter` | propulsion |
| `ground_contacts` | 1.2.2 Airframe (ADH has no landing-gear number) | list of `name`, `type` (BOGEY, STRUCTURE), `position`, `spring_N_per_m`, `damping_N_per_m_s`, `source`, `placeholder` | structures |
| `mass_properties` | 1.2 AirVehicle (later: each part) | `mass`, `cg`, `inertia`, `source`, `placeholder` | structures |
| requirement `muas.target` | requirements of 1.2 | `key` (flat name, for example `short_period_zeta_min`), `value`, `bound` (min, max, target), `units`, `source`, `placeholder` | requirements |
| requirement `muas.analysis_points` | requirements of 1.2 | `speeds_mps`, `source`, `placeholder` | requirements |
| requirement `muas.mission` | requirements of 1.2 | the mission profile (below) | requirements |

`sign` of a servo output: +1 means a PWM above the trim gives a positive deflection in the JSBSim sign. The
autopilot node is the ground truth for SITL and for the flight controller. Aerolink makes the ArduPilot parameters from it.

## Missions

ADH has no mission class. A mission is an ADH `Requirement` with `category = "mission"` on node 1.2. Its typed
profile sits under the requirement's `muas.mission` key (AeroPlan `aeroplan.muas.mission.Mission`).

- Positions are site-relative: `ahead_m` along the take-off heading of the site, `right_m` to its right, `alt_agl_m` above ground.
- Items: `takeoff`, `speed`, `waypoint`, `jump`, `loiter_turns`, `loiter_to_alt`, `land`. The last item must be `land`.
- `params`: ArduPilot parameter values that the mission needs.
- `site`: the name of a site. Sites (GPS point, heading) are operational data and stay in the Aerolink config.
- Hand YAML lives in `muas-fleet-data/aircraft/<ac>/missions/<name>.yaml`.
