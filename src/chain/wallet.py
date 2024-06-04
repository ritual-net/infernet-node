"""Wallet

On-chain transaction handling.
"""

from __future__ import annotations

from typing import Optional, cast

from eth_account import Account
from eth_account.datastructures import SignedTransaction
from eth_typing import ChecksumAddress
from reretry import retry  # type: ignore
from web3.contract.async_contract import AsyncContractFunction
from web3.exceptions import ContractCustomError, ContractLogicError
from web3.types import Nonce, TxParams

from chain.coordinator import (
    Coordinator,
    CoordinatorDeliveryParams,
    CoordinatorSignatureParams,
    CoordinatorTxParams,
)
from chain.errors import is_infernet_error
from chain.rpc import RPC
from shared.subscription import Subscription
from utils.logging import log


class Wallet:
    """On-chain transaction handling.

    Public methods:
        address: Returns wallet address
        deliver_compute: Sends Coordinator.deliverCompute() tx
        deliver_compute_delegatee: Sends Coordinator.deliverComputeDelegatee() tx

    Private methods:
        _sign_tx_params: Signs TxParams from LocalAccount(private_key)
        _collect_nonce: Collects nonce from chain and updates local self._nonce
        _increment_nonce: Increments local self._nonce
        __send_tx_retries: Counterpart to _send_tx_retries
        _send_tx_retries: Attempts to send tx with N times
        _simulation_passed: Simulates function call and checks if it passes

    Private attributes:
        _rpc (RPC): RPC instance
        _coordinator (Coordinator): Coordinator instance
        _max_gas_limit (int): Wallet-enforced max gas limit per tx
        _account (Account): Account initialized from private key
        _nonce (Optional[int]): Account nonce
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
        self._nonce: Optional[int] = None
        self._allowed_sim_errors = allowed_sim_errors or []
        self._payment_address = payment_address

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

    def _sign_tx_params(self: Wallet, tx_params: TxParams) -> SignedTransaction:
        """Signs tx_params with account, generating a signed raw transaction

        Args:
            tx_params (TxParams): transaction to sign

        Returns:
            SignedTransaction: signed raw transaction
        """
        return cast(SignedTransaction, self._account.sign_transaction(tx_params))

    async def _collect_nonce(self: Wallet) -> None:
        """Collects nonce from chain, stores in self._nonce"""
        nonce = await self._rpc.get_nonce(self.address)
        self._nonce = nonce

    def _increment_nonce(self: Wallet) -> None:
        """Increments self._nonce by 1, if exists

        Raises:
            RuntimeError: Thrown if nonce is not yet initialized
        """

        # Throw if nonce is not incrementable
        if self._nonce is None:
            raise RuntimeError("Cannot increment None nonce")

        # Increment nonce
        self._nonce += 1

    async def __send_tx_retries(
        self: Wallet, tx: SignedTransaction, retries: int, current_try: int
    ) -> Optional[bytes]:
        """Internal counterpart to _send_tx_receipts with current_try counter

        Args:
            tx (SignedTransaction): signed transaction
            retries (int): number of times to retry failed tx
            current_try (int): current attempt count

        Raises:
            RuntimeError: Throws if maximum retries is hit without success

        Returns:
            Optional[bytes]: transaction hash
        """
        err = ""

        try:
            # Send transaction
            return await self._rpc.send_transaction(tx)
        except ValueError as e:
            err = str(e)
            # Handle some exceptions
            # Nonce mismatch (most common)
            if len(e.args) > 0 and e.args[0]["message"].startswith("nonce"):
                # Re-collect nonce
                await self._collect_nonce()

        # If maximum retries hit, throw error
        if retries == current_try:
            raise RuntimeError(f"Failed sending tx: {err}")

        # Retry transaction
        return await self.__send_tx_retries(tx, retries, current_try + 1)

    async def _send_tx_retries(
        self: Wallet, tx: SignedTransaction, retries: int
    ) -> Optional[bytes]:
        """Trys to send tx `retries` times until successful or RuntimeError

        Args:
            tx (SignedTransaction): signed transaction
            retries (int): number of attempts to make to send tx

        Returns:
            Optional[bytes]: transaction hash
        """
        return await self.__send_tx_retries(tx, retries, 0)

    async def _simulation_passed(
        self: Wallet, fn: AsyncContractFunction, subscription: Subscription
    ) -> bool:
        """Simulate the function call and check if it passes.
        * In case of a failed simulation, it retries 3 times, with a delay of 0.5
            seconds.
        * Simulation errors may be bypassed if they are in the `allowed_sim_errors` list.
            In which case, the simulation is considered to have passed.
        * For infernet-specific errors, more verbose logging is provided.
        * Handles ContractCustomError and ContractLogicError exceptions, for other
            exceptions, it bubbles up.

        Args:
            fn (AsyncContractFunction): Function to simulate
            subscription (Subscription): Subscription to check

        Returns:
            bool: True if simulation passed, False otherwise
        """
        try:

            @retry(
                exceptions=(ContractCustomError, ContractLogicError), tries=3, delay=0.5
            )  # type: ignore
            async def _sim() -> None:
                try:
                    await fn.call({"from": self._account.address})
                except Exception as e:
                    for err in self._allowed_sim_errors:
                        if err.lower() in str(e).lower():
                            return
                    raise e

            await _sim()
            return True
        except ContractCustomError as e:
            if not is_infernet_error(e, subscription):
                log.error(
                    "Failed to simulate transaction",
                    error=e,
                    subscription=subscription,
                )
            return False
        except ContractLogicError as e:
            log.warn(
                "Contract logic error while simulating",
                error=e,
                subscription=subscription,
            )
            return False

    async def deliver_compute(
        self: Wallet,
        subscription: Subscription,
        input: bytes,
        output: bytes,
        proof: bytes,
    ) -> Optional[bytes]:
        """Sends Coordinator.deliverCompute() tx.
        Transactions are first simulated using `.call()` to prevent submission of invalid
        transactions that result in the user's gas being wasted.

        If a simulation passes & transaction still fails, it will be retried thrice.

        Args:
            subscription (Subscription): Subscription to respond to
            input (bytes): optional response input
            output (bytes): optional response output
            proof (bytes): optional response proof

        Raises:
            RuntimeError: Throws if can't collect nonce to send tx

        Returns:
            Optional[bytes]: transaction hash
        """

        if self._nonce is None:
            # Collect nonce if doesn't exist
            await self._collect_nonce()
        else:
            # Else, increment nonce
            self._increment_nonce()

        # Throw if still unsuccessful in collecting nonce
        if self._nonce is None:
            raise RuntimeError("Could not collect nonce")

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

        if not await self._simulation_passed(fn, subscription):
            return None

        await self._collect_nonce()

        coordinator_params = CoordinatorTxParams(
            nonce=self._nonce,
            sender=self.address,
            gas_limit=self._max_gas_limit,
        )

        tx = await fn.build_transaction(
            {
                "nonce": cast(Nonce, coordinator_params.nonce),
                "from": coordinator_params.sender,
                "gas": coordinator_params.gas_limit,
            }
        )

        # build & sign the transaction
        signed_tx = self._sign_tx_params(tx)

        # Send tx, retrying submission thrice
        return await self._send_tx_retries(signed_tx, 3)

    async def deliver_compute_delegatee(
        self: Wallet,
        subscription: Subscription,
        signature: CoordinatorSignatureParams,
        input: bytes,
        output: bytes,
        proof: bytes,
    ) -> Optional[bytes]:
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

        Raises:
            RuntimeError: Throws if can't collect nonce to send tx

        Returns:
            Optional[bytes]: transaction hash
        """

        if self._nonce is None:
            # Collect nonce if doesn't exist
            await self._collect_nonce()
        else:
            # Else, increment nonce
            self._increment_nonce()

        # Throw if still unsuccessful in collecting nonce
        if self._nonce is None:
            raise RuntimeError("Could not collect nonce")

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

        if not await self._simulation_passed(fn, subscription):
            # if simulation of the transaction fails, we'll skip sending it.
            return None

        await self._collect_nonce()

        coordinator_params = CoordinatorTxParams(
            nonce=self._nonce, sender=self.address, gas_limit=self._max_gas_limit
        )

        # building the raw unsigned transaction
        tx = await fn.build_transaction(
            {
                "nonce": cast(Nonce, coordinator_params.nonce),
                "from": coordinator_params.sender,
                "gas": coordinator_params.gas_limit,
            }
        )

        # Sign coordinator tx
        signed_tx = self._sign_tx_params(tx)

        # Send tx, retrying submission thrice
        return await self._send_tx_retries(signed_tx, 3)
