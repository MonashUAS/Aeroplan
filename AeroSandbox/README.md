# AeroSandbox spoke

The initial sizing: the first source of a new aircraft. It gives the ADH `performance` record "sizing" of node 1.2.

| Item | Place |
|---|---|
| Input | `AeroSandbox/work/<aircraft>/athena_outputs.txt` (the printout of the Athena sizing scripts) |
| Settings | none |
| Writes | node 1.2 `performance` (Discipline "sizing"), `muas.sources` (the printout as an asset of the register) |

The printout gives no units. `spoke.py` (`UNITS`) gives each output a unit and says how sure it is: `consistency`
(a relation between outputs proves it), `magnitude` (plausible, not proven) or `unknown`.

The sizing scripts go in this folder when they are added. Their output goes in `work/<aircraft>/`.
