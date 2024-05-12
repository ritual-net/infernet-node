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

from docker import from_env  # type: ignore
from docker.errors import NotFound  # type: ignore
from docker.models.containers import Container  # type: ignore
from docker.types import DeviceRequest  # type: ignore

from shared import AsyncTask
from utils import log
from utils.config import ConfigContainer, ConfigDocker
from utils.logging import log_ascii_status

DEFAULT_STARTUP_WAIT: float = 60.0


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
        credentials: Optional[ConfigDocker],
        startup_wait: Optional[float],
        managed: Optional[bool],
    ) -> None:
        """Initialize ContainerManager with given configurations and credentials.

        Args:
            configs (dict[str, ConfigContainer]): Container configurations to run.
            credentials (ConfigDocker): Docker registry credentials.
            startup_wait (Optional[float]): Number of seconds to wait for containers
                to start. If None, uses DEFAULT_STARTUP_WAIT.
            managed (Optional[bool]): If True, containers are managed by the
                orchestrator. If False, containers are not managed and must be started
                manually. If None, defaults to True.
        """
        super().__init__()

        # Store configs, credentials, and port mappings in state
        self._configs: list[ConfigContainer] = configs
        self._creds = credentials
        self._images: list[str] = [config["image"] for config in self._configs]
        self._port_mappings: dict[str, int] = {
            config["id"]: config["port"] for config in self._configs
        }
        self._loop = get_event_loop()
        self._shutdown = False

        self._startup_wait = (
            DEFAULT_STARTUP_WAIT if startup_wait is None else startup_wait
        )
        self._managed = True if managed is None else managed

        # Store container objects in state. Only used if managed is True
        self._containers: dict[str, Container] = {}

        # Docker daemon must be running on host. Only used if managed is True
        self.client = from_env() if self._managed else None

        log.info("Initialized Container Manager", port_mappings=self._port_mappings)

    @property
    def port_mappings(self: ContainerManager) -> dict[str, int]:
        """Port mappings for containers. Does NOT guarantee containers are running"""
        return self._port_mappings

    @property
    def running_containers(self: ContainerManager) -> list[str]:
        """Get list of running container IDs"""

        # If not managed, return all container IDs as running. TODO: Once /health
        # endpoint are a requirement for all containers, use them to check if containers
        # are running.
        if not self._managed:
            return [config["id"] for config in self._configs]

        # Container objects are cached, need to reload attributes
        for container in self._containers.values():
            try:
                container.reload()
            except Exception as e:
                raise ValueError(
                    f"Container {container.name} was removed or can't be reloaded: {e}"
                )

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
        """Setup orchestrator. If containers are managed:

        1. Pulls images in parallel, if not already pulled.
        2. Prunes any containers with conflicting IDs, if prune_containers is True.
        3. Creates containers, if not already created.
        4. Starts containers, if not already started.
        5. Waits for startup_wait seconds for containers to start.

        """

        if not self._managed:
            log.info("Skipping container manager setup, containers are not managed")
            return

        try:
            # Pull images
            await self._pull_images()

            # Optionally prune existing containers. This is destructive
            if prune_containers:
                self._prune_containers()

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

            # Show ASCII status in logs
            log_ascii_status(f"Running containers: {current_containers}", True)

            # Check if any containers exited / crashed
            if len(current_containers) < len(running_containers):
                log.warning(
                    "Container(s) failed / exited / crashed",
                    failed_containers=[
                        container
                        for container in running_containers
                        if container not in current_containers
                    ],
                )
            elif len(current_containers) > len(running_containers):
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
        if not self._managed:
            log.info("Skipping container manager stop, containers are not managed")
            return

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

    async def _pull_images(self: ContainerManager) -> None:
        """Pulls all managed images in parallel.

        This method makes the following assumptions:
         - If an image exists locally and remotely, and the hashes match, it is not
            pulled (i.e. the local cached version is used).
         - If the image exists locally and remotely but the hashes DO NOT match, the
            image is pulled (i.e. remote version is ALWAYS assumed to be desired). This
            ensures that the official version of an image is always used (instead of the
            cached, potentially stale one), including when an official image is reverted
            to an older version (i.e. official == latest cannot be assumed in general).

        NOTE: For image development, always use unique local tags (e.g. ":dev") to
        ensure a different remote version is NOT pulled.

        Raises:
            RuntimeError: If any images could not be pulled or found locally.
        """
        log.info("Pulling images, this may take a while...")

        async def pull_image(image: str) -> bool:
            """Pull a docker image asynchronously

            - If an image exists locally and remotely, and the hashes match, it is not
                pulled, i.e. locally cached version is used.
            - If the image exists locally and remotely but the hashes DO NOT match, it
                is pulled and overwritten.
            - If image exists either locally or remotely, uses the existing image.
            - If the image exists neither locally nor remotely, returns False.

            Args:
                image (str): Image id to pull

            Returns:
                bool: True if image exists locally or was successfully pulled, False
                    otherwise.
            """

            try:
                log.info(f"Pulling image {image}...")
                await self._loop.run_in_executor(
                    None,
                    lambda: self.client.images.pull(image, auth_config=self._creds),
                )
                log.info(f"Successfully pulled image {image}")
                return True

            except Exception as e:
                # Check if image exists locally
                if self.client.images.get(image):
                    log.info(f"Image {image} already exists locally")
                    return True

                log.error(f"Error pulling image {image}", error=e)
                return False

        # Pull images in parallel
        tasks = [pull_image(image_id) for image_id in self._images]
        results = await gather(*tasks)

        if not all(results):
            raise RuntimeError("Could not pull all images.")

    def _prune_containers(self: ContainerManager) -> None:
        """Prunes containers by ID

        Force stops and removes any (running) containers with names matching any IDs
        provided in the managed containers config.

        WARNING: This action is destructive. Use with caution.
        """

        all_containers = self.client.containers.list(all=True)
        container_ids = [config["id"] for config in self._configs]

        for container in all_containers:
            if container.name in container_ids:
                log.warning("Pruning container", id=container.id)
                container.remove(force=True)

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

            try:
                # Check if the container already exists
                container = self.client.containers.get(id)

                # Store existing container object in state
                self._containers[id] = container

                # Start the container if it's not running
                if container.status != "running":
                    container.start()
                    log.info(f"Started existing container: {id}")
                else:
                    log.info(f"Container already running: {id}")

            except NotFound:
                # Container does not exist, so create and run a new one
                command = config["command"]
                env = config["env"]
                image = config["image"]
                port = config["port"]

                # Request GPU device if enabled
                device_requests = []
                if "gpu" in config and config["gpu"]:
                    device_requests = [DeviceRequest(count=-1, capabilities=[["gpu"]])]

                # Run container and store object in state
                self._containers[id] = self.client.containers.run(
                    image=image,
                    command=command,
                    detach=True,
                    environment=env,
                    name=id,
                    ports={"3000/tcp": ("0.0.0.0", port)},
                    restart_policy={
                        "Name": "on-failure",
                        "MaximumRetryCount": 5,
                    },
                    device_requests=device_requests,
                )
                log.info(f"Created and started new container: {id}")
