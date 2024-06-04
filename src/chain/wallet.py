"""Wallet

On-chain transaction handling.
"""

from __future__ import annotations

import asyncio
from typing import Optional, cast

from eth_account import Account
from eth_typing import ChecksumAddress
from reretry import retry  # type: ignore
from web3.contract.async_contract import AsyncContractFunction
from web3.exceptions import ContractCustomError, ContractLogicError

from chain.coordinator import (
    Coordinator,
    CoordinatorDeliveryParams,
    CoordinatorSignatureParams,
)
from chain.errors import raise_if_infernet_error
from chain.rpc import RPC
from shared.subscription import Subscription
from utils.logging import log


class Wallet:
    """On-chain transaction handling.

    Public methods:
        deliver_compute: Sends Coordinator.deliverCompute() tx
        deliver_compute_delegatee: Sends Coordinator.deliverComputeDelegatee() tx

    Private methods:
        _simulate_transaction: Simulates function call and checks if it passes, bubbles
            up errors if not

    Private attributes:
        _rpc (RPC): RPC instance
        _coordinator (Coordinator): Coordinator instance
        _max_gas_limit (int): Wallet-enforced max gas limit per tx
        _account (Account): Account initialized from private key
        _allowed_sim_errors (Optional[list[str]]): List of allowed error messages to
            ignore when simulating transactions. Checks for inclusion in error
            message, case-insensitive. i.e. ["bad input"] will match
            error message: "Contract reverted with error: Bad input.
        _payment_address (ChecksumAddress): Node's payment wallet address.
        _tx_lock (asyncio.Lock): Lock to prevent race conditions when web3py is sending
            multiple transactions at once.

    Public attributes:
        payment_address (ChecksumAddress): Node's payment wallet address
        address (ChecksumAddress): Wallet address
    """

    def __init__(
        self: Wallet,
        rpc: RPC,
        coordinator: Coordinator,
        private_key: str,
        max_gas_limit: int,
        payment_address: str,
        allowed_sim_errors: Optional[list[str]],
    ) -> None:
        """Initialize Wallet

        Args:
            rpc (RPC): RPC instance
            coordinator (Coordinator): Coodinator instance
            private_key (str): 0x-prefixed private key
            max_gas_limit (int): Wallet-enforced max gas limit per tx
            allowed_sim_errors (Optional[list[str]]): List of allowed error messages to
                ignore when simulating transactions. Checks for inclusion in error
                message, case-insensitive. i.e. ["bad input"] will match
                error message: "Contract reverted with error: Bad input.

        Raises:
            ValueError: Throws if private key is not 0x-prefixed
        """

        # Ensure private key is correct format
        if not private_key.startswith("0x"):
            raise ValueError("Private key must be 0x-prefixed")

        self._rpc = rpc
        self._coordinator = coordinator
        self._max_gas_limit = max_gas_limit

        # Initialize account
        self._account = Account.from_key(private_key)
        self._allowed_sim_errors = allowed_sim_errors or []
        self._payment_address = payment_address
        self._tx_lock = asyncio.Lock()

        log.info("Initialized Wallet", address=self._account.address)

    @property
    def payment_address(self: Wallet) -> ChecksumAddress:
        """Returns Node's payment wallet address

        Returns:
            ChecksumAddress: node's payment wallet address
        """
        return cast(ChecksumAddress, self._payment_address)

    @property
    def address(self: Wallet) -> ChecksumAddress:
        """Returns wallet address

        Returns:
            ChecksumAddress: wallet address
        """
        return cast(ChecksumAddress, self._account.address)

    async def _simulate_transaction(
        self: Wallet, fn: AsyncContractFunction, subscription: Subscription
    ) -> bool:
        """Simulates the function call, retrying 3 times with a delay of 0.5 and
        raises if there's errors.
        * Simulation errors may be bypassed if they are in the `allowed_sim_errors` list.
            In which case, the simulation is considered to have passed.
        * For infernet-specific errors, more verbose logging is provided, and an
            `InfernetError` is raised.
        * The rest of the errors bubble up as is.

        Args:
            fn (AsyncContractFunction): Function to simulate
            subscription (Subscription): Subscription to check

        Returns:
            bool: True if simulation was bypassed due to allowed errors, False otherwise

        Raises:
            ContractCustomError: Raises if contract-specific error occurs
            ContractLogicError: Raises if contract logic error occurs
            InfernetError: Raises if infernet-specific error occurs
        """
        try:

            @retry(
                exceptions=(ContractCustomError, ContractLogicError), tries=3, delay=0.5
            )  # type: ignore
            async def _sim() -> bool:
                try:
                    await fn.call({"from": self._account.address})
                except Exception as e:
                    for err in self._allowed_sim_errors:
                        if err.lower() in str(e).lower():
                            return True
                    raise e
                return False

            return cast(bool, await _sim())
        except ContractCustomError as e:
            raise_if_infernet_error(e, subscription)
            log.error(
                "Failed to simulate transaction",
                error=e,
                subscription=subscription,
            )
            raise e
        except ContractLogicError as e:
            log.warn(
                "Contract logic error while simulating",
                error=e,
                subscription=subscription,
            )
            raise e

    async def deliver_compute(
        self: Wallet,
        subscription: Subscription,
        input: bytes,
        output: bytes,
        proof: bytes,
        simulate_only: bool = False,
    ) -> bytes:
        """Sends Coordinator.deliverCompute() tx.
        Transactions are first simulated using `.call()`. If simulation fails, the
        error is bubbled up. This is to prevent submission of invalid transactions that
        result in the user's gas being wasted.

        If a simulation passes & transaction still fails, it will be retried thrice.

        Args:
            subscription (Subscription): Subscription to respond to
            input (bytes): optional response input
            output (bytes): optional response output
            proof (bytes): optional response proof
            simulate_only (bool): if True, only simulate the transaction & return after

        Raises:
            RuntimeError: If can't collect nonce to send tx
            InfernetError: If infernet-specific error occurs during simulation
            ContractCustomError: If contract-specific error occurs during
                simulation
            ContractLogicError: If contract logic error occurs during simulation

        Returns:
            bytes: transaction hash
        """

        # Build Coordinator tx
        fn = self._coordinator.get_deliver_compute_tx_contract_function(
            data=CoordinatorDeliveryParams(
                subscription=subscription,
                interval=subscription.interval,
                input=input,
                output=output,
                proof=proof,
                node_wallet=self.payment_address,
            )
        )

        skipped = await self._simulate_transaction(fn, subscription)
        if simulate_only:
            return b""

        async with self._tx_lock:
            # By default, gas gets estimated (which includes a simulation call)
            # if we're purposefully skipping an error in simulation, we need to set gas
            # limit manually
            if skipped:
                return await fn.transact({"gas": self._max_gas_limit})
            else:
                return await fn.transact()

    async def deliver_compute_delegatee(
        self: Wallet,
        subscription: Subscription,
        signature: CoordinatorSignatureParams,
        input: bytes,
        output: bytes,
        proof: bytes,
        simulate_only: bool = False,
    ) -> bytes:
        """Send Coordinator.deliverComputeDelegatee() tx.
        Transactions are first simulated using `.call()` to prevent submission of invalid
        transactions that result in the user's gas being wasted.

        If a simulation passes & transaction still fails, it will be retried thrice.

        Args:
            subscription (Subscription): Subscription to respond to
            signature (CoordinatorSignatureParams): signed delegatee permission
            input (bytes): optional response input
            output (bytes): optional response output
            proof (bytes): optional response proof
            simulate_only (bool): if True, only simulate the transaction & return after
                simulating

        Returns:
            bytes: transaction hash

        Raises:
            RuntimeError: If can't collect nonce to send tx
            InfernetError: If infernet-specific error occurs during simulation
            ContractCustomError: If contract-specific error occurs during
                simulation
            ContractLogicError: If contract logic error occurs during simulation
        """

        # Build Coordinator tx
        fn = self._coordinator.get_deliver_compute_delegatee_tx_contract_function(
            data=CoordinatorDeliveryParams(
                subscription=subscription,
                interval=subscription.interval,
                input=input,
                output=output,
                proof=proof,
                node_wallet=self.payment_address,
            ),
            signature=signature,
        )

        skipped = await self._simulate_transaction(fn, subscription)

        if simulate_only:
            return b""

        async with self._tx_lock:
            # By default, gas gets estimated (which includes a simulation call)
            # if we're purposefully skipping an error in simulation, we need to set gas
            # limit manually
            if skipped:
                return await fn.transact({"gas": self._max_gas_limit})
            else:
                return await fn.transact()
