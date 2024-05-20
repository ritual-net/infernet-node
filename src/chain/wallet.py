"""Wallet

On-chain transaction handling.
"""

from __future__ import annotations

import time
from typing import Optional, cast

from eth_account import Account
from eth_account.datastructures import SignedTransaction
from eth_typing import ChecksumAddress
from web3.exceptions import ContractCustomError
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
        register_node: Sends Coordinator.registerNode() tx
        activate_node: Sends Coordinator.activateNode() tx

    Private methods:
        _sign_tx_params: Signs TxParams from LocalAccount(private_key)
        _collect_nonce: Collects nonce from chain and updates local self._nonce
        _increment_nonce: Increments local self._nonce
        __send_tx_retries: Counterpart to _send_tx_retries
        _send_tx_retries: Attempts to send tx with N times

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
    ) -> None:
        """Initialize Wallet

        Args:
            rpc (RPC): RPC instance
            coordinator (Coordinator): Coodinator instance
            private_key (str): 0x-prefixed private key
            max_gas_limit (int): Wallet-enforced max gas limit per tx

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
        log.info("Initialized Wallet", address=self._account.address)

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

    async def deliver_compute(
        self: Wallet,
        subscription: Subscription,
        input: bytes,
        output: bytes,
        proof: bytes,
    ) -> Optional[bytes]:
        """Sends Coordinator.deliverCompute() tx, retrying failed txs thrice

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
            )
        )

        start = time.time()
        try:
            # while i < 3:
            #     # simulate transaction first
            #     try:
            #         await fn.call({"from": self._account.address})
            #     except ContractCustomError as e:
            #         log.warn(
            #             "Failed to simulate transaction, retrying after 0.5s", error=e
            #         )
            #         await sleep(0.5)
            #         i += 1
            await fn.call({"from": self._account.address})
        except ContractCustomError as e:
            duration = time.time() - start
            log.warn(
                "Failed to simulate transaction",
                error=e,
                duration=duration,
                subscription=subscription,
            )
            is_infernet_error(e, subscription)
            # log.info(
            #     "repeatedly failed to simulate transaction",
            #     error=e,
            #     duration=duration,
            #     subscription=subscription,
            # )
            # if is_infernet_error(e, subscription):
            #     # returning early since we know the error, no need to retry
            #     return None
            # log.error("Failed to simulate transaction", error=e)
            # return None

        await self._collect_nonce()

        coordinator_params = CoordinatorTxParams(
            nonce=self._nonce,
            sender=self.address,
            gas_limit=min(subscription.max_gas_limit, self._max_gas_limit),
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
        """Senjkk Coordinator.deliverComputeDelegatee() tx, retrying failed txs thrice

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
        tx_params = await self._coordinator.get_deliver_compute_delegatee_tx(
            data=CoordinatorDeliveryParams(
                subscription=subscription,
                interval=subscription.interval,
                input=input,
                output=output,
                proof=proof,
            ),
            tx_params=CoordinatorTxParams(
                nonce=self._nonce,
                sender=self.address,
                gas_limit=min(subscription.max_gas_limit, self._max_gas_limit),
            ),
            signature=signature,
        )

        # Sign coordinator tx
        signed_tx = self._sign_tx_params(tx_params)

        # Send tx, retrying submission thrice
        return await self._send_tx_retries(signed_tx, 3)

    async def register_node(self: Wallet) -> Optional[bytes]:
        """Sends Coordinator.registerNode() tx, retrying failed txs thrice

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

        # Build registration tx
        tx_params = await self._coordinator.get_node_registration_tx(
            node_address=self.address,
            tx=CoordinatorTxParams(
                nonce=self._nonce,
                sender=self.address,
                gas_limit=min(100000, self._max_gas_limit),
            ),
        )

        # Sign tx
        signed_tx = self._sign_tx_params(tx_params)

        # Send tx
        return await self._send_tx_retries(signed_tx, 3)

    async def activate_node(self: Wallet) -> Optional[bytes]:
        """Sends Coordinator.activateNode() tx, retrying failed txs thrice

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

        # Build registration tx
        tx_params = await self._coordinator.get_node_activation_tx(
            tx=CoordinatorTxParams(
                nonce=self._nonce,
                sender=self.address,
                gas_limit=min(100000, self._max_gas_limit),
            )
        )

        # Sign tx
        signed_tx = self._sign_tx_params(tx_params)

        # Send tx
        return await self._send_tx_retries(signed_tx, 3)
