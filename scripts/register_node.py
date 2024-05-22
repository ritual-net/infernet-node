"""Register Node

Used to register a new node with the Infernet coordinator.

Process:
    1. Ensure node has an Inactive status at the Coordinator
    2. Call `registerNode()`
"""

from __future__ import annotations

import asyncio

# Update path to include src modules
import sys

from chain.coordinator import Coordinator, NodeStatus
from chain.rpc import RPC
from chain.wallet import Wallet
from utils.config import ConfigDict, load_validated_config
from utils.logging import log

sys.path.extend([".", "./src"])


async def register_node() -> None:
    """Core registration script"""

    # Load config
    config: ConfigDict = load_validated_config()

    # Create new RPC, Wallet
    rpc = RPC(config["chain"]["rpc_url"])
    coordinator = Coordinator(rpc, config["chain"]["coordinator_address"])
    wallet = Wallet(
        rpc,
        coordinator,
        config["chain"]["wallet"]["private_key"],
        config["chain"]["wallet"]["max_gas_limit"],
        config["chain"]["wallet"].get("allowed_sim_errors"),
    )

    # Check node status from Coordinator
    (status, cooldown) = await coordinator.get_node_status(wallet.address)

    # If status is not inactive, return
    if status.value != NodeStatus.Inactive.value:
        log.error(
            "Node not registerable",
            status=status.name,
            cooldown_start=cooldown,
        )
        return

    # Send node registration tx

    tx_hash = await wallet.register_node()
    if tx_hash:
        log.info("Sent registration tx", tx_hash=tx_hash.hex())


loop = asyncio.get_event_loop()
loop.run_until_complete(register_node())
