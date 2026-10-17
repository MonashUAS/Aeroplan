"""Neutral point of an aircraft tree by the AeroSandbox vortex lattice (wing, htail, fin, no fuselage).

    tools/aerosandbox/.venv/Scripts/python.exe tools/aerosandbox/neutral_point.py currawong

Writes work/aerosandbox/<aircraft>/neutral_point.json: x_np_m, mac_m, method, panel counts, a hash of the tree files
and the date. It prints the wing root leading edge x (ADR 0023: it must be 0). The method is the one of
`Airframe._neutral_point` in rosella.py: alpha 0 and 4 deg, 16 spanwise and 12 chordwise panels, x_np = x_ref - c_ref dCm/dCL.
The SpecSheet spoke reads the file for the battery trim. Run it again after a change of the wing, tail or c_ref.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

SPANWISE, CHORDWISE, VELOCITY_M_S, ALPHAS_DEG = 16, 12, 17.0, (0.0, 4.0)
SURFACES = ("wing_main", "htail", "fin")
BODIES = ("fuselage", "tail_boom")


def tree_hash(tree: Path) -> str:
    """sha256 of every JSON file of the tree (names and bytes, sorted)."""
    h = hashlib.sha256()
    for f in sorted(tree.rglob("*.json")):
        h.update(f.relative_to(tree).as_posix().encode())
        h.update(f.read_bytes())
    return h.hexdigest()


def neutral_point(aircraft: str) -> Dict[str, Any]:
    import aerosandbox as asb
    from aeroplan import adh_doc, source_tree
    import spec as asb_spec
    from asb_worker import build_airplane

    tree = ROOT / "aircraft" / aircraft
    doc = source_tree.read(tree).doc
    ref = adh_doc.node(doc, "1.2")["muas"]["reference"]
    s_ref, b_ref, c_ref = (ref[k]["value"] for k in ("s_ref", "b_ref", "c_ref"))
    x_ref = float(ref["mrp"]["point"]["xyz"][0])
    wing = adh_doc.find(doc, "wing_main")["muas"]["planform"]
    wing_le_x = float(wing["position"]["xyz"][0] + wing["sections"][0]["x_offset"])
    pr = adh_doc.find(doc, "prop_cruise")["muas"]["propeller"]          # a propulsor is needed to build the airplane; the VLM ignores it
    plane = build_airplane({"name": aircraft, "reference": {"s_m2": s_ref, "b_m": b_ref, "c_m": c_ref, "xyz_ref": [x_ref, 0.0, 0.0]},
                            "surfaces": [asb_spec._surface_spec(doc, n) for n in SURFACES], "fuselages": [],
                            "propulsion": {"hub": pr["hub"]["xyz"], "thrust_axis": [-1.0, 0.0, 0.0],
                                           "diameter_m": pr["diameter"]["value"]}})
    # The VLM has no body. The body term (fuselage and tail boom, AeroBuildup body model) moves the NP forward.
    frames = [{"name": b, "frames": [f.tolist() for f in asb_spec.body_frames(adh_doc.find(doc, b)["geometry"]["body"])]}
              for b in BODIES]
    bodies = build_airplane({"name": "bodies", "reference": {"s_m2": s_ref, "b_m": b_ref, "c_m": c_ref, "xyz_ref": [x_ref, 0.0, 0.0]},
                             "surfaces": [], "fuselages": frames,
                             "propulsion": {"hub": pr["hub"]["xyz"], "thrust_axis": [-1.0, 0.0, 0.0],
                                            "diameter_m": pr["diameter"]["value"]}})
    out = []
    for a in ALPHAS_DEG:
        op = asb.OperatingPoint(atmosphere=asb.Atmosphere(altitude=0.0), velocity=VELOCITY_M_S, alpha=a)
        r = asb.VortexLatticeMethod(plane, op, spanwise_resolution=SPANWISE, chordwise_resolution=CHORDWISE,
                                    align_trailing_vortices_with_wind=False).run()
        bd = asb.AeroBuildup(bodies, op).run()
        out.append((float(r["CL"]) + float(bd["CL"]), float(r["Cm"]) + float(bd["Cm"])))
    d_cl, d_cm = out[1][0] - out[0][0], out[1][1] - out[0][1]
    x_np = float(plane.xyz_ref[0] - c_ref * d_cm / d_cl)
    return {"aircraft": aircraft, "x_np_m": x_np, "mac_m": float(c_ref), "x_ref_m": x_ref, "wing_root_le_x_m": wing_le_x,
            "method": "AeroSandbox VortexLatticeMethod (wing + htail + fin) plus AeroBuildup body term (fuselage, tail boom), alpha 0 and 4 deg, "
                      "x_np = x_ref - c_ref dCm/dCL",
            "panels": {"spanwise": SPANWISE, "chordwise": CHORDWISE}, "velocity_m_s": VELOCITY_M_S,
            "tree_sha256": tree_hash(tree), "date": datetime.date.today().isoformat()}


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print(__doc__)
        return 2
    res = neutral_point(args[0])
    out = ROOT / "work" / "aerosandbox" / args[0] / "neutral_point.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
    print(f"wing_main root leading edge x = {res['wing_root_le_x_m']:+.4f} m (must be 0, ADR 0023)")
    print(f"neutral point x_np = {res['x_np_m']:+.4f} m, mac = {res['mac_m']:.4f} m -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
