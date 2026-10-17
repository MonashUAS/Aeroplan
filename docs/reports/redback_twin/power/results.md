# Redback twin: power and battery against the flight logs

Step 5A of the Redback twin plan. The numbers are in `results.json` in this folder. The scan of all logs is in `batt_monitor_scan.csv`.

## Sources

- Log: `00000171.BIN`, sha256 215616e25dd4532d0256e1ae4e9572d2cd73d8774ea1ae4c4b2642549ef0a57d. ArduCopter 4.7.0, CubeOrangePlus, QUAD/X.
- Parameters: `00000171_log.parm`, sha256 3592de49e0fa3bedf37e3baac96ad93658b6368cd131ed73b0e359bcdaee3e13. The first logged value of each name.
- Package: Redback 0.2.0 aerolink profile, package hash 2cc698f0e41b692d. The mass is 9.134 kg from the weight sheet. The aircraft was not weighed for this flight.
- EMST and model values: `multirotor_results.json` of the AeroPlan 0.2.0 build, sha256 f508ab84f67010658f0498465fb96deae950469539ac1758ee8032f7d1bdb66c.
- User facts for flight 00000171: the pack start voltage is 4.2 V per cell (full charge). The rest voltage after the flight is 23.1 V for each 6S battery. The air temperature at the site is 40 C. The ESCs are PWM ESCs.
- Scan: 66 logs in the fleet data folder of the user (`.BIN` and `.bin` files, 831 MB), read with `tools/scan_batt_monitor.py`. Nothing in that folder was changed.
- Time in this report for flight 00000171 is log time. Zero is the first log message (boot time 461.3 s). The takeoff is at 5.4 s. The RTL starts at 732.4 s. The disarm is at 867.0 s.

## Main findings

1. **No log of the fleet has a working current sensor.** Flight 00000171 has no usable pack voltage or current. The scan shows the same for the 65 other logs. So no log gives an electrical power. The model factors cannot be measured from a log today.
2. **The pack voltage worked on battery instance 1 in 19 logs** (five of 2026-05-13 and 14 of 2026-07-10 to 2026-07-24). The current there is 0 A. These logs give the voltage and the sag. They give no power.
3. **The motor command matches the model.** The logged hover command is 0.605. The model command at the site density (40 C) is about 0.611. The command at speed does not match: the log command is 7 % lower than the model at 16.7 m/s.
4. **An energy bracket for flight 00000171** (start 4.2 V per cell, end 3.85 V per cell) gives a mean power of 921 to 950 W over the flight. The maker model gives 1041 W in hover and 1107 W over the mission mix, both at 40 C. Most models are 6 to 20 % above the bracket. The data do not support the expectation that the maker understates the power. A table error of 4 to 6 points of SOC would remove the gap.
5. **The motor library of flight 00000171 held its voltage compensation at the lower limit** because the battery monitor read 16 V. This sets the ArduCopter command map of the twin.

## Segments of flight 00000171

Written to `tools/ardupilot/settings/redback.yaml` (13 segments, log time). The speed is the EKF ground speed. The aircraft has no airspeed sensor, so the wind is not known.

| Segment | Start (s) | End (s) | Ground speed (m/s) | Climb (m/s) | Mean actuator |
|---|---|---|---|---|---|
| ground_prestart | 0.0 | 5.4 | 0.0 | 0.0 | 0.086 |
| takeoff_climb | 8.5 | 50.0 | 0.1 | 2.6 | 0.604 |
| cruise_transit_92m | 55.0 | 328.0 | 16.7 | 0.0 | 0.596 |
| descent_to_survey | 334.0 | 366.0 | 0.2 | -1.6 | 0.521 |
| hover_1 | 366.4 | 378.8 | 0.1 | 0.0 | 0.611 |
| hover_2 | 379.5 | 385.7 | 0.1 | 0.0 | 0.586 |
| cruise_survey_52m | 388.0 | 726.0 | 5.9 | 0.0 | 0.602 |
| hover_3 | 728.3 | 733.3 | 0.1 | 0.0 | 0.620 |
| climb_rtl | 734.2 | 745.9 | 0.1 | 2.6 | 0.678 |
| cruise_rtl | 750.0 | 790.0 | 10.0 | 0.0 | 0.614 |
| hover_4 | 797.3 | 800.8 | 0.2 | -0.1 | 0.601 |
| descent_landing | 801.0 | 858.0 | 0.1 | -1.5 | 0.571 |
| landing | 858.0 | 867.0 | 0.1 | -0.5 | 0.610 |

The two short arm periods after the flight (19 s and 16 s) have a throttle out of 0. The motors did not lift the aircraft. They add no flight energy.

## Characteristics against the Mk4 estimate sheet

The sheet is an estimate. It is not truth. The sheet column "Update Post Avi Testing" gives the mass and the thrust. The column "INITIAL" holds six batteries.

| Item | Sheet | Log or user fact | Difference | Note |
|---|---|---|---|---|
| Mass (kg) | 9.182 | 9.134 (weight sheet) | -0.5 % | The log gives no mass. |
| Hover thrust per rotor (g) | 2295.5 | 2283.0 (9.134 kg / 4) | -0.5 % | Mass-implied. |
| Hover power, 4 rotors (W) | 918.2 (10 g/W) | not logged | not known | The sheet value at 9.134 kg is 913 W. At 40 C it is about 970 W. |
| Hover current (A) | not given | not logged | not known | 918.2 W at 44.4 V gives 20.7 A. This is a derived value. |
| Hover actuator command | not given | 0.605 (0.586 to 0.620, 4 windows) | model 0.578 is 4.4 % lower | Log value is (PWM - 1050) / 890. The model at 40 C is about 0.611. |
| Hover rpm | not given | not logged | not known | No ESC telemetry. |
| Battery energy (Wh) | 599.4 (2157.84 kJ) | 599.4 (12S3P, 13.5 Ah, 44.4 V nominal) | 0 % | Same by construction. |
| Climb rate (m/s) | 5.0 | 2.6 (median, takeoff) | -48 % | The mission sets the rate. |
| Search cruise speed (m/s) | 14 | 5.9 (survey legs), 16.7 (transit legs) | | The mission sets the speed. |
| Cruise pitch at about 17 m/s (deg) | -33 at 14 m/s | -10.8 | | Steady samples, ground speed. |
| Drag at 17 m/s, from pitch | 76.8 N (CdA 0.64 m2) | 17.1 N (CdA 0.099 m2) | -78 % | D = m g tan(pitch). Wind not known. |
| Airborne time (min) | 7.55 (1 battery), 34.96 (6 batteries) | 14.4 (5.4 s to 867.0 s) | | See the battery section. |

## Scan of the fleet logs

The command is `python -I tools/scan_batt_monitor.py LOG_FOLDER --out OUT_FOLDER`. It reads PARM, BAT, CTUN, RCOU, MSG, VER, ESC, EDT2, RPM, ARM, GPS and XKF1 only. The scan of 66 logs (831 MB) takes under 2 minutes. Every log read. The full table (60 columns for each log and battery instance) is `batt_monitor_scan.csv`.

Verdict letters: W = WORKING, S = SUSPECT, B = BROKEN. The voltage and the current have separate verdicts. The overall verdict is the worse one. A log has up to three battery instances.

Summary of the 186 battery instances (voltage, current): 137 are B and B, 27 are B and S, 19 are W and B, 2 are S and S, 1 is S and B. The four Mk1 logs have no BAT message (BATT_MONITOR is not set). No instance has a working current.

The aircraft mark comes from the folder name only. The folders of 2026-07-05 to 2026-09-16 have no mark in the name. The README of the data folder does not state the marks either. The parameter files do not separate the marks: MOT_SPIN_MIN 0.20, MOT_SPIN_MAX 0.95, MOT_THST_EXPO 0.78 and MOT_BAT_VOLT_MAX 50.4 V are equal in every log, and the learned MOT_THST_HOVER passes from log to log. The Mk1 folder name says 2025 and the GPS date says 2026-01-28.

| Folder | Log | Date | Mark in folder name | Firmware | Voltage (inst 0, 1, 2) | Current (inst 0, 1, 2) | Flight (s) | ESC, EDT2, RPM | MOT_PWM_TYPE |
|---|---|---|---|---|---|---|---|---|---|
| 2026.07.05 | 00000093.BIN | 2026-07-05 | none | V4.6.3 | BBB | SSS | 0.0 | 0, 0, 0 | 0.0 |
| 2026.07.05 | 00000094.BIN | 2026-07-05 | none | V4.6.3 | BBB | SSS | 0.0 | 0, 0, 0 | 0.0 |
| 2026.07.05 | 00000095.BIN | 2026-07-05 | none | V4.6.3 | BBB | BBB | 5.7 | 0, 0, 0 | 0.0 |
| 2026.07.05 | 00000096.BIN | 2026-07-05 | none | V4.6.3 | BBB | BBB | 107.7 | 0, 0, 0 | 0.0 |
| 2026.07.05 | 00000097.BIN | 2026-07-05 | none | V4.6.3 | BBB | BBB | 988.4 | 0, 0, 0 | 0.0 |
| 2026.07.10 | 00000104.BIN | 2026-07-10 | none | V4.6.3 | BBB | SSS | 0.0 | 0, 0, 0 | 0.0 |
| 2026.07.10 | 00000105.BIN | 2026-07-10 | none | V4.6.3 | BBB | BBB | 0.8 | 0, 0, 0 | 0.0 |
| 2026.07.10 | 00000106.BIN | 2026-07-10 | none | V4.6.3 | BBB | SSS | 0.0 | 0, 0, 0 | 0.0 |
| 2026.07.10 | 00000107.BIN | 2026-07-10 | none | V4.6.3 | BWB | BBB | 504.7 | 0, 0, 0 | 0.0 |
| 2026.07.10 | 00000108.BIN | 2026-07-10 | none | V4.6.3 | BWB | BBB | 806.8 | 0, 0, 0 | 0.0 |
| 2026.07.10 | 00000109.BIN | 2026-07-10 | none | V4.6.3 | BWB | BBB | 747.8 | 0, 0, 0 | 0.0 |
| 2026.07.10 | 00000110.BIN | 2026-07-10 | none | V4.6.3 | BWB | BBB | 257.2 | 0, 0, 0 | 0.0 |
| 2026.07.17 | 00000113.BIN | 2026-07-17 | none | V4.6.3 | BBB | BBB | 1.2 | 0, 0, 0 | 0.0 |
| 2026.07.17 | 00000114.BIN | 2026-07-17 | none | V4.6.3 | BSB | SSS | 0.0 | 0, 0, 0 | 0.0 |
| 2026.07.17 | 00000115.BIN | 2026-07-17 | none | V4.6.3 | BSB | BBB | 1.2 | 0, 0, 0 | 0.0 |
| 2026.07.17 | 00000116.BIN | 2026-07-17 | none | V4.6.3 | BWB | BBB | 784.6 | 0, 0, 0 | 0.0 |
| 2026.07.17 | 00000117.BIN | 2026-07-17 | none | V4.6.3 | BWB | BBB | 985.0 | 0, 0, 0 | 0.0 |
| 2026.07.17 | 00000118.BIN | 2026-07-17 | none | V4.6.3 | BWB | BBB | 177.4 | 0, 0, 0 | 0.0 |
| 2026.07.17 | 00000119.BIN | 2026-07-17 | none | V4.6.3 | BWB | BBB | 354.7 | 0, 0, 0 | 0.0 |
| 2026.07.24 | 00000122.BIN | 2026-07-24 | none | V4.6.3 | BBB | BBB | 9.5 | 0, 0, 0 | 0.0 |
| 2026.07.24 | 00000123.BIN | 2026-07-24 | none | V4.6.3 | BWB | BBB | 269.2 | 0, 0, 0 | 0.0 |
| 2026.07.24 | 00000124.BIN | 2026-07-24 | none | V4.6.3 | BWB | BBB | 372.0 | 0, 0, 0 | 0.0 |
| 2026.07.24 | 00000125.BIN | 2026-07-24 | none | V4.6.3 | BWB | BBB | 489.9 | 0, 0, 0 | 0.0 |
| 2026.07.24 | 00000126.BIN | 2026-07-24 | none | V4.6.3 | BWB | BBB | 440.0 | 0, 0, 0 | 0.0 |
| 2026.07.24 | 00000127.BIN | 2026-07-24 | none | V4.6.3 | BWB | BBB | 451.4 | 0, 0, 0 | 0.0 |
| 2026.07.24 | 00000128.BIN | 2026-07-24 | none | V4.6.3 | BWB | BBB | 609.5 | 0, 0, 0 | 0.0 |
| 2026.08.05 | 00000131.BIN | 2026-08-03 | none | V4.7.0 | BBB | BBB | 8.6 | 0, 0, 0 | 0.0 |
| 2026.08.05 | 00000132.BIN | 2026-08-03 | none | V4.7.0 | BBB | SSS | 0.0 | 0, 0, 0 | 0.0 |
| 2026.08.05 | 00000133.BIN | 2026-08-04 | none | V4.7.0 | BBB | SBS | 0.0 | 0, 0, 0 | 0.0 |
| 2026.08.05 | 00000134.BIN | 2026-08-05 | none | V4.7.0 | BBB | BBB | 602.1 | 0, 0, 0 | 0.0 |
| 2026.08.05 | 00000135.BIN | 2026-08-05 | none | V4.7.0 | BBB | BBB | 680.1 | 0, 0, 0 | 0.0 |
| 2026.08.05 | 00000136.BIN | 2026-08-05 | none | V4.7.0 | BBB | BBB | 1454.2 | 0, 0, 0 | 0.0 |
| 2026.08.05 | 00000137.BIN | 2026-08-05 | none | V4.7.0 | BBB | BBB | 1161.8 | 0, 0, 0 | 0.0 |
| 2026.08.05 | 00000139.BIN | 2026-08-05 | none | V4.7.0 | BBB | SSS | 0.0 | 0, 0, 0 | 0.0 |
| 2026.08.05 | 2x Auto Drop Run.BIN | 2026-08-05 | none | V4.7.0 | BBB | BBB | 736.6 | 0, 0, 0 | 0.0 |
| 2026.08.05 | Prop Test.BIN | 2026-08-05 | none | V4.7.0 | BBB | BBB | 3.9 | 0, 0, 0 | 0.0 |
| 2026.08.15 | 2026-08-15 09-14-16.bi | 2026-08-14 | none | V4.7.0 | BBB | BBB | 5.7 | 0, 0, 0 | 0.0 |
| 2026.08.15 | 2026-08-15 11-04-30.bi | 2026-08-15 | none | V4.7.0 | BBB | BBB | 991.9 | 0, 0, 0 | 0.0 |
| 2026.08.15 | 2026-08-15 12-25-08.bi | 2026-08-15 | none | V4.7.0 | BBB | BBB | 445.1 | 0, 0, 0 | 0.0 |
| 2026.08.15 | 2026-08-15 13-22-58.bi | 2026-08-15 | none | V4.7.0 | BBB | BBB | 642.6 | 0, 0, 0 | 0.0 |
| 2026.08.15 | 2026-08-15 13-58-15.bi | 2026-08-15 | none | V4.7.0 | BBB | BBB | 583.6 | 0, 0, 0 | 0.0 |
| 2026.09.12 | 00000149.BIN | 2026-09-11 | none | V4.7.0 | BBB | BBB | 9.0 | 0, 0, 0 | 0.0 |
| 2026.09.12 | 00000150.BIN | 2026-09-11 | none | V4.7.0 | BBB | BBB | 178.9 | 0, 0, 0 | 0.0 |
| 2026.09.12 | 00000151.BIN | 2026-09-11 | none | V4.7.0 | BBB | BBB | 957.1 | 0, 0, 0 | 0.0 |
| 2026.09.12 | 00000152.BIN | 2026-09-11 | none | V4.7.0 | BBB | BBB | 957.0 | 0, 0, 0 | 0.0 |
| 2026.09.15 - Skyway Range  | 00000171.BIN | 2026-09-15 | none | V4.7.0 | BBB | BBB | 852.9 | 0, 0, 0 | 0.0 |
| 2026.09.16 - Skyway Range  | 00000173.BIN | 2026-09-16 | none | V4.7.0 | BBB | BBB | 6.9 | 0, 0, 0 | 0.0 |
| 2026.09.16 - Skyway Range  | 00000174.BIN | 2026-09-16 | none | V4.7.0 | BBB | BBB | 316.1 | 0, 0, 0 | 0.0 |
| Mk1 Maiden - 28.01.2025 | 00000052.BIN | 2026-01-28 | Mk1 | V4.6.3 | none | none | 0.0 | 0, 0, 0 | 0.0 |
| Mk1 Maiden - 28.01.2025 | 00000053.BIN | 2026-01-28 | Mk1 | V4.6.3 | none | none | 14.9 | 0, 0, 0 | 0.0 |
| Mk1 Maiden - 28.01.2025 | 00000054.BIN | 2026-01-28 | Mk1 | V4.6.3 | none | none | 47.6 | 0, 0, 0 | 0.0 |
| Mk1 Maiden - 28.01.2025 | 00000055.BIN | 2026-01-28 | Mk1 | V4.6.3 | none | none | 627.4 | 0, 0, 0 | 0.0 |
| Mk2 2nd Flight - 27.04.202 | 00000067.BIN | 2026-04-27 | Mk2 | V4.6.3 | BBB | BBB | 6.0 | 0, 0, 0 | 0.0 |
| Mk2 2nd Flight - 27.04.202 | 00000068.BIN | 2026-04-27 | Mk2 | V4.6.3 | BBB | BBB | 1.7 | 0, 0, 0 | 0.0 |
| Mk2 2nd Flight - 27.04.202 | 00000069.BIN | 2026-04-27 | Mk2 | V4.6.3 | BBB | BBB | 147.3 | 0, 0, 0 | 0.0 |
| Mk2 2nd Flight - 27.04.202 | 00000070.BIN | 2026-04-27 | Mk2 | V4.6.3 | BBB | BBB | 958.4 | 0, 0, 0 | 0.0 |
| Mk2 2nd Flight - 27.04.202 | 00000071.BIN | 2026-04-27 | Mk2 | V4.6.3 | BBB | BBB | 767.1 | 0, 0, 0 | 0.0 |
| Mk2 2nd Flight - 27.04.202 | 00000072.BIN | 2026-04-27 | Mk2 | V4.6.3 | BBB | BBB | 271.5 | 0, 0, 0 | 0.0 |
| Mk2 3rd Flight - 13.05.202 | 00000080.BIN | 2026-05-13 | Mk2 | V4.6.3 | BBB | SSS | 0.0 | 0, 0, 0 | 0.0 |
| Mk2 3rd Flight - 13.05.202 | 00000081.BIN | 2026-05-13 | Mk2 | V4.6.3 | BSB | SSS | 0.0 | 0, 0, 0 | 0.0 |
| Mk2 3rd Flight - 13.05.202 | 00000082.BIN | 2026-05-13 | Mk2 | V4.6.3 | BBB | BBB | 8.5 | 0, 0, 0 | 0.0 |
| Mk2 3rd Flight - 13.05.202 | 00000083.BIN | 2026-05-13 | Mk2 | V4.6.3 | BWB | BBB | 314.0 | 0, 0, 0 | 0.0 |
| Mk2 3rd Flight - 13.05.202 | 00000084.BIN | 2026-05-13 | Mk2 | V4.6.3 | BWB | BBB | 18.2 | 0, 0, 0 | 0.0 |
| Mk2 3rd Flight - 13.05.202 | 00000085.BIN | 2026-05-13 | Mk2 | V4.6.3 | BWB | BBB | 192.6 | 0, 0, 0 | 0.0 |
| Mk2 3rd Flight - 13.05.202 | 00000086.BIN | 2026-05-13 | Mk2 | V4.6.3 | BWB | BBB | 72.4 | 0, 0, 0 | 0.0 |
| Mk2 3rd Flight - 13.05.202 | 00000087.BIN | 2026-05-13 | Mk2 | V4.6.3 | BWB | BBB | 1285.9 | 0, 0, 0 | 0.0 |

What the scan shows:

- **Instance 0** (pin 14, multiplier 12.02, current pin 15) reads 15 to 16 V and 0 A in every log (one log of 2026-04-27 has another multiplier). It does not follow the pack.
- **Instance 2** (pin 14, multiplier 10.1) reads 12 to 14 V and 0 A in every log. It does not follow the pack.
- **Instance 1** (voltage pin 13, current pin 4) follows the pack in 19 logs. The multiplier there is 19.07 or 18.96. The voltage drops 0.6 to 1.0 V at the start of flight and recovers 0.4 to 0.6 V after landing. The current is 0 A in these logs. In the flights of 2026-07-05 and from 2026-08-05 the multiplier is 15.0 to 15.2, and the instance reads 49.5 to 50.2 V with 66 A (the ADC limit). The input is at its limit.
- In the logs of 2026-04-27 (Mk2) instance 1 has voltage and current on pin 14 (logs 00000070 to 00000072). That pin reads 1.33 V in every log. The 26 A in those logs is 1.33 V times 20 A/V and does not change with the load.
- No log has ESC, EDT2 or RPM messages. MOT_PWM_TYPE is 0 (PWM) in all logs.

## Hover and propulsion data from the logs

**Is there a reliable way to analyse propulsion data from these logs? Not today.** The reasons:

| Needed for a power validation | State in the logs |
|---|---|
| Pack current | No log has it. Current pin 15 and pin 4 read 0 A. Pin 14 reads a constant 1.33 V. |
| Pack voltage | Good in 19 logs (instance 1), none after 2026-07-24. |
| Current sensor calibration | Not known. BATT_AMP_PERVLT of the working pin was never calibrated against a bench ammeter. |
| rpm | No RPM or ESC message in any log. No RPM sensor (RPM1_TYPE is 0). |
| Mass for each flight | Not recorded. Only the weight sheet total (9.134 kg) exists. |
| Air temperature | Not logged. The BARO and IMU temperatures are board temperatures. The user gave 40 C for 2026-09-15. |
| Aircraft mark | Not stated for the folders of July to September. The parameters do not tell. |

**What the logs give.** For the 19 logs with a working voltage, the longest steady hover (ground speed under 0.8 m/s, climb rate under 0.3 m/s, above 3 m) gives the pack voltage and the motor command. The table shows the hovers of 20 s or more. The current and the power are not available. The command of the model (maker table, EMST) is 0.578 at 9.134 kg and ISA sea level. The mass of each flight is not known, so the comparison is a check of size only.

| Log | Date | Hover (s) | Pack voltage (V) | ThO | Command | Learned MOT_THST_HOVER at start | Current, power |
|---|---|---|---|---|---|---|---|
| 00000107.BIN | 2026-07-10 | 181 | 47.7 | 0.222 | 0.581 | 0.2262 | not available |
| 00000108.BIN | 2026-07-10 | 40 | 45.9 | 0.245 | 0.606 | 0.2281 | not available |
| 00000110.BIN | 2026-07-10 | 60 | 44.7 | 0.258 | 0.618 | 0.2310 | not available |
| 00000116.BIN | 2026-07-17 | 22 | 47.2 | 0.230 | 0.589 | 0.2580 | not available |
| 00000117.BIN | 2026-07-17 | 125 | 47.9 | 0.222 | 0.581 | 0.2285 | not available |
| 00000118.BIN | 2026-07-17 | 28 | 45.6 | 0.236 | 0.595 | 0.2315 | not available |
| 00000119.BIN | 2026-07-17 | 51 | 44.8 | 0.240 | 0.599 | 0.2251 | not available |
| 00000126.BIN | 2026-07-24 | 31 | 49.1 | 0.184 | 0.535 | 0.2276 | not available |
| 00000127.BIN | 2026-07-24 | 82 | 46.8 | 0.203 | 0.554 | 0.1927 | not available |
| 00000128.BIN | 2026-07-24 | 49 | 45.5 | 0.221 | 0.576 | 0.1918 | not available |
| 00000083.BIN | 2026-05-13 | 24 | 49.1 | 0.243 | 0.603 | 0.3846 | not available |
| 00000087.BIN | 2026-05-13 | 64 | 48.2 | 0.242 | 0.599 | 0.2447 | not available |

Hover command is the mean of the four RCOU outputs, (PWM - 1050) / 890. It is 0.53 to 0.62 in these hovers. The model gives 0.578 at ISA sea level and about 0.611 at 40 C. The flight at 17 July (00000117) and the one at 10 July (00000107) have the longest hovers (125 s and 181 s) and give 0.580 and 0.581. If the mass and the air temperature of those days were equal to the model, the match would be within 1 %. Nobody recorded them.

**Energy from the voltage alone.** For the same 19 logs the rest voltage before takeoff and after landing gives the state of charge with the OCV table. The charge is the change of SOC times 13.5 Ah (12S3P is assumed for these days). The mean current over the flight then follows. Long flights (500 s or more) give 17.2 to 22.7 A: 00000107 18.2 A, 00000108 19.7 A, 00000109 20.9 A, 00000116 17.2 A, 00000117 17.7 A, 00000087 22.7 A. The start voltage is above the table top in 7 of the 19 logs (clamped to 100 %), and the end rest voltage is taken 10 to 40 s after landing, before the pack has relaxed. So the values are rough. They agree with the 19.7 A of flight 00000171 and all but one are below the 22.2 A of the maker hover.

**Minimal test flight for a reliable power validation.**

1. Fix the current sensor. Connect a power module to the pack, set BATT_MONITOR, BATT_VOLT_PIN, BATT_CURR_PIN, BATT_VOLT_MULT and BATT_AMP_PERVLT. Check both with a bench voltmeter and a bench ammeter. Record the reading of the ammeter at one steady load.
2. Weigh the aircraft with the battery on the day. Record the air temperature and the pressure on the ground.
3. Charge the pack to 4.2 V per cell. Record the rest voltage per 6S battery before the flight.
4. Hover for 60 s at 10 m height or more, in calm air, with LOG_BITMASK and the logging rates set so that BAT, CTUN, RCOU and XKF1 are at 10 Hz or more. Add a second hover of 60 s at a second mass if possible (for example with 1 kg of ballast), to separate the mass effect.
5. Land, wait 10 minutes, record the rest voltage per 6S battery.
6. Optional: an RPM source (an ESC with telemetry, or an RPM sensor) gives the rpm. This fits the chain constant kappa.

With these data the hover power follows from the logged voltage and current. The logged mass and the air density correct it to the model condition.

## Hover density and the model at the site

The log has no air temperature. The user gives 40 C. The pressure in the hover windows of flight 00000171 is 98.67 kPa (98.35 kPa for hover_4). The density is 1.097 kg/m3 (rho = p / (287.05 T)). That is 0.895 of the model density (1.225).

At equal thrust the rotor power scales with the density to the power -0.5. The reason: with constant thrust and power coefficients, the rpm scales with rho^-0.5 and the power with rho^-0.5. The factor is 1.057. This is a momentum and blade-element scaling. It was not checked with the live Fit C model.

| Model | Hover power ISA (W) | Hover power at 40 C (W) | Hover current at 40 C (A) |
|---|---|---|---|
| Maker table (EMST hover) | 985 | 1041 | 23.5 |
| Fit C live | 1022 | 1080 | 24.3 |
| Fit B live | 951 | 1005 | 22.6 |
| Propalyser chain (3244 rpm) | 983 | 1039 | not given |
| Maker datasheet at 3244 rpm | 880 | 930 | not given |
| Mk4 sheet (estimate) | 918 | 970 | not given |

## Power comparison for flight 00000171

The log holds no power, so the log factor is not measured. The energy bracket below replaces it.

**Energy bracket.** Start: 4.2 V per cell, taken as SOC 100 % (the table ends at 4.144 V). End: 3.85 V per cell (23.1 V for each 6S), SOC 65.1 % from the table (table range 64.6 to 65.6 %). Capacity 13.5 Ah. The flight lasts 861.6 s.

| Item | Value |
|---|---|
| Charge used | 4709 mAh (statistical half width 441 mAh for 0.05 V, table spread 70 mAh) |
| Mean current | 19.7 A (17.5 to 21.8 A) |
| Mean power at 46.8 V to 48.3 V pack voltage | 921 to 950 W |

The pack voltage under load is not logged. 48.3 V is the mean of the start (50.4 V) and the end (46.2 V) rest voltage. The lower value takes 1.5 V of sag off the end. The sag is an assumption.

**The flight was mostly cruise, so the mean is not the hover power.** The mean power of the maker model over the mission mix (EMST rows at 0, 5, 10 and 15 m/s and in climb, linear in speed and climb rate, descent taken as hover) is 1047 W at ISA and 1107 W at 40 C.

| Model | Model power at 40 C (W) | Model divided by the bracket |
|---|---|---|
| Maker table, hover | 1041 | 1.10 to 1.13 |
| Maker table, mission mix | 1107 | 1.17 to 1.20 |
| Fit C, hover | 1080 | 1.14 to 1.17 |
| Fit B, hover | 1005 | 1.06 to 1.09 |
| Propalyser chain, hover | 1039 | 1.09 to 1.13 |
| Maker datasheet, hover | 930 | 0.98 to 1.01 |
| Mk4 sheet, hover | 970 | 1.02 to 1.05 |

A comparison for each segment type is not possible. The energy exists for the whole mission only.

**The break-even.** The maker hover power at 40 C matches the energy when the end SOC is 61.1 %. The mission mix matches it at 58.7 %. The table gives 65.1 %. The difference is 4 to 6 points of SOC. The OCV table is for another cell, it has one temperature (25 C), and its notes say that it reads low after a discharge. A true cell at 3.85 V is then at a lower SOC than the table says. The size of this error is not known. So the bracket does not reject a maker that understates the power, but the data give no support for it. They point to a maker table that is 10 to 20 % high at the site.

**Command against speed (no battery needed).** The command of the log is lower than the model at speed.

| Type | Model at ISA | Model at 40 C (approximate) | Log | Log over model |
|---|---|---|---|---|
| Hover (4 windows) | 0.578 | 0.611 | 0.605 | 0.99 |
| Survey 5.9 m/s | 0.579 | 0.612 | 0.602 | 0.98 |
| RTL cruise 10 m/s | 0.587 | 0.620 | 0.614 | 0.99 |
| Transit 16.7 m/s (model 15 m/s) | 0.608 | 0.643 | 0.596 | 0.93 |
| Takeoff climb 2.6 m/s (model 2 m/s) | 0.612 | 0.647 | 0.604 | 0.93 |

The model at 40 C is the ISA command times 1.057 (the command scales with the rpm). This is an approximation. The model uses 48 V. The pack voltage in the flight was 46 to 50 V. A lower voltage raises the command.

## Hover command and the ArduPilot map

Logged hover command: mean of the four RCOU outputs, (PWM - 1050) / 890.

| Window (s) | ThO | Learned MOT_THST_HOVER | Mean command | Motors 1 to 4 |
|---|---|---|---|---|
| 366.4 to 378.8 | 0.250 | 0.192 | 0.611 | 0.652, 0.666, 0.496, 0.630 |
| 379.5 to 385.7 | 0.227 | 0.209 | 0.586 | 0.612, 0.641, 0.460, 0.630 |
| 728.3 to 733.3 | 0.259 | 0.276 | 0.620 | 0.703, 0.577, 0.653, 0.552 |
| 797.3 to 800.8 | 0.238 | 0.252 | 0.601 | 0.671, 0.516, 0.665, 0.546 |

The command differs between motors by up to 0.2. The motors do not share the thrust equally. The spread changes between windows. This points to a CG offset or to a trim in the mix. It belongs to the mass data of step 5B.

**The map that fits the log.** MOTB gives lift_max 0.690 for the whole flight and a battery voltage ratio of 0.81. 0.81 is MOT_BAT_VOLT_MIN / MOT_BAT_VOLT_MAX (40.8 / 50.4), the lower limit. The motor library read 16 V from battery instance 0, so it held the voltage compensation at its lower limit all flight. The scan shows that instance 0 reads 15 to 16 V in every log. So the same holds for the other flights, except the logs where the compensation is off.

The fit with the lowest error on all airborne samples:

1. thrust request = ThO / lift_max (lift_max 0.690).
2. x = ((e - 1) + sqrt((1 - e)^2 + 4 e thrust)) / (2 e), with e = MOT_THST_EXPO 0.78.
3. actuator = MOT_SPIN_MIN + (MOT_SPIN_MAX - MOT_SPIN_MIN) x, with 0.20 and 0.95.
4. PWM = MOT_PWM_MIN + actuator (MOT_PWM_MAX - MOT_PWM_MIN), with 1050 and 1940.

| Map | Bias | RMS error (actuator) |
|---|---|---|
| lift_max = 1 (the map in Aerolink accontrol today) | -0.074 | 0.076 |
| lift_max 0.69 inside the curve only | -0.142 | 0.144 |
| thrust / 0.69, then the curve | +0.009 | 0.021 |

This is an empirical fit. The ArduPilot 4.7 source is not in this workspace, so the formula is not checked against the code.

At the learned hover thrust 0.2118 the fitted map gives an actuator of 0.5765 (PWM 1563 us). The model ESC command is 0.578. They agree within 0.2 %. At the end value 0.2516 the map gives 0.618. The map with lift_max = 1 gives 0.499 and 0.533. It is 13 % too low for the flown aircraft.

What this means for the twin:

- The twin must reproduce lift_max 0.69 to reproduce the flown command. The twin sets SIM_BATT_VOLTAGE from MOT_BAT_VOLT_MAX. That gives lift_max 1 and a hover command of 0.499. A SIM_BATT_VOLTAGE at or below MOT_BAT_VOLT_MIN (40.8 V) gives the flown map. The better fix is a working battery monitor on the real aircraft. The decision belongs to step 5B.
- The ESCs are PWM ESCs. The log agrees: MOT_PWM_TYPE is 0, SERVO1 to SERVO4 (function 33 to 36) drive PWM outputs 1 to 4, and RCOU shows 1050 to 1895 us. The ESC input is 1050 + 890 c, with c the actuator from 0 to 1. The twin command c is the actuator. The twin must use MOT_PWM_MIN and MOT_PWM_MAX (1050 and 1940) and not SERVOn_MIN and SERVOn_MAX (1100 and 1900). The error is 0.4 % at hover and 4.5 points at the spin-arm value (0.15).

## Battery of flight 00000171

Limits: another cell type, a 25 C table that is the only table, no cell temperature in the log (BAT temperature is 0), and BATT_CAPACITY in the parameters is 4500 mAh for the main monitor. The capacity used here is 13.5 Ah (3 strings of 4.5 Ah). The OCV table ends at 4.144 V per cell (SOC 99.6 %). The start value of 4.2 V per cell is above it, so the start SOC of 100 % is a user fact and not a table value.

| Item | Value | Source |
|---|---|---|
| Start rest voltage | 4.2 V per cell (50.4 V) | user fact |
| End rest voltage, one 6S battery | 23.1 V (3.850 V per cell) | user fact |
| Battery rest voltage at the end, 12S | 46.2 V | 2 x 23.1 V |
| Start SOC | 100 % | user fact |
| End SOC | 65.1 % (table range 64.6 to 65.6 %, statistical half width 3.3 % with 0.05 V) | OCV table, 25 C |
| Charge used | 4709 mAh | 34.9 % of 13.5 Ah |
| Charge remaining | 8791 mAh of 13500 mAh | end check |
| Xing R and C | not computed | no usable voltage or current |
| 2RC extension | not computed | no usable voltage or current |
| Current scale and interval | not computed | no logged current |

The Aerolink command `flight battery` stops at the start check. The first five seconds of battery instance 0 give 1.338 V per cell, outside the table. Instance 1 has a constant current, so the sag fit has no excitation.

Notes on the battery data of this flight:

- BAT instance 0 uses pin 14 with multiplier 12.02. It reads 1.336 V at the pin. A 12S pack at 46 V to 50 V needs a multiplier near 34 to 37 for that pin voltage. The reading does not drop under load. Its range over the flight is 0.27 V.
- BAT instance 1 (BATT2, pin 13, multiplier 15) gives 49.50 V and 66.0 A for 99.5 % of the log, also on the ground after the landing. It is at the ADC limit. The charge counter integrates 66 A and reaches 20.5 Ah. The PreArm message "Battery 2 low voltage failsafe" comes from this channel. The multiplier was 19.07 in July.

## Fitted values

| Value | Result | Written to |
|---|---|---|
| Battery internal resistance Rb | not fitted, no voltage and current | nothing |
| Chain kappa | not fitted, no rpm and no power | nothing. The Propalyser file keeps the fitted chain_kappa_nd and chain_r_tot_ohm from the maker tables (the user accepts this). |
| Current scale | not fitted, no logged current | nothing |
| Segments | 13 segments | `tools/ardupilot/settings/redback.yaml` |

The AeroPlan package is not rebuilt. The segments need a new AeroPlan version before they reach a package. The motor outputs of the package stay marked as placeholder, as the user decided.

## Plots

- `01_command_and_segments.png`: the mean motor command with the segments.
- `02_hover_power_models.png`: hover power of each model at ISA and at 40 C, with the energy band.
- `03_battery_voltage_channels.png`: the three logged battery voltages.
- `04_soc_end_point.png`: the start and the end SOC on the OCV table.
- `05_command_map.png`: the command map against the log.

## Open questions

1. The pack voltage and current of a flight. The power module needs a fix (see the test flight above).
2. The mass of each flight and the aircraft mark of the July to September logs.
3. Where the cell rest-voltage curve of the NXE 6S 4500 mAh differs from the table. A measurement of the real cell at 40 C would close the 4 to 6 points of SOC.
4. Whether 5B accepts the lift_max 0.69 finding for SIM_BATT_VOLTAGE.
