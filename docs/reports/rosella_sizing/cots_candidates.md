# Rosella H4 12S: COTS candidates for the lift system

Date of web research: 2026-10-18 (second pass the same day). This file lists off-the-shelf motors, ESCs and battery packs for the H4 12S quad lift system. Every number comes from a page that was fetched and read. The source is in the last column of each row. A value that no page gave is written "not published". Reseller data is marked "reseller". Search-result text that was not read on the page itself is marked "snippet". A value that I calculated is marked "calculated" or "derived".

Change in this version: the 95 Wh limit per pack is removed. Larger packs and 12S packs are now allowed. Two nice-to-have checks are added: DroneCAN on the ESC and a hall sensor or encoder on the motor or ESC.

## 1. Design target

Source: `work/aerosandbox/rosella/sizing/H4_12S.json` (L4 result, solver status Solve_Succeeded).

| Item | Value | JSON field |
|---|---|---|
| Cells in series | 12S | `cells_s` |
| Mass (MTOW) | 13.58 kg (limit 15 kg) | `names.M` |
| Weight | 133.2 N | `names.W` |
| Rotor diameter | 0.660 m (26 in) | `D_m` |
| Rotor pitch | 0.198 m (P/D 0.30, base blade MAD FLUXER 22x6.6) | `pitch_m` |
| Motor Kv | 138.5 rpm/V | `design.kv` |
| Peak motor torque | 2.41 N m | `design.q_cap` |
| Peak motor current | 35.9 A | `names.I_pk` |
| Motor no-load current | 0.99 A | `names.i0` |
| Motor resistance (model) | 0.0861 ohm | `names.rm` |
| Motor mass | 0.310 kg | `names.m_motor` |
| ESC mass | 0.036 kg | `names.m_esc` |
| Battery capacity | 9.16 Ah | `design.cap_Ah` |
| Battery mass | 2.568 kg | `names.m_batt` |
| Battery resistance (model) | 0.0295 ohm | `names.R_b` |
| Hover thrust per rotor | 33.4 N | `names.Th` |
| Hover torque per rotor | 0.96 N m | `names.Qh` |
| Mission energy | 325.3 Wh | `names.E_Wh` |

Derived numbers from the task brief (not in the JSON):

- Nominal pack energy: 44.4 V x 9.16 Ah = 407 Wh.
- Peak thrust per rotor: about 85 N at thrust to weight 2.5.
- Peak battery current: about 160 A (4 motors x about 36 A plus losses).
- Hover battery current: about 33 A.

Notes on the targets:

- The JSON ESC mass is 36 g. No 12S COTS ESC in this file is that light except the Zubax Myxa (27 g bare) and the ARK 12S CAN (22 g). Four ESCs of 110 g add about 295 g over the model. The 15 kg limit still holds.
- Motor Kv sets the full-throttle rpm. Thrust varies with rpm squared. A Kv 100 motor on the same 12S pack reaches about 28 percent less rpm than Kv 138.5. This gives about 48 percent less thrust on the same prop. A Kv 100 motor needs a larger or higher-pitch prop. That is a design change.
- Torque constant used below: Kt = 9.549 / Kv in N m per A. Current for 2.4 N m = 2.4 / Kt + no-load current.

## 2. Component ranking

### 2.1 Scoring rule

Each component gets five scores from 0 to 5. The total is out of 100: total = 8 x Fit + 4 x Mass + 4 x Data + 2 x Price + 2 x Nice.

| Criterion | Weight | How the 0 to 5 score is set |
|---|---|---|
| Fit to the design target | 40 % | Motor: 5 = Kv within 10 % and torque margin of 20 % or more. 4 = Kv within 25 % and torque margin of 10 % or more. 3 = torque margin of 0 % or more, or Kv off by more than 25 %, or peak torque not published. 2 = Kv off by more than 25 % with a thrust loss. 1 = torque below target. ESC: 5 = 60 A continuous or more and a 12S rating. 4 = 45 to 59 A, or no voltage margin. 3 = 40 to 44 A, or conflicting current data. 1 = 25 to 39 A. 0 = under 25 A, below 12S, or current not published. Battery: first the 160 A peak must be met on published data, if not the fit is 1. Then the energy of the best arrangement against 407 Wh: 5 = -5 to +30 %. 4 = -10 to -5 % or +30 to +50 %. 3 = -20 to -10 % or +50 to +80 %. 2 = beyond. |
| Mass | 20 % | Motor: 5 = 320 g or less, 4 = to 350 g, 3 = to 400 g, 2 = to 450 g. ESC: 5 = 40 g or less, 4 = to 80 g (or to 60 g with enclosure), 3 = to 120 g, 2 = to 150 g, 1 = not published, 0 = over 150 g. Battery by Wh per kg of the arrangement: 5 = 200 or more, 4 = 170, 3 = 150, 2 = 130, 1 = less. |
| Data quality and availability | 20 % | 5 = maker page with full specs, price and in stock. 4 = maker or reseller page with price and a small gap. 3 = reseller only, sold out, or backorder. 2 = snippet only, or large gap. 1 = almost no data. |
| Price | 10 % | Motor in USD: 5 = 150 or less, 4 = to 200, 3 = to 250, 2 = to 300 or not published, 1 = over 300. ESC in USD: 5 = 100 or less, 4 = to 130, 3 = to 200, 2 = to 350 or not published, 1 = over 350. Battery by price per Wh in the listed currency (no conversion): 5 = 0.40 or less, 4 = to 0.60, 3 = to 0.90, 2 = to 1.30 or not published, 1 = more. |
| Nice-to-haves | 10 % | Motor: 5 = hall sensor or encoder confirmed on a source page, else 0. ESC: 3 points for DroneCAN confirmed by a maker or ArduPilot page, plus 2 points for a sensor or encoder input confirmed. Battery: 5 = smart pack with a communication protocol confirmed, else 0. "Not published" scores 0. |

Hard limits. A part that breaks a hard limit is ranked below all parts that pass and is marked "hard fail". Hard limits are: motor mass above 400 g, motor peak torque below 2.3 N m, ESC continuous current below 40 A, ESC mass above 150 g, ESC rating below 50.4 V, battery arrangement that does not meet 160 A on published data.

All scores are my judgement from the cited pages. They rank candidates for a first pass. They do not replace a bench test.

### 2.2 Motors

| Rank | Motor | Fit | Mass | Data | Price | Nice | Score | Reasons |
|---|---|---|---|---|---|---|---|---|
| 1 | T-Motor MN701-S KV135 | 5 | 4 | 5 | 3 | 0 | 82 | Kv within 3 % of target. Bench torque 2.98 N m on a 26 in prop (+24 %). 350 g. About 220 USD each. No sensor published. |
| 2 | MAD M6C12 IPE V3 KV170 | 4 | 5 | 3 | 4 | 0 | 72 | Torque 3.03 N m (+26 %), 51.5 A, 277 g. Kv is 23 % high. Reseller only and sold out. |
| 3 | MAD M6C12 IPE V3 KV150 | 4 | 5 | 2 | 4 | 0 | 68 | Torque 2.64 N m (+10 %), 277 g. The current limit of 36.2 A and the torque do not agree. Reseller only and sold out. |
| 4 | Vertiq 81-08 150KV (motor with built-in ESC) | 3 | 5 | 3 | 1 | 5 | 68 | 12S, 60 A, 315 g, embedded position sensor. Only 1.3 N m continuous stall torque is published, peak torque is not. Price 430 to 650 USD includes the ESC. |
| 5 | MAD M6C10 IPE V3 KV150 | 3 | 5 | 2 | 4 | 0 | 60 | Torque 2.38 N m has no margin. 234 g. Reseller only and sold out. |
| 6 | Hobbywing M8108 100KV | 2 | 5 | 4 | 2 | 0 | 56 | Torque 2.83 N m on a 28 in prop. Kv is 28 % low. No price. |
| 7 | T-Motor U8 Lite KV100 | 2 | 5 | 4 | 2 | 0 | 56 | Torque 2.42 N m on a 27 in prop. Kv is 28 % low. No KV100 price. |
| 8 | KDE Direct KDE7208XF-135 | 4 | 3 | 1 | 2 | 0 | 52 | Kv matches. Torque is derived, not published. The page is archived. |
| 9 | KDE Direct KDE6213XF-185 | 3 | 3 | 3 | 2 | 0 | 52 | 50 A continuous, 300 USD. Kv is 34 % high. Torque is derived. The maximum prop on 12S is 24.5 in. |
| 10 | T-Motor MN705-S KV125 | 5 | 2 | 5 | 3 | 0 | 74 | Hard fail: 450 g is above 400 g. Torque 3.29 N m is the highest. |
| 11 | T-Motor MN605-S KV170 | 1 | 4 | 5 | 5 | 0 | 54 | Hard fail: bench torque 2.06 N m is below 2.3 N m. |

### 2.3 ESCs

| Rank | ESC | Fit | Mass | Data | Price | Nice | Score | Reasons |
|---|---|---|---|---|---|---|---|---|
| 1 | KDE Direct KDE-UAS85UVC | 5 | 3 | 5 | 2 | 3 | 82 | 85 A, 4S to 14S LiHV, 110 g (150 g with wires). DroneCAN confirmed. Full maker page. 345 USD. No hall input published. |
| 2 | T-Motor FLAME 60A 12S V2.0 | 5 | 4 | 3 | 5 | 0 | 78 | 60 A, 99.99 USD, 73.5 g (reseller copy of the maker guide). No DroneCAN published. |
| 3 | T-Motor ALPHA 80A 12S | 5 | 3 | 4 | 4 | 0 | 76 | 80 A, 52.2 V input, 110 g, 129.99 USD. PWM only per T-Motor. |
| 4 | Zubax Myxa AD0505B (45 A) | 4 | 4 | 4 | 3 | 3 | 76 | 45 A, 13 to 51 V, 27 g (56 g with enclosure), FOC, DroneCAN variant. Maker recommends a newer part. No LiHV. |
| 5 | T-Motor ALPHA 60A 12S V1.2 | 4 | 4 | 4 | 4 | 0 | 72 | 60 A, 73 g, 109.99 USD. The 50.4 V limit leaves no margin. |
| 6 | T-Motor FLAME 80A 12S V2.0 | 5 | 3 | 3 | 4 | 0 | 72 | 80 A, 119.99 USD, 109 g (reseller copy). |
| 7 | Vertiq 81-08 (built-in ESC) | 3 | 5 | 3 | 1 | 5 | 68 | See motor rank 4. Counts for both motor and ESC. |
| 8 | MAD AMPX 60A (5-14S) | 3 | 3 | 3 | 5 | 3 | 64 | DroneCAN or Cyphal on V2.0, 99 USD. Current data conflict (40 A or 60 A). |
| 9 | T-Motor V80A 14S | 3 | 3 | 3 | 2 | 5 | 62 | CAN and PWM, encoder cable listed in the spec, 40 A continuous, 110 g. About 210 USD (reseller). |
| 10 | T-Motor FLAME 100A 14S | 5 | 1 | 2 | 4 | 0 | 60 | 100 A, 6 to 14S, mass not published. |
| 11 | T-Motor ALPHA 120A 12S | 5 | 1 | 2 | 3 | 0 | 58 | Oversize for a 36 A motor. Snippet data only. |
| 12 | Hobbywing XRotor Pro H80A 14S FOC | 3 | 3 | 2 | 2 | 2 | 52 | 40 A continuous, 87 g, CAN. Sold out and no price. DroneCAN is on the ArduPilot page only. |
| Hard fail | Hobbywing XRotor Pro H60A 14S FOC | 1 | 4 | 2 | 2 | 2 | 40 | 25 A continuous. |
| Hard fail | Hobbywing Platinum Pro 180A HV V5 | 5 | 0 | 2 | 2 | 0 | 52 | 250.6 g. |
| Hard fail | VimDrones ESC S50 | 0 | 1 | 2 | 2 | 3 | 22 | 6S only. |
| Hard fail | ARK 12S CAN ESC | 0 | 5 | 2 | 1 | 3 | 36 | Continuous current "TBD". |
| Not scored | Hargrave microDRIVE | - | - | - | - | - | - | Current, mass and price not published on the pages read. |

### 2.4 Batteries

Each score uses the arrangement with the energy nearest to 407 Wh. Pack data and arrangements are in section 5.

| Rank | Pack | Arrangement | Fit | Mass | Data | Price | Nice | Score | Reasons |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Tattu Plus 6S 10000 mAh smart (25C, 50C burst) | 2S1P, 2 packs | 5 | 3 | 3 | 2 | 5 | 78 | 444 Wh, 2932 g, 250 A continuous. Smart pack with a communication protocol. Only 2 packs. |
| 2 | SMC HCL-HV2 6S 2900 mAh 90C LiHV | 2S3P, 6 packs | 5 | 4 | 3 | 4 | 0 | 76 | 397 Wh, 2262 g, 175 Wh per kg. Sold out. LiHV charges to 52.2 V. |
| 3 | Tattu Plus 6S 12000 mAh smart (15C, 30C burst) | 2S1P, 2 packs | 4 | 3 | 3 | 2 | 5 | 70 | 533 Wh, 3280 g, 180 A continuous. 31 % more energy than needed. |
| 4 | Tattu R-Line 6S 4500 mAh 95C | 2S2P, 4 packs | 5 | 3 | 3 | 2 | 0 | 68 | 400 Wh, 2600 g, 855 A continuous. Backorder. |
| 4 | Tattu 4S 5200 mAh 35C | 3S2P, 6 packs | 5 | 4 | 2 | 2 | 0 | 68 | 462 Wh, 2619 g. Weight from an eBay listing. |
| 6 | Tattu R-Line V5.0 6S 1550 mAh | 2S6P, 12 packs | 5 | 2 | 3 | 2 | 0 | 64 | 413 Wh, 3048 g. 12 packs. |
| 6 | Tattu 6S 4500 mAh 25C | 2S2P, 4 packs | 5 | 3 | 2 | 2 | 0 | 64 | 400 Wh, 2440 to 2600 g (weight sources differ), 225 A continuous. |
| 8 | Tattu FunFly 6S 1300 mAh 100C | 2S7P, 14 packs | 5 | 1 | 4 | 1 | 0 | 62 | 404 Wh, 3150 g. 14 packs. |
| 9 | SMC HCL-HV2 6S 4000 mAh 90C LiHV | 2S2P, 4 packs | 3 | 4 | 3 | 4 | 0 | 60 | 365 Wh, 2112 g. 10 % short on energy. |
| 9 | Tattu R-Line V6 6S 1600 mAh | 2S6P, 12 packs | 5 | 1 | 3 | 2 | 0 | 60 | 426 Wh, 3360 g. 12 packs. |
| 11 | Tattu Plus 12S 10000 mAh 15C smart | 1 pack | 3 | 2 | 3 | 2 | 5 | 58 | 444 Wh, 2978 g. 150 A continuous is below 160 A. Burst not listed. One pack. |
| 12 | Tattu 6S 1400 mAh 75C | 2S7P, 14 packs | 5 | 1 | 2 | 2 | 0 | 56 | 435 Wh, 3360 g. Snippet data. |
| 13 | Tattu 6S 4200 mAh 35C | 2S2P, 4 packs | 4 | 2 | 2 | 2 | 0 | 52 | 373 Wh, 2620 g. Snippet data. |
| 14 | Tattu R-Line 6S 4000 mAh 95C | 2S2P, 4 packs | 3 | 2 | 3 | 1 | 0 | 46 | 355 Wh, 2664 g. 13 % short on energy. |
| Hard fail | Flywoo P45B 6S 4500 mAh Li-ion | 2S2P, 4 packs | 1 | 5 | 3 | 5 | 0 | 50 | 90 A continuous. Peak not published. 230 Wh per kg. |
| Hard fail | Flywoo P30B 6S 3000 mAh Li-ion | 2S3P, 6 packs | 1 | 5 | 3 | 4 | 0 | 48 | 105 A continuous. Peak not published. 225 Wh per kg. |
| Hard fail | Tattu semi-solid 6S 12000 mAh | 2S1P, 2 packs | 1 | 5 | 3 | 2 | 0 | 44 | 3C continuous (36 A), 10C for under 3 s (120 A). Below 160 A. |

### 2.5 Top three matched sets

Set score is the mean of the three component scores. Mass change is first order against the model (motors 4 x 310 g, ESCs 4 x 36 g, battery 2568 g). It ignores the effect on boom and structure. Cost counts only prices on the source pages. Prices in GBP are not converted.

| Set | Parts | Set score | Total mass of motors, ESCs, battery | First-order MTOW | Energy | Cost estimate | Nice-to-haves in the set |
|---|---|---|---|---|---|---|---|
| 1 | MN701-S KV135 x4, KDE-UAS85UVC x4, Tattu Plus 6S 10000 mAh 2S1P | 80.7 | 1400 + 600 (with wires) + 2932 = 4932 g | 13.58 + 0.98 = 14.56 kg | 444 Wh | Motors 879.96 USD (two 2-packs). ESCs 1380.00 USD. Battery price not published. Listed total 2259.96 USD plus battery. | DroneCAN ESC: yes. Smart battery: yes. Motor sensor: not published. ESC sensor input: not published. |
| 2 | MN701-S KV135 x4, ALPHA 80A 12S x4, SMC HCL-HV2 2900 mAh 2S3P | 78.0 | 1400 + 440 + 2262 = 4102 g | 13.58 + 0.15 = 13.73 kg | 397 Wh | Motors 879.96 USD. ESCs 519.96 USD. Battery 203.94 GBP. Listed total 1399.92 USD plus 203.94 GBP. | DroneCAN ESC: no (PWM only). Smart battery: not published. Sensor: not published. |
| 3 | Vertiq 81-08 150KV x4 (motor and ESC in one unit), Tattu Plus 6S 10000 mAh 2S1P | 71.3 | 1260 + 2932 = 4192 g | 13.58 + 0.24 = 13.82 kg | 444 Wh | Vertiq 1720 to 2600 USD (430 or 650 USD each, the page shows both). Battery price not published. | DroneCAN: yes on the 85 Kv G2 datasheet, 150 Kv not read. Position sensor: yes. DShot: yes. Smart battery: yes. |

Set 1 is the best on score and has DroneCAN. It leaves only 0.44 kg of mass margin. Set 2 has the best mass and cost but no nice-to-haves. Set 3 is the only set with a position sensor, but the peak torque of the Vertiq 150KV is not published.

## 3. Motors in detail

"Survey" means the motor is already in `tools/aerosandbox/data/motor_survey.csv`. The "Hall or encoder" column is "not published" when the page read does not mention a sensor.

| # | Maker, model | Kv | Mass g | Max current A | Max torque N m (condition) | Torque margin vs 2.4 | Current at 2.4 N m A | Cells | Size mm | Phase R mohm | No-load A | Prop | Price USD | Hall or encoder | Survey | Source |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | T-Motor MN701-S KV135 | 135 | 350 (with cable) | 42 peak 180 s, continuous not published | 2.98 (bench, G26x8.5, 46.6 V, 100 percent, 39.5 A) | +24 % | 34.8 | 6-12S | dia 79.2 x 37.4 | 94 | 0.9 at 20 V | 24-26 in, G26x8.5 | 439.98 per 2 (220 each) | not published | yes | https://store.tmotor.com/product/mn701-s-kv135-motor-navigator-type.html |
| 2 | MAD M6C12 IPE V3 KV170 | 170 | 277 | 51.5 max (type not stated) | 3.03 (maker table, condition not stated) | +26 % | 43.6 | 12S | dia 72 x 35.4 | 77 | 0.89 at 20 V | 21x6.3, 22x6.6, 22.1x7.4, 24x7.2 | 181.04 (sold out) | not published | no | https://rcdrone.top/de/products/mad-m6c12-ipe-v3-drone-motor-de (reseller) |
| 3 | MAD M6C12 IPE V3 KV150 | 150 | 277 | 36.2 max (type not stated) | 2.64 (maker table, condition not stated) | +10 % | 38.4 | 12S | dia 72 x 35.4 | 90 | 0.67 at 20 V | 21x6.3, 22x6.6, 22x7.0, 24x7.2 | 181.04 (sold out) | not published | no | https://rcdrone.top/de/products/mad-m6c12-ipe-v3-drone-motor-de (reseller) |
| 4 | Vertiq 81-08 150KV (motor, ESC and position sensor) | 150 | 315 | 60 continuous 10 s, 90 burst | not published (1.3 continuous, stalled, 180 s) | not published | 38.4 (calculated from Kv) | 12S (50.4 V) | dia 87.1 x 35.32 | not published | not published | 20 to 32 in (listing) | 430 or 650 (page shows both) | yes (embedded position sensor) | no | https://www.crowdsupply.com/iq-motion-control/iq-vertiq-8108 (maker partner, Crowd Supply) |
| 5 | MAD M6C10 IPE V3 KV150 | 150 | 234 | 36.3 max | 2.38 (maker table) | -1 % | 38.4 | 12S | dia 72 x 33.4 | 120 | 0.7 at 20 V | 21x6.3, 22x6.6, 22x7.0, 22.1x7.4, 24x7.2 | 177.90 (sold out) | not published | yes | https://rcdrone.top/de/products/m6c10-ipe-v3-burstenloser-drohnenmotor (reseller) |
| 6 | Hobbywing M8108 100KV | 100 | 271 (with 100 mm wire) | 34.3 max | 2.83 (pull test, GP28x9.2, 46 V, 100 percent, 29.9 A) | +18 % | 26.2 | 12S | dia 87.1 x 26.9 | 163.3 | 1.11 | GP28x9.2, GP29x9.5, ML30x9.8 | not published | not published | no | http://www.hobbywing.com/en/products/hm8108 |
| 7 | T-Motor U8 Lite KV100 | 100 | 238 (with cable) | 29.3 peak 180 s | 2.42 (bench, G27x8.8, 48 V, 100 percent, 26.0 A) and 2.73 (G28x9.2, 29.3 A) | +1 % and +14 % | 26.2 | 12S | dia 87.1 x 27.05 | 170 | 0.7 at 18 V | 27-28 in | not published for KV100 | not published | yes | https://store.tmotor.com/product/u8-lite-kv85-u-efficiency.html |
| 8 | KDE Direct KDE7208XF-135 | 135 | 380 (445 with wires) | 38 continuous 180 s, peak not published | not published (Kt x 38 A = 2.69, derived) | +12 % | 34.8 | 6S to 12S LiHV (52.2 V) | dia 80 x 42.5 | 113 (delta, phase to phase) | 0.4 at 10 V | KDE 27.5x8.9 (max 24.5 in on 12S) | not published (page archived) | not published | no | https://www.kdedirect.com/collections/uas-multi-rotor-brushless-motors/products/kde7208xf-135 |
| 9 | KDE Direct KDE6213XF-185 | 185 | 360 (415 with wires) | 50 continuous 180 s | not published (Kt 0.0516 x 50 A = 2.58, derived) | +7 % | 46.9 | 6S to 12S LiHV (52.2 V) | dia 70 x 42 | 72 (phase to phase) | 0.6 at 10 V | KDE 24.5x8.1 (max on 12S) | 300.00 | not published | no | https://www.kdedirect.com/collections/uas-multi-rotor-brushless-motors/products/kde6213xf-185 |
| 10 | T-Motor MN705-S KV125 | 125 | 450 (with cable) | 45 peak 180 s | 3.29 (bench, G26x8.5, 46.7 V, 100 percent, 36.4 A) | +37 % | 31.7 | 12S | dia 79.2 x 42.4 | 63 | 1.4 at 22 V | 26-27 in | 479.98 per 2 (240 each) | not published | yes | https://store.tmotor.com/product/mn705-s-kv125-motor-navigator-type.html |
| 11 | T-Motor MN605-S KV170 | 170 | 350 (with cable) | 35 peak 180 s | 2.06 (bench, P22x6.6, 47.0 V, 100 percent, 34.6 A) | -14 % | 43.6 | 6-12S | dia 68.8 x 34.9 | 65 | 1.0 at 20 V | 20-22 in, P22x6.6 | 279.98 per 2 (140 each) | not published | yes | https://store.tmotor.com/product/mn605-s-kv170-motor-navigator-type.html |

Fit notes:

1. MN701-S KV135: best overall fit. Real bench data on a 26 in prop. Mass is 40 g above the model and below 400 g.
2. M6C12 KV170: highest torque margin of the light motors. Kv is 23 percent high, so it draws about 8 A more at 2.4 N m.
3. M6C12 KV150: the current limit of 36.2 A gives (36.2 - 0.67) x 0.0637 = 2.26 N m. The maker table says 2.64 N m. The two numbers disagree. Ask MAD.
4. Vertiq 81-08 150KV: the module holds the motor, a 60 A ESC and a position sensor. It replaces one ESC. The Crowd Supply page gives 1.3 N m as the continuous stalled torque. The 2.4 N m peak has no source. The Vertiq 81-08 85 Kv G2 datasheet shows 292 g, 14S, 60 A, DroneCAN and DShot, and "propeller positioning capabilities". It is another Kv and another generation.
5. M6C10 KV150: already used on Redback. Torque has no margin.
6 and 7. Hobbywing M8108 100KV and U8 Lite KV100: light and strong at 27 to 28 in. Kv is 28 percent low and the rotor cannot reach the 4500 rpm design point on 26 in.
8. KDE7208XF-135: Kv matches. Torque is derived. The maker marks the page "archived".
9. KDE6213XF-185: Kv is 34 percent high and the maximum prop on 12S is 24.5 in.
10. MN705-S KV125: highest torque but 450 g is over the 400 g limit.
11. MN605-S KV170: bench torque 2.06 N m at 100 percent throttle on P22x6.6 is below target.

Other motors read but not ranked:

| Motor | Reason not ranked | Source |
|---|---|---|
| T-Motor MN705-S KV140 (475 g, 58 A peak, 3.72 N m with G26x8.5 at 5 deg C) | Mass over 400 g | https://store.tmotor.com/product/mn705-s-kv125-motor-navigator-type.html |
| KDE Direct KDE7215XF-135 (555 g, 45 A continuous, Kt 0.0707, 640 g with wires) | Mass over 400 g | https://www.kdedirect.com/collections/uas-multi-rotor-brushless-motors/products/kde7215xf-135 |
| MAD M8C08 8108 IPE V2.0 KV100 (283 g, 29 A, 2.553 N m, 27x8.1 prop) | Kv 100, same limit as the Hobbywing M8108 | https://rcdrone.top/it/products/mad-m8c08-8108-ipe-v2-0-motore-drone (reseller) |
| Hobbywing M8110 95KV (315 g, 43.2 A, 3.22 N m with ML30x9.8 at 46 V) | Kv 95, 30 in prop | http://www.hobbywing.com/en/products/hm8108 |
| T-Motor MN601-S KV170 (250 g, 30 A peak, 1.49 N m at P21x6.3) | Torque too low | https://store.tmotor.com/product/mn601-s-kv170-motor-navigator-type.html |
| Hobbywing XRotor X8 100KV | Motor and ESC are one unit and no official weight was found | https://www.hobbywing.com (page not found at the URL tried) |
| MAD AeroMax AM75 with encoder and PT1000 temperature sensor (dia 196.8 x 110 mm, stated thrust 70 to 80 kgf) | Far too large. It is the only MAD motor found with an encoder for propeller stop | https://ozrobotics.com/shop/mad-am75-heavy-lift-drone-motor-with-temperature-sensor-and-encoder-to-stop-propeller/ (snippet, reseller) |

## 4. ESCs in detail

Needs: 12S (50.4 V), continuous at least 40 A (50 to 80 A preferred), mass at most 150 g, ArduPilot compatible. The two nice-to-have columns say if the maker or ArduPilot pages confirm DroneCAN and a sensor or encoder input.

| # | Maker, model | Cells and voltage | Continuous A | Peak A | Mass g | Size mm | Protocol | Telemetry | DroneCAN | Sensor or encoder input | Price USD | Source |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | KDE Direct KDE-UAS85UVC | 4S LiPo to 14S LiHV (14.8 to 60.9 V) | 85 (180 s, with airflow) | 175 for 5 s | 110 (150 with wires and bullets) | 46 x 71 | CAN, PWM | live telemetry over CAN, EEPROM log of voltage, current, temperature, eRPM | yes (DroneCAN quickstart on page, listed on ArduPilot KDE page) | not published | 345.00 | https://www.kdedirect.com/products/kde-uas85uvc and https://ardupilot.org/plane/docs/common-kde-can-escs.html |
| 2 | T-Motor FLAME 60A 12S V2.0 | 6-12S LiPo | 60 | 80 for 10 s | 73.5 (snippet, T-Motor guide via reseller) | 66.5 x 38.5 x 17.7 (snippet) | not listed | not listed | not published | not published | 99.99 | https://store.tmotor.com/product/flame-60a-12s-V2-esc.html |
| 3 | T-Motor ALPHA 80A 12S | 12S, 18-52.2 V | 80 | 100 for 10 s | 110 (with cables) | 88.5 x 36.6 x 19 | PWM 1100-1940 us at 500 Hz, DShot not published | not listed | no (T-Motor blog lists PWM only) | not published | 129.99 | https://store.tmotor.com/goods.php?id=584 and https://uav-en.tmotor.com/blog/industrial-drone-esc-pwm-vs-drone-can-guide.html |
| 4 | Zubax Myxa AD0505B (45 A variant) | 13-51 V (Li-ion 4-12S) | 45 (37 for the A variant, 1200 W continuous power) | not published | 27 bare, 56 with enclosure | 55 x 35 x 20 | DroneCAN ("Telega v0") and Cyphal variants | not explicitly stated | yes | not mentioned | EUR 149 (A0) to EUR 193 (B2Z) | https://shop.zubax.com/products/zubax-myxa |
| 5 | T-Motor ALPHA 60A 12S V1.2 (FOC) | 12S, 18-50.4 V | 60 | 80 | 73 (with cables) | 78.7 x 32.5 x 16.2 | PWM 1100-1940 us at 500 Hz, DShot not published | not listed | no (PWM only) | not published | 109.99 | https://store.tmotor.com/product/alpha-60a-12s-esc.html |
| 6 | T-Motor FLAME 80A 12S V2.0 | 6-12S LiPo | 80 | 120 for 10 s | 109 (reseller manual copy) | 84 x 35.5 x 19.5 (reseller) | not listed on maker page, 600 Hz refresh (reseller) | not listed | not published | not published | 119.99 | https://store.tmotor.com/product/flame-80a-12s-V2-esc.html and https://robu.in/product/t-motor-flame-80a-12s-v2-0-esc/ (reseller) |
| 7 | MAD AMPX 60A (5-14S), V2.0 CAN | 5-14S, 16-64 V | 60 on the MAD store title. 40 with a 48 A limit on the reseller page | not listed | 111 (without wires, reseller) | 71 x 31.44 x 15.8 (reseller) | PWM and CAN | voltage, current, temperature, status over CAN | yes (DroneCAN or CyphalCAN, V2.0) | not mentioned | 99.00 (MAD store). 145.00 reseller, sold out | https://mad-motor.com/products/mad-ampx-esc-60a-5-14s-wbox and https://rcdrone.top/it/products/mad-ampx-60a-5-14s-drone-esc-support-pwm-can (reseller) |
| 8 | T-Motor V80A 14S (FOC) | 6-14S, 18-60 V | 40 (cooling needed) | 80 for 10 s (snippet) | 78 without cables, 110 with cables | 84 x 34.4 x 19 | PWM and CAN, 50-500 Hz | data feedback: yes | yes (T-Motor blog lists "DRONE CAN/PWM", the spec PDF says only "PWM&CAN") | yes (the spec PDF lists an encoder cable with an M6 aviation connector) | about 209.86 (reseller, sold out) | https://store.tmotor.com/images/file/202506/061749196106720896.pdf and https://uav-en.tmotor.com/blog/industrial-drone-esc-pwm-vs-drone-can-guide.html |
| 9 | T-Motor FLAME 100A 14S | 6-14S LiPo | 100 | 120 for 10 s | not published | not published | 500 or 600 Hz PWM (resellers differ) | not listed | not published | not published | 129.99 (snippet) | https://www.ligpower.com/product/flame-100a-14s-esc.html (snippet, reseller) |
| 10 | T-Motor ALPHA 120A 12S | 6-12S LiPo | 120 (store snippet), 100 (T-Motor blog table) | not read | not read | not read | PWM 500 Hz | not read | no (PWM only per blog) | not published | 169.99 (snippet) | https://uav-en.tmotor.com/Multirotor/ESC (snippet) and the T-Motor blog above |
| 11 | Hobbywing XRotor Pro H80A 14S FOC | 6-14S, 18-63 V | 40 | 80 | 87 (without wires) | 84 x 35 x 20 | PWM 50-500 Hz and CAN (custom serial port) | status, speed, throttle, current, voltage via DataLink | listed as a DroneCAN ESC on the ArduPilot Hobbywing page, but the maker page says only "CAN (Custom Serial port)" | not published | not published (sold out) | https://www.hobbywingdirect.com/products/eps-esc-foc-h80 and https://ardupilot.org/copter/docs/common-hobbywing-dronecan-esc.html |
| 12 | Vertiq 81-08 (ESC built into the motor) | 4-14S, 12-60 V (85 Kv G2 datasheet) | 60 | 90 burst (150 Kv listing) | included in motor mass | included | DroneCAN, DShot 150-1200, PWM, UART, OneShot, Multishot | standard and custom telemetry, motor health | yes (85 Kv G2 datasheet) | yes (position sensor, propeller positioning) | see motor row 4 | https://www.unmannedsystemstechnology.com/wp-content/uploads/2022/08/81-08_85Kv_G2_datasheet.pdf and https://docs.px4.io/main/en/peripherals/vertiq.html |
| 13 | Hobbywing XRotor Pro H60A 14S FOC | 12-14S, 44-63 V | 25 (with good cooling) | 60 for 3 s | 73 (without wires) | 75 x 35.5 x 20.3 | PWM 50-500 Hz and CAN (Hobbywing protocol) | status over DataLink, ESC telemetry not specified | not on the maker page, listed on the ArduPilot Hobbywing page | not published | not published | https://www.hobbywing.com/en/products/xrotor-h60a-14s-foc--bldc-v1126 |
| 14 | Hobbywing Platinum Pro 180A HV V5 | 6-14S | 180 | 260 | 250.6 (with cables) | 100.6 x 45.5 x 26.1 | PWM | not read | not published | not published | not read | https://originhobbies.com/shop/esc-speed-controllers/hobbywing-platinum-180a-v5-hv-esc-14s-sbec-12v-10a-hw30209103/ (snippet, reseller) |
| 15 | VimDrones ESC S50 (AM32) | 2-6S only | 50 (cooling needed above 30 A) | not published | not published | 40 x 17 board | DroneCAN (CAN version), DShot or PWM (standard version) | RPM, voltage, current, temperature | yes | not published | not published | https://dev.vimdrones.com/products/vimdrones_esc_s50/ |
| 16 | ARK 12S CAN ESC | 4-12S, 9-70 V absolute | "TBD" (thermal validation incomplete) | "TBD" | 22 | 57.75 x 36.2 x 9.04 | CAN FD with DroneCAN firmware, also PWM and DShot | serial telemetry and analog current out | yes | not published | 399.00 (out of stock) | https://arkelectron.com/product/ark-12s-can-esc/ |
| 17 | Hargrave Technologies microDRIVE | 15-60 V (snippet) | not published | not published | not published | not published | DroneCAN | primary and extended status including motor angle | yes (ArduPilot page) | yes (ArduPilot page: motor angle needs external position sensing. A snippet says the MP model has hall inputs) | not published | https://ardupilot.org/plane/docs/common-hargrave-dronecan-escs.html |

Notes:

- Rows 1 to 9 meet the electrical need. Row 8 has only 40 A continuous. Rows 3 and 5 are FOC ESCs for multirotors.
- Row 7 conflicts: the MAD store title says 60 A and the reseller page says 40 A continuous. Ask MAD.
- No fetched maker page confirms DShot on a 12S ESC of 40 A or more. ArduPilot states that DShot must only be used on ESCs known to support it. Source: https://ardupilot.org/copter/docs/common-dshot-escs.html. Use PWM until the maker confirms.
- The ArduPilot DroneCAN ESC list names: AM32 ESCs, Currawong Velocity, Hargrave, Hobbywing CAN, Holybro Kotleta20, KDE UVC, Zubax Mitochondrik, Zubax Myxa and Zubax Orel 20. Source: https://ardupilot.org/plane/docs/common-uavcan-escs.html. I did not read the Currawong, Holybro, Mitochondrik or Orel pages.
- The XC-ESC U60 (5-14S, 60 A) lists a "CAN" interface but the snippet does not name DroneCAN. Source: https://www.xc-esc.com/product/u60-esc-for-drones-and-uav/ (snippet).
- Peak ratings last 3 to 10 s. The 160 A battery peak lasts a few seconds. Check the duration with the maker.

## 5. Battery packs

The pack energy limit is removed. Wh = nominal voltage x rated capacity (calculated). The weights marked "snippet" come from search-result text.

### 5.1 Pack data

| # | Maker, model | S | mAh | Nominal V | Wh | Mass g | Continuous C | Burst C | Continuous A per pack | Connector | Chemistry | Smart | Price | Source |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Tattu Plus 6S 10000 mAh | 6S1P | 10000 | 22.2 | 222 | 1466 (+/-20) | 25 | 50 | 250 (calculated) | not specified | LiPo | yes (communication protocol, status indicator, alerts) | not published | https://www.grepow.com/product-news/tattu-plus-6s-smart-lipo-battery-for-drone.html |
| 2 | SMC HCL-HV2 2900 mAh 90C | 6S | 2900 | 22.8 | 66.1 | 377 | 90 | not published | 261 (calculated) | XT60 | LiHV | not published | 33.99 GBP (sold out) | https://www.unmannedtechshop.co.uk/de/products/smc-hcl-hv2-flight-22-8v-6s-2900mah-90c-lipo-battery-xt60 (reseller) |
| 3 | Tattu Plus 6S 12000 mAh | 6S1P | 12000 | 22.2 | 266.4 | 1640 (+/-20) | 15 | 30 | 180 (calculated) | not specified | LiPo | yes | not published | https://www.grepow.com/product-news/tattu-plus-6s-smart-lipo-battery-for-drone.html |
| 4 | Tattu R-Line 4500 mAh 95C | 6S1P | 4500 | 22.2 | 99.9 | 650 (+/-20) | 95 | 190 | 428 (calculated) | XT90-S | LiPo | not published | 128.00 USD (backorder) | https://nextfpv.com/products/tattu-r-line-4500mah-95c-6s1p-lipo-battery-pack-with-xt90s-plug-for-uav |
| 5 | Tattu 4S 5200 mAh 35C | 4S | 5200 | 14.8 | 77.0 | 436.5 (+/-20, eBay listing) | 35 | 70 (snippet) | 182 (calculated) | XT60 | LiPo | not published | not read | https://ca.wrekd.com/collections/batteries-chargers/products/tattu-14-8v-4s-5200mah-35c-lipo-battery-xt60 (reseller, page truncated) |
| 6 | Tattu R-Line V5.0 1550 mAh | 6S | 1550 | 22.2 | 34.4 | 254 (+/-20) | 150 (one figure) | not split | 233 (calculated) | XT60 | LiPo | not published | 36.95 GBP | https://www.unmannedtechshop.co.uk/products/tattu-r-line-version-5-0-1550mah-22-2v-150c-6s-lipo-battery-pack-with-xt60-plug (reseller) |
| 7 | Tattu 6S 4500 mAh 25C | 6S1P | 4500 | 22.2 | 99.9 | 610 or 650 (two snippets differ) | 25 | 50 (snippet) | 113 (calculated) | XT90 | LiPo | not published | not read | https://thinkrobotics.com/collections/buy-batteries-and-battery-chargers-online/products/tattu-22-2v-6s-25c-lipo-battery-pack (snippet) and https://www.gensace.de/tattu-4500mah-22-2v-25c-6s1p-lipo-battery-pack-with-xt90.html (page gave HTTP 404) |
| 8 | Tattu FunFly 1300 mAh 100C | 6S1P | 1300 | 22.2 | 28.9 | 225 (+/-20) | 100 | 200 | 130 (calculated) | XT60 | LiPo | not published | 39.49 USD | https://wrekd.com/products/tattu-funfly-22-2v-6s-1300mah-100c-lipo-battery-xt60 (reseller) |
| 9 | SMC HCL-HV2 4000 mAh 90C | 6S | 4000 | 22.8 | 91.2 | 528 | 90 | not published | 360 (calculated) | XT90 | LiHV | not published | 44.99 GBP (sold out) | https://www.unmannedtechshop.co.uk/de/products/smc-hcl-hv2-flight-22-8v-6s-4000mah-90c-lipo-battery-xt90 (reseller) |
| 10 | Tattu R-Line V6 1600 mAh | 6S | 1600 | 22.2 | 35.5 | about 280 | 150 (spec list) | 160 in title | 240 (calculated) | XT60 | LiPo | not published | 34.50 GBP | https://www.unmannedtechshop.co.uk/products/tattu-r-line-v6-1600mah-6s-160c-lipo-battery-with-xt60-st (reseller) |
| 11 | Tattu Plus 12S 10000 mAh (compact) | 12S1P | 10000 | 44.4 | 444 | 2978 (+/-20) | 15 | not listed | 150 (calculated) | AS150U | LiPo | yes ("smart battery pack" in the product name) | 465.00 USD sale (backorder) | https://www.nextfpv.com/products/tattu-plus-1-0-compact-version-10000mah-44-4v-15c-12s1p-lipo-smart-battery-pack-with-as150uplug |
| 12 | Tattu 6S 1400 mAh 75C | 6S | 1400 | 22.2 | 31.1 | 240 (snippet) | 75 | 150 | 105 (calculated) | not read | LiPo | not published | not read | https://www.getfpv.com/tattu-1400mah-6s-75c-lipo-battery.html (snippet, page gave HTTP 403) |
| 13 | Tattu 6S 4200 mAh 35C | 6S | 4200 | 22.2 | 93.2 | 655 (snippet) | 35 | 50 | 147 (calculated) | XT60 | LiPo | not published | not read | https://www.getfpv.com/tattu-4200mah-6s-35c-lipo-battery.html (snippet, page gave HTTP 403) |
| 14 | Tattu R-Line 4000 mAh 95C | 6S1P | 4000 | 22.2 | 88.8 | 666 (+/-40) | 95 | 190 | 380 (calculated) | AS150 | LiPo | not published | 135.00 USD (backorder) | https://nextfpv.com/hr/products/tattu-r-line-4000mah-95c-6s1p-lipo-battery-pack-with-as150-connector |
| 15 | Flywoo Explorer Molicel P45B 4500 mAh | 6S1P | 4500 | 22.2 | 99.9 | 433.7 | not stated | not published | 45 (stated) | XT60 | Li-ion 21700 | not published | 37.95 GBP (sold out) | https://www.unmannedtechshop.co.uk/fr/products/flywoo-explorer-molicell-p45b-21700-6s1p-4500mah-lionpack-battery (reseller) |
| 16 | Flywoo Explorer Molicel P30B 3000 mAh | 6S1P | 3000 | 22.2 | 66.6 | 295.7 | not stated | not published | 35 (stated) | XT60 | Li-ion 18650 | not published | 39.50 GBP (sold out) | https://www.unmannedtechshop.co.uk/products/flywoo-explorer-molicell-p30b-18650-6s1p-3000mah-lionpack-battery (reseller) |
| 17 | Tattu semi-solid 12000 mAh | 6S1P | 12000 | 22.2 | 266.4 | 800 | 3 | 10 for under 3 s | 36 continuous, 120 for under 3 s (calculated) | XT90S-F | semi-solid LiPo | not published | 267.34 EUR (out of stock) | https://gensace.de/de/products/tattu-semi-solid-state-380wh-kg-12000mah-10c-22-2v-6s1p-lipo-battery-pack-with-xt90s-f-plug |

Notes on conflicts:

- The gensace page for the semi-solid 12000 mAh pack says 380 Wh per kg and 800 g. 266.4 Wh / 0.800 kg = 333 Wh per kg. The two figures do not agree. A search snippet gave 580 g. The page value of 800 g is used.
- The Tattu 6S 4500 mAh 25C weight is 610 g in one snippet and 650 g in another. Both are used as a range.

### 5.2 12S arrangements

Target: 12S, about 9.2 Ah, 407 Wh, 160 A peak, hover 33 A. Mass reference: 2568 g (model). Energy error is against 407 Wh. "Meets 160 A" uses the continuous current of the arrangement, or the burst current when it is the only published value (marked).

| # | Pack | Arrangement | Packs | 12S Ah | Total Wh | Total mass g | Wh per kg | Continuous current of the arrangement A | Meets 160 A peak | Note |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Tattu Plus 6S 10000 | 2S1P | 2 | 10.0 | 444 | 2932 | 151 | 250 (500 burst) | yes | +9 % energy. Smart packs |
| 2 | SMC HCL-HV2 2900 | 2S3P | 6 | 8.7 | 397 | 2262 | 175 | 783 | yes | -2.5 % energy. LiHV charges to 52.2 V |
| 3 | Tattu Plus 6S 12000 | 2S1P | 2 | 12.0 | 533 | 3280 | 162 | 180 (360 burst) | yes | +31 % energy. Smart packs |
| 4 | Tattu R-Line 4500 95C | 2S2P | 4 | 9.0 | 399.6 | 2600 | 154 | 855 | yes | -1.8 % energy |
| 5 | Tattu 4S 5200 | 3S2P | 6 | 10.4 | 462 | 2619 | 176 | 364 | yes | +13 % energy |
| 6 | Tattu R-Line V5 1550 | 2S6P | 12 | 9.3 | 413 | 3048 | 135 | 1395 | yes | 12 packs |
| 7 | Tattu 6S 4500 25C | 2S2P | 4 | 9.0 | 399.6 | 2440 to 2600 | 154 to 164 | 225 (450 burst, snippet) | yes | -1.8 % energy |
| 8 | Tattu FunFly 1300 | 2S7P | 14 | 9.1 | 404 | 3150 | 128 | 910 | yes | 14 packs |
| 9 | SMC HCL-HV2 4000 | 2S2P | 4 | 8.0 | 365 | 2112 | 173 | 720 | yes | -10 % energy |
| 10 | Tattu R-Line V6 1600 | 2S6P | 12 | 9.6 | 426 | 3360 | 127 | 1440 | yes | 12 packs |
| 11 | Tattu Plus 12S 10000 | single pack | 1 | 10.0 | 444 | 2978 | 149 | 150 | marginal (94 %), burst not listed | One pack, no series link |
| 12 | Tattu 6S 1400 75C | 2S7P | 14 | 9.8 | 435 | 3360 | 129 | 735 | yes | 14 packs |
| 13 | Tattu 6S 4200 35C | 2S2P | 4 | 8.4 | 373 | 2620 | 142 | 294 | yes | -8 % energy |
| 14 | Tattu R-Line 4000 95C | 2S2P | 4 | 8.0 | 355 | 2664 | 133 | 760 | yes | -13 % energy. 2S3P gives 533 Wh and 3996 g |
| 15 | Flywoo P45B 4500 | 2S2P | 4 | 9.0 | 399.6 | 1735 | 230 | 90 | no on published data | 2S4P (8 packs, 799 Wh, 3470 g) reaches 180 A but has twice the energy |
| 16 | Flywoo P30B 3000 | 2S3P | 6 | 9.0 | 400 | 1774 | 225 | 105 | no on published data | 160 A is 1.5 times the continuous rating. Peak not published |
| 17 | Tattu semi-solid 12000 | 2S1P | 2 | 12.0 | 533 | 1600 | 333 | 36 (120 for under 3 s) | no | Hover (33 A) is within the 3C rating. Peak is below 160 A |

LiHV note: a 12S LiHV pack charges to 52.2 V. An ESC rated 50.4 V does not accept this. Of the ESCs above, the ALPHA 80A page states 52.2 V input. The KDE-UAS85UVC states 60.9 V. The Zubax Myxa states 51 V maximum, which is below 52.2 V.

## 6. Nice-to-have findings

### 6.1 DroneCAN on the ESC

| ESC | DroneCAN | Source |
|---|---|---|
| KDE-UAS85UVC (85 A, 14S) | yes | https://www.kdedirect.com/products/kde-uas85uvc and the KDE blog https://www.kdedirect.com/blogs/news/kde-direct-adds-dronecan-to-uvc-series-escs. KDE added DroneCAN to the UVC firmware. The blog names no model. The ArduPilot KDE page lists KDE-UAS125UVC-HE and KDE-UAS85UVC |
| Zubax Myxa AD0505A/B (37 or 45 A, 4-12S) | yes ("Telega v0 (DroneCAN)" variants) | https://shop.zubax.com/products/zubax-myxa |
| MAD AMPX 60A V2.0 (5-14S) | yes (DroneCAN or CyphalCAN) | https://mad-motor.com/products/mad-ampx-esc-60a-5-14s-wbox |
| T-Motor V80A 14S (40 A) | yes in the T-Motor blog ("DRONE CAN/PWM"). The spec PDF says only "PWM&CAN" | https://uav-en.tmotor.com/blog/industrial-drone-esc-pwm-vs-drone-can-guide.html |
| T-Motor V150A 14S (70 A) | yes in the same blog | the same blog. The V150A page was not read |
| Vertiq 81-08 (built-in ESC) | yes on the 85 Kv G2 datasheet. The PX4 page says only the larger modules have DroneCAN | https://docs.px4.io/main/en/peripherals/vertiq.html |
| Hargrave microDRIVE | yes | https://ardupilot.org/plane/docs/common-hargrave-dronecan-escs.html |
| ARK 12S CAN ESC | yes, but continuous current is "TBD" | https://arkelectron.com/product/ark-12s-can-esc/ |
| Hobbywing XRotor Pro H80A and H60A | ArduPilot lists "Hobbywing CAN ESCs" as DroneCAN. The maker page says "CAN (Custom Serial port)". Order the CAN version | https://ardupilot.org/copter/docs/common-hobbywing-dronecan-esc.html |
| T-Motor ALPHA 60A, ALPHA 80A, ALPHA 120A, FLAME series | no or not published (the blog lists the ALPHA series as PWM) | https://uav-en.tmotor.com/blog/industrial-drone-esc-pwm-vs-drone-can-guide.html |
| Holybro Kotleta20 | listed by ArduPilot as DroneCAN. Current and voltage not read | https://ardupilot.org/plane/docs/common-uavcan-escs.html |

The ArduPilot page says the autopilot logs DroneCAN ESC telemetry (voltage, current, temperature, RPM, error count, power) in CESC messages. Source: https://ardupilot.org/plane/docs/common-uavcan-escs.html.

Only three DroneCAN ESCs meet 40 A continuous and 12S on the pages read: KDE-UAS85UVC (85 A), MAD AMPX 60A V2.0 (60 A on its store title, 40 A on the reseller page) and T-Motor V80A 14S (40 A). The Zubax Myxa B (45 A) meets the current but is limited to 51 V.

### 6.2 Hall sensor or encoder

| Item | Hall or encoder | What it gives | Source |
|---|---|---|---|
| Vertiq 81-08 (150KV and 85Kv G2) | yes, embedded position sensor | Sensored control at any speed, propeller positioning, optional multi-turn angle firmware | https://www.crowdsupply.com/iq-motion-control/iq-vertiq-8108 and the 85 Kv G2 datasheet |
| T-Motor V80A 14S ESC | yes, an encoder cable with an M6 aviation connector is in the spec | The page does not say what the encoder is used for | https://store.tmotor.com/images/file/202506/061749196106720896.pdf |
| Hargrave microDRIVE ESC | yes, external motor position sensing. A snippet says the MP model has hall inputs | The ESC reports motor angle in the DroneCAN extended status. The motor angle needs external position sensing | https://ardupilot.org/plane/docs/common-hargrave-dronecan-escs.html |
| MAD AeroMax AM75 with encoder | yes, magnetic encoder to lock the propeller at a stop position. Needs compatible ESC firmware | Too large for this aircraft (dia 196.8 mm) | https://ozrobotics.com/shop/mad-am75-heavy-lift-drone-motor-with-temperature-sensor-and-encoder-to-stop-propeller/ (snippet, reseller) |
| T-Motor MN, U8 and MAD M6 motors, KDE XF motors, Hobbywing M8108 | not published | The pages read do not mention a hall sensor or an encoder | the motor pages in section 3 |
| Zubax Myxa, KDE-UAS85UVC | not published | The pages read do not mention a hall input | the ESC pages in section 4 |

What I did not find:

- No page says that ArduPilot uses a motor hall sensor or encoder for a propeller stop position on a multirotor. The ArduPilot RPM page lists hall sensors as an RPM source only. Source: https://ardupilot.org/plane/docs/common-rpm.html (snippet).
- No standard 26 in class outrunner (T-Motor, MAD M6, KDE, Hobbywing) was found with a hall or encoder option.
- To get a sensor and DroneCAN at the target size, the options found are the Vertiq module or an ESC with an encoder input (V80A, Hargrave) paired with a custom sensor. Both need a check with the maker.

## 7. Notes on the sets

- Set 1 mass: motors 4 x 350 g = 1400 g (+161 g over model), ESCs 4 x 150 g with wires = 600 g (+455 g), battery 2932 g (+364 g). Net +980 g.
- Set 2 mass: motors +161 g, ESCs 4 x 110 g = 440 g (+295 g), battery 2262 g (-306 g). Net +150 g. The ALPHA 80A takes the 52.2 V of the LiHV pack.
- Set 3 mass: Vertiq 4 x 315 g = 1260 g replaces motors and ESCs of 1384 g in the model (-124 g). Battery +364 g. Net +240 g.
- A set that uses the MAD M6C12 KV170 (277 g) saves 131 g over the MN701-S set. The motor is sold out at the reseller.

## 8. Gaps and risks

Data not published:

- The KDE motors have no published torque. The values in the table come from Kt x current. Ask KDE for torque curves.
- MAD publishes one current figure per motor and does not say if it is continuous or peak. The M6C12 KV150 current and torque do not agree.
- T-Motor motor pages give peak current for 180 s. They do not give continuous current.
- The Vertiq 81-08 150KV has no published peak torque, no phase resistance and no 150 Kv datasheet in the pages read. The Crowd Supply page shows 430 USD in one table and 650 USD in the listing.
- ESC protocol: no maker page for the T-Motor 12S ESCs names DShot. Weights for FLAME 60A, FLAME 80A and FLAME 100A are not on the maker page. The FLAME 100A weight was not found.
- Battery: SMC does not publish a burst C rating. The Tattu Plus 6S pages give no price and no connector. The Tattu 4S 5200, 6S 4200 and 6S 1400 pages could not be read (truncated or HTTP 403). Weights for those come from snippets and one eBay listing.
- The MAD maker site (madcomponents.co) has a bad certificate. Most MAD motor data comes from reseller rcdrone.top.
- The T-Motor V80A PDF text was garbled in part. The DroneCAN claim comes from the T-Motor blog table. The peak current of 80 A for 10 s comes from a snippet.
- Currawong Velocity, Holybro Kotleta20, Zubax Mitochondrik and Zubax Orel 20 are listed by ArduPilot as DroneCAN ESCs. I did not read their pages for current and voltage.

Items to verify with the maker:

1. MN701-S KV135 continuous current at 12S with a 26 in prop, and the thermal limit at 85 N thrust.
2. KDE-UAS85UVC: DroneCAN firmware version, the 150 g mass with wires, and a hall or encoder input.
3. Vertiq 81-08 150KV: peak torque, 12S or 14S rating, DroneCAN on this Kv, and price.
4. ALPHA 80A: DShot support, telemetry output, and the 52.2 V input limit under regenerative braking.
5. SMC HCL-HV2: real discharge rate, burst rate and the 4.35 V per cell charge limit.
6. Tattu Plus packs: connector, price and the communication protocol (SMBus or CAN) for ArduPilot.
7. Stock and lead time: most packs and some motors show "sold out" or "backorder".

Technical risks:

- Peak battery current. The model peak is about 160 A. The Li-ion packs (Flywoo) are rated 35 to 45 A continuous per pack. Use them only if the cell maker confirms the peak.
- The semi-solid pack allows 10C for under 3 s. That is 120 A for the 12 Ah arrangement. The pack cannot meet the 160 A peak alone.
- Tattu Plus 12S 10000 mAh is rated 15C continuous (150 A). The peak of 160 A is above this.
- Voltage sag. Many small parallel strings share the load unevenly. Match the packs and keep the same age and internal resistance.
- Series and parallel assembly of lithium packs needs a balance and protection plan. A parallel string with a failed cell can drive current into the failed pack. Use a fuse or diode scheme from the pack maker.
- Mass. The ESCs are at least 37 g heavier each than the 36 g model value, except the Zubax and ARK parts. Update the model before the next solve.
- Kv. A Kv 100 motor (Hobbywing M8108, U8 Lite) cannot reach the 4500 rpm design point on 26 in.
- Scores are my judgement. Change a score and the rank can change. The top parts (MN701-S, KDE-UAS85UVC, Tattu Plus 6S, SMC 2900) stay in the top group for small changes of one point.

Shipping and regulation notes for lithium packs:

- The airline limit for one battery is set by pack energy. Calculate it as nominal voltage x rated capacity. Check the carrier rules for each pack. Many packs here are above 100 Wh.
- One reseller page says that batteries cannot ship by air (nextfpv). Plan ground shipment. Check UN38.3 test reports and the carrier rules for each pack.
- Li-ion packs (Flywoo) and semi-solid packs need the same UN38.3 test summary.
- Spare packs on airlines are limited by pack energy and by count. A set of 6 spare packs may exceed the limit. Check the airline before travel.
- Installed packs in an aircraft are a separate case from spare packs. Check the rule of the carrier and of the authority for the flight.
