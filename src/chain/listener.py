"""ChainListener

Off-chain replay of on-chain Coordinator events.

Repeatedly syncs new Coordinator events and subscriptions. On startup, syncs
subscriptions from Coordinator up to head block. On each iteration, checks for
new Coordinator events and subscriptions, filters them through Guardian, and
forwards them to ChainProcessor.
"""

from __future__ import annotations

import asyncio
from asyncio import create_task, sleep
from typing import cast

from eth_typing import BlockNumber
from reretry import retry  # type: ignore

from chain.coordinator import Coordinator
from chain.processor import ChainProcessor
from chain.reader import Reader
from chain.registry import Registry
from chain.rpc import RPC
from orchestration.guardian import Guardian
from shared.config import ConfigSnapshotSync
from shared.message import GuardianError, SubscriptionCreatedMessage
from shared.service import AsyncTask
from utils import log

SUBSCRIPTION_SYNC_BATCH_SIZE = 20


def get_batches(start: int, end: int, batch_size: int) -> list[tuple[int, int]]:
    """
    Get batches of size batch_size from start to end (inclusive), used for snapshot sync.
    """
    if start == end:
        return [(start, start + 1)]
    if end - start + 1 <= batch_size:
        return [(start, end + 1)]
    else:
        return [
            (i, min(i + batch_size - 1, end) + 1)
            for i in range(start, end + 1, batch_size)
        ]


class ChainListener(AsyncTask):
    """Off-chain replay of on-chain Coordinator events.

    Public methods:
        setup: Inherited from AsyncTask. Snapshot syncs relevant subscriptions.
        run_forever: Inherited from AsyncTask. Syncs new Coordinator events.
        cleanup: Inherited from AsyncTask. Unused because process is stateless.

    Private methods:
        _sync_subscription_creation: Syncs net-new subscriptions
        _snapshot_sync: Called by setup() as well as run_forever() to sync subscriptions.
            Syncs all subscriptions seen till head block.

    Private attributes:
        _rpc (RPC): RPC instance
        _coordinator (Coordinator): Coordinator instance
        _registry (Registry): Registry instance
        _reader (Reader): Reader instance
        _guardian (Guardian): Guardian instance
        _processor (ChainProcessor): ChainProcessor instance
        _last_synced (int): Last synced chain block number
        _trail_head_blocks (int): How many blocks to trail head by
        _snapshot_sync_sleep (int): Snapshot sync sleep time between each batch
        _snapshot_sync_batch_size (int): Snapshot sync batch size to sync in parallel
        _snapshot_sync_starting_sub_id (int): Snapshot sync starting subscription ID
        _syncing_period (float): How long to sleep between each iteration
    """

    def __init__(
        self: ChainListener,
        rpc: RPC,
        coordinator: Coordinator,
        registry: Registry,
        reader: Reader,
        guardian: Guardian,
        processor: ChainProcessor,
        trail_head_blocks: int,
        snapshot_sync: ConfigSnapshotSync,
    ) -> None:
        """Initializes new ChainListener

        Args:
            rpc (RPC): RPC instance
            coordinator (Coordinator): Coordinator instance
            registry (Registry): Registry instance
            reader (Reader): Reader instance
            guardian (Guardian): Guardian instance
            processor (ChainProcessor): ChainProcessor instance
            trail_head_blocks (int): How many blocks to trail head by
            snapshot_sync (ConfigSnapshotSync): Snapshot sync configuration
        """

        # Initialize inherited AsyncTask
        super().__init__()

        self._rpc = rpc
        self._coordinator = coordinator
        self._registry = registry
        self._reader = reader
        self._guardian = guardian
        self._processor = processor
        self._trail_head_blocks = trail_head_blocks
        self._snapshot_sync_sleep = snapshot_sync.sleep
        self._snapshot_sync_batch_size = snapshot_sync.batch_size
        self._snapshot_sync_starting_sub_id = snapshot_sync.starting_sub_id
        self._syncing_period = snapshot_sync.sync_period
        log.info("Initialized ChainListener")

    async def _sync_batch_subscriptions_creation(
        self: ChainListener,
        start_id: int,
        end_id: int,
        block_number: BlockNumber,
    ) -> None:
        """Syncs a batch of subscriptions from start_id to end_id (inclusive)

        Consumed by:
            1. Snapshot sync when initially syncing subscriptions
            2. Parsing subscription creation logs when event replaying creation

        Process:
            1. Collect subscriptions at specified block number through Reader SC
            2. Collect batch response count at specified block number through Reader SC
            3. For subscriptions that are on last interval,
                collect and set response count
                (useful to filter out completed subscriptions)
            4. Validate subscriptions against guardian rules
            5. If validated, forward subscriptions to ChainProcessor

        Args:
            start_id (int): starting subscription ID of batch
            end_id (int): ending subscription ID of batch
            block_number (BlockNumber): block number to collect at (TOCTTOU)
        """
        while not self._shutdown:
            subscriptions = await self._reader.read_subscription_batch(
                start_id, end_id, block_number
            )

            # Get IDs, intervals and response count data
            # for subscriptions that are on last interval
            filtered_ids = [sub.id for sub in subscriptions if sub.last_interval]
            filtered_intervals = [
                sub.interval for sub in subscriptions if sub.last_interval
            ]
            filtered_subscriptions_response_count = (
                await self._reader.read_redundancy_count_batch(
                    filtered_ids, filtered_intervals, block_number
                )
            )

            assert (
                len(filtered_ids)
                == len(filtered_intervals)
                == len(filtered_subscriptions_response_count)
            ), "Arrays must have the same length"

            for i in range(len(filtered_ids)):
                sub_id = filtered_ids[i]
                interval = filtered_intervals[i]
                response_count = filtered_subscriptions_response_count[i]

                # Find the corresponding subscription in the subscriptions list
                for subscription in subscriptions:
                    if subscription.id == sub_id:
                        subscription.set_response_count(interval, response_count)
                        # Create new subscription created message

            for subscription in subscriptions:
                msg = SubscriptionCreatedMessage(subscription)

                # Run message through guardian
                filtered = self._guardian.process_message(msg)

                if isinstance(filtered, GuardianError):
                    # If filtered out by guardian, message is irrelevant
                    log.info(
                        "Ignored subscription creation",
                        id=sub_id,
                        err=filtered.error,
                    )
                else:
                    # Pass filtered message to ChainProcessor
                    create_task(self._processor.track(msg))
                    log.info("Relayed subscription creation", id=subscription.id)
            break
        return

    async def _snapshot_sync(self: ChainListener, head_block: BlockNumber) -> None:
        """Snapshot syncs subscriptions from Coordinator up to the latest subscription
        read at the head block. Retries on failure, with exponential backoff. Since
        `ChainProcessor` keeps track of subscriptions indexed by their ID, this method
        is idempotent.

        Args:
            head_block (BlockNumber): latest block to snapshot sync to

        Process:
            1. Collect highest subscription ID from Coordinator at head block
            2. From _last_subscription_id + 1 -> head_sub_id, _sync_subscription_creation
        """

        # Get the highest subscription ID at the head block
        head_sub_id = await self._coordinator.get_head_subscription_id(head_block)
        log.info(
            "Collected highest subscription id",
            id=head_sub_id,
            head_block=head_block,
        )

        # Subscription indexes are 1-indexed at contract level. For
        # subscriptions 1 -> head, sync subscription creation sync is happening
        # in parallel in batches of size self._snapshot_sync_batch_size. To throttle,
        # sleeps self._snapshot_sync_sleep seconds between each batch
        start = self._last_subscription_id + 1

        batches = get_batches(start, head_sub_id, self._snapshot_sync_batch_size)

        if len(batches) == 1 and batches[0][0] == batches[0][1]:
            # no new subscriptions to sync
            return

        log.info("Syncing new subscriptions", batches=batches)

        @retry(delay=self._snapshot_sync_sleep, backoff=2)  # type: ignore
        async def _sync_subscription_batch_with_retry(batch: tuple[int, int]) -> None:
            """Sync subscriptions in batch with retry and exponential backoff"""
            try:
                await self._sync_batch_subscriptions_creation(
                    batch[0], batch[1], head_block
                )

            except Exception as e:
                log.error(
                    f"Error syncing subscription batch {batch}. Retrying...",
                    batch=batch,
                    err=e,
                )
                raise e

        for _batch in batches:
            # sync for this batch
            await _sync_subscription_batch_with_retry(_batch)

            # sleep between batches to avoid getting rate-limited by the RPC
            await asyncio.sleep(self._snapshot_sync_sleep)

    async def setup(self: ChainListener) -> None:
        """ChainListener startup

        Process:
            1. Collect head block number from RPC
            2. Snapshot sync subscriptions from Coordinator up to head block
            3. Update locally-aware latest block in memory
        """

        # Get head block
        head_block = await self._rpc.get_head_block_number() - self._trail_head_blocks
        # Update last synced block
        self._last_block = head_block
        self._last_subscription_id = self._snapshot_sync_starting_sub_id

        log.info(
            "Started snapshot sync",
            head=head_block,
            behind=self._trail_head_blocks,
        )

        # Snapshot sync subscriptions
        await self._snapshot_sync(cast(BlockNumber, head_block))
        head_sub_id = await self._coordinator.get_head_subscription_id(
            cast(BlockNumber, head_block)
        )
        # Setting this after snapshot, to avoid a 2nd full run of "run_forever" method
        self._last_subscription_id = head_sub_id

        log.info("Finished snapshot sync", new_head=head_block)

    async def run_forever(self: ChainListener) -> None:
        """Core ChainListener event loop

        Process:
            1. Collects chain head block and latest locally synced block
            2. If head > locally_synced:
                2.1. Collects coordinator subscription creations (locally_synced, head)
                    2.1.1. Up to a maximum of 100 blocks to not overload RPC
                2.2. Syncs new subscriptions and updates last synced block
            3. Else, if chain head block <= latest locally synced block, sleeps for 500ms
        """

        log.info("Started ChainListener lifecycle", last_synced=self._last_block)

        while not self._shutdown:
            # Collect chain head block
            head_block = cast(
                BlockNumber,
                (
                    cast(int, await self._rpc.get_head_block_number())
                    - self._trail_head_blocks
                ),
            )

            # Check if latest locally synced block < chain head block
            if self._last_block < head_block:
                # Setup number of blocks to sync
                num_blocks_to_sync = min(head_block - self._last_block, 100)
                # Setup target block (last + diff inclusive)
                target_block = cast(BlockNumber, self._last_block + num_blocks_to_sync)
                head_sub_id = await self._coordinator.get_head_subscription_id(
                    target_block
                )
                log.info(f"head sub id is: {head_sub_id}")
                num_subs_to_sync = min(
                    head_sub_id - self._last_subscription_id,
                    self._snapshot_sync_batch_size,
                )

                # Collect all Coordinator emitted event logs in range
                log.info(
                    "Checking subscriptions",
                    last_sub_id=self._last_subscription_id,
                    head_sub_id=head_sub_id,
                    num_subs_to_sync=num_subs_to_sync,
                    head_block=head_block,
                )

                # sync new subscriptions
                await self._snapshot_sync(head_block)

                # Update last synced block
                self._last_block = target_block
                self._last_subscription_id = head_sub_id

                log.info(
                    "Checked for new subscriptions",
                    last_synced=self._last_block,
                    last_sub_id=self._last_subscription_id,
                    head_sub_id=head_sub_id,
                )
            else:
                # Else, if already synced to head, sleep
                log.debug(
                    "No new blocks, sleeping for: ",
                    self._syncing_period,
                    "seconds",
                    head=head_block,
                    synced=self._last_block,
                    behind=self._trail_head_blocks,
                )
                await sleep(self._syncing_period)

    async def cleanup(self: ChainListener) -> None:
        """Stateless task, no cleanup necessary"""
        pass
