from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network
from typing import Any, Dict, Union, cast

from chain.container_lookup import ContainerLookup
from chain.wallet_checker import WalletChecker
from shared.message import (
    DelegatedSubscriptionMessage,
    FilteredMessage,
    GuardianError,
    MessageType,
    OffchainJobMessage,
    PrefilterMessage,
    SubscriptionCreatedMessage,
)
from utils.config import ConfigContainer
from utils.logging import log


@dataclass(frozen=True)
class ContainerRestrictions:
    """Container restrictions"""

    allowed_ips: list[Union[IPv4Network, IPv6Network]]
    allowed_addresses: list[str]
    allowed_delegate_addresses: list[str]
    external: bool
    generates_proofs: bool


class Guardian:
    """Filters job requests based on container restrictions

    Both off-chain and on-chain job requests are filtered based on sanity checks and
    container-level restrictions, such as origin IP address, whether a matches the
    payment requirements, and allowed chain addresses. If a message fails filtering, a
    GuardianError is returned. Otherwise, the message is returned for processing.

    Attributes:
        _container_lookup (ContainerLookup): Container lookup, used for
            deserialization of subscriptions.
        _restrictions (dict[str, ContainerRestrictions]): Container restrictions
        _chain_enabled (bool): Is chain module enabled?
        _wallet_checker (WalletChecker): Wallet checker, used for filtering
            subscriptions that don't match payment requirements

    Methods:
        process_message: Parses and filters message

    Private Methods:
        _is_external: Is container external
        _is_allowed_ip: Is IP address allowed for container
        _is_allowed_address: Is chain address allowed for container
        _error: Create error message for given message id
        _process_offchain_message: Filters off-chain job messages
        _process_delegated_subscription_message: Filters delegated Subscription messages
        _process_coordinator_created_message: Filters on-chain Coordinator subscription
            creation messages
    """

    def __init__(
        self: Guardian,
        configs: list[ConfigContainer],
        chain_enabled: bool,
        container_lookup: ContainerLookup,
        wallet_checker: WalletChecker,
    ) -> None:
        """Initialize Guardian

        Args:
            configs (list[ConfigContainer]): Container configurations
            chain_enabled (bool): Is chain module enabled?
            container_lookup (ContainerLookup): Container lookup, used for reverse hash
                lookup of subscriptions' `containers` field.
            wallet_checker (WalletChecker): Wallet checker, used for filtering
                subscriptions that don't match payment requirements
        """
        super().__init__()

        self._chain_enabled = chain_enabled
        self._container_lookup: ContainerLookup = container_lookup
        self._wallet_checker: WalletChecker = wallet_checker

        # Initialize container restrictions
        self._restrictions: dict[str, ContainerRestrictions] = {
            container["id"]: ContainerRestrictions(
                allowed_ips=[
                    ip_network(ip, strict=False) for ip in container["allowed_ips"]
                ],
                allowed_addresses=list(map(str.lower, container["allowed_addresses"])),
                allowed_delegate_addresses=list(
                    map(str.lower, container["allowed_delegate_addresses"])
                ),
                external=container["external"],
                generates_proofs=cast(Dict[str, bool], container).get(
                    "generates_proofs", False
                ),
            )
            for container in configs
        }

        log.info("Initialized Guardian")

    @property
    def restrictions(self: Guardian) -> dict[str, Any]:
        """Returns container restrictions as a dictionary"""
        return {
            container: asdict(self._restrictions[container])
            for container in self._restrictions
        }

    def _is_external(self: Guardian, container: str) -> bool:
        """Is container external

        Args:
            container (str): Container ID

        Returns:
            bool: True if container is external, False otherwise
        """
        return self._restrictions[container].external

    def _generates_proof(self: Guardian, container: str) -> bool:
        """Does container generate proof

        Args:
            container (str): Container ID

        Returns:
            bool: True if container generates proof, False otherwise
        """
        return self._restrictions[container].generates_proofs

    def _is_allowed_ip(self: Guardian, container: str, address: str) -> bool:
        """Is IP address allowed for container

        Args:
            container (str): Container ID
            address (str): IP address

        Returns:
            bool: True if container is allowed for given address, False otherwise
        """

        # If no specified IPs, allow all
        if len(self._restrictions[container].allowed_ips) == 0:
            return True

        return any(
            ip_address(address) in network
            for network in self._restrictions[container].allowed_ips
        )

    def _is_allowed_address(
        self: Guardian, container: str, address: str, onchain: bool
    ) -> bool:
        """Is chain address allowed for container

        Args:
            container (str): container ID
            address (str): chain address
            onchain (bool): if message originating on-chain or off-chain

        Returns:
            bool: True if container is allowed for given address, else False
        """

        # Select restrictions list based on message origination
        if onchain:
            restrictions = self._restrictions[container].allowed_addresses
        else:
            restrictions = self._restrictions[container].allowed_delegate_addresses

        # If no specified allowed addresses, allow all
        if len(restrictions) == 0:
            return True
        return address.lower() in restrictions

    def _error(
        self: Guardian, message: PrefilterMessage, error: str, **kwargs: Any
    ) -> GuardianError:
        """Create error message for given message id

        Args:
            message (PrefilterMessage): Message to create error for
            error (str): Error message
            **kwargs (Any): Additional error parameters

        Returns:
            GuardianError: Guardian error message
        """
        return GuardianError(message=message, error=error, params=kwargs)

    def _process_offchain_message(
        self: Guardian, message: OffchainJobMessage
    ) -> Union[GuardianError, OffchainJobMessage]:
        """Filters off-chain job messages (off-chain creation and delivery)

        Filters:
            1. Checks if at least 1 container ID is present in message
            2. Checks if any message container IDs are unsupported
            3. Checks if first container ID is external container
            4. Checks if request IP is allowed for container
            5. Checks if the last container in the pipeline generates a proof if the
                message requires one

        Args:
            message (OffchainJobMessage): Raw message

        Returns:
            Union[GuardianError, OffchainJobMessage]: Error message if filtering fails,
                otherwise parsed message to be processed
        """

        supported_containers = list(self._restrictions.keys())

        # Filter out empty container list
        if len(message.containers) == 0:
            return self._error(
                message,
                "No containers specified",
            )

        # Filter out containers that are not supported
        for container in message.containers:
            if container not in supported_containers:
                return self._error(
                    message,
                    "Container not supported",
                    container=container,
                )

        # Filter out internal first container
        if not self._is_external(message.containers[0]):
            return self._error(
                message,
                "First container must be external",
                first_container=message.containers[0],
            )

        if message.requires_proof and not self._generates_proof(message.containers[-1]):
            return self._error(
                message,
                "Container does not generate proof",
                container=message.containers[-1],
            )

        # Filter out containers that are not allowed for the IP
        for container in message.containers:
            if not self._is_allowed_ip(container, message.ip):
                return self._error(
                    message,
                    "Container not allowed for address",
                    container=container,
                    address=message.ip,
                )

        return message

    def _process_delegated_subscription_message(
        self: Guardian, message: DelegatedSubscriptionMessage
    ) -> Union[GuardianError, DelegatedSubscriptionMessage]:
        """Filters delegated Subscription messages (off-chain creation,
            on-chain delivery)

        Filters:
            1. Checks if chain module is enabled
            2. Signature checks:
                2.1. Checks that signature expiry is valid
            3. Checks if at least 1 container ID is present in subscription
            4. Checks if first container ID is external container
            5. Checks if any subscription container IDs are unsupported
            6. Checks if subscription owner is in allowed addresses
            7. Checks if subscription requires proof but the last container in their
                pipeline does not generate one

        Non-filters:
            1. Does not check if signature itself is valid (handled by processor)
            2. Does not check if owner has delegated a signer (handled by processor)

        Args:
            message (DelegatedSubscriptionMessage): raw message

        Returns:
            Union[GuardianError, DelegatedSubscriptionMessage]: Error message if
                filtering fails, otherwise parsed message to be processed
        """

        # Filter out if chain not enabled
        if not self._chain_enabled:
            return self._error(
                message, "Chain not enabled", delegated_subscription=message
            )

        # Filter out expired signature
        if message.signature.expiry < int(time.time()):
            return self._error(
                message, "Signature expired", delegated_subscription=message
            )

        subscription = message.subscription.deserialize(self._container_lookup)

        supported_containers = list(self._restrictions.keys())

        # Filter out containers that are not supported
        for container in subscription.containers:
            if container not in supported_containers:
                return self._error(
                    message, "Container not supported", container=container
                )

        # Filter out internal first container
        if not self._is_external(subscription.containers[0]):
            return self._error(
                message,
                "First container must be external",
                first_container=subscription.containers[0],
            )

        # Filter out subscriptions that require proofs but the last container in their
        # pipeline does not generate one
        if subscription.requires_proof and not self._generates_proof(
            subscription.containers[-1]
        ):
            return self._error(
                message,
                "Container does not generate proof",
                container=subscription.containers[-1],
            )

        # Filter out unallowed subscription recipients
        for container in subscription.containers:
            if not self._is_allowed_address(container, subscription.owner, False):
                return self._error(
                    message,
                    "Container not allowed for address",
                    container=container,
                    address=subscription.owner,
                )

        return message

    def _process_coordinator_created_message(
        self: Guardian, message: SubscriptionCreatedMessage
    ) -> Union[GuardianError, SubscriptionCreatedMessage]:
        """Filters on-chain Coordinator subscription creation messages

        Filters:
            1. Checks if subscription is complete
            2. Checks if at least 1 container ID is present in subscription
            3. Checks if first container ID is external container
            4. Checks if any subscription container IDs are unsupported
            5. Checks if subscription owner is in allowed addresses
            6. Checks if subscription requires proof but the last container in their
                pipeline does not generate one

        Args:
            message (SubscriptionCreatedMessage): raw message

        Returns:
            Union[GuardianError, SubscriptionCreatedMessage]: Error message if
                filtering fails, otherwise parsed message to be processed
        """

        subscription = message.subscription

        # Filter out completed subscriptions
        if message.subscription.completed:
            return self._error(message, "Subscription completed")

        if len(subscription.containers) == 0:
            return self._error(
                message,
                "Container-set not supported",
                containers_hash=subscription.containers_hash,
            )

        log.info(f"Subscription containers: {subscription.containers}")

        # Filter out internal first container
        if not self._is_external(subscription.containers[0]):
            return self._error(
                message,
                "First container must be external",
                first_container=subscription.containers[0],
            )

        # Filter out unallowed subscription recipients
        for container in subscription.containers:
            if not self._is_allowed_address(container, subscription.owner, True):
                return self._error(
                    message,
                    "Container not allowed for address",
                    container=container,
                    address=subscription.owner,
                )

        # Filter out subscriptions that require proof but the last container in their
        # pipeline does not generate one
        if subscription.requires_proof and not self._generates_proof(
            subscription.containers[-1]
        ):
            return self._error(
                message,
                "Container does not generate proof",
                container=subscription.containers[-1],
            )

        # filter out subscriptions that don't match payment requirements
        (matches, _) = self._wallet_checker.matches_payment_requirements(subscription)
        if not matches:
            return self._error(
                message,
                "Invalid payment",
                subscription_id=subscription.id,
            )

        return message

    def process_message(
        self: Guardian, message: PrefilterMessage
    ) -> Union[GuardianError, FilteredMessage]:
        """Public method to parse and filter message.

        Routes message to appropriate filter method based on message type.

        Args:
            message (PrefilterMessage): Message to filter

        Returns:
            Union[GuardianError, FilteredMessage]: Error message if parsing or filtering
                fails, otherwise filtered message
        """
        match message.type:
            case MessageType.OffchainJob:
                return self._process_offchain_message(cast(OffchainJobMessage, message))
            case MessageType.DelegatedSubscription:
                return self._process_delegated_subscription_message(
                    cast(DelegatedSubscriptionMessage, message)
                )
            case MessageType.SubscriptionCreated:
                return self._process_coordinator_created_message(
                    cast(SubscriptionCreatedMessage, message)
                )
        return self._error(message, "Not supported", raw=message)
