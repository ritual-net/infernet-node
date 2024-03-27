from __future__ import annotations

import asyncio
import os
import signal
from typing import Any, Optional, cast

from chain.coordinator import Coordinator
from chain.listener import ChainListener
from chain.processor import ChainProcessor
from chain.rpc import RPC
from chain.wallet import Wallet
from orchestration import ContainerManager, DataStore, Guardian, Orchestrator
from server import RESTServer, StatSender
from shared import AsyncTask
from utils import log, setup_logging
from utils.config import ConfigDict, load_validated_config
from utils.logging import log_ascii_status


class NodeLifecycle:
    """Entrypoint for Infernet node lifecycle

    Attributes:
        _tasks (list[AsyncTask]): List of initialized tasks
        _asyncio_tasks (list[asyncio.Task[Any]]): List of `run_forever` asyncio tasks
        _stat_sender (Optional[StatSender]): StatSender instance

    Public Methods:
        on_startup: Node initialization and setup
        lifecycle_main: Node lifecycle

    Private Methods:
        _lifecycle_setup: Process async setup lifecycles for tasks
        _lifecycle_run: Run node lifecycle
        _lifecycle_stop: Process stop events for async tasks
        _lifecycle_cleanup: Process cleanup for async tasks and services
        _shutdown: Gracefully shutdown node
    """

    def __init__(self: NodeLifecycle):
        self._tasks: list[AsyncTask] = []
        self._asyncio_tasks: list[asyncio.Task[Any]] = []
        self._stat_sender: Optional[StatSender] = None

    def on_startup(self: NodeLifecycle) -> None:
        """Node startup

        1. Collect and update global config
        2. Setup logging
        3. Initialize tasks
        4. Forward stats to Fluentbit
        """

        # Get version from version.txt
        with open("version.txt", "r") as file:
            version = file.read().strip()

        # Load and validate config
        config_path = os.environ.get("INFERNET_CONFIG_PATH", "config.json")
        config: ConfigDict = load_validated_config(config_path)

        # Setup logging
        setup_logging(config["log_path"])
        log.info("Running startup", chain_enabled=config["chain"]["enabled"])

        # Initialize container manager
        manager = ContainerManager(
            configs=config["containers"],
            credentials=config.get("docker"),
            startup_wait=config.get("startup_wait"),
            managed=config.get("manage_containers"),
        )
        self._tasks.append(manager)

        # Initialize data store
        store = DataStore(config["redis"]["host"], config["redis"]["port"])

        # Initialize guardian + orchestrator
        guardian = Guardian(config["containers"], config["chain"]["enabled"])
        orchestrator = Orchestrator(manager, store)

        # Initialize chain-specific tasks
        processor: Optional[ChainProcessor] = None
        wallet: Optional[Wallet] = None
        snapshot_sync: dict[str, int] = cast(
            dict[str, int], config.get("snapshot_sync", {})
        )

        if config["chain"]["enabled"]:
            rpc = RPC(config["chain"]["rpc_url"])
            coordinator = Coordinator(rpc, config["chain"]["coordinator_address"])
            wallet = Wallet(
                rpc,
                coordinator,
                config["chain"]["wallet"]["private_key"],
                config["chain"]["wallet"]["max_gas_limit"],
            )
            processor = ChainProcessor(rpc, coordinator, wallet, orchestrator)
            listener = ChainListener(
                rpc,
                coordinator,
                guardian,
                processor,
                config["chain"]["trail_head_blocks"],
                snapshot_sync_sleep=snapshot_sync.get("sleep"),
                snapshot_sync_batch_size=snapshot_sync.get("batch_size"),
            )
            self._tasks.extend([processor, listener])

        # Initialize REST server
        self._tasks.append(
            RESTServer(
                guardian,
                manager,
                orchestrator,
                processor if processor else None,
                store,
                config["chain"],
                config["server"],
                version,
                wallet.address if wallet else None,
            )
        )

        # Forward stats to Fluentbit, if enabled
        if config["forward_stats"]:
            self._stat_sender = StatSender(version, guardian, store, wallet)
            self._tasks.append(self._stat_sender)

    async def _lifecycle_setup(self: NodeLifecycle) -> None:
        """Process async setup lifecycles for tasks"""
        log.info("Running node lifecycle setup")
        for resource in self._tasks:
            await resource.setup()

    async def _lifecycle_run(self: NodeLifecycle) -> int:
        """Runs node lifecycle

        Returns:
            int: Non-zero exit code if any task failed
        """
        log.info("Running node lifecycle")

        # Run tasks in parallel
        self._asyncio_tasks = [
            asyncio.create_task(task.run_forever()) for task in self._tasks
        ]

        # Wait for any service crashes or exits
        done, _ = await asyncio.wait(
            self._asyncio_tasks, return_when=asyncio.FIRST_EXCEPTION
        )
        for task in done:
            # Check if any tasks failed
            exception = task.exception()

            # If exception occured, log and shutdown
            if exception:
                stack = str(task.get_stack())
                log.error(stack)
                log_ascii_status(f"Node exited{': ' + str(exception)}", False)

                # Send error to fluentbit
                if self._stat_sender:
                    await self._stat_sender.send_node_stats_shutdown(
                        f"{stack}\n{exception}"
                    )

                # Trigger node shutdown
                await self._shutdown()

                # Non-zero exit code, indicating error
                return 1

        # At this point, no exception occured, so is a normal shutdown, in which case
        # self._shutdown() has already been called. Send stats without error (if
        # enabled) and return 0 to indicate successful shutdown without errors.
        if self._stat_sender:
            await self._stat_sender.send_node_stats_shutdown()
        return 0

    async def _lifecycle_stop(self: NodeLifecycle) -> None:
        """Process stop events for async tasks"""
        log.info("Stopping node lifecycle")

        # Stop all tasks
        for task in self._tasks:
            await task.stop()

        # Wait for all task `run_forever` loops to stop
        await asyncio.gather(*self._asyncio_tasks, return_exceptions=True)

    async def _lifecycle_cleanup(self: NodeLifecycle) -> None:
        """Process cleanup for async tasks and services"""
        log.info("Cleaning up node lifecycle")
        for resource in self._tasks:
            await resource.cleanup()

    async def _shutdown(self: NodeLifecycle) -> None:
        """Gracefully shutdown node. Run `lifecycle_stop` and `lifecycle_cleanup`"""
        await self._lifecycle_stop()
        await self._lifecycle_cleanup()
        log.info("Shutdown complete.")

    def lifecycle_main(self: NodeLifecycle) -> None:
        """Node lifecycle

        1. `lifecycle_setup` — Process async lifecycle setup
        2. `lifecycle_run` — Run lifecycle
        3. On stop, `lifecycle_stop` and `lifecycle_cleanup`
        """

        # Get asyncio event loop
        loop = asyncio.get_event_loop()

        # Run lifecycle setup
        loop.run_until_complete(self._lifecycle_setup())

        # Register signal handlers for graceful shutdown
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self._shutdown()))

        # Run lifecycle
        exit_code = loop.run_until_complete(self._lifecycle_run())

        # Exit with exit code
        exit(exit_code)


if __name__ == "__main__":
    node = NodeLifecycle()
    node.on_startup()
    node.lifecycle_main()
