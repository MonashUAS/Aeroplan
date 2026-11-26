"""The ratchet of the architecture rules (ADR 0031): rule -> {file: why the file breaks the rule today}.

A file on this list may keep its violations. A new file may not join without a review of this diff. A file on the list
with no violation left fails the check, so the list only gets shorter. Each entry names the work that removes it.
"""

ALLOW = {
    "AP010": {
        "aeroplan/wing.py": "the tool-neutral wing form holds flow5 degrees (dihedral, twist). Phase 2: radians",
        "aeroplan/geometry.py": "planform_of gives the flow5 degree form. Phase 2: radians in the core form",
        "aeroplan/parts.py": "reads the degree form of the wing. Goes with geometry.py in Phase 2",
        "aeroplan/visual.py": "reads the degree form of the wing. Goes with geometry.py in Phase 2",
        "aeroplan/aero_buildup.py": "the flow5 build-up tables use degrees. Phase 2: move the edge into aeroplan/flow5/",
        "aeroplan/multirotor.py": "the seed reads the arm angle in degrees from the settings. Phase 2: settings in radians",
        "aeroplan/skin_body.py": "the fit report prints an angle in degrees. Phase 2: report radians",
    },
    "AP014": {
        "aircraft/redback/datasets/aero.redback.json": "the dataset description names the old contract path. The spoke "
                                                       "text is fixed: run `python -m aeroplan build redback` to remove it",
    },
    "AP011": {
        "aeroplan/flow5/sweep.py": "flow5 itself uses g = 9.81. The sweep must use the value of the tool to compare",
    },
}
