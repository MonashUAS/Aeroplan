# First day (about 15 minutes)

1. Install Python 3.10 or newer and git.
2. Clone the repository and install AeroPlan in editable mode (the spokes need the repository folders):
   ```
   git clone <AeroPlan repository URL>
   cd Aeroplan
   pip install -e .[test]
   ```
3. Check the aircraft: `python -m aeroplan check currawong`. The last line says "All checks pass."
4. Look at the ADH tree and the asset register: `python -m aeroplan show currawong`.
5. Read the one-page summary of the aircraft: `docs/reference/aircraft/currawong.md`.
6. Run the tests: `python -m pytest`.

The first command builds the patched ADH package in `standards/adh/build/` (git ignores it).

<<<<<<< HEAD
Next: read the [quadplane modelling report](../reports/quadplane_model/README.md) or a tool README in `aeroplan/<tool>/README.md`.
=======
Next: [Change the aircraft with your tool](../howto/change-the-aircraft.md).

To run the Rosella sizing notebook, you must also do the steps in [Size a quadplane](../howto/size-a-quadplane.md#before-you-start):
make the AeroSandbox Python with a Proptimiser checkout (`python -m aeroplan setup AeroSandbox --proptimiser <checkout>`) and copy
the 4 blade files into `work/`.
>>>>>>> b31b0d65b77b3a5c09863475a94377eaacd237c6
