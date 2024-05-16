from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal, Optional, Union


class JobLocation(Enum):
    """Job location"""

    ONCHAIN = 0
    OFFCHAIN = 1
    STREAM = 2


@dataclass(frozen=True)
class ContainerInput:
    """Container source, destination, and data"""

    source: int  # JobLocation (ONCHAIN or OFFCHAIN)
    destination: int  # JobLocation (ONCHAIN or OFFCHAIN or STREAM)
    data: Any


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

    source: int  # JobLocation (ONCHAIN or OFFCHAIN)
    destination: int  # JobLocation (ONCHAIN or OFFCHAIN or STREAM)
    data: Any


JobStatus = Literal["running", "success", "failed"]


@dataclass(frozen=True)
class JobResult:
    """Job result"""

    id: str
    status: JobStatus
    intermediate_results: list[ContainerResult]
    result: Optional[ContainerResult]
