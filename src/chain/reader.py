"""Reader

Off-chain interface to the Reader Contract.

Examples:
    >>> rpc = RPC("https://my_rpc_url.com")
    >>> reader = Reader(rpc, "0x...", container_lookup=container_lookup)
    >>> reader.read_subscription_batch(start_id, end_id, block_number)
    >>> reader.read_redundancy_count_batch(ids, intervals, block_number)
"""

from __future__ import annotations

from typing import List, cast

from eth_typing import BlockNumber

from chain.container_lookup import ContainerLookup
from chain.rpc import RPC
from shared.subscription import Subscription
from utils.constants import READER_ABI
from utils.logging import log


class Reader:
    """Off-chain interface to Reader
        (Infernet Coordinator utility contract for Subscription reading).

    Public methods:
        read_subscription_batch: Returns Subscriptions from Coordinator in batch
            from start_id to end_id
        read_redundancy_count_batch: Given Subscription ids and intervals
            return redundancy count of (subscription, interval)-pair

    Private attributes:
        _rpc (RPC): RPC instance
        _contract (AsyncContract): Reader AsyncContract instance
    """

    def __init__(
        self: Reader,
        rpc: RPC,
        reader_address: str,
        container_lookup: ContainerLookup,
    ) -> None:
        """Initializes new Reader

        Args:
            rpc (RPC): RPC instance
            reader_address (str): Reader contract address
            container_lookup (ContainerLookup): ContainerLookup instance
        Raises:
            ValueError: Reader address is incorrectly formatted
        """

        # Check if Reader address is a valid address
        if not rpc.is_valid_address(reader_address):
            raise ValueError("Reader address is incorrectly formatted")

        self._rpc = rpc
        self._lookup = container_lookup

        # Setup Reader contract
        self._checksum_address = rpc.get_checksum_address(reader_address)
        self._contract = rpc.get_contract(
            address=self._checksum_address,
            abi=READER_ABI,
        )
        log.debug("Initialized Reader", address=self._checksum_address)

    async def read_subscription_batch(
        self: Reader, start_id: int, end_id: int, block_number: BlockNumber
    ) -> List[Subscription]:
        """Reads Subscriptions from Coordinator in batch

        Args:
            start_id (int): starting id of batch
            end_id (int): last id of batch
            block_number(BlockNumber): the block number to query at
        Returns:
            List[Subscription]: Subscriptions object list
        """

        subscriptions_data = await self._contract.functions.readSubscriptionBatch(
            start_id, end_id
        ).call(block_identifier=block_number)
        subscriptions = []
        for i, sub in enumerate(subscriptions_data):
            subscription_id = (
                start_id + i
            )  # Assuming IDs are in increasing order starting from start_id
            subscription = Subscription(subscription_id, self._lookup, *sub)
            subscriptions.append(subscription)
        return subscriptions

    async def read_redundancy_count_batch(
        self: Reader, ids: List[int], intervals: List[int], block_number: BlockNumber
    ) -> List[int]:
        """Given Subscription ids and intervals,
            collects redundancy count of (subscription, interval)-pair

        Args:
            ids (List[int]): Subscription ids
            intervals (List[int]): intervals

        Returns:
            count(List[int]): redundancy count list
        """
        return cast(
            List[int],
            await self._contract.functions.readRedundancyCountBatch(
                ids, intervals
            ).call(block_identifier=block_number),
        )
