from __future__ import annotations

from dataclasses import asdict
from json import JSONDecodeError
from os import environ
from typing import Any, AsyncGenerator, Optional

from aiohttp import ClientSession, ClientTimeout

from shared import ContainerError, ContainerOutput, ContainerResult
from shared.job import ContainerInput, JobInput, JobLocation
from shared.message import OffchainJobMessage
from utils import log

from .docker import ContainerManager
from .store import DataStore


class Orchestrator:
    """Orchestrates container execution

    Orchestrates container execution and tracks job status and results. Handles
    off-chain messages and on-chain subscriptions. Calls containers in order and
    passes output of previous container as input to next container. If any container
    fails, the job is marked as failed. If all containers succeed, the job is marked as
    successful. Stores job status and results.

    Attributes:
        _manager (ContainerManager): container manager
        _store (DataStore): data store
        _host (str): host address

    Methods:
        process_chain_processor_job: Processes on-chain job from chain processor
        process_offchain_job: Processes off-chain job message

    Private Methods:
        _run_job: Run a job
    """

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

    def _get_container_url(self: Orchestrator, container: str) -> str:
        """
        Get the service output URL for the specified container.

        If a custom URL is defined in container config, use this.
        Otherwise, retrieve the port for the container and construct the URL using the 
        host and port.

        Args:
            container (str): The name of the container.

        Returns:
            str: The URL of the service output for the container.
        """
        container_url = self._manager.get_url(container)
        if container_url:
            return f"{container_url}/service_output"
        else:
            port = self._manager.get_port(container)
            return f"http://{self._host}:{port}/service_output"


    def _get_headers(self: Orchestrator, container: str) -> dict[str, str]:
        """
        Get the headers for the specified container, including Bearer authorization if available.

        The headers will always include the 'Content-Type' set to 'application/json'.
        If the container has a Bearer token, it is included in the 'Authorization' header.

        Args:
            container (str): The name of the container.

        Returns:
            dict[str, str]: A dictionary containing the necessary headers for the container.
        """
        bearer = self._manager.get_bearer(container)
        headers = {"Content-Type": "application/json"}
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        return headers

    async def _run_job(
        self: Orchestrator,
        job_id: Any,
        job_input: JobInput,
        containers: list[str],
        message: Optional[OffchainJobMessage],
        requires_proof: Optional[bool],
    ) -> list[ContainerResult]:
        """Runs a job

        Calls containers in order and passes output of previous container as input to
        next container. If any container fails, the job is marked as failed. If all
        containers succeed, the job is marked as successful. Stores job status and
        results.

        Args:
            job_id (Any): job identifier
            job_input (JobInput): initial input to first container
            containers (list[str]): ordered list of containers to execute
            message (Optional[OffchainJobMessage]): optional offchain job message to
                track state in store
            requires_proof (bool): whether job requires proof

        Returns:
            list[ContainerResult]: job execution results
        """

        # Start job
        self._store.set_running(message)

        # Setup input and results
        results: list[ContainerResult] = []

        # If only one container, destination of first container is destination of job
        # Otherwise, destination of first container is off-chain, and source of next
        # container is off-chain (i.e. chaining containers together)
        input_data = ContainerInput(
            source=job_input.source,
            destination=(
                job_input.destination
                if len(containers) == 1
                else JobLocation.OFFCHAIN.value
            ),
            data=job_input.data,
            requires_proof=bool(requires_proof),
        )

        # Call container chain
        async with ClientSession() as session:
            for index, container in enumerate(containers):
                # Get container port and URL
                url = self._get_container_url(container)
                headers = self._get_headers(container)
                try:
                    async with session.post(
                        url,
                        json=asdict(input_data),
                        headers=headers,
                        timeout=ClientTimeout(total=180),
                    ) as response:

                        # Handle JSON response
                        output = await response.json()
                        results.append(ContainerOutput(container, output))

                        # Track container success
                        self._store.track_container_status(
                            container,
                            "success",
                        )

                        # If next container is the last container, set destination to
                        # job destination. Otherwise, set destination to off-chain
                        # (i.e. chaining containers together)
                        input_data = ContainerInput(
                            source=JobLocation.OFFCHAIN.value,
                            destination=(
                                job_input.destination
                                if index == len(containers) - 2
                                else JobLocation.OFFCHAIN.value
                            ),
                            data=output,
                            requires_proof=bool(requires_proof),
                        )

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

                    # Track container failure
                    self._store.track_container_status(
                        container,
                        "failed",
                    )

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

                    # Track container failure
                    self._store.track_container_status(
                        container,
                        "failed",
                    )

                    return results

        # Track job success
        self._store.set_success(message, results)

        return results

    async def process_chain_processor_job(
        self: Orchestrator,
        job_id: Any,
        job_input: JobInput,
        containers: list[str],
        requires_proof: bool,
    ) -> list[ContainerResult]:
        """Processes arbitrary job from ChainProcessor

        Args:
            job_id (Any): job identifier
            job_input (JobInput): initial input to first container
            containers (list[str]): ordered list of containers to execute
            requires_proof (bool): whether job requires proof

        Returns:
            list[ContainerResult]: container execution results
        """
        return await self._run_job(
            job_id=job_id,
            job_input=job_input,
            containers=containers,
            message=None,
            requires_proof=requires_proof,
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
            job_input=JobInput(
                source=JobLocation.OFFCHAIN.value,
                destination=JobLocation.OFFCHAIN.value,
                data=message.data,
            ),
            containers=message.containers,
            message=message,
            requires_proof=message.requires_proof,
        )

    async def process_streaming_job(
        self: Orchestrator, message: OffchainJobMessage
    ) -> AsyncGenerator[bytes, None]:
        """Runs a streaming job

        Calls streaming container and yields chunks of output as they are received. If
        the container fails, the job is marked as failed. If the container succeeds, the
        job is marked as successful, and the full output is stored in Redis as an array
        of chunks.

        NOTE: If multiple containers are specified in the message, only the first
        container is executed, the rest are ignored.

        Args:
            message (OffchainJobMessage): raw off-chain job message

        Yields:
            bytes: streaming output chunks

        Raises:
            Exception: If the container fails
        """

        # Only one container is supported for streaming (i.e. no chaining)
        container = message.containers[0]

        url = self._get_container_url(container)
        headers = self._get_headers(container)
        # Start job and track container
        self._store.set_running(message)

        # Hold chunks in memory to store final results in Redis
        chunks = []

        async with ClientSession() as session:
            try:
                job_input = JobInput(
                    source=JobLocation.OFFCHAIN.value,
                    destination=JobLocation.STREAM.value,
                    data=message.data,
                )

                async with session.post(
                    url,
                    json=asdict(job_input),
                    headers=headers,
                    timeout=ClientTimeout(total=60),
                ) as response:
                    # Raises exception if status code is not 200
                    response.raise_for_status()

                    async for chunk in response.content.iter_any():
                        chunks.append(chunk)
                        yield chunk

                # Track job success
                final_result = b"".join(chunks).decode("utf-8")
                self._store.set_success(
                    message,
                    [ContainerOutput(container, dict({"output": final_result}))],
                )

                # Track container success
                self._store.track_container_status(
                    container,
                    "success",
                )

            except Exception as e:
                # Track job failure
                log.error(
                    "Container error", id=message.id, container=container, error=str(e)
                )
                self._store.set_failed(message, [ContainerError(container, str(e))])

                # Track container failure
                self._store.track_container_status(
                    container,
                    "failed",
                )
