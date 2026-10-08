# Procedure for engineers

How to add data to Currawong, change a value, or close a gap. Follow the steps in order.

## A. Add a new raw file

1. Copy the file by hand into `muas-fleet-data/aircraft/currawong/raw/<group>/`. Use `cp -p` (keeps the date).
   Do not use a symbolic link. Do not write a path to another repo in any file.
2. Add an entry to `inventory_notes.yaml`. Fill every field you know. Write `unknown` for the others.
   Quote any value that contains a colon.
3. Run the integration (section C). A file with no entry shows in `unclassified` and the command exits with 1.
4. Add the new facts to [](missing_data.md) if the file closes or opens a gap.

## B. Change a hand value

1. Edit `config/currawong.yaml`. Keep the comment that gives the source of the value.
2. When the value comes from a measurement, set `placeholder: false` for that section.
   Also write the source (file, date, person) in a comment.
3. Run the integration.
4. Run the tests in the AeroPlan repo.

`aeroplan integrate` never overwrites `config/currawong.yaml`. Use `--force-config` to rebuild it from the
raw legacy JSON. That discards your edits.

## C. Run the integration

```
cd Aeroplan
python scripts/build_adh.py
set PYTHONPATH=src;packages/muas_adh/build/src
python -m aeroplan.cli integrate currawong ../muas-fleet-data/aircraft/currawong
```

It rewrites `reference.json`, `configs.json`, `adh/`, `datasets/processed/` and `inventory.yaml`.
It reads only `raw/` and `config/currawong.yaml`. The folder path is an argument. No file holds it.

## D. Write a new adapter

1. Subclass `aeroplan.adapters.base.Adapter`. Put the file name and the facts you rely on in the module docstring.
   State where each fact comes from. Mark every fact that nobody verified.
2. Write a `manifest.json` and a `points.parquet` for each dataset. Use the types in `aeroplan.muas`.
3. For each doubt, set a `placeholder` or `unverified` flag. Do not choose a value.
4. Give every dataset an uncertainty record. If no estimate exists, use status `unavailable` and say why in `basis`.
5. Test the adapter with a small synthetic file (see `tests/sources.py`). Do not put real data in a test.
6. Register the adapter in `aeroplan/adapters/__init__.py`.

## E. Build the export package

1. Commit AeroPlan and `muas-fleet-data` first. The command refuses uncommitted changes.
2. Build the package. Give the person who makes it and a new version:

   ```
   python -m aeroplan.cli package build currawong ../muas-fleet-data/aircraft/currawong <out_dir> --author "<name>" --version 0.1.0
   ```

3. Read the datum table that the command prints. A failed check stops the build and writes nothing.
4. Wrap the folder into one file: `python -m aeroplan.cli package pack <out_dir> currawong.h5`.
5. Copy `currawong.h5` by hand into the Aerolink `packages/` folder. Then, in Aerolink: `aerolink inspect`,
   `aerolink all`, `aerolink check`, `aerolink fg build`.

A package is never edited. A change needs a new version.

## F. Commit

1. In `muas-fleet-data`: add files by name (`git add <file>`). Do not use `git add -A`.
   LFS files (`.h5`, `.stl`, `.fl5`) and a 125 MB STEP file are in the tree.
2. In `Aeroplan`: run `ruff` if you use it, then `pytest`. The CI runs `pytest` and the upstream ADH tests.

## Rules that stop errors

- **Never assume.** A value with no source is `unknown`. A value from an unverified source is flagged.
- **Never edit `raw/`.** A changed file has a different hash. Add the new file next to the old one.
- **Units.** SI in the SSOT. Angles are radians in the SSOT and degrees in hand config and dataset inputs
  (the dataset states the units of each column).
- **Frames.** Currawong data uses the flow5 frame: x aft, y right, z up, origin at the flow5 origin.
  The CAD nose is 0.6564 m ahead of it (M-01). Do not mix it with a nose-datum value.
- **MRP.** The MRP is the nominal CG. Today that CG is a placeholder. When the CG changes, the MRP changes and every
  dataset needs a moment transfer. `frames.transfer_moment_coefficients` does it.
