"""Ethereum JSON-RPC client

General interface over web3.py to expose commonly-used functions.

Examples:
    >>> rpc = RPC("https://my_rpc_url.com")

    >>> rpc.is_valid_address("0x123")
    False

    >>> rpc.get_keccak(["uint8"], [1])
    0x5fe7f977e71dba2ea1a68e21057beebb9be2ac30c6410aa38d4f3fbe41dcffd2

    >>> rpc.is_valid_address("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045")
    True

    >>> rpc.get_checksum_address("0xd8da6bf26964af9d7eed9e03e53415d37aa96045")
    0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045

    >>> rpc.get_event_hash("SubscriptionCreated(uint256)")
    0x04344ed7a67fec80c444d56ee1cee242f3f75b91fecc8dbce8890069c82eb48e

    >>> rpc.get_contract("0x...", [{ABI}])
    AsyncContract()

    >>> await rpc.get_chain_id()
    1234

    >>> rpc.get_nonce("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045")
    1

    >>> await rpc.get_block_by_number(1000)
    {"number": 1000, ...}

    >>> await rpc.get_head_block_number()
    1000

    >>> await rpc.get_tx_success("0x...")
    (True, True)

    >>> await rpc.get_event_logs({"address": 0x..., "fromBlock": 1})
    [{...}]

    >>> await rpc.send_transaction(SignedTransaction(...))
    0x6d0fda2e2168959f04ca777e66cf4b29cfebc53c0a071a0b7b559ea6c345d093
"""

from __future__ import annotations

import asyncio
from functools import cache
from typing import Any, Sequence, cast

import validators  # type: ignore
from async_lru import alru_cache
from eth_account.datastructures import SignedTransaction
from eth_typing import BlockNumber, ChecksumAddress, HexStr
from web3 import AsyncHTTPProvider, AsyncWeb3
from web3.contract.async_contract import AsyncContract
from web3.exceptions import TransactionNotFound
from web3.types import ABIElement, BlockData, FilterParams, LogReceipt, Nonce

from utils.logging import log


class RPC:
    """General interface over web3.py to expose commonly used functions.

    Public methods:
        is_valid_address: Checks if provided string is valid ETH address
        get_keccak: Returns Solidity Keccak256 encoded values
        get_checksum_address: Returns checksum-validated ETH address
        get_event_hash: Converts event name (str) to hashed event signature
        get_contract: Creates new AsyncContract object given contract params
        get_chain_id: Collects connected RPC provider's chain ID
        get_nonce: Returns nonce for an address
        get_block_by_number: Returns block data by block number
        get_head_block_number: Returns latest confirmed chain block number
        get_tx_success: Returns whether a tx was successfully processed on-chain
        get_event_logs: Returns event logs via eth_newFilter + eth_getFilterChanges
        send_transaction: Sends signed transaction

    Private attributes:
        _web3 (AsyncWeb3): Async web3.py client
    """

    def __init__(self: RPC, rpc_url: str) -> None:
        """Initializes new Ethereum-compatible JSON-RPC client

        Args:
            rpc_url (str): HTTP(s) RPC url

        Raises:
            ValueError: RPC URL is incorrectly formatted
        """

        # Validate URL is correctly formatted
        if not validators.url(rpc_url):
            raise ValueError("Incorrect RPC URL format")

        # Setup new Web3 HTTP provider w/ 10 minute timeout
        # Long timeout is useful for event polling, subscriptions
        provider = AsyncHTTPProvider(
            endpoint_uri=rpc_url, request_kwargs={"timeout": 60 * 10}
        )

        self._web3: AsyncWeb3 = AsyncWeb3(provider)
        log.info("Initialized RPC", url=rpc_url)

    @cache
    def is_valid_address(self: RPC, address: str) -> bool:
        """Checks if an address is a correctly formatted Ethereum address

        Args:
            address (str): address

        Returns:
            bool: true if correctly formatted, else false
        """
        return self._web3.is_address(address)

    def get_keccak(self: RPC, abi_types: list[str], values: list[Any]) -> bytes:
        """Returns Keccak256 encoded values

        Args:
            abi_types (list[Any]): Solidity ABI types
            values (list[Any]): values to encode

        Returns:
            bytes: keccak256 encoded response bytes
        """
        return cast(bytes, self._web3.solidity_keccak(abi_types, values))

    @cache
    def get_checksum_address(self: RPC, address: str) -> ChecksumAddress:
        """Returns a checksummed Ethereum address

        Args:
            address (str): stringified address

        Returns:
            ChecksumAddress: checksum-validated Ethereum address
        """
        return self._web3.to_checksum_address(address)

    @cache
    def get_event_hash(self: RPC, event_name: str) -> str:
        """Gets hashed event signature

        Args:
            event_name (str): emitted event name

        Returns:
            str: keccak-hashed event signature
        """
        return self._web3.keccak(text=event_name).hex()

    def get_contract(
        self: RPC, address: ChecksumAddress, abi: list[Any]
    ) -> AsyncContract:
        """Given contract details, creates new instance of AsyncContract object

        Args:
            address (ChecksumAddress): contract address
            abi (list[object]): contract ABI

        Returns:
            AsyncContract: async-callable contract object
        """
        return self._web3.eth.contract(
            address=address, abi=cast(Sequence[ABIElement], abi)
        )

    @alru_cache
    async def get_chain_id(self: RPC) -> int:
        """Collects connected RPC's chain ID

        Returns:
            int: chain ID
        """
        return await self._web3.eth.chain_id

    async def get_nonce(self: RPC, address: ChecksumAddress) -> Nonce:
        """Collects nonce for an address

        Args:
            address (ChecksumAddress): address to collect tx count

        Returns:
            Nonce: transaction count (nonce)
        """
        return await self._web3.eth.get_transaction_count(address)

    @alru_cache
    async def get_block_by_number(self: RPC, block_number: BlockNumber) -> BlockData:
        """Collects block data by block number

        Args:
            block_number (BlockNumber): block number

        Returns:
            BlockData: block data
        """
        return await self._web3.eth.get_block(block_number)

    async def get_head_block_number(self: RPC) -> BlockNumber:
        """Collects latest confirmed block number from chain

        Returns:
            BlockNumber: head block number
        """
        return await self._web3.eth.get_block_number()

    async def get_tx_success_with_retries(
        self: RPC, tx_hash: HexStr, retries: int = 10, sleep: float = 0.2
    ) -> tuple[bool, bool]:
        """Collects tx success status by tx_hash with retries

        Args:
            tx_hash (HexStr): transaction hash to check
            retries (int): number of retries
            sleep (float): sleep time between retries

        Returns:
            tuple[bool, bool]: (transaction found, transaction success status)
        """
        for i in range(retries):
            tx_found, tx_success = await self.get_tx_success(tx_hash)
            if tx_found:
                return (tx_found, tx_success)
            await asyncio.sleep(sleep)
        return (False, False)

    async def get_tx_success(self: RPC, tx_hash: HexStr) -> tuple[bool, bool]:
        """Collects tx success status by tx_hash

        Args:
            tx_hash (HexStr): transaction hash to check

        Returns:
            tuple[bool, bool]: (transaction found, transaction success status)
        """
        try:
            receipt = await self._web3.eth.get_transaction_receipt(tx_hash)
            return (True, receipt["status"] == 1)
        except TransactionNotFound:
            # In cases where tx has not yet been processed on-chain
            return (False, False)

    async def get_event_logs(self: RPC, params: FilterParams) -> list[LogReceipt]:
        """Given filter parameters, creates a new filter, and collects all event logs

        Args:
            params (FilterParams): filter parameters

        Returns:
            list[LogReceipt]: collected logs
        """

        # Create event filter at node
        event_filter = await self._web3.eth.filter(params)
        log.debug("Created event filter", id=event_filter.filter_id)

        # Collect filter logs
        logs = await event_filter.get_all_entries()
        log.debug("Collected event logs", count=len(logs))

        return logs

    async def send_transaction(self: RPC, tx: SignedTransaction) -> bytes:
        """Sends signed transaction. Bubble up error traceback

        Args:
            tx (SignedTransaction): signed transaction

        Returns:
            bytes: transaction hash
        """
        try:
            return await self._web3.eth.send_raw_transaction(tx.rawTransaction)
        except Exception as e:
            log.debug("rpc.send_transaction failed", error=str(e))
            raise
