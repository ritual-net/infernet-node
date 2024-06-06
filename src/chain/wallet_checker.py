from __future__ import annotations

from typing import Optional, Tuple, cast

import structlog
from eth_typing import ChecksumAddress

from chain.registry import Registry
from chain.rpc import RPC
from shared import Subscription
from utils.config import ConfigContainer
from utils.constants import ERC20_ABI, WALLET_FACTORY_ABI, ZERO_ADDRESS

log = structlog.getLogger(__name__)


class WalletChecker:
    """A class to check wallet validity and balance.

    A wallet is valid if it is instantiated through Infernet's `WalletFactory` contract.

    Public methods:
        is_valid_wallet: Check if a wallet is valid.
        has_enough_balance: Check if a wallet has enough balance.
        matches_payment_requirements: Check if a subscription matches payment
        requirements.

    Private methods:
        _erc20_balance: Get the ERC20 balance of a wallet.

    Private attributes:
        _rpc: An instance of the RPC class.
        _registry: An instance of the Registry class.
        _accepted_payments: A dictionary of accepted payments for each container.
    """

    def __init__(
        self: WalletChecker,
        rpc: RPC,
        registry: Registry,
        container_configs: list[ConfigContainer],
        payment_address: Optional[ChecksumAddress] = None,
    ):
        """
        Args:
            rpc (RPC): An instance of the RPC class.
            registry (Registry): An instance of the Registry class.
            container_configs (list[ConfigContainer]): A list of container
            configurations.
            payment_address (Optional[ChecksumAddress], optional): The payment address of
                the node.
        """
        self._rpc = rpc
        self._registry = registry
        self._payment_address: Optional[ChecksumAddress] = payment_address
        self._accepted_payments = {
            container["id"]: container.get("accepted_payments") or {}
            for container in container_configs
        }

    async def is_valid_wallet(self: WalletChecker, address: ChecksumAddress) -> bool:
        """
        Check if a wallet is valid. Uses the `isValidWallet` function of the
        `WalletFactory` contract.

        Args:
            address (ChecksumAddress): The address of the wallet.

        Returns:
            bool: True if the wallet is valid, False otherwise.
        """
        return cast(
            bool,
            await self._rpc.get_contract(
                self._registry.wallet_factory, WALLET_FACTORY_ABI
            )
            .functions.isValidWallet(address)
            .call(),
        )

    async def _erc20_balance(
        self: WalletChecker, address: ChecksumAddress, token: ChecksumAddress
    ) -> int:
        """
        Get the ERC20 balance of a wallet.

        Args:
            address (ChecksumAddress): The address of the wallet.
            token (ChecksumAddress): The address of the ERC20 token.

        Returns:
            int: The ERC20 balance of the wallet.
        """
        return cast(
            int,
            await self._rpc.get_contract(token, ERC20_ABI)
            .functions.balanceOf(address)
            .call(),
        )

    async def has_enough_balance(
        self: WalletChecker,
        address: ChecksumAddress,
        token: ChecksumAddress,
        amount: int,
    ) -> Tuple[bool, int]:
        """
        Check if a wallet has enough balance.

        Args:
            address (ChecksumAddress): The address of the wallet.
            token (ChecksumAddress): The address of the ERC20 token.
            amount (int): The amount to check.

        Returns:
            Tuple[bool, int]: A tuple containing a boolean indicating if the wallet has
            enough balance and the current balance of the wallet.
        """
        if token == ZERO_ADDRESS:
            balance = await self._rpc.get_balance(address)
        else:
            balance = await self._erc20_balance(address, token)
        return balance >= amount, balance

    def matches_payment_requirements(self: WalletChecker, sub: Subscription) -> bool:
        """
        Check if a subscription matches payment requirements.
        1. Ensure that payment address is provided.
        2. Check that the subscription matches the payment requirements.

        Args:
            sub (Subscription): The subscription to check.

        Returns:
            bool: True if the subscription matches payment requirements, False otherwise.
        """
        skip_banner = f"Skipping subscription: {sub.id}"

        if self._payment_address is None and sub.provides_payment:
            log.info(
                f"{skip_banner}: No payment address provided for the node",
                sub_id=sub.id,
            )
            return False

        for container in sub.containers:
            if not self._accepted_payments[container]:
                # no payment requirements for this container, it allows everything
                continue

            if sub.payment_token not in self._accepted_payments[container]:
                log.info(
                    f"{skip_banner}: Token {sub.payment_token} not "
                    f"accepted for container {container}.",
                    sub_id=sub.id,
                    token=sub.payment_token,
                    container=container,
                    accepted_tokens=list(self._accepted_payments[container].keys()),
                )
                # doesn't match, but requires payment
                return False

        # minimum required payment for the subscription is the sum of the payment
        # requirements of each container
        min_payment = sum(
            self._accepted_payments[container].get(sub.payment_token, 0)
            for container in sub.containers
        )

        if sub.payment_amount < min_payment:
            log.info(
                f"{skip_banner}: Token {sub.payment_token} below "
                f"minimum payment requirements",
                sub_id=sub.id,
                token=sub.payment_token,
                sub_amount=sub.payment_amount,
                min_amount=min_payment,
            )
            return False

        return True
