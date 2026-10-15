# CREO spoke

The CAD link: a pointer, a pose and a hinge line for each CAD part mesh.

| Item | Place |
|---|---|
| Input | `CREO/work/<aircraft>/cad/*.stl` (exports of the Creo assembly) |
| Settings | `CREO/settings/<aircraft>.yaml`: units, and for each part its file, ADH item and transform |
| Writes | `muas.visual` of each ADH item: mesh pointer (an asset of the register: path and sha256), transform, hinge of a movable part |
| Skins | `skins:` in the settings: an outer skin (a faceted STEP file, for example the fuselage shrinkwrap) -> `muas.skin` of the item. The raw CAD shape for the datum checks, the OpenVSP view and the OpenVSP analysis (CompGeom, parasite drag, VSPAERO panel) |
| Body from a skin | `skins.<name>.body: {frames, points, cut, min_height_m}` -> the spoke slices the skin into the ADH `geometry.body` of the item (`aeroplan.skin_body`) and records the method, the settings and the fit in `muas.skin.body_fit` (RMS gap, largest gap, volume). The ADH body is a fit of the skin, so every tool (flow5, OpenVSP, AeroSandbox) reads it. The skin stays the exact shape |
| Tubes | `tubes:` in the settings: a round tube body that the CAD does not hold yet (the tail boom) -> a subcomponent of its ADH node with `geometry.body` (ADH `Body`) and `muas.tube` (radius, end items, source, placeholder). It runs from the aft end of the body of `from_instance` to the root quarter chord of `to_instance`. This step runs without the CAD folder |

The meshes stay on your machine. Without them, the Aerolink export makes simpler shapes from the ADH data.
Later: mass properties from the Creo mass report.

## The fuselage body from the shrinkwrap

The Creo shrinkwrap (`fuseskinshrinkwrap.stp`) is the outer skin of the fuselage. It also holds the centre panel of the
CAD wing and a thin sheet at the tail end. The slicer handles both:

- `cut: {x_m: [x0, x1], y_max_m}`: in these stations a hit above the half width `y_max_m` is a wing hit. The frame takes
  the pod outline from a straight line between the nearest good rays.
- `min_height_m`: the body ends where the skin section is this tall (plus 5 mm). The last 23 mm of the Currawong skin is
  a corrugated sheet 3 mm thick, which no frame can describe.
- Currawong: 41 frames of 37 points. RMS gap to the skin 0.86 mm, largest 6.5 mm (wing panel and tail sheet left out).

The datum table shows a larger gap (frames to skin, 42 mm largest): the frames cross the wing junction, where the skin
has no pod surface.

