# Aero data methods

Where the aero data of an aircraft comes from, how its sources are checked, and which books back each claim.
Source of this page: the docs update of Claude session `session_01NT8D2VH1aDdbrHnz1rLktQ`
(Aerolink branch `claude/docs-generalize-flight-log-plan-k9j82o`, commit 536238a, `docs/methods.md` sections 1 to 3 and 12).
The sections that describe the simulation itself (JSBSim model, linear models, modes, autopilot) stay in Aerolink.
Keys like [Etkin & Reid 1996] refer to the list at the end of this page.

## 1. Frames

| Frame | Axes | Origin | Used by |
|---|---|---|---|
| Structural (flow5, JSBSim `metrics`) | x aft, y right, z up | flow5 origin | flow5, the CAD parts, the hand config, JSBSim locations |
| Body | x forward, y right, z down | CoG | forces and moments in the simulation |
| Stability | body axes turned by the trim alpha about y | CoG | flow5 stability derivatives |
| Wind | x along the airspeed | CoG | lift, drag, side force |

The session doc states that the flow5 origin is the **wing root leading edge**. No measurement or flow5 file in AeroPlan
confirms it yet. Its position relative to the nose is still unknown ([](../currawong/missing_data.md), M-01).
Axis definitions: [Etkin & Reid 1996], ch. 4. [Stevens et al. 2016].

## 2. The source of the derivatives: flow5

flow5 solves the potential flow with a vortex lattice or a three-dimensional panel method [Katz & Plotkin 2001] [Drela 2014].
A viscous polar adds the section drag from XFoil at each strip [Drela 1989]. The Currawong sweep uses the panel method
TRIUNIFORM because the vortex lattice ignores the fuselage [flow5].

| flow5 polar | Gives | AeroPlan dataset |
|---|---|---|
| T7 stability analysis | trim state and stability derivatives | check value now. Rate terms later (M-11) |
| T1 fixed-speed alpha sweep | CL, CD, Cm against alpha | `aero.flow5.alpha`, `aero.flow5.alpha_viscous` |
| T5 sideslip sweep | CY, Cl, Cn against beta | `aero.flow5.beta` |
| T6 control polar | coefficients against a flap deflection | `aero.flow5.elevator`, `aileron`, `rudder` |

Limits:

- A potential-flow method does not model separation. flow5 gives no stall, and its drag is a lower bound.
- A strip-theory XFoil drag fails near stall. flow5 drops those points (17 lost points in the 2026-10-04 sweep).
- The flow5 `Cl` and `Cn` columns have the opposite sign of the aeronautical moments. Aerolink found this with a dihedral
  wing at +5 deg of sideslip. AeroPlan stores the columns as written and states the sign in each dataset.

## 3. The sweep validation (Aerolink, 2026-10-04)

The sweep compared the T7 result with independent runs. AeroPlan keeps the result in `raw/` (`results.json`).

| Check | Physics | Source |
|---|---|---|
| `CL_trim = m g / (q S)` | lift equals weight in level flight | [Etkin & Reid 1996], ch. 2 |
| T7 `Cma` against `dCm/dalpha` of T1 | one derivative from two analyses | [Etkin & Reid 1996], ch. 2 |
| `NP_x = x_cg - cbar dCm/dCL` | the neutral point is where `dCm/dCL = 0` | [Etkin & Reid 1996], ch. 2. [Nelson 1998], ch. 2 |
| T7 `Cnb` against `dCn/dbeta` of T5 | one derivative from two analyses | [Etkin & Reid 1996], ch. 2 |

## 4. Static stability and the reference geometry

The static margin is `SM = -Cma / CLa = (x_np - x_cg) / cbar` [Etkin & Reid 1996], ch. 2 [Nelson 1998], ch. 2.
The Currawong hand config gives `S` and `cbar` as implied values:

- `S_implied = m g / (q CL_trim)`
- `cbar_implied = (x_np - x_cg) / SM`

Both depend on the placeholder mass and CG. Confirm them in the flow5 reference dimensions (M-21).
Tail volumes `V_H = S_h l_h / (S cbar)` and `V_V = S_v l_v / (S b)`: [Sadraey 2012], ch. 6. [Raymer 2018].

## 5. Known gaps in the aero data (from the session doc)

| Gap | Effect | Data that measures it |
|---|---|---|
| Mass, CG and inertia are placeholders | every moment derivative scales with the inertia, the static margin moves with the CG | ground measurement first |
| Control derivatives from potential flow | no hinge gap, no boundary layer. Real control power is often lower | doublets and multisines |
| No `Cmadot` | short-period damping too low | pitch doublets |
| Drag polar fitted at one point | wrong drag away from the trim speed | power-off glides |
| Placeholder stall shape | wrong behaviour near stall | stall approaches at altitude |
| Constant derivatives | wrong at low speed and high alpha | tests at several speeds |

## References

- **[Etkin & Reid 1996]** B. Etkin and L. D. Reid, *Dynamics of Flight: Stability and Control*, 3rd ed. Wiley, 1996.
- **[Nelson 1998]** R. C. Nelson, *Flight Stability and Automatic Control*, 2nd ed. McGraw-Hill, 1998.
- **[Stevens et al. 2016]** B. L. Stevens, F. L. Lewis and E. N. Johnson, *Aircraft Control and Simulation*, 3rd ed. Wiley, 2016.
- **[Katz & Plotkin 2001]** J. Katz and A. Plotkin, *Low-Speed Aerodynamics*, 2nd ed. Cambridge University Press, 2001.
- **[Drela 2014]** M. Drela, *Flight Vehicle Aerodynamics*. MIT Press, 2014.
- **[Drela 1989]** M. Drela, "XFOIL: An analysis and design system for low Reynolds number airfoils", Lecture Notes in Engineering 54, Springer, 1989, pp. 1-12.
- **[Sadraey 2012]** M. H. Sadraey, *Aircraft Design: A Systems Engineering Approach*. Wiley, 2012.
- **[Raymer 2018]** D. P. Raymer, *Aircraft Design: A Conceptual Approach*, 6th ed. AIAA, 2018.
- **[flow5]** A. Deperrois, *flow5* (version 7.57), documentation and source (GPL-3.0). https://flow5.tech.
