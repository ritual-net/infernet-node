from dataclasses import dataclass
from typing import Any, Literal, Optional, Union


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

JobStatus = Literal["running", "success", "failed"]


@dataclass(frozen=True)
class JobResult:
    """Job result"""

    id: str
    status: JobStatus
    intermediate_results: list[ContainerResult]
    result: Optional[ContainerResult]
