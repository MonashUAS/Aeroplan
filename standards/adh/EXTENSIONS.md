# MUAS extension register

This register lists every key under `muas`. For each key it gives what ADH has, and why MUAS adds the key. Read
this file before you add a `muas` key. A new key needs a row here. `tests/test_adh_compat.py` stops the build when a
key of the models has no row, or when a row names a key that does not exist.

The rule (CLAUDE.md, ADR 0027): ADH decides the design. Store each fact once. Add a MUAS key only where ADH is silent
or broken. When ADH has the field, store the value in ADH and keep only the rest under `muas`.

ADH means the vendored Boeing ADH, commit `96179ca`, with the patches in `patches/`. The class paths are relative to
`upstream/src/aircraft_data_hierarchy/`.

## Node keys (`muas` of an ADH node or subcomponent: `aeroplan.muas.node.MuasNodeExt`)

| Key | What ADH has | Why MUAS adds it |
|---|---|---|
| `ext_version` | Nothing | The version of the MUAS form of this block. The build sets it. |
| `instance` | `Component.name` is free text and need not be unique | A unique name for each item, so that other items can refer to it (`parent`, `to_instance`). |
| `fidelity` | Nothing (`performance.ModelDescription` has no fidelity level) | The fidelity level L0 to L4 of the data of the item. |
| `mass_properties` | `systems_parameters.PhysicalCharacteristics` (weight in kg and CG, systems only). `airframe_parameters.FlightConditions.weight` (an analysis input). No inertia. | Mass, CG and the inertia tensor of any item, with a source and a placeholder flag. Source standards: SAWE RP A-14 for the terms and the sign of the products of inertia. CPACS `massDescription` (mass, location, massInertia) for the form. |
| `provenance` | `behavior.Provenance` (author, creation date) | The tool, the content hashes (SHA-256) of the inputs, and the configuration ID. ADH has no hash. |
| `control_surface` | `airframe_parameters.AsymmetricControl` and `SymmetricFlap` hold the span ratios and the chord ratio. MUAS stores them there. | The parent surface, the deflection limits, the sign convention, the S-119 name, the JSBSim property and the side. ADH has no field for them. |
| `propeller` | `airframe_parameters.PropellerPowerProperties` (blade count, angle lists) | The installation: the hub, the thrust axis, the spin, the role (lift or cruise) and the motor output. |
| `actuator` | Nothing | The servo dynamics: the time constant and the rate limit. |
| `autopilot` | The node 1.2.5.10 exists with no fields | The autopilot, the servo map and the outputs. |
| `ground_contacts` | Nothing (no landing gear class and no WBS number) | The gear contact points with spring and damping. They sit on node 1.2.2. |
| `reference` | `airframe_parameters.ReferenceData` holds S, b and c (Sref, BLref, Cbar). MUAS stores them there, in SI (patch 0004). | The design frame, the body frame, the Euler sequence, the MRP, the surface sign conventions and the vehicle kind. ADH has no frame and no MRP. |
| `initial_conditions` | `airframe_parameters.FlightConditions` defines an analysis sweep (DATCOM), not a start state | The trim state at the start of a simulation. |
| `datasets` | Nothing (`DataRepository`, node 1.10.2, has no fields) | The datasets of the item by role: pointers into the asset register. |
| `aero_settings` | Nothing | The settings of the aero model build, for example the stall values. |
| `lifting_surface` | `airframe_geometry.LiftingSurface` holds the shape (edge splines and airfoils). MUAS stores the shape there only (ADR 0027). | The section frame of the tools (position, rx, ry in rad), the tool name and role of the surface, the foil names, the symmetry and the structural mass. |
| `point_masses` | Nothing | The point masses of the mass model. |
| `visual` | `airframe_geometry.Mesh` holds mesh points in the document | The view parts: a reference to a CAD mesh asset, the transform and the material. Large meshes stay out of the source tree (ADR 0003). |
| `skin` | Nothing | A reference to the CAD skin of a body (the input of the body fit, ADR 0016). |
| `tube` | `airframe_geometry.Body` holds the shape of the tube. MUAS stores the shape there. | The inputs of a tube body (radius, wall, ends), its material and source. ADH has no material model. |
| `propulsion_system` | `propulsion.Propulsion` and `PropulsionCycle` model a gas turbine cycle | The electric propulsion: motor, ESC, battery and the propulsion tables. |
| `sources` | Nothing | The raw files that a spoke read: pointers into the asset register. |
| `geometry_tool` | Nothing | The spoke that wrote the geometry last (the changed file wins, ADR 0009). |
| `assets` | Nothing (`DataRepository`, node 1.10.2, has no fields) | The asset register: one entry for each file and dataset, by content hash (ADR 0004). Node 1.10.2 only. |
| `software_releases` | The node 1.2.9 exists with no fields | The flight software releases. Node 1.2.9 only. |
| `flight_tests` | The node 1.8.1.4 exists with no fields | The flight events (ADR 0021). Node 1.8.1.4 only. |
| `build` | `behavior.FileHeader` is the header of one DAVE-ML file | The build record of the aircraft: the AeroPlan commit, the author, the version, the spoke changes and the placeholder list. |

## Requirement keys (`muas` of an ADH `Requirement`: `aeroplan.muas.requirement.RequirementExt`)

| Key | What ADH has | Why MUAS adds it |
|---|---|---|
| `mission` | `requirements.Requirement` holds text only. ADH has no mission class. | A typed mission profile. The mission stays an ADH requirement with category "mission". |
| `target` | `requirements.Requirement` holds text only | One design or handling target with a value, units and a bound (min, max, target). |
| `analysis_points` | `requirements.Requirement` holds text only | The airspeeds of the linear model family. |

## Source tree key (`muas.package` of the root node file: `aeroplan.muas.node.PackageInfo`)

| Key | What ADH has | Why MUAS adds it |
|---|---|---|
| `package` | Nothing | The kind (aircraft or flight-record) and the consumers (packing profiles) of the source tree. The reader moves it out of the ADH document, and the package keeps it in its manifest (ADR 0026). |

## Values that MUAS stores in ADH fields

| Fact | ADH field | Rule |
|---|---|---|
| Wing and tail shape | `geometry.lifting_surface` | The only stored shape. `aeroplan.geometry.planform_of` gives the tool sections. |
| Body shape | `geometry.body` | The only stored shape. |
| S, b, c | Node 1.2 `parameters.reference_data` (`Sref`, `BLref`, `Cbar`) | SI (patch 0004). Write the aliases: ADH drops a field name without an error. Use `adh_doc.set_reference` and `adh_doc.reference`. |
| Control surface span and hinge | `parameters.asymmetric_control` (left or right) or `parameters.symmetric_flap` (both halves) | chord ratio = 1 - hinge x/c. Use `adh_doc.set_control_geometry` and `adh_doc.control_surface`. |
| Uncertainty effect | `behavior.UncertaintyEffect` | The ADH enum checks the value. MUAS keeps no copy of the enum. |
| Correlation | `behavior.Correlation` (`var_id`, `corr_coef`) | MUAS uses the same field names and adds the bound -1 to 1. |
