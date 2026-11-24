# Aerolink spoke

The simulator export: the `.muas` package that Aerolink flies.

| Item | Place |
|---|---|
| Export | `python -m aeroplan export Aerolink <aircraft> <out>` writes `<out>/<aircraft>-<version>-aerolink.muas` |
| Import | none. Flight records come in through the ArduPilot spoke |

The export is the same as `python -m aeroplan pack <aircraft> --profile aerolink --out <out>`. The package
embeds the ADH JSON, the aero and propulsion datasets (HDF5) and the 3D view `preview/aircraft.glb` (glTF 2.0).
It links everything else.

Copy the file into `Aerolink/aircraft/`. The glTF parts come from the CREO work folder when the files are there
with the registered sha256. Else they come from the ADH shapes: lifting surfaces, the body, and the control surfaces
(span and hinge of `muas.control_surface`). Each glTF node holds its ADH item and, for a movable part, its hinge
axis in the node `extras`.
