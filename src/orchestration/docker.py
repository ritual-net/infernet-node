"""Docker container manager.

Manages docker containers for the orchestrator. Pulls images, starts containers,
and waits for containers to start before returning. Prunes any containers with
conflicting IDs.

Example:
    >>> manager = ContainerManager(
        {
            "container-1": ConfigContainer(port=3000, image="image1", ...),
            "container-2": ConfigContainer(port=3001, image="image2", ...),
            "container-3": ConfigContainer(port=3002, image="image3", ...)
        },
        DockerCredentials("...", "..."),
        startup_wait=60,
    )
    >>> await manager.setup()

    >>> manager.port_mappings
    {"container-1": 3000, "container-2": 3001, "container-3": 3002}

    >>> manager.running_containers
    ["container-1", "container-2", "container-3"]

    # Some time later, "container-2" crashes
    >>> manager.running_containers
    ["container-1", "container-3"]

    # Cleanup (containers are force stopped)
    >>> await manager.cleanup()
"""

from __future__ import annotations

from asyncio import gather, get_event_loop, sleep
from typing import Any, Optional

# from docker import from_env  # type: ignore
# from docker.errors import NotFound  # type: ignore
# from docker.models.containers import Container  # type: ignore
# from docker.types import DeviceRequest  # type: ignore

from shared import AsyncTask
from utils import log
from utils.config import ConfigContainer, ConfigDocker

DEFAULT_STARTUP_WAIT: float = 60.0

from typing import TypedDict
class Container():
    id: str
    running: bool

    def __init__(self: Container, id: str) -> None:
        self.id = id
        self.running = True

    @property
    def running(self: Container) -> bool:
        return True

class ContainerManager(AsyncTask):
    """Manages lifecycle of Docker containers.

    Pulls images, starts containers, and waits for services to start before
    returning. Optionally prunes any containers with conflicting IDs. Force stops all
    containers on cleanup.

    Public methods:
        setup: Pulls images, prunes existing (old) containers, starts new containers,
            and waits for containers to start.
        run_forever: Continuously checks if any containers exited / crashed.
        stop: Force stops all containers.

    Public attributes:
        port_mappings (dict[str, int]): Port mappings for containers. Does NOT
            guarantee containers are running.
        running_containers (list[str]): List of running containers (by ID).

    Private attributes:
        _configs (list[ConfigContainer]): Container configurations to run.
        _creds (ConfigDocker): Docker registry credentials.
        _containers (dict[str, Container]): Container objects, keyed by ID.
        _images (list[str]): List of image ids to pull.
        _loop (asyncio.AbstractEventLoop): Asyncio event loop.
        _shutdown (bool): True if container manager is shutting down, False otherwise.
    """

    _startup_wait: float

    def __init__(
        self: ContainerManager,
        configs: list[ConfigContainer],
        credentials: ConfigDocker,
        startup_wait: Optional[float],
    ) -> None:
        """Initialize ContainerManager with given configurations and credentials.

        Args:
            configs (dict[str, ConfigContainer]): Container configurations to run.
            credentials (ConfigDocker): Docker registry credentials.
            startup_wait (Optional[float]): Number of seconds to wait for containers
                to start.
        """
        super().__init__()

        # Store configs, credentials, and port mappings in state
        self._configs: list[ConfigContainer] = configs
        self._creds: ConfigDocker = credentials
        self._images: list[str] = [config["image"] for config in self._configs]
        self._port_mappings: dict[str, int] = {
            config["id"]: config["port"] for config in self._configs
        }
        self._loop = get_event_loop()
        self._startup_wait = (
            DEFAULT_STARTUP_WAIT if startup_wait is None else startup_wait
        )
        self._shutdown = False

        # Store container objects in state
        self._containers: dict[str, Container] = {}

        log.info("Initialized Container Manager", port_mappings=self._port_mappings)

    @property
    def port_mappings(self: ContainerManager) -> dict[str, int]:
        """Port mappings for containers. Does NOT guarantee containers are running"""
        return self._port_mappings

    @property
    def running_containers(self: ContainerManager) -> list[str]:
        """Get list of running container IDs"""

        # Container objects are cached, need to reload attributes
        for container in self._containers.values():
            container.reload()

        # IDs of running containers
        return [
            id
            for id, container in self._containers.items()
            if container.status == "running"
        ]

    @property
    def running_container_info(self: ContainerManager) -> list[dict[str, Any]]:
        """Get running container information"""
        return [
            {
                "id": config["id"],
                "description": config["description"] if "description" in config else "",
                "external": config["external"],
                "image": config["image"],
            }
            for config in self._configs
            if config["id"] in self.running_containers
        ]

    def get_port(self: ContainerManager, container: str) -> int:
        """Returns port for given container"""
        return self._port_mappings[container]

    #######################
    ## Lifecycle methods ##
    #######################

    async def setup(
        self: ContainerManager,
        prune_containers: bool = False,
    ) -> None:
        """Setup orchestrator

        1. Pulls images in parallel, if not already pulled.
        2. Prunes any containers with conflicting IDs, if prune_containers is True.
        3. Creates containers, if not already created.
        4. Starts containers, if not already started.
        5. Waits for startup_wait seconds for containers to start.

        """

        try:
            # Run containers
            self._run_containers()

            # Wait for containers to start
            log.info("Waiting for container startup", seconds=self._startup_wait)
            await sleep(self._startup_wait)

            # Containers that started
            running_containers = self.running_containers
            log.info(
                "Container manager setup complete",
                running_containers=running_containers,
            )

        except Exception as e:
            log.error("Error setting up container manager", error=e)

    async def run_forever(self: ContainerManager) -> None:
        """Lifecycle loop for container manager

        Continuously checks if any containers exited / crashed. When a container
        exits / crashes, logs the container ID as a warning and continues running.
        If no running containers remain, logs an error and exits.
        """

        # Get running containers
        running_containers = self.running_containers

        while not self._shutdown:
            # Get running containers
            current_containers = self.running_containers

            # Check if any containers exited / crashed
            if len(current_containers) > len(running_containers):
                log.warning(
                    "Container(s) failed / exited / crashed",
                    failed_containers=[
                        container
                        for container in running_containers
                        if container not in current_containers
                    ],
                )
            elif len(current_containers) < len(running_containers):
                log.warning(
                    "Container(s) back up",
                    started_containers=[
                        container
                        for container in running_containers
                        if container not in current_containers
                    ],
                )

            # Update running containers
            running_containers = current_containers

            await sleep(10)

    async def stop(self: ContainerManager) -> None:
        """Force stops all containers."""
        log.info("Stopping containers")

        self._shutdown = True
        for container in self._containers.values():
            try:
                container.stop(timeout=60)
            except Exception as e:
                log.error(f"Error stopping container {container.id}", error=e)

    async def cleanup(self: ContainerManager) -> None:
        """No cleanup required."""
        pass

    #######################
    ### Private methods ###
    #######################

    def _run_containers(self: ContainerManager) -> None:
        """Runs all containers with given configurations.

        1. For each container,
            a. If the container exists and is not running, start the container.
            b. If the container does not exist, create and run a new container with
                the given configuration.
        2. Store container objects in state.
        """

        for config in self._configs:
            id = config["id"]
            # Check if the container already exists
            container = Container(id)

            # Store existing container object in state
            self._containers[id] = container
