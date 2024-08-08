from __future__ import annotations

import asyncio
import os
import signal
from typing import Any, Optional, cast

from web3 import Web3

from chain.container_lookup import ContainerLookup
from chain.coordinator import Coordinator
from chain.listener import ChainListener
from chain.payment_wallet import PaymentWallet
from chain.processor import ChainProcessor
from chain.registry import Registry
from chain.rpc import RPC
from chain.wallet import Wallet
from chain.wallet_checker import WalletChecker
from orchestration import ContainerManager, DataStore, Guardian, Orchestrator
from server import RESTServer, StatSender
from shared import AsyncTask
from utils import log, setup_logging
from utils.config import ConfigDict, load_validated_config
from utils.logging import log_ascii_status
from version import __version__, check_node_is_up_to_date


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

        # Load and validate config
        config_path = os.environ.get("INFERNET_CONFIG_PATH", "config.json")
        config: ConfigDict = load_validated_config(config_path)

        # Setup logging
        setup_logging(config.get("log"))
        check_node_is_up_to_date()

        log.debug("Running startup", chain_enabled=config["chain"]["enabled"])

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
        container_lookup = ContainerLookup(config["containers"])

        chain_enabled = config["chain"]["enabled"]

        guardian = Guardian(
            config["containers"],
            chain_enabled,
            container_lookup=container_lookup,
            wallet_checker=None,
        )

        orchestrator = Orchestrator(manager, store)

        # Initialize chain-specific tasks
        processor: Optional[ChainProcessor] = None
        wallet: Optional[Wallet] = None
        snapshot_sync: dict[str, int] = cast(
            dict[str, int], config["chain"].get("snapshot_sync", {})
        )

        if chain_enabled:
            rpc = RPC(
                config["chain"]["rpc_url"], config["chain"]["wallet"]["private_key"]
            )

            asyncio.get_event_loop().run_until_complete(rpc.initialize())

            registry = Registry(
                rpc,
                Web3.to_checksum_address(config["chain"]["registry_address"]),
            )

            _payment_address = config["chain"]["wallet"].get("payment_address")

            payment_address = (
                _payment_address
                if _payment_address is None
                else Web3.to_checksum_address(_payment_address)
            )

            wallet_checker = WalletChecker(
                rpc=rpc,
                registry=registry,
                container_configs=config["containers"],
                payment_address=payment_address,
            )

            guardian = Guardian(
                config["containers"],
                chain_enabled,
                container_lookup=container_lookup,
                wallet_checker=wallet_checker,
            )

            # address population is an async operation, and needs to be awaited before
            # other tasks are initialized
            asyncio.get_event_loop().run_until_complete(registry.populate_addresses())

            coordinator = Coordinator(
                rpc,
                registry.coordinator,
                container_lookup=container_lookup,
            )

            wallet = Wallet(
                rpc,
                coordinator,
                config["chain"]["wallet"]["private_key"],
                config["chain"]["wallet"]["max_gas_limit"],
                payment_address,
                config["chain"]["wallet"].get("allowed_sim_errors"),
            )
            payment_wallet = PaymentWallet(payment_address, rpc)
            processor = ChainProcessor(
                rpc,
                coordinator,
                wallet,
                payment_wallet,
                wallet_checker,
                registry,
                orchestrator,
                container_lookup,
            )
            listener = ChainListener(
                rpc,
                coordinator,
                registry,
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
                __version__,
                wallet.address if wallet else None,
            )
        )

        # Forward stats to Fluentbit, if enabled
        if config["forward_stats"]:
            self._stat_sender = StatSender(
                __version__, config["server"]["port"], guardian, store, wallet
            )
            self._tasks.append(self._stat_sender)

    async def _lifecycle_setup(self: NodeLifecycle) -> None:
        """Process async setup lifecycles for tasks"""
        log.debug("Running node lifecycle setup")
        await asyncio.gather(*(resource.setup() for resource in self._tasks))

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
                log_ascii_status(f"Node exited{': ' + str(exception)}", "failure")

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

    async def _shutdown(self: NodeLifecycle) -> None:
        """Gracefully shutdown node. Stops all tasks and cleans up."""
        log.info("Shutting down node")

        # Stop all tasks
        await asyncio.gather(*(task.stop() for task in self._tasks))

        # Wait for all task `run_forever` loops to stop
        await asyncio.gather(*self._asyncio_tasks, return_exceptions=True)

        # Cleanup all tasks
        await asyncio.gather(*(task.cleanup() for task in self._tasks))

        log.debug("Shutdown complete.")

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
