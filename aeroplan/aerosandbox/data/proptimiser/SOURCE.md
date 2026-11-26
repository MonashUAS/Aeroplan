# Proptimiser blade files

Git ignores the blade files in this folder: they come from the private Proptimiser repository, and AeroPlan is public
(`.gitignore`). The owner decides if they are published.

The design file (`designs/<name>.yaml`) and the state file (`propellers/<name>.state.json`) of each blade that the sizing
models use. `component.proptimiser_home` reads a blade from `work/aerosandbox/<aircraft>/proptimiser/` first. When that
file is missing (a new clone: git ignores `work/`), it reads the copy here.

These are hand copies (ADR 0036). Copy a changed blade here by hand, and update the table.

| File | Source | sha256 |
|---|---|---|
| `currawong/designs/Currawong_V1.yaml` | Proptimiser commit 711ef86, `designs/Currawong_V1.yaml` | `3f0d4128558f704aa3292237f9c6b994a0be09f90c42543e0486c78cc6a8273d` |
| `currawong/propellers/Currawong_V1.state.json` | Proptimiser commit 711ef86, `propellers/Currawong_V1.state.json` | `6d1c0ba65bd4185bd2ca4467315325c2d52a442099b200cad567bfb7b8eb192c` |
| `redback/designs/MAD_FLUXER_22x6_6_jung.yaml` | `work/aerosandbox/redback/proptimiser/` of 2026-10-21 (Jung 2021 T-motor shape, `fit_prop --shape`). Not in a pushed Proptimiser commit in this form | `f088dcf0ce7e1b5876cc4b4820ab04ba34062d20f00bc7c0131186f029b6167c` |
| `redback/propellers/MAD_FLUXER_22x6_6_jung.state.json` | Proptimiser commit fbef09c, `propellers/MAD_FLUXER_22x6_6_jung.state.json` | `00f942535debf2cf53c6057041aa4390c4387d304a6af16ae5d7499aab506137` |
