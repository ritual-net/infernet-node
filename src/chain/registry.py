from __future__ import annotations

import structlog
from eth_typing import ChecksumAddress
from web3 import Web3

from chain.rpc import RPC
from utils.constants import REGISTRY_ABI

log = structlog.get_logger(__name__)


class NotInitializedError(Exception):
    """
    Raised when attempting to access a contract address from an uninitialized registry.
    """

    def __str__(self: NotInitializedError) -> str:
        return (
            "Registry class has not been populated with contract addresses, please "
            "call populate_addresses() before accessing the contract addresses."
        )


class Registry:
    """Off-chain interface to the infernet registry contract.

    Public methods:
        populate_addresses: Reads the addresses of the coordinator, reader, and wallet
            factory from the registry contract & stores them in the instance.
        coordinator: Returns the address of the coordinator contract.
        reader: Returns the address of the reader contract.
        wallet_factory: Returns the address of the wallet factory contract.

    Private attributes:
        _reader: Address of the reader contract.
        _coordinator: Address of the coordinator contract.
        _wallet_factory: Address of the wallet factory contract.
        _rpc: RPC instance.
        _contract: Web3 contract instance.
    """

    def __init__(self: Registry, rpc: RPC, address: ChecksumAddress):
        """Initializes the registry instance.

        Args:
            rpc: RPC instance.
            address: Address of the registry contract.
        """
        self._reader = None
        self._coordinator = None
        self._wallet_factory = None
        self._rpc = rpc
        self._contract = self._rpc.get_contract(address, REGISTRY_ABI)

    async def populate_addresses(self: Registry) -> None:
        """
        Populates the addresses of the coordinator, reader, and wallet factory contracts
        from the registry contract.
        """
        log.info("Populating addresses for registry")
        self._coordinator = await self._contract.functions.COORDINATOR().call()
        self._reader = await self._contract.functions.READER().call()
        self._wallet_factory = await self._contract.functions.WALLET_FACTORY().call()
        log.info(
            "found addresses",
            coordinator=self._coordinator,
            reader=self._reader,
            wallet_factory=self._wallet_factory,
        )

    @property
    def coordinator(self: Registry) -> ChecksumAddress:
        """
        Returns the address of the coordinator contract.

        Returns:
            Address of the coordinator contract.

        Raises:
            NotInitializedError: If the registry has not been initialized.
        """
        if self._coordinator is None:
            raise NotInitializedError()

        return Web3.to_checksum_address(self._coordinator)

    @property
    def reader(self: Registry) -> ChecksumAddress:
        """
        Returns the address of the reader contract.

        Returns:
            Address of the reader contract.

        Raises:
            NotInitializedError: If the registry has not been initialized.
        """
        if self._reader is None:
            raise NotInitializedError()

        return Web3.to_checksum_address(self._reader)

    @property
    def wallet_factory(self: Registry) -> ChecksumAddress:
        """
        Returns the address of the wallet factory contract.

        Returns:
            Address of the wallet factory contract.

        Raises:
            NotInitializedError: If the registry has not been initialized.
        """
        if self._wallet_factory is None:
            raise NotInitializedError()

        return Web3.to_checksum_address(self._wallet_factory)
