from dataclasses import dataclass
from typing import List

@dataclass
class PodConfig:
    service: str
    port: int

@dataclass
class NamespaceConfig:
    namespace: str
    pods: List[PodConfig]

@dataclass
class ContextConfig:
    context: str
    namespaces: List[NamespaceConfig]

@dataclass
class Config:
    contexts: List[ContextConfig]

@dataclass
class ContextStatus:
    name: str
    accessible: bool
    error_message: str = ""
    service_count: int = 0
