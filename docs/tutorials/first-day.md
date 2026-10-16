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

Next: [Change the aircraft with your tool](../howto/change-the-aircraft.md).
