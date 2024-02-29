import signal
import asyncio
from typing import Any, Optional, cast

from chain.rpc import RPC
from shared import AsyncTask
from chain.wallet import Wallet
from utils import log, setup_logging
from chain.listener import ChainListener
from server import RESTServer, StatSender
from chain.coordinator import Coordinator
from chain.processor import ChainProcessor
from utils.config import ConfigDict, load_validated_config, ConfigDocker
from orchestration import ContainerManager, DataStore, Guardian, Orchestrator

# Tasks
tasks: list[AsyncTask] = []

# Asyncio tasks
asyncio_tasks: list[asyncio.Task[Any]] = []


def on_startup() -> None:
    """Node startup

    1. Collect and update global config
    2. Setup logging
    3. Initialize tasks
    4. Forward stats to Fluentbit
    """
    global tasks

    # Get version from version.txt
    with open("version.txt", "r") as file:
        version = file.read().strip()

    # Load and validate config
    config: ConfigDict = load_validated_config()

    # Setup logging
    setup_logging(config["log_path"])
    log.info("Running startup", chain_enabled=config["chain"]["enabled"])

    # Initialize container manager
    manager = ContainerManager(
        config["containers"],
        cast(ConfigDocker, config.get("docker", {})),
        startup_wait=config.get("startup_wait"),
    )
    tasks.append(manager)

    # Initialize data store
    store = DataStore(config["redis"]["host"], config["redis"]["port"])

    # Initialize guardian + orchestrator
    guardian = Guardian(config["containers"], config["chain"]["enabled"])
    orchestrator = Orchestrator(manager, store)

    # Initialize chain-specific tasks
    processor: Optional[ChainProcessor] = None
    wallet: Optional[Wallet] = None

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
        )
        tasks.extend([processor, listener])

    # Initialize REST server
    tasks.append(
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
        tasks.append(StatSender(version, guardian, store, wallet))


async def lifecycle_setup() -> None:
    """Process async setup lifecycles for tasks"""
    log.info("Running node lifecycle setup")
    for resource in tasks:
        await resource.setup()


async def lifecycle_run() -> None:
    """Runs node lifecycle"""
    global asyncio_tasks
    log.info("Running node lifecycle")

    # Run tasks in parallel
    asyncio_tasks = [asyncio.create_task(task.run_forever()) for task in tasks]

    # Wait for any service crashes or exits
    done, _ = await asyncio.wait(asyncio_tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in done:
        # Check if any tasks failed
        if task.exception() is not None:
            # Log exception
            log.error(f"Task exception: {task.exception()}")


async def lifecycle_stop() -> None:
    """Process stop events for async tasks"""
    log.info("Stopping node lifecycle")

    # Process stop
    for task in tasks:
        await task.stop()

    # Wait for all task `run_forever` loops to stop
    await asyncio.gather(*asyncio_tasks, return_exceptions=True)


async def lifecycle_cleanup() -> None:
    """Process cleanup for async tasks and services"""
    log.info("Cleaning up node lifecycle")
    for resource in tasks:
        await resource.cleanup()


async def shutdown(signal: signal.Signals) -> None:
    """Gracefully shutdown node. Run `lifecycle_stop` and `lifecycle_cleanup`"""
    log.info(f"Received exit signal {signal.name}...")
    await lifecycle_stop()
    await lifecycle_cleanup()
    log.info("Shutdown complete.")


def lifecycle_main() -> None:
    """Node lifecycle

    1. `lifecycle_setup` — Process async lifecycle setup
    2. `lifecycle_run` — Run lifecycle
    3. On stop, `lifecycle_stop` and `lifecycle_cleanup`
    """

    # Get asyncio event loop
    loop = asyncio.get_event_loop()

    # Run lifecycle setup
    loop.run_until_complete(lifecycle_setup())

    # Register signal handlers for graceful shutdown
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown(s)))

    # Run lifecycle
    loop.run_until_complete(lifecycle_run())

    log.info("Exited main process")


if __name__ == "__main__":
    on_startup()
    lifecycle_main()
