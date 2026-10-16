# SpecSheet spoke

The Master Specification Sheet (weight log and CG sheet) to the mass model of the ADH.

| Item | Place |
|---|---|
| Input | The workbook that `SpecSheet/settings/<aircraft>.yaml` names (`Currawong Master Specification Sheet.xlsx` in the repository root). Later: a download of the Google Sheet into `SpecSheet/work/<aircraft>/` |
| Settings | `SpecSheet/settings/<aircraft>.yaml`: sheet names, sheet group -> ADH node, part -> position row |
| Writes | On each subassembly item: `muas.mass_properties` and `muas.point_masses`. On 1.2 AirVehicle: all point masses, the roll-up (mass, CG, inertia), `muas.sources`. The workbook goes in the asset register |
| Does not write | `muas.reference`. The MRP stays the CoG of the flow5 T7 analysis (see below) |

The spoke runs after flow5 in the build. It needs the planforms of flow5, and the sheet mass model replaces the flow5 mass model.

## What the spoke reads

- **Weight log** (`weights_sheet`). A group in column A is one subassembly. The row with "Subassembly weight override" in
  column F is the weighed mass of the whole subassembly (the rule of the sheet). The spoke refuses a sheet when the
  group totals do not add to the Total row (1 mg), when a group has no override row, or when the mapped parts weigh more
  than their subassembly. It does **not** use the "Unitemised Weight" rows of the sheet: it takes the weighed total less
  the parts it maps. (The sheet lines for Wings and Propulsion do not agree with their own totals.)
- **Position sheet** (`positions_sheet`). Column F is the distance from the origin of the flow5 frame in mm, positive
  forward: `x = -F / 1000`. The hub of the propeller and the nose of the ADH fuselage agree with this to 13 mm and 6 mm. The sheet
  has no y and no z: both are 0 (stand-ins).
- **Source of a part** (column F of the weight log): "Weighed..." gives `weighed`, "Determined from CAD" gives `cad`,
  "Calculated from..." gives `estimate`. "I made it up", "Not Weighed" and an empty cell give `estimate` with
  `placeholder: true`.

## What the spoke writes

- A part with a position row (`components` in the settings) gets its own point mass.
- The rest of the subassembly is one point mass at the mass-weighted x of the unmapped position rows. Lifting-surface
  groups (`distribute`) spread the rest over the planform in strips, so the inertia has a sensible spread.
- The point mass `source` names the sheet, the rows and the text of column F. It lists the rows that were not weighed.
- 1.2: the inertia is the parallel-axis sum of the point masses (parts have no inertia of their own: a lower bound).

## After a sheet change

```
python -m aeroplan build currawong --author "Your Name" --consumers review archive
python -m aeroplan check currawong
```

The datum table shows the sheet total, the CG in % MAC and the MRP warning. Then:
`python -m aeroplan generate flow5 currawong` writes a flow5 plane with the new point masses. Run the sweep in flow5. Copy it
into `flow5/work/currawong/sweeps/`, name it in `flow5/settings/currawong.yaml`, build again. The MRP then moves to the new CoG.

## Known limits

- Payload and water are not in the nominal configuration (the weight log has none). `AeroSandbox/lab.py` makes the tank
  configurations from the `tanks` rows of the CG sheets.
- The CG sheets are for two nose layouts. The position sheet in the settings is the one that agrees with the ADH fuselage.

## CSV mode (Redback)

Settings `format: csv` reads the weight log as a CSV (`SpecSheet/sheets/<aircraft>/`). `placement` rules put per-item weights at the rotor hubs (`hub`) or half way along the arm (`half_arm`). The rest of each weighed subassembly is one point mass at `origin_m`. `mrp: from_mass` sets the MRP to the rolled-up CG. `sanity` compares an estimate sheet (the Mk4 CSV) with the log: never truth.
