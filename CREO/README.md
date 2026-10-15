# CREO spoke

The CAD link: a pointer, a pose and a hinge line for each CAD part mesh.

| Item | Place |
|---|---|
| Input | `CREO/work/<aircraft>/cad/*.stl` (exports of the Creo assembly) |
| Settings | `CREO/settings/<aircraft>.yaml`: units, and for each part its file, ADH item and transform |
| Writes | `muas.visual` of each ADH item: mesh pointer (an asset of the register: path and sha256), transform, hinge of a movable part |
| Skins | `skins:` in the settings: an outer skin (a faceted STEP file, for example the fuselage shrinkwrap) -> `muas.skin` of the item. A reference shape for the datum checks and the OpenVSP view |
| Tubes | `tubes:` in the settings: a round tube body that the CAD does not hold yet (the tail boom) -> a subcomponent of its ADH node with `geometry.body` (ADH `Body`) and `muas.tube` (radius, end items, source, placeholder). It runs from the aft end of the body of `from_instance` to the root quarter chord of `to_instance`. This step runs without the CAD folder |

The meshes stay on your machine. Without them, the Aerolink export makes simpler shapes from the ADH data.
Later: mass properties from the Creo mass report.
