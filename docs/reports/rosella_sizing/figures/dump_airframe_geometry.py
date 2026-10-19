import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools" / "aerosandbox"))
import rosella as R
st = R.settings()
air = R.Airframe(st)
out = {
 "wing": air.surfaces["wing_main"]["sections"], "htail": air.surfaces["htail"]["sections"],
 "fuselage": air.new_fuselage_frames(),
 "tail_boom": air.tail_boom_frames,
 "wing_le": list(air.wing_le_x), "wing_te": list(air.wing_te_x),
 "x_np": air.neutral_point, "x_cg": air.x_cg, "c_ref": air.c_ref, "x_hub": air.x_hub,
 "cruise_D": air.cruise["diameter_m"],
}
Path(sys.argv[1]).write_text(json.dumps(out, default=float))
