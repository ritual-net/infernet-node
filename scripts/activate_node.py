"""Activate Node

Used to activate a new node with the Infernet coordinator.

Process:
    1. Ensure node has a Registered status at the Coordinator
    2. Ensure 1-hour cooldown has passed
    3. Call `activateNode()`
"""

from __future__ import annotations

import asyncio

# Update path to include src modules
import sys
import time

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
        config["chain"]["wallet"].get("allowed_errors"),
    )

    # Check node status from Coordinator
    (status, cooldown) = await coordinator.get_node_status(wallet.address)

    # If status is not registered, return
    if status.value != NodeStatus.Registered.value:
        log.error(
            "Node not activateable",
            status=status.name,
            cooldown_start=cooldown,
        )
        return

    # If cooldown not elapsed, return
    current_ts = int(time.time())
    cooldown_end_ts = cooldown + 3600
    if current_ts < cooldown_end_ts:
        log.error(
            "Cooldown not elapsed", remaining_seconds=cooldown_end_ts - current_ts
        )
        return

    # Send node activation tx
    tx_hash = await wallet.activate_node()
    if tx_hash:
        log.info("Sent activation tx", tx_hash=tx_hash.hex())


loop = asyncio.get_event_loop()
loop.run_until_complete(register_node())
