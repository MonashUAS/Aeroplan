# OpenVSP spoke

Puts the ADH geometry (wings, tail, fin, fuselage, control surfaces) into an OpenVSP model. A changed model comes
back into the source tree `aircraft/<aircraft>/` with `aeroplan build`.

| Item | Place |
|---|---|
| Runtime | `OpenVSP/.venv`: the Python that the OpenVSP module needs (git ignores it). `aeroplan setup OpenVSP` makes it |
| Generate | `aeroplan generate OpenVSP <aircraft>` writes `work/<aircraft>/generated/<aircraft>.vsp3` and the CAD skin STL |
| Input | `work/<aircraft>/<model>`: your changed copy of the generated model |
| Settings | `settings/<aircraft>.yaml`: the OpenVSP version of the tests, the model file name, the wings, the body, the skin |
| Writes | the changed items only: `muas.planform` and `geometry.lifting_surface`, the foils, `geometry.body`, the eta and hinge of `muas.control_surface`, `muas.geometry_tool`, an OpenVSP pointer |

## First time on a computer (about 5 minutes)

1. Download OpenVSP for your system from openvsp.org. Unzip it to any folder.
2. Run `python -m aeroplan setup OpenVSP`. If it does not find OpenVSP, add `--vsp <the OpenVSP folder>`.

Setup reads the Python version that the OpenVSP module needs (OpenVSP 3.54: Python 3.13). It installs that Python
with uv into your user profile. It needs no admin rights and does not change your own Python. It writes nothing
into the OpenVSP folder. For a new OpenVSP version, unzip it and run setup again.

## Change the geometry

1. `python -m aeroplan generate OpenVSP <aircraft>`.
2. Copy `work/<aircraft>/generated/<aircraft>.vsp3` to `work/<aircraft>/<aircraft>.vsp3`.
3. Open the copy in `vsp.exe`. Change it and save it.
4. `python -m aeroplan build <aircraft> --author "Your Name"`. Read the change lines and the datum table.

What you can change: the wing sections (span, chords, sweep, dihedral, twist), the number of sections, the foils,
the position and the X/Y rotation of a wing, the control surfaces (eta start and end, chord fraction), the fuselage
sections. The component names must stay the ADH instance names (`wing_main`, `htail`, `fin`, `fuselage`).

The build refuses a model that the ADH form cannot hold. Examples: a new component, a twist location other than
0.25 of the chord, the relative dihedral or twist switches, a control surface with a changing chord fraction.

## Rules

- The changed file wins. The build reads the model only when its sha256 differs from the OpenVSP pointer on the air
  vehicle. It writes only the items that differ from the document. A later flow5 sweep with new files replaces
  the geometry again.
- After an OpenVSP change, the datum table warns that the aero model comes from older geometry. Run a new flow5
  sweep (`aeroplan generate flow5` writes the flow5 plane from the changed file).
- The wing rules are the flow5 rules: y is the projected span station, a section twists about its quarter chord
  in the x-z plane (OpenVSP `TwistAllInXZPlaneFlag` on), and its dihedral sets the panel outboard of it. The
  dihedral of the last section sets no panel. OpenVSP has no slot for it, so the document keeps its value.
- The ADH `eta_span` is a fraction of the projected half span. OpenVSP eta is a fraction of the span along the
  panels. The spoke converts between them. They differ only when the panels have different dihedral.
- A left and right control surface with the same shape (the ailerons) is one OpenVSP control surface named
  `aileron_l+aileron_r`. A change to it changes both sides.

## Shape check (tests/test_openvsp.py)

- Every planform value, foil point, position and body frame comes back from the `.vsp3` file within 1e-9.
- Every ADH section point (each foil placed by the planform rules) and each body frame point lies on the OpenVSP
  surface within 1 um in the synthetic tests. Currawong: htail 0.27 um, fin 0.18 um, fuselage 0.20 um,
  wing_main 3.54 um.
- The 3.54 um is OpenVSP's own surface build: at the root section of a wing with dihedral, two points of the
  cambered Eppler 395 foil lie 3.5 um from the OpenVSP surface. The stored data stays exact. The ingest limit is
  10 um (`SHAPE_TOL`).
- Between two sections, OpenVSP joins the sections with straight lines. The AeroPlan view meshes and
  `parts._hinge_point` interpolate the chord and the twist instead. The difference is second order: 0.28 mm at an
  aileron end in the synthetic test wing. At a section the two rules agree.

The CAD skin (`muas.skin` of the fuselage, from the CREO spoke) goes into the model as the mesh
`fuselage_skin (reference)`. The build ignores it. `generate` gives the gap from the OpenVSP fuselage to the skin.
