from __future__ import annotations

from enum import Enum
from json import JSONDecodeError
from os import environ
from typing import Any, Optional

from aiohttp import ClientSession

from shared import ContainerError, ContainerOutput, ContainerResult
from shared.message import OffchainJobMessage
from utils import log

from .docker import ContainerManager
from .store import DataStore


class OrchestratorInputSource(Enum):
    """Orchestrator input source"""

    ONCHAIN = 0
    OFFCHAIN = 1


class Orchestrator:
    def __init__(
        self: Orchestrator,
        manager: ContainerManager,
        store: DataStore,
    ) -> None:
        super().__init__()

        self._manager = manager
        self._store = store

        # Set host based on runtime environment
        self._host = (
            "host.docker.internal"
            if environ.get("RUNTIME") == "docker"
            else "localhost"
        )

    async def _run_job(
        self: Orchestrator,
        job_id: Any,
        initial_input: dict[Any, Any],
        containers: list[str],
        message: Optional[OffchainJobMessage],
    ) -> list[ContainerResult]:
        """Run off-chain job

        Calls containers in order and passes output of previous container as input to
        next container. If any container fails, the job is marked as failed. If all
        containers succeed, the job is marked as successful. Stores job status and
        results.

        Args:
            job_id (Any): job identifier
            initial_input (dict[Any, Any]): initial input to first container
            containers (list[str]): ordered list of containers to execute
            message (Optional[OffchainJobMessage]): optional offchain job message to
                track state in store

        Returns:
            list[ContainerResult]: job execution results
        """

        # Start job
        self._store.set_running(message)

        # Setup input and results
        results: list[ContainerResult] = []
        input_data = initial_input

        # Call container chain
        async with ClientSession() as session:
            for container in containers:
                # Track container count
                self._store.track_container(container)

                # Get container port and URL
                port = self._manager.get_port(container)
                url = f"http://{self._host}:{port}/service_output"

                try:
                    async with session.post(
                        url, json=input_data, timeout=180
                    ) as response:
                        # Handle JSON response
                        output = await response.json()
                        results.append(ContainerOutput(container, output))
                        input_data = {
                            "source": OrchestratorInputSource.OFFCHAIN.value,
                            "data": output,
                        }

                except JSONDecodeError:
                    # Handle non-JSON response as error
                    response_text = await response.text()

                    # Fail job
                    results.append(ContainerError(container, response_text))
                    log.error(
                        "Container error",
                        id=job_id,
                        container=container,
                        error=response_text,
                    )

                    # Track job failure
                    self._store.set_failed(message, results)
                    return results

                except Exception as e:
                    # Fail job
                    results.append(ContainerError(container, str(e)))
                    log.error(
                        "Container error",
                        id=job_id,
                        container=container,
                        error=str(e),
                    )

                    # Track job failure
                    self._store.set_failed(message, results)
                    return results

        # Track job success
        self._store.set_success(message, results)

        return results

    async def process_chain_processor_job(
        self: Orchestrator,
        job_id: Any,
        initial_input: dict[Any, Any],
        containers: list[str],
    ) -> list[ContainerResult]:
        """Processes arbitrary job from ChainProcessor

        Args:
            job_id (Any): job identifier
            initial_input (dict[Any, Any]): initial input to first container
            containers (list[str]): ordered list of containers to execute

        Returns:
            list[ContainerResult]: container execution results
        """
        return await self._run_job(
            job_id=job_id,
            initial_input=initial_input,
            containers=containers,
            message=None,
        )

    async def process_offchain_job(
        self: Orchestrator, message: OffchainJobMessage
    ) -> None:
        """Processes off-chain job message

        Args:
            message (OffchainJobMessage): raw off-chain job message
        """
        await self._run_job(
            job_id=message.id,
            initial_input={
                "source": OrchestratorInputSource.OFFCHAIN.value,
                "data": message.data,
            },
            containers=message.containers,
            message=message,
        )
