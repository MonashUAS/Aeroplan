# 22. Quadplane path

Date: 2026-10-17

Status: accepted

## Context

The Rosella is a VTOL quadplane. It uses the Currawong V1 wing, tail and tail boom. It has a new fuselage and lift booms. It has no sizing printout and no SpecSheet. ADR 18 covers multirotors only. ADR 12 gives the mass model to the SpecSheet.

## Decision

The Rosella starts from `tools/aerosandbox/settings/rosella.json` (the `airframe` component has `base: currawong`). The notebook `tools/aerosandbox/notebooks/rosella_sizing.ipynb` and the `QuadplaneModel` of `model.py` size the propulsion and the booms with the EMST equations (Bershadsky 2016) in AeroSandbox. It has two configurations. H4 has four lift rotors. H8 has a coaxial pair on each of the four H4 stations. It solves each configuration for 6S, 8S, 10S, 12S and 14S as separate cases.

The lift propeller is a geometric scale of the Proptimiser FLUXER 22x6.6 Fit C blade (Proptimiser 711ef86). The radius is an Opti variable between 16 in and 26 in diameter. A 30 in limit gave only 5.5 % less energy for a 36 % extrapolation of the blade. The map speed is an Opti variable. It stays above 1.3 Vs. The boom wall is 1.0 mm or more. The yaw requirement is 1.5 rad/s2. This value is a placeholder, chosen after a sweep.

The solver climbs a fidelity ladder: L0 momentum, L1 CT and CP tables, L2 plus structure, stiffness, clearance and control, L3 BEMT at the hover take-off state, L4 BEMT at all states. Each level starts with an elastic feasibility phase. That phase names the infeasible constraint.

The Rosella CG is a design output: the VLM neutral point minus 10 % MAC. The sizing owns the mass model until a SpecSheet exists. This is an exception to ADR 12. The SpecSheet takes the mass model back when it exists.

The model file `tools/aerosandbox/settings/rosella.json` holds the components and the last result. The notebook writes it. It never writes the source tree. The AeroSandbox spoke writes `aircraft/rosella/` from the model file (ADR 8). A bought part is a component with fixed params. There is no second file for manual configurations.

The lift rotors have a cant for yaw authority. Each rotor tilts by the cant about its radial axis (the line from the CG to the hub), so the tilt force is tangential. The tilt moment of one rotor is T sin(cant) rho, with rho the horizontal distance from the CG to the hub. The tilt sign follows the spin: a cw rotor (seen from above) tilts to push the airframe the same way as its reaction torque. The tilts cancel in hover, because two rotors turn cw and two turn ccw. When the controller raises the thrust of the cw rotors and lowers the thrust of the ccw rotors, the tilt moment adds to the drag torque difference. A tilt about the tangential axis gives no yaw moment, so each rotor has one tilt angle only. The cant size is an Opti variable (0 to 10 deg). It costs 1 - cos(cant) of the thrust. The idea comes from the rotor-cant literature (Niemiec and Gandhi, "Effect of Rotor Cant on Trim and Autonomous Flight Dynamics of a Quadcopter", VFS 2018, and the RPI and SAE eVTOL cant papers). Those papers give no rule for the angle, so the yaw requirement sets it.

The Currawong NP and CG question is open. The wing MAC leading edge moved from x -0.080 m to 0 m between the old report and the tree. The Currawong CG does not change, because of ADR 13.

## Consequences

The sizing numbers in `aircraft/rosella/` are placeholders until a SpecSheet and maker data replace them. Aerolink gets no Rosella package until a quadplane contract exists. The packing profiles are `review` and `archive`.

Changed by [ADR 24](0024-aircraft-models-in-code.md): the script, the YAML settings file and the manual file are replaced by the model classes and one JSON file.
