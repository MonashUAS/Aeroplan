"""Quantities with explicit units, normalised to SI at load (brief D04).

Angles are stored in radians. Boundary exporters convert to degrees where a
standard (S-119 names, hand config) needs them.
"""
from __future__ import annotations

import pint
from pydantic import model_validator

from .base import MuasModel

ureg = pint.UnitRegistry()

DIMENSIONS = {
    "mass": "[mass]",
    "length": "[length]",
    "area": "[length] ** 2",
    "time": "[time]",
    "inertia": "[mass] * [length] ** 2",
    "force": "[mass] * [length] / [time] ** 2",
    "speed": "[length] / [time]",
    "density": "[mass] / [length] ** 3",
    "frequency": "1 / [time]",
    "current": "[current]",
    "voltage": "[mass] * [length] ** 2 / [time] ** 3 / [current]",
}

_DIMENSIONLESS = ("nd", "1", "dimensionless")


def _unit(units: str):
    u = units.strip()
    return ureg.dimensionless if u in _DIMENSIONLESS else ureg.Unit(u)


def parse_units(units: str):
    """Return the pint unit for an exchange `units` attribute. Raise ValueError for a spelling pint does not know."""
    try:
        return _unit(units)
    except Exception as e:  # pint raises several error types
        raise ValueError(f"units {units!r} is not a pint spelling (exchange.md: m/s, kg/m^3, N*m)") from e


def dimension_matches(units: str, dimension: str) -> bool:
    u = _unit(units)
    if dimension in ("angle", "dimensionless"):
        return u.dimensionless
    return u.dimensionality == ureg.get_dimensionality(DIMENSIONS[dimension])


class Quantity(MuasModel):
    value: float
    units: str

    @model_validator(mode="after")
    def _to_si(self):
        try:
            q = ureg.Quantity(self.value, _unit(self.units)).to_base_units()
        except Exception as e:  # pint raises several error types
            raise ValueError(f"unknown units {self.units!r}: {e}") from e
        # object.__setattr__ avoids re-entering validate_assignment
        object.__setattr__(self, "value", float(q.magnitude))
        object.__setattr__(self, "units", "nd" if q.units == ureg.dimensionless else f"{q.units:~}")
        return self

    def require(self, dimension: str, field: str = "quantity") -> "Quantity":
        if not dimension_matches(self.units, dimension):
            raise ValueError(f"{field}: units {self.units!r} are not a {dimension}")
        return self


def Q(value: float, units: str) -> Quantity:
    return Quantity(value=value, units=units)
