# Redback twin: control validation (step 5B)

This page compares the ArduCopter control of the SITL twin with the real flight log. It finds why the twin is unstable.
All numbers come from the sources named here. The raw numbers are in `results.json`.

## Sources

| Item | Value |
|---|---|
| Flight log | `00000171.BIN`, sha256 `215616e25dd4532d0256e1ae4e9572d2cd73d8774ea1ae4c4b2642549ef0a57d`. ArduCopter 4.7.0 (1511f271), Quad X |
| Log parameters | `00000171_log.parm`, sha256 `3592de49e0fa3bedf37e3baac96ad93658b6368cd131ed73b0e359bcdaee3e13` |
| Package | `redback.muas` 0.2.0, file sha256 `d20ec190cb39a7582b0222e68b25e09850c665855992e5dc34577396c64781be`, Aerolink profile hash `2cc698f0e41b692d` |
| Time base | Record time is boot time minus 461.3 s. AUTO starts at 5.4 s in the record. The takeoff is at 466.7 s boot time |
| Log rates | RATE, ATT, PIDx, RCOU, CTUN: 10 Hz. IMU: 25 Hz. No ESC, RPM or valid BAT data |
| Step 5A input | `power/results.md`, commit b8e252d: PWM ESCs, flown thrust map, lift_max 0.69, CG shift |

The log rates are far below the 100 Hz that the frequency response needs. Every frequency response here stops at 5 Hz.
Table 3 and the findings say what this limit costs.

## Findings

1. The twin is unstable because its motor and propeller lag is too large. The JSBSim engine holds the power constant.
   That gives a lag of 0.26 s at hover (J w / 3Q with the package propeller inertia 0.00128 kg m^2). A voltage-driven
   motor with the Kv 150 and R_tot 0.432 ohm of the Propalyser chain gives 0.10 s with the same inertia.
2. The linear model of the loop agrees. With the lag of 0.26 s the roll and pitch attitude loops have a phase margin of
   about -3 deg (table 2, cases 1 and 2). With 0.10 s they have +19 deg.
3. SITL agrees. The as-built twin holds a 10 m hover for 12 s. Then a pitch and roll oscillation grows at 0.41 per second
   and 1.25 Hz to a limit cycle of +/-30 deg (figure `instability_time_history.png`). The linear model gives a growth of
   0.29 per second at 1.5 Hz. A propeller inertia of 0.00049 kg m^2 (lag 0.10 s) gives a stable hover with roll and pitch
   inside 0.2 deg. Lags of 0.15 s and 0.20 s are also stable. Table 4 lists every run.
4. Inertia is not the cause. The package already has the motors, propellers, ESCs, motor mounts and 3.831 kg of
   `PROPULSION-REST` as point masses: the motors, propellers, ESCs and mounts are at the hubs. With the inertia 2.2 times
   larger and the lag unchanged, the twin is unstable at once (table 4, run 3). With the larger inertia and the shorter
   lag it is stable (run 5).
5. Command map: no change is needed. The log has PWM ESCs. The twin turns the PWM of an output into the command with
   MOT_PWM_MIN 1050 and MOT_PWM_MAX 1940. The log fit of step 5A uses the same relation (PWM = 1050 + 890 x actuator).
   The motor outputs of the package stay placeholders.
6. The battery voltage compensation is off in the as-built twin, and the override that should switch it on has no effect.
   The twin sets `SIM_BATT_VOLTAGE` from `MOT_BAT_VOLT_MAX`. The flight file reads the battery on analog pins 14 and 15.
   SITL has its battery on pins 13 and 12. So the SITL battery monitor reads nothing and ArduCopter keeps lift_max at 1.0
   (SITL log MOTB). The real aircraft flew with lift_max 0.689 (step 5A). The SITL throttle output in hover is 0.302
   against 0.212 in the log. With `BATT_VOLT_PIN 13`, `BATT_CURR_PIN 12`, `BATT_VOLT_MULT 10.1`, `BATT_AMP_PERVLT 17` and
   `SIM_BATT_VOLTAGE 16` in a scratch twin, SITL gives lift_max 0.689 and a hover throttle output of 0.214. This is the
   flown map. It raises the loop gain by 1.22 (table 2, case 2 against case 1). It does not change the stability result.
7. The log cannot separate the control authority from the motor lag. The sample rate is 10 Hz and the signals are
   feedback-coupled. Fits of the attitude target to the attitude angle (0.25 to 1 Hz) give a roll authority of 51
   rad/s^2 per mixer unit (46 to 55) with a lag of 0.21 s, and a pitch authority of 112 (94 to 152) with a lag of 0.34 s.
   The twin has 218 and 204 (flown map). The two axes disagree by a factor of 2, and the roll and pitch inertias differ
   by 15 percent. So the fits are not reliable. Treat them as "the twin authority is not below the log value, and may
   be up to 4 times higher".
8. The log shows a lightly damped 2.0 Hz mode (`psd_roll_rate.png`, `bode_roll.png`). The roll rate PSD has a narrow
   peak at 2.0 Hz. The ratio of attitude to attitude target reaches 11 at 2.0 Hz. The linear model with the as-built plant
   has its closed-loop peak at 1.8 Hz with a ratio of 10. So the real aircraft probably flew near the stability limit too,
   with an effective lag nearer 0.2 s than 0.1 s. The twin with a lag of 0.10 s is more damped than the real aircraft.
   The measured ratio stays near 5 from 2.5 to 3.6 Hz. The model does not reproduce that. The attitude target is not an
   independent input there.
9. The yaw attitude loop has a phase margin of about -1 deg in every linear case, because the yaw rate loop crossover
   is 0.2 Hz and ATC_ANG_YAW_P is 4.5 rad/s. The yaw angle limit (ATC_ACC_Y_MAX) is not in the model. SITL holds yaw in
   hover. The yaw margins are a model limit, not a measured fault.
10. The real aircraft had a CG offset. The thrust centroid in the four hover segments (from RCOU and the twin thrust
    curve) sits at x = -39 and -57 mm (loaded) and +63 and +79 mm (after about 728 s), and at y = +29, +36, +8 and +9 mm.
    The package puts the CG at x = y = 0. The replay of the hover segment shows it: motor 3 is 0.12 higher in the twin,
    motors 1, 2 and 4 are 0.03 to 0.06 lower.
11. In forward flight the twin needs more motor command than the real aircraft. In the manoeuvre segment at 30 deg of
    tilt the mean command is 0.81 in the twin and 0.65 in the log (after the first 4 s). In hover the two agree (0.597
    and 0.599). The twin propeller loses thrust with axial flow (the CT table runs only to J 0.47 and JSBSim has no
    edgewise flow model). This is a known limit (docs/twins.md). It is a model finding, not a fix.
12. Air density: the bridge has no atmosphere offset. The twin flies in ISA density at the site height (1.156 kg/m^3 at
    584 m). The user gave 1.10 kg/m^3 at 40 C. The twin thrust per command is therefore about 5 percent high. This is not
    in the overlays.

## Table 1: inertia (kg m^2, about the CG, package mass 9.134 kg)

| Case | Ixx | Iyy | Izz |
|---|---|---|---|
| Package as built (motors, propellers, ESCs, mounts at the hubs, booms at half arm, the rest at the origin) | 0.2561 | 0.2935 | 0.5430 |
| Bound, scratch only: the 3.831 kg `PROPULSION-REST` moved to the four hubs | 0.7930 | 0.9096 | 1.6929 |

The first case already has the motors, propellers and ESCs at the hubs. The bound is a ceiling that no real layout
reaches. The real value is between the two. The battery, the payload and the avionics are at the origin in the package.
Their real positions are not in the data. The thrust centroid (finding 10) says the real CG is not at the origin.
Sensitivity: inertia x1.5 and x2.2 change the roll attitude phase margin by +2 deg (case 6 and 7 against case 3). Inertia
is not a lever for stability here.

## Table 2: margins with the logged ATC gains

The loop is broken at the actuator. The model is `accontrol` (400 Hz loop, one sample of delay, gyro filter 20 Hz, lift_max
as stated). The goals are phase margin 45 deg, gain margin 6 dB, Ms 2.0. PM is the phase margin. fc is the crossover.

| No. | Case | Roll rate PM (deg) | Roll rate fc (Hz) | Roll attitude PM (deg) | Roll attitude Ms | Pitch attitude PM (deg) | Yaw attitude PM (deg) | Altitude PM (deg) | Altitude fc (Hz) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | As built, SITL voltage 50.4 V (lift_max 1.0), lag 0.26 s | 21.6 | 1.52 | -3.3 | 17.4 | -3.7 | -17.9 | 56.7 | 0.98 |
| 2 | As built with the flown voltage map (lift_max 0.69), lag 0.26 s | 20.4 | 1.70 | -2.1 | 27.3 | -2.5 | -18.9 | 56.7 | 0.98 |
| 3 | Recommended: lag 0.10 s, flown map | 32.9 | 2.77 | 18.7 | 3.2 | 19.1 | -1.2 | 88.8 | 1.97 |
| 4 | Lag 0.10 s, lift_max 1.0 | 36.1 | 2.42 | 19.8 | 3.0 | 20.1 | -1.2 | 88.8 | 1.97 |
| 5 | Lag 0.20 s, flown map | 23.9 | 1.94 | 3.9 | 14.7 | 3.7 | -13.0 | 67.1 | 1.16 |
| 6 | Lag 0.10 s, inertia x1.5, flown map | 39.4 | 2.09 | 20.5 | 2.9 | 20.7 | -1.5 | 88.8 | 1.97 |
| 7 | Lag 0.10 s, inertia x2.2, flown map | 45.0 | 1.59 | 20.8 | 2.8 | 20.7 | -2.1 | 88.8 | 1.97 |
| 8 | Lag 0.26 s, inertia x1.5, flown map | 22.9 | 1.35 | -4.7 | 12.4 | -5.1 | -16.9 | 56.7 | 0.98 |

Loop authority (rad/s^2 per mixer unit, with the thrust linearisation gain): roll 179 and 218, pitch 168 and 204, yaw 5.5 and
6.7 (case 1 and case 2). The altitude loop is the position cascade (PSC_D_POS_P, PSC_D_VEL_P, PSC_D_ACC_*) with the motor lag
and a vertical gain g / MOT_THST_HOVER. It is a simple model and it has no controller output limits. No case meets the 45 deg
goal for the attitude loops, even the recommended one. The real aircraft flew at default rate gains (P 0.135, I 0.135, D 0.0036).
The chart is `margins_attitude.png`.

## Table 3: frequency responses from the log

| Pair | Valid band (coherence above 0.6) | Note |
|---|---|---|
| Rate demand to rate, roll | 0.37 to 3.4 Hz | Closed loop. Feedback and noise bias the gain above 2 Hz |
| Rate demand to rate, pitch | 0.31 to 3.8 Hz | The same |
| Rate demand to rate, yaw | 0.31 to 0.88 Hz | Too narrow to find a crossover |
| Mixer output to gyro, roll | 1.6 to 3.0 Hz | Biased by feedback: the gain follows 1/controller |
| Mixer output to gyro, pitch | 0.63 to 5.0 Hz | The same |
| Mixer output to gyro, yaw | 0.31 to 0.63 Hz | Too narrow |
| Attitude target to angle, roll | 0.25 to 0.75 Hz and 1.9 to 3.6 Hz | Exogenous input. The plots are `bode_roll.png` and `bode_pitch.png` |

The plot `frf_rate_loop.png` shows the first and second pairs. The mixer-to-gyro estimate has an input that the feedback
drives. Its gain at 2.5 to 4 Hz is 5.2 rad/s per unit and its phase is 180 deg. That is the inverse of the controller
(P 0.135 and D 0.0036 give 1/0.15). It is not the plant. The attitude-target pair is the unbiased one. The authority and
lag fits are in finding 7 and `authority_lag_fit.png`.

| Quantity | Twin as built | Twin recommended | Log (weak) | Physical estimate |
|---|---|---|---|---|
| Motor and propeller lag at hover (s) | 0.26 (SITL large-signal fit 0.28) | 0.10 (0.15 large-signal fit) | roll 0.21, pitch 0.34 (fits not reliable) | 0.10 with the package inertia, 0.13 with 0.0017 kg m^2 |
| Roll authority (rad/s^2 per mixer unit) | 218 | 218 | 51 (46 to 55) | none |
| Pitch authority | 204 | 204 | 112 (94 to 152) | none |

The physical estimate is J / (Kt^2 / R + 2 Q / w) with Kt = 0.0637 N m/A (Kv 150), R_tot 0.432 ohm (both from the Propalyser chain),
Q = 0.545 N m and w = 331.7 rad/s (twin hover). It has no motor-rotor inertia. The plot is `motor_lag.png`.

## Table 4: SITL hover runs (GUIDED takeoff to 10 m, 30 to 40 s hold)

Twin: ArduCopter 4.7.0 SITL on the package JSBSim model, the log parameter file, the Aerolink overrides. Every change is scratch.

| No. | Run | Max roll after 20 s (deg) | Max pitch after 20 s (deg) | Result |
|---|---|---|---|---|
| 1 | As built | 36 | 38 | Unstable |
| 2 | As built, `SIM_BATT_VOLTAGE` 16 V only | 34 | 40 | Unstable. The override has no effect (finding 6) |
| 3 | Inertia x2.2, lag 0.26 s | 82 | 80 | Unstable at once |
| 4 | Lag 0.10 s | 0.08 | 0.17 | Stable |
| 5 | Inertia x2.2 and lag 0.10 s | 0.12 | 0.15 | Stable |
| 6 | Lag 0.10 s, `SIM_BATT_VOLTAGE` 16 V only | 0.13 | 0.12 | Stable |
| 7 | Lag 0.10 s and the flown voltage map | 0.07 | 0.11 | Stable. Throttle output 0.214 |
| 8 | Lag 0.15 s and the flown voltage map | 0.09 | 0.10 | Stable |
| 9 | Lag 0.20 s and the flown voltage map | 0.09 | 0.08 | Stable |

The stability limit in SITL is between a lag of 0.20 s and 0.26 s. The linear model gives a phase margin of 4 deg at 0.20 s and
-2 deg at 0.26 s. The lag is set in the scratch model with the propeller ixx: 0.00049 gives 0.10 s, 0.00074 gives 0.15 s, 0.00098 gives
0.20 s (lag = ixx x 0.26 / 0.00128). The lag at other operating points differs from the hover value.

## Table 5: SITL against the log, logged targets replayed

The twin flies in GUIDED. The driver sends the logged ATT target (roll, pitch, yaw relative to the start) at 25 Hz. The climb
rate demand is the logged climb rate (the thrust field of a GUIDED attitude target is a climb rate). The twin starts in a level hover, so
the first 4 s are a start-up transient. The table skips them. Rates from the twin pass a 20 Hz second-order low-pass
(INS_GYRO_FILTER). Theil U: 0 is a perfect match. The band of `compare.bands` is 0.3. The twin is the recommended one (lag 0.10 s, flown map)
unless the row says "as built". The time offset between the twin truth and the SITL boot clock is -0.04 to -0.05 s.

| Channel | Hover U | Hover RMS | Manoeuvre U | Manoeuvre RMS | Manoeuvre as built U | Manoeuvre as built RMS |
|---|---|---|---|---|---|---|
| Roll (deg) | 0.061 | 0.67 | 0.312 | 4.55 | 0.465 | 7.73 |
| Pitch (deg) | 0.127 | 0.75 | 0.033 | 1.61 | 0.069 | 3.29 |
| Yaw change (deg) | 0.073 | 3.02 | 0.023 | 6.82 | 0.049 | 14.4 |
| Roll rate (deg/s) | 0.582 | 4.51 | 0.513 | 5.12 | 0.535 | 5.23 |
| Pitch rate (deg/s) | 0.571 | 4.76 | 0.530 | 5.31 | 0.525 | 5.50 |
| Yaw rate (deg/s) | 0.361 | 2.47 | 0.264 | 11.6 | 0.394 | 18.7 |
| Altitude change (m) | 0.717 | 0.236 | 0.340 | 0.151 | 0.244 | 0.121 |
| Motor 1 command | 0.047 | 0.058 | 0.125 | 0.181 | 0.131 | 0.190 |
| Motor 2 command | 0.050 | 0.063 | 0.037 | 0.059 | 0.044 | 0.070 |
| Motor 3 command | 0.118 | 0.126 | 0.235 | 0.315 | 0.238 | 0.321 |
| Motor 4 command | 0.029 | 0.035 | 0.097 | 0.146 | 0.100 | 0.152 |

The hover window is log 367.3 to 385.5 s. The manoeuvre window is log 98 to 114 s (it holds the manoeuvre at 99.6 to 103 s and a
change to 30 deg of pitch). The as-built row of the manoeuvre has no voltage map and a lag of 0.26 s. The twin stays up in the
replay because the replay gives a smooth target and starts from a hover. The as-built twin still rings in the first 3 s (rates to 190 deg/s).
Attitude and yaw match well. The rate channels have a high U because the log rate is a 10 Hz sample of a noisy signal and the
twin rate is smooth. The motor 3 and manoeuvre motor bias are the CG offset and the forward-flight thrust loss (findings 10 and 11).
The plots are `overlay_hover.png` and `overlay_manoeuvre.png`. The altitude U of the hover is high because the altitude change is
0.2 m in total and the log has a slow drift.

## Table 6: k_rotor_drag

The twin supports it (body drag in `jsbsim_xml.py`: Fx = -0.5 rho S CDx u|u| - k n_sum u). The log has cruise at 15 to 17.5 m/s
ground speed (60 to 300 s). The fit uses ten steady 10 s windows at 15.6 to 17.1 m/s ground speed. For each window the tilt of the
thrust is D / W. The unknowns are the wind (two numbers), the quadratic drag coefficient a and the rotor drag k.

| Fit | Wind (m/s north, east) | a = 0.5 rho S CDx (N/(m/s)^2) | k_rotor_drag (kg) | RMS tilt error (deg) |
|---|---|---|---|---|
| Quadratic drag only | 5.4, 1.1 | 0.081 (se 0.004) | not fitted | 1.24 |
| With k | not separable | 0 to 0.08 | 0 to 0.007 | 1.24 to 1.64 |

The package placeholders give a = 0.0516 (S 0.06 m^2, CDx 1.404, k 0). The data fix the total drag (a = 0.081 with k = 0, that is
CDx S = 0.132 m^2, 57 percent above the placeholder). They do not separate k from CDx. Every pair (a, k) on the line from (0.081, 0) to (0.021, 0.0046 kg)
fits as well. So k_rotor_drag is not identifiable from this log. The wind is a free parameter. The plot is `drag_fit.png`.
The fit assumes thrust along the body z axis, a steady state and flow along the track.

## Recommended changes (for the user to decide)

1. Aerolink twin: lower the effective motor lag from 0.26 s to about 0.10 s. The physical lag of a voltage-driven motor is
   0.10 s (0.13 s with a motor rotor inertia). The JSBSim engine cannot do it. The scratch fix is an equivalent propeller inertia
   (0.00049 kg m^2 for 0.10 s at hover). A better fix is a voltage-driven motor model in the twin (a code change in Aerolink).
2. Aerolink config: add the battery pin overrides (`BATT_VOLT_PIN 13`, `BATT_CURR_PIN 12`, `BATT_VOLT_MULT 10.1`,
   `BATT_AMP_PERVLT 17`) so that `SIM_BATT_VOLTAGE` reaches ArduCopter. Then decide the voltage: the real monitor read 16.0 V
   (step 5A). At the nominal pack voltage of 44.4 V, lift_max is 0.79, not 0.69.
3. Propulsion data: the package propeller `ixx_kgm2` 0.00128 is the propeller only. The contract says it must include the motor rotor.
   Measure the rotor inertia. A larger value raises the lag.
4. Mass model: the real CG is not at the origin (finding 10). A weighed CG and the battery and payload positions will help.
   The package inertia is a lower bound of the real value. The margins do not depend on it (table 2).
5. Next flight: set `LOG_BITMASK` for fast attitude and raw IMU, `INS_LOG_BAT_OPT`, and fly a SystemID chirp (SID_AXIS roll, pitch,
   yaw) in calm air. The authority and lag then follow from a 400 Hz log. The present 10 Hz log cannot do it.
6. Controller: the real aircraft flew near the margin (finding 8). Rate gains lower than the defaults, or a lower
   `ATC_ANG_*_P`, give more margin on the real aircraft.

## Commits (Aerolink, local)

| Commit | Message |
|---|---|
| 67bb5e2 | Require the harmonic notch parameters only when the notch is on |
| 9c8f58c | Add the battery voltage compensation to the ArduCopter loop gain |

The first fixes a real bug: `aerolink control` refused the Redback parameter file because ArduPilot leaves `INS_HNTCH_*` out when the
notch is off. The second adds `lift_max` to the loop gain (the request of step 5A). Both have tests. The full Aerolink tests pass
(387 passed, 1 skipped).

## Open questions

1. The user said DroneCAN ESCs. The log parameters say PWM ESCs (step 5A, user fact). Confirm PWM.
2. What is the true battery voltage during the flight? The monitor read 16.0 V all flight.
3. Is the 2.0 Hz ringing of the real aircraft a known behaviour? It says the real loop has a low phase margin.
4. The authority of the real aircraft is 1.5 to 4 times lower than the twin (finding 7, weak). Which of inertia, thrust slope and lag causes it?
5. Air temperature and density: the twin needs an atmosphere offset to use the 40 C density.
