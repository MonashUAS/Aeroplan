# Fly it in Aerolink

1. `python -m aeroplan export Aerolink currawong <out>` writes `<out>/currawong-<version>-aerolink.muas`.
2. Copy the file into `Aerolink/aircraft/` as `currawong.muas`. Copy it by hand. Do not use a symlink or a path to the other repository.
3. In Aerolink: `aerolink inspect`, `aerolink check`, `aerolink fg build`, then fly.

The package holds the 3D view as glTF (`preview/aircraft.glb`). The parts come from the CAD files when they are on
your machine (`work/creo/`). Without CAD files, they come from the ADH shapes (lifting surfaces, body, control
surfaces). They then look simpler, but they move the same.

`pack --profile aerolink` refuses an aircraft that lacks an item Aerolink needs. The message lists the missing items.
