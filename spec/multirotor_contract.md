# Multirotor contract (AeroPlan to Aerolink)

This page is the contract for a multirotor in a `.muas` package (format muas 2.0.0). AeroPlan owns it. Aerolink keeps a hand
copy. The first aircraft is the Redback, an X quadcopter. Nobody changes this page without a new version of the contract.

Contract version: 1 (2026-10-16). MUAS extension version: 0.4.0.

Rules:

- Units are SI. Angles are radians. A quantity is `{value, units}` with SI base units (a Kv of 150 rpm/V is stored as
  15.708 with the pint base units of rad/s per volt: read `value` as rad/s per volt).
- Read every number from the package. Do not copy a number from this page into code. The Redback values on this page are
  examples of build 0.1.x.
- A value with `placeholder: true` is a stand-in. Show it in the warnings.
- A command that needs an item that the package does not hold stops and names the item. It uses no default value.

## 1. How to find a vehicle kind

| Item | Place | Value |
|---|---|---|
| Vehicle kind | node 1.2 AirVehicle, `muas.reference.kind` | `multirotor`. An absent key means a fixed-wing aircraft |
| Design frame | node 1.2, `muas.reference.design_frame` | `x_aft_y_right_z_up_m_bodyOrigin` (new value: the origin is the middle of the four hubs) |

A multirotor has no control surface and no cruise propeller. A package with a lift rotor and a control surface or a cruise
propeller is refused. A quadplane gets its own kind later.

## 2. Frames and axes

- Design frame (all positions and axes in the ADH data): x aft, y right, z up, metres. The origin is the body origin, the
  middle of the four hubs.
- Body frame of the aero dataset and of the simulator: FRD (x forward, y right, z down).
  Map: `x_frd = -x_design`, `y_frd = y_design`, `z_frd = -z_design`.
- Euler sequence 3-2-1, local NED: as `muas.reference` says.

## 3. Where each item sits in the ADH tree

The nested ADH document `aircraft.adh.json` has one key for each WBS class, in snake_case. The path starts at the root
`1.0 AircraftSystem`.

| Item | WBS node and path in `aircraft.adh.json` | Key under `muas` |
|---|---|---|
| Reference data | 1.2 `air_vehicle` | `reference` |
| Initial conditions | 1.2 `air_vehicle` | `initial_conditions` |
| Mass properties | 1.2 `air_vehicle` | `mass_properties`, `point_masses` |
| Aero dataset id | 1.2 `air_vehicle` | `datasets` (entry with `role` = `aero`) |
| Ground contacts | 1.2.2 `air_vehicle.airframe` | `ground_contacts` |
| Demo shapes of body and arms | 1.2.2 `air_vehicle.airframe` | `visual` (also in `preview/aircraft.glb`) |
| Lift rotor 1 | 1.2.3.9 `air_vehicle.propulsion.propeller_or_fan_installation` (the node) | `propeller` |
| Lift rotors 2, 3, 4 | the same node, in its `subcomponents` list (a subcomponent has no WBS number) | `propeller` |
| Propulsion system | the node of lift rotor 1 | `propulsion_system` |
| Propulsion dataset id | the node of lift rotor 1 | `datasets` (entry with `role` = `propulsion`) |
| Autopilot and motor outputs | 1.2.5.10 `air_vehicle.avionics.automatic_flight_control` | `autopilot` |
| Asset register | 1.10.2 `data.data_repository` | `assets` |

Find an item by `muas.instance`, not by its place in a list. The instance names of the Redback are `prop_lift_1` to
`prop_lift_4`, `airframe`, `autopilot` and `redback_airvehicle`.

### 3.1 Lift rotors (`muas.propeller`)

Each lift rotor is one item with a `muas.propeller` block:

| Field | Meaning |
|---|---|
| `role` | `lift`. The consumer reads only the items with this role as rotors |
| `motor` | The autopilot motor number, 1 to 4 (ArduPilot MOTn). Unique. The consumer maps `motor` to the output `motor<n>` |
| `hub` | `{frame: design, xyz, units: m}`. The point where the thrust acts and the disc turns |
| `thrust_axis` | Unit vector in the design frame. For a lift rotor it is `[0, 0, 1]` (up). The check refuses any other value |
| `spin` | `cw` or `ccw`. See section 3.2 |
| `diameter` | The propeller diameter in metres (Redback: 0.5588 m, 22 in) |
| `system` | The `system_id` of the propulsion system that drives the rotor. All four rotors name the same system |

Redback values (build 0.1.x, hubs rounded to 0.1 mm):

| `motor` | `muas.instance` | ArduPilot Quad X position | ArduPilot turn (seen from above) | `spin` stored | `hub` x, y, z (m) |
|---|---|---|---|---|---|
| 1 | `prop_lift_1` | front right | CCW | `cw` | -0.4005, +0.3738, +0.0479 |
| 2 | `prop_lift_2` | rear left | CCW | `cw` | +0.4005, -0.3738, +0.0479 |
| 3 | `prop_lift_3` | front left | CW | `ccw` | -0.4005, -0.3738, +0.0479 |
| 4 | `prop_lift_4` | rear right | CW | `ccw` | +0.4005, +0.3738, +0.0479 |

The hubs are the mirror images of one arm that the user measured in CAD (549.968 mm, direction angles X 132.822 deg,
Y 85.000 deg, Z 43.2582 deg; CAD axes -Z forward, +Y up, X right). The values keep all digits of the angles.

### 3.2 Sign convention of `spin` (exact)

`spin` is the turn direction seen when you look ALONG the thrust vector from behind the rotor. This is the JSBSim sense
convention. For a lift rotor the thrust points up, so you look up from below.

- `cw` means: the angular velocity vector points along `thrust_axis` (right-hand rule). The shaft turns in the positive
  sense about `+z`. Seen from above, the rotor turns counter-clockwise. The reaction torque on the airframe points down
  (against `thrust_axis`), so the airframe yaws clockwise seen from above.
- `ccw` means: the angular velocity vector points against `thrust_axis`. Seen from above, the rotor turns clockwise.

To change the view: ArduPilot gives the turn direction seen from above. `spin` = `cw` when ArduPilot says CCW, and
`spin` = `ccw` when ArduPilot says CW.

Rotor torque on the airframe about the rotor axis: `Q_reaction = -sign * Q * thrust_axis`, with `sign = +1` for `cw`
and `sign = -1` for `ccw`, and `Q` the shaft torque (above 0) from the propulsion dataset.

### 3.3 Motor outputs (`muas.autopilot`, node 1.2.5.10)

`muas.autopilot.firmware` is `ArduCopter`. `outputs` is a list. Each motor output has:

| Field | Meaning |
|---|---|
| `channel` | The flight controller output, 1 to 16. Redback: output n drives motor n |
| `function` | `motor1` to `motor4`. These are `SERVOn_FUNCTION` 33 to 36 in ArduPilot (motor1 = 33, motor2 = 34, motor3 = 35, motor4 = 36) |
| `targets` | One `muas.instance`: the lift rotor whose `propeller.motor` equals the number in `function` |
| `sign` | Absent. A motor output has no sign |
| `pwm_min_us`, `pwm_max_us` | The ESC end points in microseconds. They come from the contract B file (`/esc` `pwm_low_us`, `pwm_high_us`). Both are required. `pwm_min_us` is below `pwm_max_us` |
| `pwm_trim_us` | Absent for a motor |
| `placeholder` | `true` until the `.parm` of the aircraft confirms the map |

The consumer maps a PWM value to the ESC command with `command = (pwm - pwm_min_us) / (pwm_max_us - pwm_min_us)`, limited to
0 to 1. The throttle map of the propulsion dataset turns the command into the power fraction.

ArduPilot Quad X (frame class 1, type 1): motor 1 front right CCW, motor 2 rear left CCW, motor 3 front left CW, motor 4 rear
right CW (seen from above).

### 3.4 Propulsion system (`muas.propulsion_system`)

The block comes from the Propalyser contract B file (schema `propulsion-system`, version 2). It sits once, on the node
of lift rotor 1. It holds `system_id` (Redback: `redback_mk4`), `basis`, `p_max` (shaft power at full command, the scale of
`power_fraction`), `diameter`, `blades`, `ixx` (propeller inertia about the shaft), `motor` (`kv`, `r`, `i0`, `kappa`,
`r_tot`, `q0`, `mass`, `imax_continuous`), `esc` (`pwm_low`, `pwm_high`, `imax_continuous`), `battery` (`cells_s`,
`cells_p`, `capacity`, `v_nominal`). The Redback battery is 12S3P: `cells_s` 12, `cells_p` 3, 44.4 V, 13.5 A h.

The Ct/Cp table and the throttle map are the dataset with `role` = `propulsion` (form `tables`):

- `prop_ctcp`: columns `J`, `CT`, `CP` (nd). `J = V / (n D)`, `CT = T / (rho n^2 D^4)`, `CP = P / (rho n^3 D^5)`, `n` in rev/s.
- `throttle_map`: columns `esc_command_norm` (0 to 1), `power_fraction` (power over `p_max`).

All four rotors use this one dataset. The consumer finds it through the dataset id of the node of lift rotor 1 (or through
the `system` name of any rotor). The dataset id is `asset:sha256:<hash>` in the entry of `muas.datasets`. The register entry (node 1.10.2,
`muas.assets`) gives its `name` (`propulsion.<system_id>`) and where its bytes are: `storage` `inline` (the JSON value is in
`inline`), or `embedded` (`package_path` `data/<name>.h5`, the HDF5 form of the JSON that AeroPlan `h5json` writes).

## 4. Aero dataset: the body drag

The dataset with `role` = `aero` on node 1.2 is a DAVE-ML 2.0 model in the ADH `DAVEfunc` form (form `daveml-adh`). The consumer
turns it into XML (as for a fixed-wing aircraft) or reads it directly. It is forces only. There are no moments.

Variable IDs (units; axes):

| varID | Kind | Units | Meaning |
|---|---|---|---|
| `u` | input | m/s | Air-relative velocity of the body along x, body axes FRD, positive forward |
| `v` | input | m/s | Same, along y, positive right |
| `w` | input | m/s | Same, along z, positive down |
| `n_sum` | input | rev/s | The sum of the four rotor speeds, each above 0 |
| `rho` | input | kg/m^3 | Air density. Default value 1.225 (ISA sea level, ISO 2533) |
| `S_ref` | constant | m^2 | Reference area. It equals `muas.reference.s_ref` |
| `CDx`, `CDy`, `CDz` | constants | nd | Body drag coefficients on `S_ref` for a flow along that axis |
| `k_rotor_drag` | constant | kg | Rotor drag. Force per (rev/s of `n_sum`) per (m/s of velocity) |
| `Fx`, `Fy`, `Fz` | outputs | N | Aerodynamic force on the body, body axes FRD, positive forward, right, down |

Formulas:

    Fx = -0.5 rho S_ref CDx u |u| - k_rotor_drag n_sum u
    Fy = -0.5 rho S_ref CDy v |v| - k_rotor_drag n_sum v
    Fz = -0.5 rho S_ref CDz w |w|

Each force opposes the velocity along its axis. The model has no cross terms and no angle of attack. The rotor thrust, the
rotor torque and the inflow loss of the rotors are NOT in it: the propulsion dataset has the rotor load. The five
constants have `initialValue` and a description `source: <text>; placeholder: true|false`. Today all are placeholders (the drag
area comes from stand-in shapes; `k_rotor_drag` is 0 until the flight log fits it). The file has six `checkData` static shots
that the consumer can run.

`rho` is an input that the user list (u, v, w, n_sum) did not have. A formula with `rho` needs it. In JSBSim, bind it to the
atmosphere density property.

## 5. Mass properties

`muas.mass_properties` on node 1.2: `mass`, `cg` (design frame), `inertia` (kg m^2, about the CG, axes parallel to the design
frame, products `+integral(xy dm)`: Ixy = +sum(m x y)), `source` `estimate`, `placeholder` `true`. `muas.point_masses` lists the 26
point masses that give it (a part has no inertia of its own). The MRP equals the CG. The consumer refuses a package when
the MRP is more than 1 mm from the CG.

The Redback mass model (weight sheet, user rules of 2026-10-16): the motors, propellers, ESCs and motor mounts are point
masses at the four hubs, the boom arms are point masses half way along the arm, and all other mass is at the origin.

## 6. Ground contacts

`muas.ground_contacts` on node 1.2.2: a list. Each item has `name`, `type` (`STRUCTURE` for a foot), `position` (design frame),
`spring_N_per_m`, `damping_N_per_m_s`. The Redback has four feet (`FOOT_FR`, `FOOT_FL`, `FOOT_RL`, `FOOT_RR`). The positions are
stand-ins (`placeholder: true`): the real gear is not measured. At least three contacts are needed to stand.

## 7. Reference data

`muas.reference` on node 1.2: `kind` `multirotor`, `s_ref` (the frontal area of the demo body box, a placeholder), `b_ref` (the
hub-to-hub distance in y), `c_ref` (the hub-to-hub distance in x), `mrp`, `nominal_cg`, `design_frame`. `surface_signs` is empty.

`muas.initial_conditions`: `values.speed_mps` is 0 (hover) and `values.altitude_m` is a placeholder.

## 8. What the consumer check requires

AeroPlan checks this with `aeroplan.consumers.missing_for_flight` before it packs the `aerolink` profile. Aerolink makes the same
checks and refuses a package that fails. A multirotor needs:

1. `muas.reference` with `kind` `multirotor`, `muas.initial_conditions`, `muas.mass_properties` on node 1.2, and the MRP within 1 mm
   of the CG.
2. Four items with `muas.propeller.role` = `lift` and `motor` = 1, 2, 3, 4 (no number twice), each with `thrust_axis` = `[0, 0, 1]`.
3. One `muas.propulsion_system`, and a `system` on every rotor that equals its `system_id`.
4. The datasets with `role` `aero` (node 1.2) and `propulsion` (node of lift rotor 1).
5. `muas.autopilot` with the outputs `motor1` to `motor4`. Output n has `targets` = the instance of the rotor with `motor` n, and has
   `pwm_min_us` and `pwm_max_us`.
6. `muas.ground_contacts` with at least 3 contacts.
7. No `muas.control_surface` and no rotor with role `cruise`.

The `aerolink` profile embeds the ADH JSON, the aero and propulsion datasets and `preview/aircraft.glb`. It links everything else.

## 9. 3D view (`preview/aircraft.glb`)

glTF 2.0 binary, design frame (the asset `extras.frame` says so), metres. One node for each part. Node `extras` hold `item` (the
`muas.instance`), `material`, `source`, `placeholder` and, for a rotor disc, `alpha`.

| Part name | Shape | Item | Moves |
|---|---|---|---|
| `body` | box | `airframe` | no |
| `arm_1` to `arm_4` | tube from the origin to the hub | `airframe` | no |
| `motor_1` to `motor_4` | cylinder at the hub | `prop_lift_<n>` | no |
| `rotor_1` to `rotor_4` | thin disc, diameter of the propeller | `prop_lift_<n>` | turns about `thrust_axis` through the hub with the sense of `spin` |

A disc has `extras.alpha` (0 to 1). The glTF material has `alphaMode` BLEND with that opacity. A viewer draws it semi-transparent.
All shapes are demo shapes without CAD (`placeholder: true`).

## 10. Open items (placeholders until measured)

Body drag area and arm drag, `k_rotor_drag`, landing gear foot positions, body box and arm tube sizes, avionics current,
battery and wiring resistance, `kappa` of the motor chain, propeller and rotor inertia. The flight log of the Redback fits
several of them.
