from typing import List, Optional
from pydantic import Field, field_validator, InstanceOf, SerializeAsAny
from ...common_base_model import CommonBaseModel


class EngineElement(CommonBaseModel):
    """
    Represents an individual element in the engine cycle.

    Attributes:
        name (str): The name of the engine element.
        options (dict, optional): The options associated with the engine element.
    """

    name: str = Field(..., description="The name of the engine element.")
    type: str = Field(..., description="The type of engine element this is.")
    options: Optional[dict] = Field(None, description="The options associated with the engine element.")

    # NOTE: Temp fix to known pydanticV2 error
    statics: Optional[bool] = Field(None, description="If true calculate static properties")
    mn: Optional[float] = Field(None, description="On-design Mach number")
    ram_recovery: Optional[float] = Field(None, description="Ram recovery factor")
    area: Optional[float] = Field(None, description="On-design frontal area of component")

    map_data: Optional[str] = Field(None, description="Map data for the compressor")
    map_extrap: Optional[bool] = Field(None, description="Flag to indicate if map extrapolation is used")
    map_interp_method: Optional[str] = Field(None, description="Method to use for map interpolation.")
    bleed_names: Optional[List[str]] = Field(None, description="Names of the bleed ports")
    pr_des: Optional[float] = Field(None, description="On-design pressure ratio(Input)")
    eff_des: Optional[float] = Field(None, description="On-design efficeincy(Input)")
    mn: Optional[float] = Field(None, description="On-design mach number(Input)")
    s_PR: Optional[float] = Field(None, description="On-design pressure ratio(Output)")
    s_eff: Optional[float] = Field(None, description="On-design efficiency(Output)")
    s_Wc: Optional[float] = Field(None, description="On-design air mass flow rate(Output)")
    s_Nc: Optional[float] = Field(None, description="On-design Nc(Output)")
    area: Optional[float] = Field(None, description="On-design frontal area of component(Output)")
    frac_W: Optional[List[float]] = Field(
        None, description="Fraction of incoming flow to bleed off(associated with each bleed connection)"
    )
    frac_P: Optional[List[float]] = Field(
        None, description="Fraction of incoming pressure to bleed off(associated with each bleed connection)"
    )
    frac_work: Optional[List[float]] = Field(
        None, description="Fraction of work to bleed off(associated with each bleed connection)"
    )

    bpr: Optional[float] = Field(None, description="Bypass ratio")
    mn1: Optional[float] = Field(None, description="On-design mach number for the first flow path(Input)")
    mn2: Optional[float] = Field(None, description="On-design mach number for the second flow path(Input)")
    area1: Optional[float] = Field(None, description="On-design frontal area for the first flow path(Output)")
    area2: Optional[float] = Field(None, description="On-design frontal area for the second flow path(Output)")

    fuel_type: Optional[str] = Field(None, description="Type of fuel used")
    mn: Optional[float] = Field(None, description="On-design mach number")
    dp_qp: Optional[float] = Field(None, description="On-design pressure drop ratio")
    FAR: Optional[float] = Field(None, description="On-design fuel-air ratio")
    Wfuel: Optional[float] = Field(None, description="On-design fuel injection rate")

    nozz_type: Optional[str] = Field(None, description="Type of nozzle")
    loss_coef: Optional[str] = Field(None, description="Loss coefficient")
    cv: Optional[float] = Field(None, description="Discharge coefficient")

    num_ports: Optional[int] = Field(None, description="Number of ports on the shaft")
    nmech: Optional[float] = Field(None, description="Mechanical speed in RPM")
    nmech_type: Optional[str] = Field(None, description="Low or high pressure shaft")
    HPX: Optional[float] = Field(None, description="Horsepower transfer")

    dPqP: Optional[float] = Field(None, description="On-design pressure drop ratio")
    Q_dot: Optional[float] = Field(
        None, description="On-design heat flow rate into (positive) or out of (negative) the air"
    )

    @field_validator("fuel_type")
    def validate_fuel_type(cls, v):
        allowed_types = ["FAR", "Jet-A(g)"]
        if v not in allowed_types:
            raise ValueError(f"Fuel type must be one of {allowed_types}")
        return v
    
class Inlet(EngineElement):
    """
    Inlet conditions for the engine.

    Attributes
    ----------
    mn : Optional[float]
        Mach number.
    ram_recovery : Optional[float]
        Ram recovery factor.
    area : Optional[float]
        On-design frontal area.
    """

    statics: Optional[bool] = Field(None, description="If true calculate static properties")
    mn: Optional[float] = Field(None, description="On-design Mach number")
    ram_recovery: Optional[float] = Field(None, description="Ram recovery factor")
    area: Optional[float] = Field(None, description="On-design frontal area of component")


class Compressor(EngineElement):
    """
    Compressor component of the engine.

    Attributes
    ----------
    mn : Optional[float]
        Mach number.
    map_data : Optional[str]
        Map data for the compressor.
    bleed_names : Optional[List[str]]
        Names of the bleed ports.
    map_extrap : Optional[bool]
        Flag to indicate if map extrapolation is used.
    pr_des : Optional[float]
        Design condition pressure ratio
    eff_des : Optional[float]
        Design condition efficeincy
    """

    statics: Optional[bool] = Field(None, description="If true calculate static properties")
    map_data: Optional[str] = Field(None, description="Map data for the compressor")
    map_extrap: Optional[bool] = Field(None, description="Flag to indicate if map extrapolation is used")
    map_interp_method: Optional[str] = Field(None, description="Method to use for map interpolation.")
    bleed_names: Optional[List[str]] = Field(None, description="Names of the bleed ports")
    pr_des: Optional[float] = Field(None, description="On-design pressure ratio(Input)")
    eff_des: Optional[float] = Field(None, description="On-design efficeincy(Input)")
    mn: Optional[float] = Field(None, description="On-design mach number(Input)")
    s_PR: Optional[float] = Field(None, description="On-design pressure ratio(Output)")
    s_eff: Optional[float] = Field(None, description="On-design efficiency(Output)")
    s_Wc: Optional[float] = Field(None, description="On-design air mass flow rate(Output)")
    s_Nc: Optional[float] = Field(None, description="On-design Nc(Output)")
    area: Optional[float] = Field(None, description="On-design frontal area of component(Output)")
    frac_W: Optional[List[float]] = Field(
        None, description="Fraction of incoming flow to bleed off(associated with each bleed connection)"
    )
    frac_P: Optional[List[float]] = Field(
        None, description="Fraction of incoming pressure to bleed off(associated with each bleed connection)"
    )
    frac_work: Optional[List[float]] = Field(
        None, description="Fraction of work to bleed off(associated with each bleed connection)"
    )


class Turbine(EngineElement):
    """
    Turbine component of the engine.

    Attributes
    ----------
    mn : Optional[float]
        Mach number.
    map_data : Optional[str]
        Map data for the turbine.
    bleed_names : Optional[List[str]]
        Names of the bleed ports.
    map_extrap : Optional[bool]
        Flag to indicate if map extrapolation is used.
    pr_des : Optional[float]
        Design condition pressure ratio
    effDes : Optional[float]
        Design condition efficeincy
    """

    statics: Optional[bool] = Field(None, description="If true calculate static properties")
    map_data: Optional[str] = Field(None, description="Map data for the compressor")
    map_extrap: Optional[bool] = Field(None, description="Flag to indicate if map extrapolation is used")
    map_interp_method: Optional[str] = Field(None, description="Method to use for map interpolation.")
    bleed_names: Optional[List[str]] = Field(None, description="Names of the bleed ports")
    pr_des: Optional[float] = Field(None, description="On-design pressure ratio(Input)")
    eff_des: Optional[float] = Field(None, description="On-design efficeincy(Input)")
    mn: Optional[float] = Field(None, description="On-design mach number(Input)")
    s_PR: Optional[float] = Field(None, description="On-design pressure ratio(Output)")
    s_eff: Optional[float] = Field(None, description="On-design efficiency(Output)")
    s_Wc: Optional[float] = Field(None, description="On-design air mass flow rate(Output)")
    s_Nc: Optional[float] = Field(None, description="On-design Nc(Output)")
    area: Optional[float] = Field(None, description="On-design frontal area of component(Output)")
    frac_W: Optional[List[float]] = Field(
        None, description="Fraction of incoming flow to bleed off(associated with each bleed connection)"
    )
    frac_P: Optional[List[float]] = Field(
        None, description="Fraction of incoming pressure to bleed off(associated with each bleed connection)"
    )
    frac_work: Optional[List[float]] = Field(
        None, description="Fraction of work to bleed off(associated with each bleed connection)"
    )


class Splitter(EngineElement):
    """
    Splitter component of the engine.

    Attributes
    ----------
    bpr : Optional[float]
        Bypass ratio.
    mn1 : Optional[float]
        Mach number for the first flow path.
    mn2 : Optional[float]
        Mach number for the second flow path.
    area1 : Optional[float]
        Area for the second flow path.
    area2 : Optional[float]
        Area for the second flow path.
    """

    statics: Optional[bool] = Field(None, description="If true calculate static properties")
    bpr: Optional[float] = Field(None, description="Bypass ratio")
    mn1: Optional[float] = Field(None, description="On-design mach number for the first flow path(Input)")
    mn2: Optional[float] = Field(None, description="On-design mach number for the second flow path(Input)")
    area1: Optional[float] = Field(None, description="On-design frontal area for the first flow path(Output)")
    area2: Optional[float] = Field(None, description="On-design frontal area for the second flow path(Output)")


class Duct(EngineElement):
    """
    Duct component of the engine.

    Attributes
    ----------
    mn : Optional[float]
        Mach number.
    dp_qp : Optional[float]
        Pressure drop ratio.
    """

    statics: Optional[bool] = Field(None, description="If true calculate static properties")
    mn: Optional[float] = Field(None, description="On-design mach number")
    dPqP: Optional[float] = Field(None, description="On-design pressure drop ratio")
    Q_dot: Optional[float] = Field(
        None, description="On-design heat flow rate into (positive) or out of (negative) the air"
    )
    area: Optional[float] = Field(None, description="On-design frontal area of component")


class Bleed(EngineElement):
    """
    Bleed output component

    Attributes
    ----------
    bleed_names : Optional[List[str]]
        Names of the bleed connections associated
    statics : Optional[bool]
        If true calculate static properties
    """

    bleed_names: Optional[List[str]] = Field(None, description="Names of the bleed connections associated")
    statics: Optional[bool] = Field(None, description="If true calculate static properties")
    frac_W: Optional[List[float]] = Field(
        None, description="Fraction of incoming flow to bleed off(associated with each bleed connection)"
    )
    frac_P: Optional[List[float]] = Field(
        None, description="Fraction of incoming pressure to bleed off(associated with each bleed connection)"
    )
    frac_work: Optional[List[float]] = Field(
        None, description="Fraction of work to bleed off(associated with each bleed connection)"
    )
    mn: Optional[float] = Field(None, description="On-design mach number.")


class Combustor(EngineElement):
    """
    Combustor component of the engine.

    Attributes
    ----------
    fuel_type : Optional[str]
        Type of fuel used.
    mn : Optional[float]
        Mach number.
    dp_qp : Optional[float]
        Pressure drop ratio.
    """

    statics: Optional[bool] = Field(None, description="If true calculate static properties")
    fuel_type: Optional[str] = Field(None, description="Type of fuel used")
    mn: Optional[float] = Field(None, description="On-design mach number")
    dp_qp: Optional[float] = Field(None, description="On-design pressure drop ratio")
    FAR: Optional[float] = Field(None, description="On-design fuel-air ratio")
    Wfuel: Optional[float] = Field(None, description="On-design fuel injection rate")
    area: Optional[float] = Field(None, description="On design frontal area of component(Output)")

    @field_validator("fuel_type")
    def validate_fuel_type(cls, v):
        allowed_types = ["FAR", "Jet-A(g)"]
        if v not in allowed_types:
            raise ValueError(f"Fuel type must be one of {allowed_types}")
        return v


class Nozzle(EngineElement):
    """
    Nozzle component of the engine.

    Attributes
    ----------
    nozz_type : Optional[str]
        Type of nozzle.
    loss_coef : Optional[str]
        Loss coefficient.
    cv : Optional[float]
        Discharge coefficient.
    """

    statics: Optional[bool] = Field(None, description="If true calculate static properties")
    mn: Optional[float] = Field(None, description="On-design mach number")
    nozz_type: Optional[str] = Field(None, description="Type of nozzle")
    loss_coef: Optional[str] = Field(None, description="Loss coefficient")
    cv: Optional[float] = Field(None, description="Discharge coefficient")
    area: Optional[float] = Field(None, description="On-design frontal area of component(Output)")


class Shaft(EngineElement):
    """
    Shaft component of the engine.

    Attributes
    ----------
    num_ports : Optional[int]
        Number of ports on the shaft.
    nmech : Optional[float]
        Mechanical speed in RPM.
    """

    num_ports: Optional[int] = Field(None, description="Number of ports on the shaft")
    nmech: Optional[float] = Field(None, description="Mechanical speed in RPM")
    nmech_type: Optional[str] = Field(None, description="Low or high pressure shaft")
    HPX: Optional[float] = Field(None, description="Horsepower transfer")


class PropulsionCycle(CommonBaseModel):
    """
    Represents a complete engine cycle.

    Attributes:
        name (str): The name of the engine cycle.
        design (bool): Whether the engine cycle is in design mode.
        thermo_method (str, optional): The thermodynamic method used in the engine cycle. Defaults to 'CEA'.
        thermo_data (str, optional): The thermodynamic data used in the engine cycle.
        elements (List[EngineElement]): The list of engine elements in the engine cycle.
        balance_components (List[BalanceComponent], optional): The list of balance components in the engine cycle.
        global_connections (dict, optional): The global connections in the engine cycle.
        flow_connections (dict, optional): The flow connections in the engine cycle.
        solver_settings (dict, optional): The solver settings for the engine cycle.
    """

    name: str = Field(..., description="The name of the engine cycle.")
    elements: List[SerializeAsAny[InstanceOf[EngineElement]]] = Field(..., description="The list of engine elements in the engine cycle.")
    global_connections: Optional[List[str]] = Field(None, description="The global connections in the engine cycle.")
    flow_connections: Optional[List[List[str]]] = Field(None, description="The flow connections in the engine cycle.")
