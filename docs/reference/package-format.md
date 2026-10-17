# The `.muas` package (format muas 2.0.0)

```
<aircraft>-<version>-<profile>.muas     (ZIP64 when needed)
  mimetype                              "application/vnd.muas+zip", the first entry, not compressed
  manifest.json                         kind, format version, ADH fork, MUAS schema version, profile, consumers,
                                        the files {path, sha256, size, role, storage, asset}, the package hash
  aircraft.adh.json                     the monolithic ADH tree
  data/<name>.h5                        embedded datasets (not compressed in the ZIP, gzip by chunk inside HDF5)
  assets/<sha256>-<name>                embedded raw files (archive profile)
  preview/aircraft.glb                  the glTF view of the parts
```

The design frame in `aircraft.adh.json` has its origin at the root leading edge of `wing_main`, x aft (ADR 0023). `aeroplan check` fails when this wing is not at x = 0. A multirotor keeps ADR 0018.

| Profile | Embedded | Linked |
|---|---|---|
| `aerolink` | ADH JSON, aero and propulsion datasets, flight files, glTF | everything else |
| `review` | ADH JSON, glTF preview, summary plots | data and CAD |
| `flight-record` | flight-record, segment and parameter datasets | raw logs, video |
| `archive` | everything that can be fetched | nothing |

- A package is never edited. A pack with other content and the same name is refused: build a new version first.
- The same source tree gives the same package bytes.
- `aeroplan unpack` and `aeroplan verify` check the mimetype, every file hash, the package hash and every dataset hash. Every fetch of a linked asset checks its hash.
- A consumer states what it needs. `pack --profile aerolink` refuses an aircraft that lacks an item Aerolink needs. A linked asset that is missing on this machine does not make a package invalid.
