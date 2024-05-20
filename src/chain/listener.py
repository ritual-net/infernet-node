"""ChainListener

Off-chain replay of on-chain Coordinator events.

Listens to a single Infernet Coordinator contract for SubscriptionCreated,
SubscriptionCancelled, and SubscriptionFulfilled events. Validates relevant
events against guardian and forwards to ChainProcessor.
"""

from __future__ import annotations

import asyncio
from asyncio import create_task, sleep
from typing import Optional, cast

from eth_abi.abi import decode
from eth_typing import BlockNumber
from reretry import retry  # type: ignore
from web3.types import LogReceipt

from chain.coordinator import Coordinator, CoordinatorEvent
from chain.processor import ChainProcessor
from chain.rpc import RPC
from orchestration.guardian import Guardian
from shared.message import (
    GuardianError,
    SubscriptionCancelledMessage,
    SubscriptionCreatedMessage,
    SubscriptionFulfilledMessage,
)
from shared.service import AsyncTask
from utils import log

SNAPSHOT_SYNC_BATCH_SIZE = 200
SNAPSHOT_SYNC_BATCH_SLEEP_S = 1.0


class ChainListener(AsyncTask):
    """Off-chain replay of on-chain Coordinator events.

    Public methods:
        setup: Inherited from AsyncTask. Snapshot syncs relevant subscriptions.
        run_forever: Inherited from AsyncTask. Syncs new Coordinator events.
        cleanup: Inherited from AsyncTask. Unused because process is stateless.

    Private methods:
        _sync_subscription_creation: Syncs net-new subscriptions
        _snapshot_sync: Called by setup(). Syncs all subscriptions seen till head block.
        _parse_created_log: Parses SubscriptionCreated event logs.
        _parse_cancelled_log: Parses SubscriptionCancelled event logs.
        _parse_fulfilled_log: Parses SubscriptionFulfilled event logs.
        _process_event_logs: Segments logs by type and passes to _parse_* fns.

    Private attributes:
        _rpc (RPC): RPC instance
        _coordinator (Coordinator): Coordinator instance
        _guardian (Guardian): Guardian instance
        _processor (ChainProcessor): ChainProcessor instance
        _last_synced (int): Last synced chain block number
        _trail_head_blocks (int): How many blocks to trail head by
        _snapshot_sync_sleep (int): Snapshot sync sleep time between each batch
        _snapshot_sync_batch_size (int): Snapshot sync batch size to sync in parallel
    """

    def __init__(
        self: ChainListener,
        rpc: RPC,
        coordinator: Coordinator,
        guardian: Guardian,
        processor: ChainProcessor,
        trail_head_blocks: int,
        snapshot_sync_sleep: Optional[int],
        snapshot_sync_batch_size: Optional[int],
    ) -> None:
        """Initializes new ChainListener

        Args:
            rpc (RPC): RPC instance
            coordinator (Coordinator): Coordinator instance
            guardian (Guardian): Guardian instance
            processor (ChainProcessor): ChainProcessor instance
            trail_head_blocks (int): How many blocks to trail head by
            snapshot_sync_sleep (int): Snapshot sync sleep time between each batch
            snapshot_sync_batch_size (int): Snapshot sync batch size to sync in parallel
        """

        # Initialize inherited AsyncTask
        super().__init__()

        self._rpc = rpc
        self._coordinator = coordinator
        self._guardian = guardian
        self._processor = processor
        self._trail_head_blocks = trail_head_blocks
        self._snapshot_sync_sleep = (
            SNAPSHOT_SYNC_BATCH_SLEEP_S
            if snapshot_sync_sleep is None
            else snapshot_sync_sleep
        )
        self._snapshot_sync_batch_size = (
            SNAPSHOT_SYNC_BATCH_SIZE
            if snapshot_sync_batch_size is None
            else snapshot_sync_batch_size
        )
        log.info("Initialized ChainListener")

    async def _sync_subscription_creation(
        self: ChainListener,
        id: int,
        block_number: BlockNumber,
        tx_hash: Optional[str],
    ) -> None:
        """Syncs net-new subscriptions

        Consumed by:
            1. Snapshot sync when initially syncing subscriptions
            2. Parsing subscription creation logs when event replaying creation

        Process:
            1. Collect subscription at specified block number
            2. If subscription is on last interval, collect and set response count
                (useful to filter out completed subscriptions)
            3. Validate subscriptions against guardian rules
            4. If validated, forward subscriptions to ChainProcessor

        Args:
            id (int): subscription ID
            block_number (BlockNumber): block number to collect at (TOCTTOU)
            tx_hash (Optional[str]): optional tx_hash if syncing via event replay
        """

        # Collect subscription
        subscription = await self._coordinator.get_subscription_by_id(
            subscription_id=id, block_number=block_number
        )

        # If subscription is on last interval
        if subscription.last_interval:
            # Collect and set response count for interval (always last)
            interval = subscription.interval
            response_count = await self._coordinator.get_subscription_response_count(
                subscription_id=id,
                interval=interval,
                block_number=block_number,
            )
            subscription.set_response_count(interval, response_count)

        # Create new subscription created message
        msg = SubscriptionCreatedMessage(tx_hash, subscription)

        # Run message through guardian
        filtered = self._guardian.process_message(msg)

        if isinstance(filtered, GuardianError):
            # If filtered out by guardian, message is irrelevant
            log.info("Ignored subscription creation", id=id, err=filtered.error)
            return

        # Pass filtered message to ChainProcessor
        create_task(self._processor.track(msg))
        log.info("Relayed subscription creation", id=id)

    async def _snapshot_sync(self: ChainListener, head_block: BlockNumber) -> None:
        """Snapshot syncs subscriptions from Coordinator up to head block

        Args:
            head_block (BlockNumber): latest block to snapshot sync to

        Process:
            1. Collect highest subscription ID from Coordinator at head block
            2. From 1..highest subscription ID, _sync_subscription_creation
        """

        # Get highest subscription ID at head block
        head_id = await self._coordinator.get_head_subscription_id(head_block)
        log.info("Collected highest subscription id", id=head_id)

        # Subscription indexes are 1-indexed at contract level
        # For subscriptions 1 -> head, sync subscription creation
        # sync is happening in parallel in batches of size
        # self._snapshot_sync_batch_size, to throttle, sleeps self._snapshot_sync_sleep
        # seconds between each batch

        @retry(delay=self._snapshot_sync_sleep, backoff=2)  # type: ignore
        async def _sync_subscription_with_retry(batch: range) -> None:
            """Sync subscriptions in batch with retry and exponential backoff"""
            try:
                await asyncio.gather(
                    *(
                        self._sync_subscription_creation(id, head_block, None)
                        for id in batch
                    )
                )
            except Exception as e:
                log.error(
                    f"Error syncing subscription batch {batch}. Retrying...",
                    batch=batch,
                    err=e,
                )
                raise e

        batches = [
            range(i, i + self._snapshot_sync_batch_size)
            for i in range(1, head_id + 1, self._snapshot_sync_batch_size)
        ]
        for batch in batches:
            # sync for this batch
            await _sync_subscription_with_retry(batch)

            # sleep between batches to avoid getting rate-limited by the RPC
            await asyncio.sleep(self._snapshot_sync_sleep)

    async def _parse_created_log(self: ChainListener, receipt: LogReceipt) -> None:
        """Parses SubscriptionCreated event

        Process:
            1. Collect subscription ID, log block number, tx_hash from receipt
            2. Sync net-new subscription via _sync_subscription_creation

        Args:
            log (LogReceipt): subscription creation log
        """

        # Parse subscription ID, block number from log receipt
        id = int(receipt["topics"][1].hex(), 16)
        block_number = receipt["blockNumber"]
        tx_hash = receipt["transactionHash"].hex()

        await self._sync_subscription_creation(id, block_number, tx_hash)

    async def _parse_cancelled_log(self: ChainListener, receipt: LogReceipt) -> None:
        """Parses SubscriptionCancelled event

        Process:
            1. Collect subscription ID from receipt
            2. Validates SubscriptionCancelled message
            3. If validated, forwards message to ChainProcessor

        Args:
            log (LogReceipt): subscription cancelled log
        """

        # Parse subscription ID from log receipt
        id = int(receipt["topics"][1].hex(), 16)

        # Create new subscription cancelled message
        msg = SubscriptionCancelledMessage(subscription_id=id)

        # Run message through guardian
        filtered = self._guardian.process_message(msg)

        if isinstance(filtered, GuardianError):
            # If filtered out by guardian, message is irrelevant
            log.info("Ignored subscription cancellation", id=id, err=filtered.error)
            return

        # Pass filtered message to ChainProcessor
        create_task(self._processor.track(msg))
        log.info("Relayed subscription cancellation", id=id)

    async def _parse_fulfilled_log(self: ChainListener, receipt: LogReceipt) -> None:
        """Parses SubscriptionFulfilled event

        Process:
            1. Collect subscription ID, block number, fulfilling node from receipt
            2. Collects block timestamp by quering for block data by block number
            3. Validates SubscriptionFulfilled message
            4. If validated, forwards message to ChainProcessor

        Args:
            log (LogReceipt): subscription fulfilled log
        """

        # Parse subscription ID, block number, fulfilling node from log receipt
        id = int(receipt["topics"][1].hex(), 16)
        block_number = receipt["blockNumber"]
        fulfilling_node = cast(str, decode(["address"], receipt["topics"][2])[0])

        # Collect transaction timestamp
        block = await self._rpc.get_block_by_number(block_number)
        timestamp = cast(int, block["timestamp"])

        # Create new subscription fulfillment message
        msg = SubscriptionFulfilledMessage(
            subscription_id=id,
            node=self._rpc.get_checksum_address(fulfilling_node),
            timestamp=timestamp,
        )

        # Run message through guardian
        filtered = self._guardian.process_message(msg)

        if isinstance(filtered, GuardianError):
            # If filtered out by guardian, message is irrelevant
            log.info("Ignored subscription fulfillment", id=id, err=filtered.error)
            return

        # Pass filtered message to ChainProcessor
        create_task(self._processor.track(msg))
        log.info("Relayed subscription fulfillment", id=id)

    async def _process_event_logs(
        self: ChainListener, event_logs: list[LogReceipt]
    ) -> None:
        """Processes event logs according to log type

        Process:
            1. Segments event log by type
            2. Executes relevant _parse_* fn according to type

        Args:
            event_logs (list[LogReceipt]): event log receipts
        """

        # Collect event => event hashes
        hashes = self._coordinator.get_event_hashes()
        # Invert mapping (event hash => event)
        names = {hash: evt for evt, hash in hashes.items()}

        # Setup event topic hashes
        for log_receipt in event_logs:
            # Collect event topic from event log receipt
            event_topic: str = log_receipt["topics"][0].hex()
            # Collect event from event topic
            event = names[event_topic]

            # Execute relevant _parse_* fn according to event type
            match event:
                case CoordinatorEvent.SubscriptionCreated:
                    await self._parse_created_log(log_receipt)
                case CoordinatorEvent.SubscriptionCancelled:
                    await self._parse_cancelled_log(log_receipt)
                case CoordinatorEvent.SubscriptionFulfilled:
                    await self._parse_fulfilled_log(log_receipt)

    async def setup(self: ChainListener) -> None:
        """ChainListener startup

        Process:
            1. Collect head block number from RPC
            2. Snapshot sync subscriptions from Coordinator up to head block
            3. Update locally-aware latest block in memory
        """

        # Get head block
        head_block = await self._rpc.get_head_block_number() - self._trail_head_blocks
        log.info(
            "Started snapshot sync",
            head=head_block,
            behind=self._trail_head_blocks,
        )

        # Snapshot sync subscriptions
        await self._snapshot_sync(cast(BlockNumber, head_block))

        # Update last synced block
        self._last_synced = head_block
        log.info("Finished snapshot sync", new_head=head_block)

    async def run_forever(self: ChainListener) -> None:
        """Core ChainListener event loop

        Process:
            1. Collects chain head block and latest locally synced block
            2. If head > locally_synced:
                2.1. Collects coordinator events between (locally_synced, head)
                    2.1.1. Up to a maximum of 100 blocks to not overload RPC
                2.2. Parses, validates, and pushes events to ChainProcessor
            3. Else, if chain head block <= latest locally synced block, sleeps for 500ms
        """

        log.info("Started ChainListener lifecycle", last_synced=self._last_synced)
        while not self._shutdown:
            # Collect chain head block
            head_block = (
                cast(int, await self._rpc.get_head_block_number())
                - self._trail_head_blocks
            )

            # Check if latest locally synced block < chain head block
            if self._last_synced < head_block:
                # Setup number of blocks to sync
                num_blocks_to_sync = min(head_block - self._last_synced, 100)
                # Setup target block (last + diff inclusive)
                target_block = self._last_synced + num_blocks_to_sync

                # Collect all Coordinator emitted event logs in range
                event_logs = await self._coordinator.get_event_logs(
                    cast(BlockNumber, self._last_synced + 1),
                    cast(BlockNumber, target_block),
                )

                # Process collected event logs
                await self._process_event_logs(event_logs)

                # Update last synced block
                self._last_synced = target_block
                log.info(
                    "Checked new blocks for events",
                    num_blocks=num_blocks_to_sync,
                    log_count=len(event_logs),
                    new_synced=self._last_synced,
                    behind=self._trail_head_blocks,
                )
            else:
                # Else, if already synced to head, sleep
                log.debug(
                    "No new blocks, sleeping for 500ms",
                    head=head_block,
                    synced=self._last_synced,
                    behind=self._trail_head_blocks,
                )
                await sleep(0.5)

    async def cleanup(self: ChainListener) -> None:
        """Stateless task, no cleanup necessary"""
        pass
