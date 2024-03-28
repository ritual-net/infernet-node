from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal, Optional, Union


class ChainLocation(Enum):
    """Chain location"""

    ONCHAIN = 0
    OFFCHAIN = 1


@dataclass(frozen=True)
class ContainerInput:
    """Container source, destination, and data"""

    source: int  # ChainLocation
    destination: int  # ChainLocation
    data: Any
    type: int  # OrchestratorInputType


@dataclass(frozen=True)
class ContainerOutput:
    """Container output"""

    container: str
    output: dict[str, Any]


@dataclass(frozen=True)
class ContainerError:
    """Container error"""

    container: str
    error: str


ContainerResult = Union[ContainerError, ContainerOutput]


@dataclass(frozen=True)
class JobInput:
    """Job source, destination, and data"""

    source: int  # ChainLocation
    destination: int  # ChainLocation
    data: Any
    type: int  # OrchestratorInputType


JobStatus = Literal["running", "success", "failed"]


@dataclass(frozen=True)
class JobResult:
    """Job result"""

    id: str
    status: JobStatus
    intermediate_results: list[ContainerResult]
    result: Optional[ContainerResult]
