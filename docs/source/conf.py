# Sphinx configuration. Follows the layout of Boeing/aircraft-data-hierarchy docs/source/conf.py (96179ca):
# sources in docs/source, build with `cd docs; sphinx-build -M html ./source ./_build`.
# Difference: Markdown pages through myst_parser (ADH uses myst_nb, which needs Jupyter).
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath("../../src"))
sys.path.insert(0, os.path.abspath("../../packages/muas_adh/build/src"))  # the patched ADH, from scripts/build_adh.py

project = "AeroPlan"
copyright = f"{date.today().year}, MUAS"
author = "MUAS"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.mathjax",
    "myst_parser",
]

myst_enable_extensions = ["amsmath", "dollarmath", "colon_fence", "tasklist"]
myst_heading_anchors = 3
source_suffix = {".md": "markdown", ".rst": "restructuredtext"}

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

autodoc_member_order = "bysource"
autodoc_class_signature = "separated"
autodoc_typehints = "description"
autodoc_mock_imports = []

html_theme = "sphinx_rtd_theme"
html_static_path = []
