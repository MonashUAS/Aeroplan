# CREO spoke

The CAD link: a pointer, a pose and a hinge line for each CAD part mesh.

| Item | Place |
|---|---|
| Input | `CREO/work/<aircraft>/cad/*.stl` (exports of the Creo assembly) |
| Settings | `CREO/settings/<aircraft>.yaml`: units, and for each part its file, ADH item and transform |
| Writes | `muas.visual` of each ADH item: mesh pointer (an asset of the register: path and sha256), transform, hinge of a movable part |
| Skins | `skins:` in the settings: an outer skin (a faceted STEP file, for example the fuselage shrinkwrap) -> `muas.skin` of the item. A reference shape for the datum checks and the OpenVSP view |

The meshes stay on your machine. Without them, the Aerolink export makes simpler shapes from the ADH data.
Later: mass properties from the Creo mass report.
