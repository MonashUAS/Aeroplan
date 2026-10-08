# Uncertainty schema

The SSOT stores an uncertainty record for every dataset, mass value and derived result.
Code: `aeroplan/muas/uncertainty.py`. Schema: `schema/v0.1.0/uncertainty.schema.json`.

## Where the design comes from

| Source | What it gives |
|---|---|
| NASA-STD-7009B (approved 2024-03-05) | [M&S 29]: record uncertainty in input, results and derived values, and record margins and factors of safety with what they cover. [M&S 28] and [M&S 34]: record the process and the reason. [M&S 33]: report a quantitative estimate, a qualitative description, or a clear statement that none exists. |
| ADH / DAVE-ML (S-119) | Effect (additive, multiplicative, percentage, absolute). Normal and uniform distributions. Correlation. |
| MGP (AIAA 2023-1185) | Sigma for each dataset or each point, and the method used to get it. |
| JCGM 101:2008 | Monte Carlo coverage intervals. Propalyser uses it. Added because real data needed it. |

NASA-STD-7009B does not define a data format. The layout here is a MUAS design.

## Fields

| Field | Meaning | Rule |
|---|---|---|
| `status` | `quantitative`, `qualitative` or `unavailable` | [M&S 33] a, b, c |
| `scope` | `input`, `result` or `derived` | [M&S 29] a, b, c |
| `basis` | The process and the reason | Required, not empty |
| `method` | `repeat_scatter`, `binning`, `grid_study`, `tool_spread`, `sysid_cov`, `measurement_chain`, `vendor_spec`, `monte_carlo`, `engineering` | Required when quantitative |
| `distribution` | `normal`, `uniform` or `interval` | Required when quantitative |
| `effect` | additive, multiplicative, percentage, absolute | Required when quantitative |
| `sigma`, `num_sigmas` | Dataset value (normal) | Needs `sigma` or `per_point_column` |
| `lower`, `upper` | Bounds (uniform, interval) | `lower <= upper` |
| `coverage` | Probability inside the interval | Required for `interval` |
| `per_point_column` | Name of the sigma column in `points.parquet` | |
| `factors` | Margins and factors of safety, with what they cover | [M&S 29] b |
| `correlations` | Correlation with other variables | ADH form |
| `qualitative_level` | `small`, `medium`, `large` | Required when qualitative |

An `unavailable` record carries no number. It is a valid, honest state. Every Currawong aero dataset has it today (see [](../currawong/missing_data.md), M-20).

## Mapping to ADH

`Uncertainty.to_adh()` builds the ADH `Uncertainty` class for a normal or uniform record. An interval has no ADH form.
It stays in the MUAS record. Per-point sigma exports as a second table in the DAVE-ML file.

## Scalar results

`ScalarResult` holds one result with a coverage interval (median, lower, upper, coverage). The Propalyser Ct0 and Cp0 use it.

## Not done

- Sensitivity analysis (NASA-STD-7009B section 4.3.5).
- Propagation of uncertainty through the composed model.
- A GP fit (MGP). The data is stored so that the fit is possible later.
