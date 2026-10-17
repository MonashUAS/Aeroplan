# Redback twin: power and battery against the flight log

Step 5A of the Redback twin plan. The numbers are in `results.json` in this folder.

## Sources

- Log: `00000171.BIN`, sha256 215616e25dd4532d0256e1ae4e9572d2cd73d8774ea1ae4c4b2642549ef0a57d. ArduCopter 4.7.0, CubeOrangePlus, QUAD/X.
- Parameters: `00000171_log.parm`, sha256 3592de49e0fa3bedf37e3baac96ad93658b6368cd131ed73b0e359bcdaee3e13. The first logged value of each name.
- Package: Redback 0.2.0 aerolink profile, package hash 2cc698f0e41b692d. The mass is 9.134 kg from the weight sheet. The aircraft was not weighed for this flight.
- EMST and model values: `multirotor_results.json` of the AeroPlan 0.2.0 build, sha256 f508ab84f67010658f0498465fb96deae950469539ac1758ee8032f7d1bdb66c.
- Rest voltage after the flight, 23.1 V for each 6S battery: a user fact. Nobody logged it.
- Time in this report is log time. Zero is the first log message (boot time 461.3 s). The takeoff is at 5.4 s. The RTL starts at 732.4 s. The disarm is at 867.0 s.

## Main finding

**The log holds no usable power data.** The tables below show why.

1. No ESC or RPM message is in the log (ESC, EDT2 and RPM have 0 records). The log has no rpm, no ESC current and no ESC voltage.
2. No battery channel follows the 12S pack. Instance 0 reads 16.0 V and 0.0 A for the whole log. Instance 1 sits at its ADC limit (49.50 V and 66.0 A, both exact limits: 3.3 V times 15 and 3.3 V times 20). Instance 2 reads 13.5 V and 0.0 A. Plot 03 shows the three voltages.
3. The Xing fit, the UKF, the pack resistance and the current scale need a voltage and a current. They cannot run on this log. The Aerolink command stops with "rest voltage 1.338 V per cell is outside the OCV table".

So the factor by which each model understates or overstates the hover power is **not measured**. This report gives an energy bracket instead. The bracket depends on a start state of charge that nobody logged. It cannot confirm that the maker understates the power.

## Segments

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
| Hover power, 4 rotors (W) | 918.2 (10 g/W) | not logged | not known | The sheet value at 9.134 kg is 913 W. |
| Hover current (A) | not given | not logged | not known | 918.2 W at 44.4 V gives 20.7 A. This is a derived value. |
| Hover actuator command | not given | 0.605 (0.586 to 0.620, 4 windows) | model 0.578 is 4.4 % lower | Log value is (PWM - 1050) / 890. |
| Hover rpm | not given | not logged | not known | No ESC telemetry. |
| Battery energy (Wh) | 599.4 (2157.84 kJ) | 599.4 (12S3P, 13.5 Ah, 44.4 V nominal) | 0 % | Same by construction. |
| Climb rate (m/s) | 5.0 | 2.6 (median, takeoff) | -48 % | The mission sets the rate. |
| Search cruise speed (m/s) | 14 | 5.9 (survey legs), 16.7 (transit legs) | | The mission sets the speed. |
| Cruise pitch at about 17 m/s (deg) | -33 at 14 m/s | -10.8 | | Steady samples, ground speed. |
| Drag at 17 m/s, from pitch | 76.8 N (CdA 0.64 m2) | 17.1 N (CdA 0.099 m2) | -78 % | D = m g tan(pitch). Wind not known. |
| Airborne time (min) | 7.55 (1 battery), 34.96 (6 batteries) | 14.4 (5.4 s to 867.0 s) | | See the battery section. |

## Hover density

The log has no air temperature. The BARO temperature (46 C) and the IMU temperature (45 C) are board temperatures. The pressure in the hover windows is 98.67 kPa (98.35 kPa for hover_4).

- ISA temperature at that pressure altitude: density 1.199 kg/m3, ratio to the model density (1.225) 0.978. This is the value used here.
- If the air was at 25 C: 1.153 kg/m3 (ratio 0.941).
- The board temperature is not an air temperature. It would give 1.076 kg/m3. This is a lower bound that does not apply.

At equal thrust the rpm scales with the root of the density. The command moves by about the same factor: 0.989 at ratio 0.978. The hover command of the log at the model density is then about 0.598.

## Power comparison

Hover electrical power for four rotors at 9.134 kg, ISA sea level, 48 V maker basis.

| Model | Hover power (W) | Hover current (A) | Hover command | Log power | Factor |
|---|---|---|---|---|---|
| Maker table (AeroPlan 0.2.0, EMST hover) | 985 | 22.2 | 0.578 | not logged | not measured |
| Fit C live (Proptimiser BEMT) | 1022 | 23.0 | | not logged | not measured |
| Fit B live | 951 | 21.4 | | not logged | not measured |
| Propalyser chain (3244 rpm) | 983 | | | not logged | not measured |
| Maker datasheet at 3244 rpm | 880 | | | not logged | not measured |
| Mk4 sheet (estimate) | 918 | | | not logged | not measured |

**Energy bracket.** The end state of charge is 65.1 % (table range 64.6 to 65.6 %). The mean current over the 861.6 s of flight follows from the charge used. The charge used depends on the start state, which is not logged. Plot 02 shows the band.

| Assumed start (rest voltage per cell) | Start SOC (%) | Charge used (mAh) | Mean current (A) | Mean power at 46.2 V to 49 V (W) |
|---|---|---|---|---|
| 4.14 V (top of the table) | 99.6 | 4656 | 19.5 | 899 to 953 |
| 4.10 V | 95.8 | 4142 | 17.3 | 800 to 848 |
| 4.05 V | 91.0 | 3501 | 14.6 | 676 to 717 |

For the first row, the model hover power divided by the mean power is 1.03 to 1.10 for the maker table and the EMST hover, 1.07 to 1.14 for Fit C, 1.00 to 1.06 for Fit B, 1.03 to 1.09 for the chain, 0.92 to 0.98 for the datasheet. The other rows give larger ratios.

Two points limit this bracket.

- The OCV table is of another cell (five LP-503562-IS-3 LiPo cells, 25 C, SOC 10 to 100 %, 3.54 to 4.14 V). The notes of the table say that it reads low after a discharge. A true cell at 3.85 V is then at a lower SOC. That raises the charge used and the power. If the true end SOC were 50 %, the mean current would be 28 A.
- The mean over the flight is not the hover power. The flight has climbs (actuator 0.68) and a fast leg at 17 m/s (0.584). The mean actuator of the flight is close to the hover value.

Result: the bracket runs from 676 W to well above 1000 W. It does not support the expectation that the maker understates the power, and it does not reject it. A start rest voltage or a log with a working current sensor settles the question.

**Command against speed.** The EMST model gives a command of 0.579 at 5 m/s and 0.608 at 15 m/s. The log gives 0.604 at 6 m/s and 0.584 at 17 m/s. The log command falls at speed. The model command rises. This is a direct disagreement of the J > 0 shape, or of the wind. It does not depend on the battery.

## Hover command and the ArduPilot map

Logged hover command: mean of the four RCOU outputs, (PWM - 1050) / 890.

| Window (s) | ThO | Learned MOT_THST_HOVER | Mean command | Motors 1 to 4 |
|---|---|---|---|---|
| 366.4 to 378.8 | 0.250 | 0.192 | 0.611 | 0.652, 0.666, 0.496, 0.630 |
| 379.5 to 385.7 | 0.227 | 0.209 | 0.586 | 0.612, 0.641, 0.460, 0.630 |
| 728.3 to 733.3 | 0.259 | 0.276 | 0.620 | 0.703, 0.577, 0.653, 0.552 |
| 797.3 to 800.8 | 0.238 | 0.252 | 0.601 | 0.671, 0.516, 0.665, 0.546 |

The command differs between motors by up to 0.2. The motors do not share the thrust equally. The spread changes between windows. This points to a CG offset or to a trim in the mix. It belongs to the mass data of step 5B.

**The map that fits the log.** MOTB gives lift_max 0.690 for the whole flight and a battery voltage ratio of 0.81. 0.81 is MOT_BAT_VOLT_MIN / MOT_BAT_VOLT_MAX (40.8 / 50.4), the lower limit. The motor library read 16 V from battery instance 0, so it held the voltage compensation at its lower limit all flight.

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
- The log does not show DroneCAN ESCs. MOT_PWM_TYPE is 0, CAN_D1_UC_ESC_BM and CAN_D2_UC_ESC_BM are 0, SERVO1 to SERVO4 (function 33 to 36) drive PWM outputs 1 to 4, and RCOU shows 1050 to 1895 us. This conflicts with the statement of the user. It stays an open question.
- A DroneCAN ESC takes the actuator value from 0 to 1 and ignores MOT_PWM_MIN and MOT_PWM_MAX. The twin command c is then equal to the actuator. A PWM ESC gets 1050 + 890 c. The number c is the same in both cases. The twin must not rescale c with SERVOn_MIN and SERVOn_MAX (1100 and 1900). The error is 0.4 % at hover and 4.5 points at the spin-arm value (0.15).

## Battery

Limits: another cell type, a 25 C table, no cell temperature in the log (BAT temperature is 0), and BATT_CAPACITY in the parameters is 4500 mAh for the main monitor. The capacity used here is 13.5 Ah (3 strings of 4.5 Ah).

| Item | Value | Source |
|---|---|---|
| End rest voltage, one 6S battery | 23.1 V (3.850 V per cell) | user fact |
| Battery rest voltage, 12S | 46.2 V | 2 x 23.1 V |
| End SOC | 65.1 % (table range 64.6 to 65.6 %, statistical half width 3.3 % with 0.05 V) | OCV table, 25 C |
| Same at 15 C | 65.1 % | table has one temperature |
| Charge remaining | 8791 mAh of 13500 mAh | end check |
| Start SOC | not known | not logged |
| Xing R and C | not computed | no usable voltage or current |
| 2RC extension | not computed | no usable voltage or current |
| Current scale and interval | not computed | no logged current |

The Aerolink command `flight battery` stops at the start check. The first five seconds of battery instance 0 give 1.338 V per cell, outside the table. Instance 1 has a constant current, so the sag fit has no excitation.

Notes on the battery data:

- BAT instance 0 uses pin 14 with multiplier 12.02. It reads 1.336 V at the pin. A 12S pack at 46 V to 50 V needs a multiplier near 34 to 37 for that pin voltage. The reading does not drop under load. Its range over the flight is 0.27 V.
- BAT instance 1 (BATT2, pin 13, multiplier 15) gives 49.50 V and 66.0 A for 99.5 % of the log, also on the ground after the landing. It is a floating or saturated input. The charge counter integrates 66 A and reaches 20.5 Ah. The PreArm message "Battery 2 low voltage failsafe" comes from this channel.
- BATT_AMP_PERVLT (39.877) and BATT_VOLT_MULT (12.02) of the main monitor give no valid pack signal in this log.

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
- `02_hover_power_models.png`: hover power of each model with the energy band.
- `03_battery_voltage_channels.png`: the three logged battery voltages.
- `04_soc_end_point.png`: the end SOC on the OCV table.
- `05_command_map.png`: the command map against the log.

## Open questions

1. The pack voltage and current of this flight. Fix the power module (BATT_MONITOR, pin, multiplier) and fly again, or read the ESC telemetry.
2. The start rest voltage of the 12S pack before this flight.
3. The ESC type. The log shows PWM outputs. The user states DroneCAN ESCs.
4. The air temperature at the site. The log holds only board temperatures.
5. Where the cell rest-voltage curve of the NXE 6S 4500 mAh differs from the table.
