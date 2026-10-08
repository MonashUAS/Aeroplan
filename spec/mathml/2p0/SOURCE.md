# MathML 2.0 DTD (copy)

- Files: `mathml2.dtd`, `mathml2-qname-1.mod` and the 21 entity sets under `iso8879/`, `iso9573-13/` and `mathml/`.
- Fetched: 2026-10-08 from http://www.w3.org/Math/DTD/mathml2/ (the address that the DAVE-ML 2.0 DTD includes).
- sha256 of `mathml2.dtd`: 9fc32959c4c7f37332f0d7bc6c1c34d07bac0ecf07597294fbba0c1a0f25cfb4.
- Licence: W3C document licence. The copyright and the permission notice are in the head of each file.
- Use: the DAVE-ML DTD (`spec/dave-ml/2p0/DAVEfunc.dtd`) includes MathML 2.0 by its web address. Without a local copy,
  lxml downloads it on every check. `aerolink.daveml.validate` points that include at this folder in memory, so the
  DTD check needs no network. No file here is edited.
- AeroPlan copy: copied by hand from the Aerolink copy on 2026-10-08. `aeroplan.dml_validate` points the include at
  this folder in memory. Both repositories now check against the same bytes offline.
