"""Base model for all MUAS extension types (brief D03: extra="forbid")."""
from pydantic import BaseModel, ConfigDict


class MuasModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, protected_namespaces=())
