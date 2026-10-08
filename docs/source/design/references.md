# References and assumptions register

Status: checkpoint 1. No numeric initial value was introduced. Every number in the plan snippets stays a `<placeholder>`.
The assumptions below are structural (conventions and definitions), not numeric.

## Textbook references

Page, equation and table numbers are NOT given. Nobody has checked them against a copy of each book.
The tag [reference/index needed] marks each missing locator. Add it before you cite the source in a report.

| Key | Reference |
|---|---|
| [Raymer] | Raymer, D. P., *Aircraft Design: A Conceptual Approach*, 6th ed., AIAA Education Series, 2018. The user's PDF (Downloads) is the Sixth Edition and has a text layer. Locators are PDF page numbers from a keyword search. Printed page numbers differ by about 30. Rows without a locator keep the tag [reference/index needed]. |
| [SLJ] | Stevens, B. L., Lewis, F. L., Johnson, E. N., *Aircraft Control and Simulation*, 3rd ed., Wiley, 2016. |
| [E&R] | Etkin, B., Reid, L. D., *Dynamics of Flight: Stability and Control*, 3rd ed., Wiley, 1996. |
| [S-119] | ANSI/AIAA S-119-2011, *Flight Dynamic Model Exchange Standard* (DAVE-ML). |
| [Roskam] | Roskam, J., *Airplane Design* and *Airplane Flight Dynamics and Automatic Flight Controls*, DARcorporation. |

## Assumptions register

| ID | Assumption | Basis | Locator |
|---|---|---|---|
| A1 | Coefficients use wing area, span and mean chord (S_ref, b_ref, c_ref). | [Raymer], topic: wing geometry and mean aerodynamic chord | Ch. 4, PDF p.117 (mean aerodynamic chord named as a wing reference; keyword hit, not read in full) |
| A2 | Mass, CG and inertia roll up by component about one CG. | [Raymer], topic: weights and CG, component weight build-up | [reference/index needed] |
| A3 | Moment transfer: M_new = M_old + r x F. | [SLJ] or [E&R], topic: forces and moments about a reference point | [reference/index needed] |
| A4 | Body axes: x forward, y right, z down (FRD). Design frame: x aft, y right, z up. A fixed rotation maps one to the other. | Aerolink CLAUDE.md (design frame). [SLJ] or [E&R] (body axes). | [reference/index needed] |
| A5 | Sign checks: Cm_alpha < 0, Cn_beta > 0, Cl_beta < 0. Damping: Cm_q, Cl_p, Cn_r < 0. | [Raymer], topic: stability and control. [E&R], topic: stability derivatives. | Ch. 16, PDF pp.624-625 (negative pitching-moment derivative means stable). Other signs: [reference/index needed] |
| A6 | Coefficients are build-up terms: static, control increment, rate derivative, power increment. | [Raymer], topic: aerodynamics build-up. [Roskam], aerodynamic derivatives. | [reference/index needed] |
| A7 | Fidelity ladder L0 to L4 (handbook, AeroSandbox, Flow5/VSPAERO, CFD/stand/CAD, flight). | Project plan, [Prev]. Not from a textbook. | none |
| A8 | Propeller thrust and power use Ct and Cp against J and rpm. | Propalyser and Proptimiser README. Textbook: [Raymer], topic: propeller performance. | Ch. 13, PDF pp.512-514 (advance ratio, thrust and power coefficients; eqs. 13.16 to 13.18) |
| A9 | Interface conclusions in `interfaces.md`. | Four repo files only. Not from a textbook. | none |
| A10 | The neutral point is set by geometry. The CG is set by mass. | [Raymer] and [E&R], topic: static margin and neutral point | Ch. 16, PDF pp.624-625 (static margin, e.g. ahead of the neutral point) |
| A11 | Uncertainty is recorded for input, results and derived values. A basis is recorded. Reports give a quantitative estimate, a qualitative description or a statement that none exists. | [NASA-STD-7009B] [M&S 28], [M&S 29], [M&S 33], [M&S 34]. Text checked in the PDF. | section 4.3 |
| A13 | Values in `synthetic.py` are arbitrary test stand-ins. | Not from any source. The package carries `placeholder: true`. | none |
| A12 | The uncertainty data layout is a MUAS design. | Not from a standard. Mapped to ADH `Uncertainty` (DAVE-ML). | none |

Additional sources:

| Key | Reference |
|---|---|
| [NASA-STD-7009B] | NASA-STD-7009B, *Standard for Models and Simulations*, approved 2024-03-05. https://standards.nasa.gov/sites/default/files/standards/NASA/B/1/NASA-STD-7009B-Final-3-5-2024.pdf |
| [ADH] | NASA/CR-20250007045 and Boeing/aircraft-data-hierarchy at `96179ca`. |
| [MGP] | Scoggins et al., AIAA 2023-1185. |

## Numeric values

None in this checkpoint. When a sizing or mass default is needed, add a row here with: value, unit, source key, locator, and the reason for the choice.
Raymer statistical data (for example empty-weight fractions) must carry the table number and the aircraft class.
