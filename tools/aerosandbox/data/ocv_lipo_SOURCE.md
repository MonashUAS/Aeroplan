# ocv_lipo.csv: open-circuit voltage (OCV) of one LiPo cell against the state of charge (SOC)

- A hand copy of the Aerolink file `spec/battery/ocv_lipo.csv` (Aerolink commit 680791e, 2026-10-17). Copied 2026-10-21.
  sha256: `eed82560919e178d1321e9537b78db19510377d95f19fdca90dfea68dd4a9a33` (the same as the Aerolink SOURCE.md).
- Aerolink derived the table from Galeotti et al. 2023, "LiPo batteries dataset: Capacity, electrochemical impedance
  spectra, and fit of equivalent circuit model at various states-of-charge and states-of-health", Data in Brief 50,
  109561, doi:10.1016/j.dib.2023.109561. Data: Mendeley Data, doi:10.17632/stcppt2r68.1, CC BY 4.0. The Aerolink
  `spec/battery/SOURCE.md` gives the method and the checks.
- Cells: five BAK LP-503562-IS-3 cells (3.7 V, 1.1 Ah) at 25 C, fresh. Not the Rosella pack cell, so the sizing model
  marks the table as a stand-in (`placeholder`). Replace it with the OCV of the pack cell when a measured curve exists.
- Rows: SOC 10 to 100 percent in steps of 10. The sizing model uses the columns `soc_pct` and `ocv_mean_v`.

## The same model in Aerolink and in the sizing model

Aerolink (`xing_soc.py`, Xing et al. 2014, Eq. 5): U_term = U_OCV(SOC, T) - I R + C. The sizing model
(`component.OCVModel`, `model.QuadplaneModel.build`) uses the same circuit for the pack, with C = 0 and one temperature
(25 C):

    V_pack = S OCV(SOC) - R_b I

R_b is the pack resistance (`battery.cell_resistance_mohm`). `aerolink flight battery` fits R_b from a flight log. Put that
value in the battery component when it exists.
