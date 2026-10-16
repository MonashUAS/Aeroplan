# Change the aircraft with your tool

Example: a member changes the wing in flow5.

1. Write the flow5 input from the SSOT: `python -m aeroplan generate flow5 currawong`. This writes
   `work/flow5/currawong/generated/currawong.xml` and the foil files.
2. Open the plane in flow5, change it, and run the sweep. Put the sweep folder in `work/flow5/currawong/sweeps/`.
3. Name the sweep in `tools/flow5/settings/currawong.yaml` (`sweep:` and `sweep_date:`).
4. Build: `python -m aeroplan build currawong --author "Your Name"`. Read the datum table. A failed check writes
   nothing.
5. Commit `aircraft/currawong/` (and the settings file, if you changed it). Raw files stay in `work/`.

Each spoke folder has a README with its input files and settings. Example: `tools/openvsp/README.md`.

The changed file wins. A geometry spoke (flow5, OpenVSP) writes the geometry of an item only when its input file
differs from the file asset that the item names. After an OpenVSP change, the datum table warns that the aero model
comes from older geometry until you run a new flow5 sweep.
