from __future__ import annotations

from typing import Optional

import structlog
from eth_typing import ChecksumAddress
from web3 import Web3
from web3.contract.async_contract import AsyncContract

from chain.rpc import RPC
from utils.constants import PAYMENT_WALLET_ABI

log = structlog.get_logger()


class PaymentWallet:
    """
    Class to interact with an Infernet `Wallet` contract. Used by `ChainProcessor` to
    escrow tokens whenever a subscription requires a proof to be generated.

    Public Methods:
        - get_owner: Get the owner of the `PaymentWallet` contract.
        - approve: Approve a spender to spend a certain amount of tokens.

    Attributes:
        - address: The address of the `PaymentWallet` contract.
    """

    def __init__(self: PaymentWallet, address: Optional[ChecksumAddress], rpc: RPC):
        self._address = address
        self._rpc = rpc

    @property
    def address(self: PaymentWallet) -> ChecksumAddress:
        """
        The address of the `PaymentWallet` contract.

        Raises:
            ValueError: If the `PaymentWallet` has no address.

        Returns:
            ChecksumAddress: The address of the `PaymentWallet` contract.
        """
        if self._address is None:
            raise ValueError("PaymentWallet has no address")
        return self._address

    def _get_contract(self: PaymentWallet) -> AsyncContract:
        """
        Get the `PaymentWallet` contract.

        Returns:
            AsyncContract: The `PaymentWallet` contract.
        """
        return self._rpc.get_contract(
            address=self.address,
            abi=PAYMENT_WALLET_ABI,
        )

    async def get_owner(self: PaymentWallet) -> ChecksumAddress:
        """
        Get the owner of the `PaymentWallet` contract.

        Returns:
            ChecksumAddress: The owner of the `PaymentWallet` contract.
        """
        return Web3.to_checksum_address(
            await self._get_contract().functions.owner().call()
        )

    async def approve(
        self: PaymentWallet,
        spender: ChecksumAddress,
        token: ChecksumAddress,
        amount: int,
    ) -> None:
        """
        Approve a spender to spend a certain amount of tokens.

        Args:
            spender (ChecksumAddress): The address of the spender.
            token (ChecksumAddress): The address of the token.
            amount (int): The amount of tokens to approve.

        Raises:
            AssertionError: If the allowance is not equal to the amount set.

        """
        _contract = self._get_contract()
        assert await _contract.functions.owner().call() == self._rpc.account
        tx = await _contract.functions.approve(spender, token, amount).transact()
        await self._rpc.web3.eth.wait_for_transaction_receipt(tx)
        allowance = await _contract.functions.allowance(spender, token).call()
        log.info(
            f"allowance: {allowance}, amount: {amount}, {allowance == amount}",
            spender=spender,
            token=token,
            allowance=allowance,
            amount=amount,
        )
        # assert allowance == amount
