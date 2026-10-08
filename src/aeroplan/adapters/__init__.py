from .cad import CadAdapter
from .config_yaml import ConfigYamlAdapter
from .flow5 import Flow5SweepAdapter
from .propalyser import PropalyserAdapter

REGISTRY = {a.name: a for a in (ConfigYamlAdapter, Flow5SweepAdapter, PropalyserAdapter, CadAdapter)}
