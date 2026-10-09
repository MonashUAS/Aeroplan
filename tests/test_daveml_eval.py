"""The DAVE-ML evaluator: tables, MathML and checkData. Every number is synthetic."""
import math

import pytest

from aeroplan import daveml_adh, daveml_eval
from aeroplan.dml_validate import validate_dml

M = 'xmlns="http://www.w3.org/1998/Math/MathML"'


def _model(check: str = "", z_calc: str = "") -> dict:
    xml = f"""<?xml version="1.0"?>
<DAVEfunc xmlns="http://daveml.org/2010/DAVEML">
  <fileHeader name="synthetic">
    <author name="test" org="test"/>
    <creationDate date="2026-01-01"/>
    <reference refID="R1" author="test" title="synthetic" date="1992"
               xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="https://example.org/r1"/>
  </fileHeader>
  <variableDef name="x" varID="x" units="deg"><isInput/></variableDef>
  <variableDef name="y" varID="y" units="nd" initialValue="0.5"><isInput/></variableDef>
  <variableDef name="tab" varID="tab" units="nd"/>
  <variableDef name="pts" varID="pts" units="nd"/>
  <variableDef name="k" varID="k" units="nd" initialValue="2.0"/>
  <variableDef name="z" varID="z" units="nd">
    <calculation><math {M}>{z_calc or '''
      <apply><plus/>
        <apply><times/><ci>k</ci><ci>tab</ci></apply>
        <apply><power/><ci>y</ci><cn>2</cn></apply>
        <apply><abs/><apply><minus/><ci>pts</ci></apply></apply>
      </apply>'''}
    </math></calculation>
    <isOutput/>
  </variableDef>
  <breakpointDef bpID="X" units="deg"><bpVals>0, 10, 20</bpVals></breakpointDef>
  <breakpointDef bpID="Y" units="nd"><bpVals>0, 1</bpVals></breakpointDef>
  <function name="tab_fn">
    <independentVarRef varID="x" min="0" max="20" extrapolate="neither"/>
    <independentVarRef varID="y" extrapolate="neither"/>
    <dependentVarRef varID="tab"/>
    <functionDefn name="tab_def">
      <griddedTableDef gtID="T1">
        <breakpointRefs><bpRef bpID="X"/><bpRef bpID="Y"/></breakpointRefs>
        <dataTable>0, 1,  10, 11,  20, 21</dataTable>
      </griddedTableDef>
    </functionDefn>
  </function>
  <function name="pts_fn">
    <independentVarPts varID="x">0 20</independentVarPts>
    <dependentVarPts varID="pts">0 -4</dependentVarPts>
  </function>
  {check}
</DAVEfunc>"""
    return daveml_adh.from_xml(xml.encode())


def test_multilinear_table_and_mathml():
    v = daveml_eval.Model(_model()).evaluate({"x": 5.0, "y": 0.5})
    assert v["tab"] == pytest.approx(5.5)                     # row-major, the last breakpoint set fastest
    assert v["pts"] == pytest.approx(-1.0)
    assert v["z"] == pytest.approx(2 * 5.5 + 0.25 + 1.0)
    v = daveml_eval.Model(_model()).evaluate({"x": 99.0})    # clamped to max, y from its initialValue
    assert v["tab"] == pytest.approx(20.5)


def test_piecewise_relations_and_atan2():
    calc = """<apply><piecewise>
        <piece><csymbol definitionURL="http://daveml.org/function_spaces.html#atan2" encoding="text">atan2</csymbol>
               <apply><lt/><ci>x</ci><cn>0</cn></apply></piece>
        <otherwise><apply><csymbol definitionURL="http://daveml.org/function_spaces.html#atan2"
          encoding="text">atan2</csymbol><ci>y</ci><cn>1</cn></apply></otherwise></piecewise></apply>"""
    v = daveml_eval.Model(_model(z_calc=calc)).evaluate({"x": 1.0, "y": 1.0})
    assert v["z"] == pytest.approx(math.pi / 4)


def test_check_data_pass_and_fail():
    shot = """<checkData><staticShot name="s1"><checkInputs>
      <signal><signalName>x</signalName><signalUnits>deg</signalUnits><signalValue>10</signalValue></signal>
      <signal><signalName>y</signalName><signalUnits>nd</signalUnits><signalValue>1</signalValue></signal>
    </checkInputs><checkOutputs>
      <signal><signalName>z</signalName><signalUnits>nd</signalUnits><signalValue>{v}</signalValue><tol>1e-9</tol></signal>
    </checkOutputs></staticShot></checkData>"""
    good = daveml_eval.run_check_data(_model(shot.format(v=2 * 11 + 1 + 2)))
    assert [s.passed for s in good] == [True]
    bad = daveml_eval.run_check_data(_model(shot.format(v=0.0)))
    assert not bad[0].passed and "z =" in bad[0].faults[0]


def test_reference_with_xlink_and_a_year_date_round_trips():
    d = _model()
    assert d["file_header"]["reference"][0]["href"] == "https://example.org/r1"
    xml = daveml_adh.to_xml(d)
    assert validate_dml(xml) == []
    assert daveml_adh.compare(xml, daveml_adh.to_xml(daveml_adh.from_xml(xml))) == []


def test_a_loop_is_refused():
    calc = "<apply><plus/><ci>z</ci><cn>1</cn></apply>"
    with pytest.raises(daveml_eval.EvalError, match="loop"):
        daveml_eval.Model(_model(z_calc=calc)).evaluate({"x": 1.0})
