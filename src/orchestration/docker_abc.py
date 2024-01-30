from __future__ import annotations

from abc import ABC, abstractmethod
from shared import AsyncTask
from typing import Any


class ContainerManager(ABC, AsyncTask):
    @abstractmethod
    def get_port(self: ContainerManager, container: str) -> int:
        pass  # pragma: no cover

    @abstractmethod
    @property
    def running_container_info(self: ContainerManager) -> list[dict[str, Any]]:
        pass  # pragma: no cover
