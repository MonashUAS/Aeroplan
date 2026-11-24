# Rosella lift propulsion: motor, ESC and propeller selection

Date: 2026-11-02. Aircraft: Rosella, H4 12S quadplane. Model: `aeroplan/aerosandbox/settings/rosella.json`, level L4 (BEMT
rotor). This report gives the results of a study in one session. The study did not change the repository. The solve scripts
and the raw results were in a temporary folder, and the repository does not keep them.

## 1. Summary

1. **Use the T-Motor VL6013 KV210 with the T-Motor V80A 14S.** It has FOC and a prop lock (the motor has the magnetic encoder
   that the ESC reads). It meets every limit with the custom 660 mm prop and with the MAD FLUXER 22x6.6, at 18 kg and at 15 kg.
   At 15 kg with the 660 mm prop, it uses only 1.8 Wh (0.5 %) more energy than the VL6011.
2. **The VL6011 KV180 with the V80A uses the least energy of the FOC and prop-lock pairs at 18 kg** (426.1 Wh, 17.08 kg).
   But it does not work with the 22 in prop, at 18 kg or at 15 kg. At 18 kg with the 660 mm prop it has no torque margin.
3. **Only four of the 59 survey motors meet the V1 limits:** the VL6011, MN801-S, VL6013 and V605. All four are T-Motor.
4. **The MAD FLUXER 22x6.6 is a good backup prop, but only with a KV210 motor** (VL6013 or V605). The KV180 and KV150 motors
   cannot turn the 22 in prop fast enough to give T/W 2.3 at 20 % SOC.
5. **The 22 in prop costs about 19 Wh (5 %) at 15 kg** against the 660 mm prop on the same motor. Hover power goes up by
   about 12 %.
6. **The 660 mm rotor of the solve is a scaled blade that nobody sells.** It is the FLUXER 22x6.6 shape at 1.18 scale. A
   custom carbon prop can supply it. Measure it on a test stand before you rely on the 660 mm results.
7. **Commercial pairings use 22 in props because of the motor Kv, not because of a manufacturing limit.** T-Motor sells
   26 in to 30 in carbon props for low-Kv motors.

## 2. Scope and method

### 2.1 Limits

| Limit | Value | Source |
|---|---|---|
| MTOW (V1) | 18 kg maximum | user requirement 2026-10-17 |
| MTOW (competition) | 15 kg, with the same propulsion | user requirement 2026-11-02 |
| T/W | 2.3 at the lowest SOC of the mission (20 %) | user requirement 2026-10-17 |
| ESC duty | 0.95 maximum | `esc.duty_max`, stand-in |
| Motor torque | at most `q_cap` = (Imax − I0) / Kv | maker Imax |
| Rotor diameter | 406 mm to 660 mm (16 in to 26 in) | user decision 2026-10-17 |

### 2.2 Method

1. Each motor solve fixes the maker Kv, Rm, I0, Imax and mass. The `q_cap` value comes from the maker Imax.
2. Each pair solve also fixes the real ESC mass.
3. The solver sizes the battery, the rotor size (when it is free), the booms and the cables for the least mission energy.
4. The 15 kg solves model the airframe and avionics redesign as one mass saving at the CG
   (`avionics.projects_mass_kg` = 1.01 kg − saving). The CG and the inertia stay the same. The wing, booms, mission and
   payload do not change. Two passes set the saving so that the MTOW is 15.0 kg with the 22 in prop. The 660 mm solves use
   the same airframe, and their MTOW is 15.04 kg to 15.13 kg, because the larger props weigh more.
5. ESC rule of this study: the continuous rating must be at least 1.2 × the climb current. The burst rating (or the
   continuous rating, when the maker gives no burst rating) must be at least 1.2 × the peak current. The ESC must be rated
   for 12S. The model has its own stand-in rule (continuous rating at least 1.2 × the peak), and that rule rejects the V80A.

## 3. Motor screen

59 motors from `data/motor_survey.csv` have full data, `q_cap` of at least 1.5 N·m, Kv 60 to 450, a mass of at most 800 g
and a voltage rating of 44 V or more. 55 of them fail a V1 limit:

| Failure | Motors | Cause |
|---|---|---|
| Duty | U8 family, MN701-S KV135 (10 % short), KDE7208XF | Kv 135 or less. At T/W 2.3 and 20 % SOC, 12S cannot turn the 660 mm rotor fast enough. |
| MTOW | MN805-S, P80 III, U12 II, X5220 (1.2 % over) | Motor mass more than about 480 g. The aircraft goes above 18 kg. |
| Torque | MN601-S, U8 KV150, MAD8108 | The motor cannot give the 2.85 N·m peak. |

The four motors that pass:

| Motor | Kv (rpm/V) | Mass | Rm | I0 | Imax | q_cap |
|---|---|---|---|---|---|---|
| T-Motor VL6011 | 180 | 300 g | 80 mΩ | 1.1 A | 55 A | 2.86 N·m |
| T-Motor MN801-S | 150 | 480 g | 50 mΩ | 1.4 A | 60 A | 3.73 N·m |
| T-Motor V605 | 210 | 385 g | 48 mΩ | 1.6 A | 70 A | 3.11 N·m |
| T-Motor VL6013 | 210 | 388 g | 50 mΩ | 1.5 A | 70 A | 3.12 N·m |

## 4. Top 10 pairs at V1 (660 mm prop)

All 10 pairs meet every V1 limit. The rank is by mission energy. For comparison, the survey-fit motor of the baseline gives
426.2 Wh at 17.42 kg. The ESC mass changes the energy by about 0.16 Wh per gram (3 Wh at most). The list thus keeps, for each
motor, the lightest FOC ESC and the lightest ESC without stated FOC, plus the FOC and prop-lock pairs.

| # | Motor | ESC | ESC mass | Energy | MTOW | FOC | Prop stop |
|---|---|---|---|---|---|---|---|
| 1 | VL6011 KV180 | Castle Phoenix Edge Lite 80 HV | 42.5 g | 420.5 Wh | 16.89 kg | not stated | no |
| 2 | VL6011 KV180 | KDE-UAS55HVC | 64 g | 423.9 Wh | 17.01 kg | not stated | no |
| 3 | VL6011 KV180 | T-Motor ALPHA 60A 12S V1.2 | 73 g (with cables) | 425.3 Wh | 17.06 kg | yes | no |
| 4 | VL6011 KV180 | T-Motor V80A 14S | 78 g | 426.1 Wh | 17.08 kg | yes | yes |
| 5 | VL6011 KV180 | MAD FOC 100A (8-14S) | 85 g | 427.2 Wh | 17.12 kg | yes | no |
| 6 | MN801-S KV150 | Castle Phoenix Edge Lite 80 HV | 42.5 g | 432.3 Wh | 17.61 kg | not stated | no |
| 7 | MN801-S KV150 | T-Motor V60A 14S | 63 g | 435.3 Wh | 17.72 kg | yes | no (no encoder in the motor) |
| 8 | VL6013 KV210 | Castle Phoenix Edge Lite 120 HV | 52 g | 441.9 Wh | 17.59 kg | not stated | no |
| 9 | V605 KV210 | T-Motor ALPHA 60A 12S V1.2 | 73 g (with cables) | 445.0 Wh | 17.69 kg | yes | no |
| 10 | VL6013 KV210 | T-Motor V80A 14S | 78 g | 446.1 Wh | 17.73 kg | yes | yes |

Notes:

1. **VL6011:** at T/W 2.3 it uses its full 55 A rating, with no torque margin. At a V1 mass above about 17.1 kg it does not
   give T/W 2.3.
2. **MN801-S:** the front duty margin is 0.9 %.
3. **V605 and VL6013:** the peak current is 67.7 A. An 80 A burst rating gives only 1.18 × the peak, below the 1.2 rule.
   The row 10 solve ended with the status "acceptable", not "ok".
4. **ESC current:** T-Motor pairs the VL6011 with the V60A. Its 60 A burst rating is only 1.09 × the 55 A peak. The V80A
   gives more margin.
5. **FOC:** the model shows no benefit from FOC. It uses the same 20 mΩ stand-in resistance for every ESC. The survey ESC
   masses mix "with cables" and "without wire".

## 5. Prop stop

| System | Prop stop | Fit for Rosella |
|---|---|---|
| T-Motor V-series ESC (V40A to V200A, 6-14S, FOC) with a VL-series motor | The ESC reads the magnetic encoder in the motor and locks the prop | yes: VL6011, VL6013 |
| Hobbywing XRotor Pro H FOC | Stops at a set angle, only with a Hobbywing IPC or encoder motor | no: no such motor passed the screen |
| MAD ENCR motor with AMPX FOC 200A | Encoder auto-centre | no: the ENCR V105 is 999 g |

The hub of the prop must fit the motor shaft at one fixed angle, so that the locked blade aligns with the boom.

## 6. Why commercial pairings use 22 in props

T-Motor pairs the VL6011 with the VZ22x7.4 (558.8 mm) and gives 10.1 kg maximum thrust per arm, for a 15 to 18 kg quad.
T-Motor also sells 26.2 in and 28.2 in carbon props (FA26.2x8.5, FA28.2x9.2, NS26 to NS30), for low-Kv motors such as
the U8. The size is thus not a manufacturing limit. The causes:

1. **The prop must suit the motor Kv.** At the same thrust, a prop that is 1.18 times larger needs about 1.18 times the
   torque, at about 0.72 times the rpm. Torque sets the motor current. With the VZ22 at 100 % throttle and 44.5 V, the
   maker data gives 49.3 A, below the 55 A rating. The 660 mm solve uses the full 55 A at 18 kg.
2. **The objectives are different.** The maker rates a general quad. The model finds the least mission energy. Ideal hover
   power falls as 1/D, so the solver puts the rotor on its upper bound (`D_m` = 0.6604 m = 1.18 × 0.5588 m).
3. **A large prop has costs that the model does not fully include:** more rotor inertia and slower thrust change, a larger
   frame, and handling on the ground. The model includes the clearance limits and the stopped-prop drag. Its control check
   uses the steady thrust limits only, and not the motor response time.

## 7. Duty

Duty is the fraction of each switching period in which the ESC connects the battery to the motor. The mean motor voltage is
duty × bus voltage. At duty 1.0 the motor gets the full bus voltage and cannot turn faster. The model calculates it at the
MAX state (T/W 2.3, 20 % SOC), `model.py` line 383:

```
duty  = (omega / Kv + (Rm + Re + Rw) × I) / V_bus
V_bus = V0_min − Rb × I_bat
```

- The numerator is the voltage that the motor needs: the back-EMF plus the drop across the motor, ESC and wire resistance.
- The denominator is the voltage that the pack gives: the OCV at 20 % SOC less the sag at the peak current.
- The 0.05 below 1.0 is headroom for the attitude control above the T/W 2.3 point.

Duty is the voltage output of the ESC. The throttle command is the input:

| ESC type | The throttle command sets | Duty compared with throttle |
|---|---|---|
| Open loop (BLHeli, most trapezoidal ESCs) | the duty, through the throttle curve | about equal, after the end-point calibration |
| FOC, voltage mode | the voltage vector (modulation index) | close to equal |
| FOC, speed or current mode | the target rpm or current. A loop inside the ESC sets the voltage | not equal. The ESC gives more duty as the pack voltage falls |

A duty failure thus means that the Kv is too low for that prop and that pack. No throttle setting can correct it.

## 8. The MAD FLUXER 22x6.6 as backup

### 8.1 At V1 (rotor fixed at 559 mm)

| Motor + ESC | Status | Energy (660 mm → 22 in) | MTOW | Peak current (660 mm → 22 in) | Front duty margin |
|---|---|---|---|---|---|
| VL6011 + any of the 5 ESCs | fails | n/a | n/a | n/a | −16.7 % |
| MN801-S + either ESC | fails | n/a | n/a | n/a | −34.8 % |
| VL6013 + Castle Edge Lite 120 HV | ok | 441.9 → 466.1 Wh | 17.47 kg | 67.2 → 56.9 A | +0.2 % |
| V605 + ALPHA 60A | ok | 445.0 → 470.1 Wh | 17.57 kg | 67.7 → 57.3 A | +0.2 % |
| VL6013 + V80A | ok | 446.1 → 470.6 Wh | 17.61 kg | 67.7 → 57.1 A | 0.0 % |

At V1 the KV210 motors pass with the 22 in prop, but with almost no front duty margin.

### 8.2 At 15 kg

The same 15 kg airframe with each prop:

| Motor + ESC | 22 in: status, energy | 22 in front duty margin | 660 mm: energy, MTOW | 660 mm front torque margin | Hover power (4 rotors, 660 mm → 22 in) |
|---|---|---|---|---|---|
| VL6011 + V80A | fails | −9.3 % | 371.0 Wh, 15.11 kg | 8.6 % | 1626 → 1829 W |
| MN801-S + V60A | fails | −23.4 % | 363.3 Wh, 15.04 kg | 29.5 % | 1564 → 1819 W |
| VL6013 + V80A | ok, 391.7 Wh | +8.1 % | 372.8 Wh, 15.13 kg | 16.4 % | 1639 → 1843 W |
| VL6013 + Castle Edge Lite 120 HV | ok, 391.7 Wh | +8.1 % | 372.8 Wh, 15.13 kg | 16.4 % | 1639 → 1843 W |
| V605 + ALPHA 60A | ok, 392.4 Wh | +8.3 % | 372.9 Wh, 15.13 kg | 16.2 % | 1641 → 1849 W |

Findings:

1. **The VL6011 does not work with the FLUXER 22 at 15 kg.** The front rotors need about 9 % more duty than the limit
   permits. The rear rotors are at the limit. The maker data agrees: T-Motor gives 10.29 kg at 100 % throttle and 44.5 V
   with its own 22 in prop. A front rotor needs about 8.9 kg at T/W 2.3 and 15 kg. The margin is small before the lower
   voltage at 20 % SOC and the 5 % duty headroom. The FLUXER 22x6.6 also has less pitch than the VZ22x7.4.
2. **The VL6013 and V605 work with both props at 15 kg,** with 8 % front duty margin at 22 in.
3. **With the 660 mm prop at 15 kg, the VL6013 costs only 1.8 Wh (0.5 %) more than the VL6011.** At V1 the difference was
   20 Wh. The VL6013 also has about twice the torque margin.
4. **The MN801-S uses the least energy at 15 kg** (363.3 Wh, 2 % less than the VL6011). But it has no encoder for the prop
   lock, its V1 duty margin is 0.9 %, and it fails with the 22 in prop.
5. **ESC margin at 15 kg:** the VL6013 peak current is 58.8 A with the 660 mm prop and 49.6 A with the 22 in prop. The V80A
   burst rating is 1.36 × and 1.61 × these peaks. Both pass the 1.2 rule.

## 9. Custom carbon props

A custom 660 mm prop is the only way to get the rotor that the solve uses. Do these steps before you rely on it:

1. Make the blade that the model uses (the Proptimiser design at 1.18 scale, `rotor` in `rosella.json`), or put the table
   of your own blade into the model.
2. Measure thrust and torque on a test stand. At 1.18 scale, the BEMT table is an extrapolation of the FLUXER fit.
3. Weigh the prop and set `rotor.mass_kg`. At present the model uses the mass fit of AIAA 2016-0581.
4. Find the first blade bending mode. Keep it out of the 1P and 2P bands of hover, as the boom resonance rule does for the
   boom.
5. Make the hub fit the motor at one fixed angle, so that the locked blade aligns with the boom.

The tip Mach limit (0.65) and the tip clearance (20 mm) in the model are stand-ins. Set them from the blade data.

## 10. Recommendation and open items

| Choice | V1, 660 mm | V1, 22 in | 15 kg, 660 mm | 15 kg, 22 in | Prop lock |
|---|---|---|---|---|---|
| **VL6013 + V80A** | 446.1 Wh, 17.73 kg (ESC 1.18 × peak) | 470.6 Wh, 17.61 kg | 372.8 Wh, 15.13 kg | 391.7 Wh, 14.99 kg | yes |
| VL6011 + V80A | 426.1 Wh, 17.08 kg (no torque margin) | fails | 371.0 Wh, 15.11 kg | fails | yes |

Open items:

1. At V1 with the 660 mm prop, the VL6013 peak (67.7 A) is 0.85 × the V80A burst rating. Make sure the V1 mass stays below
   18 kg, or use a larger V-series ESC for V1.
2. Measure the custom 660 mm prop and the FLUXER 22x6.6 on the VL6013, and compare with the model tables.
3. Put the selected motor, ESC and prop into `settings/rosella.json` as bought parts, and solve again.
4. The ESC resistance (20 mΩ), `esc.duty_max` (0.95) and the 15 kg mass saving at the CG are stand-ins.

## 11. Fixed lift system: VL6011 KV180 with V80A 14S (2026-11-17)

User decision 2026-11-17: the lift propulsion system is fixed. The model file `aeroplan/aerosandbox/settings/rosella.json` holds
the maker values of the two parts (params `part`, `kv`, `q_cap`, `mass_kg`, `rm_ohm`, `i0_A` of the motor, and `part`, `mass_kg`,
`current_A`, `current_cont_A` of the ESC). The lift rotor stays the scaled blade (`rotor.scale` is free, 406 mm to 660 mm). The
notebook `rosella_sizing.ipynb` gives this result, and `aeroplan build rosella` wrote it into the source tree (version 0.1.12).

| Value | Fixed system | Survey-fit motor (before) |
|---|---|---|
| Take-off mass | 17.22 kg | 17.55 kg |
| Mission energy | 430.5 Wh | 430.4 Wh |
| Rotor diameter | 660 mm (upper bound) | 660 mm (upper bound) |
| Battery | 12S, 11.62 A·h | 12S, 11.62 A·h |
| Motor Kv, mass | 180 rpm/V, 300 g | 147 rpm/V, 389 g |
| Peak motor current (full throttle, T/W 2.3) | 54.1 A | 45.2 A |
| Motor torque at full throttle | 2.81 N·m of 2.86 N·m (1.6 % margin) | 2.87 N·m of 2.87 N·m |
| Duty at full throttle, 20 % SOC | 0.83 of 0.95 | 0.95 of 0.95 |
| Hover current, climb current (each motor) | 24.1 A, 26.7 A | 20.3 A, 22.4 A |

No limit is broken. The active limits are the yaw control authority (1.5 rad/s²) and the peak motor current.

### ESC rule and when the peak current occurs

The limit `esc_current_A` compares 1.2 times the peak motor current (65.0 A) with the 10 s peak rating of the V80A (80 A). The
continuous rating of the V80A is 40 A.

The peak current is the current of the state `MAX`: the four rotors at full throttle in hover, with a total thrust of 2.3 times
the weight. It does not depend on the wind or on the state of charge. The state of charge only sets the duty. The torque of this
rotor is in proportion to its thrust (Q / T is 0.0289 m in the hover state and in the `MAX` state), so the motor current follows
I = 1.1 A + 23.05 A × (T/W):

| Thrust over weight (four rotors) | Motor current | Against the V80A |
|---|---|---|
| 1.0 (hover, also the reserve hover) | 24.1 A | below the continuous rating |
| 1.0, in a vertical climb at 2.5 m/s (model state `C_TO`) | 26.7 A | below the continuous rating |
| 1.40 | 33.3 A | 1.2 × current = continuous rating |
| 1.69 | 40.0 A | continuous rating |
| 2.30 (full throttle) | 54.1 A | 10 s peak rating only |

A nominal flight stays below the continuous rating. The ESC goes above it only when a rotor gives more than 1.69 times its hover
thrust: a full throttle command, a motor failure, a hard recovery, or control saturation in a strong gust. The model has no gust
case, so it gives no wind speed for this. Open items: the maker does not state how long the V80A holds a current between 40 A
and 80 A, and it does not state the duration of the 55 A peak of the VL6011. The 2.3 thrust-to-weight requirement thus holds for
10 s at most with this ESC.

## 12. Sources

- [T-Motor VL6011 propulsion system](https://uav-en.tmotor.com/2024/VL-Series-Propulsion-System_1108/1251.html)
- [T-Motor VL6013 propulsion system](https://uav-en.tmotor.com/2024/VL-Series-Propulsion-System_1108/1252.html)
- [T-Motor V-series ESCs](https://uav-en.tmotor.com/VTOL/v-series/)
- [T-Motor VTOL locking propeller (MundoGEO)](https://mundogeo.com/2025/07/08/t-motor-fully-launches-customized-vtol-locking-propeller-solutions/?lang=en)
- [T-Motor folding propellers](https://uav-en.tmotor.com/Multirotor/Propellers/Folding)
- [T-Motor NS26 to NS30 carbon props (reseller)](https://druav.com/products/t-motor-multirotor-carbon-fiber-3rd-generation-gen-propellers-ns-series-ns26x8-5-ns27x8-8-ns28x9-2-ns30x10-light-prop-pair)
- [T-Motor 28.2x9.2 carbon foldable (GetFPV)](https://www.getfpv.com/t-motor-carbon-fiber-foldable-28-2x9-2-ccw-cw-set.html)
- [Tiger 28x9.2 carbon prop, U8 to U11 (GetFPV)](https://www.getfpv.com/tiger-28x9-2-carbon-fiber-three-blade-prop-pair.html)
- [Hobbywing XRotor H100A 14S FOC](https://hobbywing.com/en/products/xrotor-h100a-14s-foc-v1123)
- [Hobbywing XRotor Pro H110A 14S FOC](https://www.hobbywing.com/en/products/xrotor-pro-h110a-14s-foc)
- [Hobbywing H110A release (IPC)](https://www.hobbywing.com/en/news/info/149)
- [MAD ENCR V105 autocenter combo (reseller)](https://rcdrone.top/products/src-mad-529-encr-v105-evtol-autocenter-motor-combo)
- [T-Motor V605 (store)](https://store.tmotor.com/goods.php?id=922)
- [T-Motor MN701-S (store)](https://store.tmotor.com/goods.php?id=459)
