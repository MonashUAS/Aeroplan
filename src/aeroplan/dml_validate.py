"""Validate DAVE-ML bytes against the vendored DAVE-ML 2.0 DTD (spec/dave-ml/2p0).

The DAVE-ML DTD includes MathML 2.0 by its w3.org address. The loader points that include at the vendored copy in
spec/mathml/2p0 (hand copy of the Aerolink copy), so the check needs no network. The files on disk stay unchanged.
"""
from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path
from typing import List

from lxml import etree

SPEC = Path(__file__).resolve().parents[2] / "spec"
DTD_PATH = SPEC / "dave-ml" / "2p0" / "DAVEfunc.dtd"
MATHML_DTD = SPEC / "mathml" / "2p0" / "mathml2.dtd"
MATHML_URL = "http://www.w3.org/Math/DTD/mathml2/mathml2.dtd"


@lru_cache(maxsize=1)
def _dtd() -> etree.DTD:
    text = DTD_PATH.read_text(encoding="utf-8")
    if MATHML_URL not in text:
        raise ValueError(f"{DTD_PATH} does not include MathML from {MATHML_URL}: check the vendored DTD")
    return etree.DTD(io.StringIO(text.replace(MATHML_URL, MATHML_DTD.as_uri())))


def validate_dml(data: bytes) -> List[str]:
    """Return DTD error messages. An empty list means the document is valid."""
    parser = etree.XMLParser(load_dtd=False, no_network=True)
    doc = etree.fromstring(data, parser).getroottree()
    dtd = _dtd()
    if dtd.validate(doc):
        return []
    return [f"line {e.line}: {e.message}" for e in dtd.error_log]
