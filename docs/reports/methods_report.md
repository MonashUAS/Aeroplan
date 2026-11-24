# AeroSandbox methods for the Currawong: gap study, recommended methods, sources, ADH mapping

Status: 2026-10-15. AeroSandbox 4.2.9, source tree `aircraft/currawong` version 0.2.5. The numbers come from
`tools/aerosandbox/notebooks/03_gap_study.ipynb`. Run that notebook again after a change of the geometry or the mass model.

Point of the study: the flow5 T7 point (V 12.0958 m/s, mass 8.28 kg, Re(c) 2.73e5), moments about the flow5 MRP
(the T7 CoG, x 0.1291 m), elevator 0. Slopes are per radian.

## 1. Findings

### 1.1 The method matrix

| Model | CLa | Cma | NP x [m] | SM about the MRP | CL0 |
|---|---|---|---|---|---|
| flow5 (DAVE-ML, T7) | 4.727 | -1.347 | 0.223 | 0.285 | 0.443 |
| VLM 8x6 | 5.335 | +0.297 | 0.111 | -0.056 | 0.497 |
| VLM 16x12 | 5.318 | +0.317 | 0.109 | -0.060 | 0.542 |
| VLM 24x16 | 5.314 | +0.327 | 0.109 | -0.062 | 0.553 |
| VLM 16x12, wake along the wind | 5.552 | +0.009 | 0.129 | -0.002 | 0.542 |
| LiftingLine | 5.728 | -1.276 | 0.203 | 0.223 | 0.545 |
| NonlinearLiftingLine | 5.443 | +0.156 | 0.120 | -0.029 | 0.551 |
| AeroBuildup, wing and tail | 5.830 | -1.404 | 0.209 | 0.241 | 0.674 |
| AeroBuildup, full, with the boom | 5.842 | -1.228 | 0.199 | 0.210 | 0.674 |

The VLM converges: 16x12 and 24x16 give the same neutral point within 1 mm.

### 1.2 Cause 1 (pitch): the tail lift slope in the NeuralFoil methods

The tail alone, lift slope on its own area:

| Method | Tail CLa [1/rad] |
|---|---|
| VLM | 3.53 |
| Lifting-line theory (Helmbold), A = 3.39 | 3.59 |
| AeroBuildup | 5.14 |
| LiftingLine | 5.88 |

The VLM agrees with theory. AeroBuildup and LiftingLine are 43 % and 64 % high. Both take the section lift from
NeuralFoil. At the tail Reynolds number (Re 2.0e5) NeuralFoil gives NACA 0012 a 2D slope of 8.35 per rad between
-1 and +1 deg, and 5.79 per rad between 2 and 6 deg. Thin-airfoil theory gives 2 pi = 6.28. The tail has -2.6 deg
incidence, so it works in this steep band (section angle about -2.6 to +0.8 deg for aircraft alpha 0 to 5 deg).
NeuralFoil is a model of XFoil. XFoil also shows this steep band for thin symmetric foils at low Re. No test data of
the tail confirms it.

The wing foils (E395 at Re 3.2e5, E393 at Re 2.5e5) have normal slopes (5.8 to 6.4 per rad). They do not cause
this effect.

### 1.3 Cause 2 (pitch): AeroBuildup has no downwash at the tail

The downwash gradient de/da at the tail (x 1.48 m, z -0.05 m):

| Source | de/da |
|---|---|
| VLM (wing alone, flow angle at the tail) | 0.322 |
| LiftingLine (same probe) | 0.249 |
| USAF DATCOM 4.4.1 formula | 0.262 |
| Lifting-line rule 2 CLa_w / (pi A) | 0.310 |
| AeroBuildup | 0 (each wing runs alone) |

### 1.4 The neutral point

Build-up from the checked parts, `h_n = h_ac + V_H (a_t / a_w)(1 - de/da)` (h_ac 0.262, V_H 0.683, a_w 4.93):

| Build-up | NP x [m] | SM about the T7 CoG | SM about the sheet CG |
|---|---|---|---|
| VLM tail, VLM de/da | 0.116 | -0.040 | +0.019 |
| Helmbold tail, DATCOM de/da | 0.128 | -0.005 | +0.054 |
| AeroBuildup tail, no downwash | 0.241 | +0.341 | +0.399 |
| AeroBuildup tail, VLM de/da | 0.166 | +0.111 | +0.170 |
| VLM 16x12 (full run) | 0.109 | -0.060 | -0.001 |
| flow5 | 0.223 | +0.285 | +0.344 |

Note (2026-10-17): these NP values use the old flow5 wing frame, where the MAC LE sits at x = -0.080 m. The source tree has the wing root LE at x = 0 (ADR 0015, ADR 0023). With the tree frame the VLM 16x12 neutral point is 0.182 m (`tools/aerosandbox/neutral_point.py`).

The T7 CoG is at 63.3 % MAC. The sheet CG (x 0.1098 m) is at 57.5 % MAC.

Result: the methods that pass the tail check (VLM, Helmbold with DATCOM) put the neutral point at x 0.11 to 0.13 m.
The static margin about the sheet CG is then 0 to 5 % c. About the T7 CoG it is negative. AeroBuildup agrees with
flow5 for two wrong reasons that add: a tail that is too strong (cause 1) and no downwash (cause 2).

**Warning.** Do not use the flow5 static margin (28.5 % c) for a flight decision until flow5 is checked (section 5, item 1).
Get a flight-test check of the CG range or a second method (AVL) first.

### 1.5 What flow5 implies

With the VLM wing AC and the tail quarter chord, the flow5 CLa and Cma imply a wing slope of 4.03 per rad (VLM 4.93,
Helmbold for A 10.1: 5.16) and a tail slope with downwash of 4.55 per rad on the tail area (VLM 2.40, Helmbold with
DATCOM de/da 2.65). So flow5 has a weak wing and a tail that is about 1.7 to 1.9 times too strong. The elevator derivatives
of flow5 put the tail centre at x 1.411 m, in front of the tail leading edge (x 1.422 m). That is a second sign that
the flow5 pitch derivatives are not consistent. The flow5 sweep files are not on this computer, so the cause in flow5
(wake model, reference values, the body panels) is not known.

### 1.6 Lift level and drag

| Wing alone | CLa | CL0 |
|---|---|---|
| VLM 16x12 | 4.93 | 0.606 |
| LiftingLine | 4.94 | 0.631 |
| AeroBuildup | 5.05 | 0.709 |
| flow5 implied | 4.03 | n/a |

- CL0 of the aircraft: flow5 0.443, VLM 0.542, AeroBuildup 0.674. The AeroBuildup increase comes from the viscous
  camber lift of NeuralFoil. The flow5 decrease is not explained. The fuselage covers 7.0 % of the span at the wing
  root. AeroBuildup has no wing-body interference, so it cannot show a lift loss there.
- Drag at the same CL (0.840): AeroBuildup 0.0445, flow5 0.0486 (CD0 + K CL^2). AeroBuildup needs 1.64 deg for this CL,
  flow5 4.81 deg. Notebook 02 compares at the same alpha, so there AeroBuildup has more drag. At the same lift it has
  less.
- AeroBuildup drag by part at that CL: wing 0.0391, horizontal tail 0.0019, fin 0.0011, fuselage 0.0031, tail boom
  0.0005.

### 1.7 The tail boom

The boom is now in the model (section 4.3). It adds CD 0.00046 (0.54 W at the T7 speed), CLa +0.003 and Cma -0.004.
The boom is not a cause of the gap. flow5 also has no boom.

### 1.8 Causes, ranked

1. Pitch: the NeuralFoil tail slope at Re 2e5 (AeroBuildup, LiftingLine) and the missing downwash (AeroBuildup).
   Together they move the neutral point about 8 cm aft (0.116 to 0.199 m).
2. Pitch: flow5 is not consistent with the inviscid theory (section 1.5). Open until the flow5 files are checked.
3. Lift level: viscous camber in NeuralFoil (+0.13 CL0 against the VLM) and an unexplained -0.10 in flow5.
4. Drag: small at the same CL (-0.004 in AeroBuildup). The boom: +0.0005.

## 2. Recommended methods

| Job | Method | Reason |
|---|---|---|
| Neutral point, static margin, Cma | `asb.VortexLatticeMethod`, 16x12 for each section, trailing legs along x | Agrees with theory on the tail and on de/da. Converged. About 3 s for each point |
| Downwash for other methods | VLM probe at the tail (`get_velocity_at_points`), check with DATCOM 4.4.1 | Gives de/da for a build-up model |
| Trim, power, endurance in `asb.Opti` (`cruise_trim`) | AeroBuildup for the wing, fin, fuselage and boom, plus a linear tail model: `L_t = q S_t a_t (alpha (1 - de/da) + i_t + tau de)` with a_t and de/da from the VLM | AeroBuildup is differentiable and has viscous drag. The linear tail removes causes 1 and 2. Change the worker after this report is accepted |
| Section polars | NeuralFoil, `model_size` "large" or larger, Re from the ADH chords | Good for the cambered wing foils (confidence 0.98). Do not trust it for the 2D slope of NACA 0012 near zero alpha at Re 2e5 |
| Body drag and lift | AeroBuildup fuselage model | Jorgensen crossflow, slender-body lift, form factor drag |
| Cross-check | AVL (not installed) | A second vortex method. Put it in the AeroSandbox venv when a check is needed |

Do not use:
- `asb.LiftingLine` for pitch. It solves the circulation with a section slope of 2 pi, then takes the final lift from
  NeuralFoil at the induced angle. With the steep NACA 0012 band this gives the largest tail error (5.88 per rad).
- `asb.NonlinearLiftingLine` for routine work. It agrees with the VLM (NP 0.120 m) but takes about 1.5 minutes for
  each point.
- `asb.LinearPotentialFlow`. It is not complete in 4.2.9 (parts raise NotImplementedError).
- The trailing-leg option `align_trailing_vortices_with_wind`. It moves the VLM neutral point 2 cm aft (0.109 to 0.129 m).
  Keep the default (along x) and report the sensitivity.

## 3. The equations and their sources

### 3.1 The airplane model (AeroSandbox 4.2.9)

| Function | Equation | Source | Use in AeroPlan | Limits |
|---|---|---|---|---|
| `Airfoil.get_aero_from_neuralfoil` | Neural network: Cl, Cd, Cm (alpha, Re, Mach, foil shape, control deflection) | NeuralFoil (P. Sharpe, MIT PhD thesis, 2024; trained on XFoil) | Section data of AeroBuildup and the lifting lines | Inherits XFoil behaviour at low Re (section 1.2). Check `analysis_confidence` |
| `aerolib.CL_over_Cl` | CL/Cl = A / (2 + sqrt(4 + A^2 beta^2 + (A tan Lambda)^2)) | Raymer, Aircraft Design: A Conceptual Approach, sect. 12.4.1, citing DATCOM | AeroBuildup 3D lift factor | Straight-wing form. No interference |
| AeroBuildup effective alpha | alpha_eff = alpha - (1 - f^0.8) sin(2 alpha)/2 (180/pi); CL = Cl f^0.2, f = CL/Cl | AeroSandbox heuristic (source comment: tuned, under 20 % CL error against tunnel data, A down to 0.5) | AeroBuildup wing sections | Not a published method |
| AeroBuildup neutral-point shift | Fitted function of A, sweep, taper | AeroSandbox fit (`studies/AeroBuildup_LL_unsweep_calibration`) | AeroBuildup wing AC | Fit, small for a straight wing |
| `aerolib.oswalds_efficiency` | e from taper, A, sweep (section 5) | Nita and Scholz, Estimating the Oswald factor from basic aircraft geometrical parameters, DLRK 2012 (eq. 36, 37) | AeroBuildup induced drag | Fuselage term set to 0 |
| AeroBuildup induced drag | D_i = (L^2 + Y^2) / (q pi b_eff^2), b_eff^2 = softmax(b_i^2 e_i) over the parts | AeroSandbox | Whole-airplane induced drag | No wing-tail interaction |
| AeroBuildup wing-on-tail effect | none | | | Cause 2 of this study |
| Fuselage potential lift and moment | Slender-body theory: lift at the nose from the base area, moment from the area distribution | Drela, Flight Vehicle Aerodynamics, eq. 6.77 and 6.78 | Fuselage and boom | Body of revolution assumed |
| Fuselage viscous crossflow | Crossflow lift with eta(fineness) and the cylinder Cd_n | Jorgensen, NASA TR R-474, 1977 (eta: AeroSandbox fit) | Fuselage and boom | High-alpha part |
| Fuselage skin friction | Cf = (3.46 log10 Re - 5.6)^-2 x FF(fineness, corner radius) | Gotten, Havermann, Braun, Marino, Bil, J. Aircraft 2021, doi 10.2514/1.C036032 | Fuselage and boom drag | Fully turbulent. Fit for optimised fuselages |
| Fuselage base drag | Cd_base(Mach) x base area | MIL-HDBK-762, sect. 5-5.3.1, fig. 5-140 (AeroSandbox fit) | Zero today: the fuselage and the boom close to a point | |
| Fuselage wave drag | Sears-Haack drag area x drag-rise fit | Raymer fig. 12.28; Lock drag rise (Hilton 1952) | Zero at Mach 0.035 | |
| `VortexLatticeMethod` | Horseshoe vortices on the camber surface, Biot-Savart influence matrix, flow tangency at the collocation points, Kutta-Joukowski forces | Standard VLM (for example Katz and Plotkin, Low-Speed Aerodynamics) | Neutral point, de/da | Inviscid. No bodies. Flat wake |
| `LiftingLine` | One horseshoe for each strip, 2 pi in the linear system, final Cl from NeuralFoil | AeroSandbox | Not recommended for pitch | Section 2 |
| `NonlinearLiftingLine` | Lifting line with the NeuralFoil Cl in the residual | AeroSandbox | Check only | Slow |
| `Atmosphere(method="differentiable")` | Smoothed fit to the 1976 COESA standard atmosphere | AeroSandbox | Density, viscosity | ISA day only |
| `MassProperties` | Sum with the parallel-axis rule | Standard | Notebook CG and inertia (AeroPlan `mass_model.rollup` is the master) | |
| `asb.Opti` | CasADi with IPOPT | Andersson et al., CasADi (2019); Wachter and Biegler, IPOPT (2006) | `cruise_trim`, `static_check` | |

### 3.2 Study methods (not AeroSandbox)

| Item | Equation | Source |
|---|---|---|
| Tail lift slope | CLa = 2 pi A / (2 + sqrt(A^2 + 4)) | Helmbold lifting-line approximation |
| Downwash gradient | de/da = 4.44 [K_A K_lambda K_H sqrt(cos Lambda_c/4)]^1.19, K_A = 1/A - 1/(1 + A^1.7), K_lambda = (10 - 3 lambda)/7, K_H = (1 - abs(h_H/b)) / (2 l_H/b)^(1/3) | USAF DATCOM sect. 4.4.1, as given in Roskam, Airplane Design Part VI |
| Neutral point | h_n = h_ac + eta V_H (a_t / a_w)(1 - de/da) | Etkin and Reid, Dynamics of Flight, chapter 2 |
| Moment transfer | Cm' = Cm + CL (x' - x_mrp) / c | Standard |

### 3.3 Propulsion (unchanged)

| Part | Equation | Source |
|---|---|---|
| Motor and ESC | I = I0 + (Q + Q0) Kv, d V_bus = omega / (kappa Kv) + R_tot I, I_bat = d I | Drela first-order motor; Propalyser `estimate/chain.py` |
| Propeller | BEMT with NeuralFoil sections, axial flow | Proptimiser (`proptimiser.casadi_prop`, Nahon 2015 per the spoke README) |

## 4. How the model maps to the ADH

### 4.1 From the ADH to AeroSandbox (`tools/aerosandbox/spec.py`, `asb_worker.build_airplane`)

| AeroSandbox object | ADH source | Conversion |
|---|---|---|
| `asb.Wing`, `WingXSec.xyz_le`, `chord` | `muas.planform` of each item in settings `wings` (the same shape as the ADH `LiftingSurface` splines) | `geometry.planform_wing` and `_edges`: leading and trailing edge points in the design frame. chord = distance LE to TE |
| `WingXSec.twist` | Planform twist, dihedral and the surface pitch `ry_deg` | Angle of the chord line from the LE and TE points (AeroSandbox ignores the TE point). A fin keeps its section twist |
| `asb.Airfoil` | ADH `airfoil_sections` of the `LiftingSurface` (`geometry.foils_of`) | Selig coordinates, normalised |
| `asb.ControlSurface` | `muas.control_surface` (parent, eta_span, hinge_x_over_c, side) | Extra sections at the span ends. A left and right pair is one antisymmetric surface |
| `asb.Fuselage`, `FuselageXSec` | ADH `Body` (`reference_axis`, `cross_sections`) of each item in settings `bodies`: the fuselage (1.2.2.2) and the tail boom (subcomponent of 1.2.2.4) | `geometry.body_frames`: each frame -> centre (x, 0, mid z), width, height, shape 2 (an ellipse). The ellipse is an approximation of the real frame |
| `Airplane.s_ref`, `b_ref`, `c_ref`, `xyz_ref` | `muas.reference` of node 1.2 (S, b, c, the MRP) | SI, design frame |
| `asb.MassProperties` | `muas.mass_properties` and `point_masses` of node 1.2 (written by the SpecSheet spoke) | SI |
| `asb.Propulsor` | `muas.propeller` (hub, thrust axis, diameter) | |
| Motor, ESC, battery | `muas.propulsion_system` (contract B) | SI |
| `OperatingPoint` | `performance` "sizing" of node 1.2 (cruise speed), settings `altitude_m` | |

The design frame of the ADH (x aft, y right, z up, m) is the AeroSandbox geometry frame. No axis change is needed.

### 4.2 From AeroSandbox back to the ADH

Nothing goes back today. The AeroSandbox spoke writes only to `work/aerosandbox/<aircraft>/`. If an AeroSandbox aero
model is ever stored, it goes in as a DAVE-ML dataset (`aero_buildup.py` form) through the spoke, with fidelity,
source and placeholder flags, next to the flow5 model.

ADH `airframe_parameters` has DATCOM-style `LiftingSurface` and `Body` parameter classes. They are the place for
derived numbers (exposed span, wetted area, stations and areas of a body) if a tool needs them stored.

### 4.3 The tail boom in the ADH

- Item: subcomponent `tail_boom` of 1.2.2.4 Empennage. ADH has no WBS number for a boom. The sheet books the boom
  mass under Tail, so the boom belongs to the empennage.
- Geometry: ADH `geometry.body` (a `Body`), four round frames: a point at each end and the full radius between them.
- `muas.tube` (new MUAS extension field, `extra="forbid"`): radius 0.0175 m, `from_instance` fuselage (aft end of its
  body), `to_instance` htail (root quarter chord), source, `placeholder: true`.
- Writer: the CREO spoke, settings `tubes:` (`tools/creo/settings/currawong.yaml`). It runs without the CAD folder.
  `muas.geometry_tool` is CREO. Replace the tube with a Creo export of the boom when there is one.
- Mass: the TAIL-BOOM point mass of 1.2.2.4 (SpecSheet spoke) is not changed.

### 4.4 Gaps in the ADH for this work

- No field for a downwash gradient or a tail efficiency. A build-up model with a linear tail needs them. Keep them in
  the DAVE-ML dataset of the model, not as loose numbers.
- No field for the wake model or the mesh of a method. Record them in the dataset provenance (`method`).

## 5. Open items

1. Get the flow5 sweep folder `currawongv5_testfuse` into `work/flow5/currawong/sweeps/`. Run flow5 T7 for the wing
   alone, the tail alone and the wing plus tail. Compare with sections 1.2 to 1.5.
2. Install AVL in the AeroSandbox venv and run the same matrix as a second vortex method.
3. Check the CG range with a flight test (ArduPilot spoke: trim elevator against airspeed at two CG positions).
4. Change `cruise_trim` to AeroBuildup plus the linear tail model (section 2), after items 1 and 2.
5. Put the tail boom into the flow5 plane XML for the new sweep.
