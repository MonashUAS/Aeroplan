# motor_survey.csv and esc_survey.csv: the maker rows of the motor and ESC mass fits

Each row is one product, copied by hand from a maker page. The `url` column gives the page and the `note` column gives
the read date and the basis of each value. The first rows were read on 2026-10-21. The survey grew to more than 100 fit
rows on 2026-11-02.

## Rules

- Copy a value only when a page gives it. Leave the cell empty when the page does not give it. The fit drops the row.
- Use the maker page first. Use a reseller page only when no maker page is available, and say so in `note`. The MAD
  AMPX and FOC ESC rows come from a reseller (rcdrone.top), because no MAD maker ESC page was reachable.
- Hobbywing Direct (hobbywingdirect.com) is the Hobbywing North America store. Its rows count as maker rows.
- Write what the page means by each number in `note`: the Imax basis (peak 180 s, continuous 180 s, peak of no stated
  duration), the I0 test voltage, the Rm basis, and whether the mass includes the cables.
- A value that the page gives as a range (Rm 134-141 mOhm) goes in as the middle of the range, and the note says so. An
  upper bound (I0 at most 2.0 A) goes in as the bound, and the note says so.
- Do not copy a row when the page gives the same Rm and I0 to two windings of one frame (T-Motor MN5212 KV420, MAD5010
  240KV). One of the two is a copy error, and the page does not say which.
- Do not copy a row when two listings of the same product disagree and no maker page settles it. Exception: the two MAD
  AMPX 80A listings (190 g and 90 g) are both in, with notes, because they can be two versions.
- Not copied for these reasons: T-Motor Flame ESCs (the pages give no mass), APD F and HV series (the pages give only
  the top of the cell range, and four HV models share one mass), Flycolor X-Cross HV3 (the reseller pages disagree and
  no maker page was reachable).
- Leave out water-cooled, car and boat ESCs (YGE Opto 255 Navy, Castle Cobra, Hobbywing SeaKing). They do not show the
  mass of an air-cooled UAV ESC.

## The fits that use the rows (`component.py`)

| Fit | Rows used | Form |
|---|---|---|
| `MotorModel` mass | kv, mass, Rm, I0 and Imax given, kv 60-450 rpm/V, mass 150-1600 g | m = exp(a0) q_cap^a1, q_cap = (Imax - I0) / Kv |
| `MotorModel` Rm | the same rows | Rm = exp(b0) kv^b1 m^b2 |
| `MotorModel` I0 | the same rows | I0 = exp(c0) kv^c1 m^c2 |
| `ESCModel` mass | cells_min <= S <= cells_max (S = 12 for Rosella), continuous current and mass given | m = exp(e0) I^e1 |

## Counts on 2026-11-02

| File | Rows | Fit rows | Rows by maker (all / fit) |
|---|---|---|---|
| motor_survey.csv | 117 | 103 | T-Motor 81 / 78, KDE Direct 16 / 14, MAD 20 / 11 |
| esc_survey.csv | 108 | 101 (12S) | Hobbywing 26 / 26, T-Motor 15 / 14, MAD 13 / 13, Castle Creations 12 / 12, Scorpion 10 / 10, Jeti 13 / 9, KDE Direct 10 / 8, YGE 5 / 5, ZTW 4 / 4 |

| Fit | Rows (before / after) | Exponent (before / after) | Log RMS (before / after) |
|---|---|---|---|
| Motor mass | 38 / 103 | 0.627 / 0.690 | 0.209 / 0.212 |
| Motor Rm | 38 / 103 | kv -1.317 / -1.201, m -1.308 / -1.440 | 0.248 / 0.342 |
| Motor I0 | 38 / 103 | kv 0.628 / 0.581, m 0.690 / 1.019 | 0.319 / 0.423 |
| ESC mass (12S) | 9 / 101 | 0.917 / 0.662 | 0.354 / 0.576 |

## Known mixed definitions

The makers do not use one test method. These differences are in the data and add to the scatter of the fits:

- Motor Imax: T-Motor gives a peak of 180 s, KDE a continuous rating of 180 s, MAD a maximum of 60 s or 180 s. The VL
  and MN11 series of T-Motor give a peak of no stated duration.
- Motor I0: the test voltage is 10 V to 24 V (35 fit rows at 10 V, 29 at 18 V). I0 grows with the voltage, so the I0
  fit has the largest scatter.
- Motor Rm: no maker except KDE says if Rm is phase to phase. KDE says "phase to phase, delta wound".
- Motor mass: T-Motor gives the mass with the cable. KDE and MAD give the motor only.
- ESC mass: 65 fit rows are without wires, 15 with cables, and 20 do not say. Bare boards (Scorpion Legatus without
  case and wires, 24 g for 80 A) and units with a fan sit at the ends of the band.
- ESC continuous current: each maker uses its own air speed and time (Hobbywing 7 m/s, Scorpion 35 m/s for 60 s, KDE
  180 s, Castle "at full throttle").

A filter on `mass_note` (for example, without wire only) would cut the ESC scatter. The fit does not use one today.
