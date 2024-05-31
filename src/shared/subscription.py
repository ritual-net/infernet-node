from __future__ import annotations

import time
from dataclasses import dataclass
from functools import cache

import structlog
from eth_account.messages import SignableMessage, encode_typed_data
from eth_typing import ChecksumAddress
from hexbytes import HexBytes
from web3 import Web3

from chain.container_lookup import ContainerLookup

log = structlog.get_logger()

UINT32_MAX = 2**32 - 1


def add0x(_hash: str) -> str:
    """
    Adds '0x' prefix to a stringified hash if it does not already have it.
    """
    if _hash.startswith("0x"):
        return _hash
    return f"0x{_hash}"


class Subscription:
    """Infernet Coordinator subscription representation

    Public methods:
        owner: Returns subscription owner
        active: Returns whether a subscription is active
        interval: Returns current subscription interval
        last_interval: Returns whether subscription is on last interval
        completed: Returns whether subscription is completed
        get_interval_by_timestamp: Returns expected interval for a response timestamp
        get_response_count: Returns number of responses tracked in interval
        set_response_count: Sets number of responses for an interval
        get_node_replied: Returns whether local node has responded in interval
        set_node_replied: Sets local node as responded in interval
        get_delegate_subscription_typed_data: Generates EIP-712 DelegateeSubscription
            data
        get_tx_inputs: Returns subscription parameters in tx array format

    Public attributes:
        id (int): Subscription ID (-1 if delegated subscription)
        owner (str): Subscription owner + recipient
        containers (list[str]): List of container IDs

    Private attributes:
        _container_lookup (ContainerLookup): Container lookup instance
        _active_at (int): Timestamp when subscription is first active
        _period (int): Time, in seconds, between each subscription interval
        _frequency (int): Number of times a subscription is processed
        _redundancy (int): Number of unique nodes that can fulfill each interval
        _container_id (str): ","-concatenated container IDs (raw format)
        _lazy (bool): Whether subscription is lazy
        _prover (str): Prover address
        _payment_amount (int): Payment amount
        _payment_token (str): Payment token
        _wallet (str): Wallet address
        _responses (dict[int, int]): Subscription interval => response count
        _node_responded (dict[int, bool]): Subscription interval => has local node
            responded?

    """

    def __init__(
        self: Subscription,
        id: int,
        container_lookup: ContainerLookup,
        owner: str,
        active_at: int,
        period: int,
        frequency: int,
        redundancy: int,
        containers_hash: bytes,
        lazy: bool,
        prover: str,
        payment_amount: int,
        payment_token: str,
        wallet: str,
    ) -> None:
        """Initializes new Subscription

        Args:
            id (int): Subscription ID (-1 if delegated subscription)
            owner (str): Subscription owner + recipient
            active_at (int): Timestamp when subscription is first active
            period (int): Time, in seconds, between each subscription interval
            frequency (int): Number of times a subscription is processed
            redundancy (int): Number of unique nodes that can fulfill each interval
            containers_hash (bytes): Keccak hash of the comma-separated list of container
                IDs.
            lazy (bool): Whether subscription is lazy
            prover (str): Prover address
            payment_amount (int): Payment amount
            payment_token (str): Payment token
            wallet (str): Wallet address
        """

        # Assign subscription parameters
        self.id = id
        self._container_lookup = container_lookup
        self._owner = owner
        self._active_at = active_at
        self._period = period
        self._frequency = frequency
        self._redundancy = redundancy
        self._containers_hash = containers_hash
        self._lazy = lazy
        self._prover = prover
        self._payment_amount = payment_amount
        self._payment_token = payment_token
        self._wallet = wallet

        self._responses: dict[int, int] = {}
        self._node_replied: dict[int, bool] = {}

    @property
    def active(self: Subscription) -> bool:
        """Returns whether a subscription is active (current time > active_at)

        Returns:
            bool: True if subscription is active, else False
        """
        return time.time() > self._active_at

    @property
    def cancelled(self: Subscription) -> bool:
        """Returns whether a subscription is cancelled (active_at = UINT32_MAX)

        Returns:
            bool: True if subscription is cancelled, else False
        """
        return self._active_at == UINT32_MAX

    @property
    def owner(self: Subscription) -> ChecksumAddress:
        """Returns subscription owner

        Returns:
            ChecksumAddress: subscription owner address
        """
        return Web3.to_checksum_address(self._owner)

    @property
    def past_last_interval(self: Subscription) -> int:
        """Returns whether a subscription is past its last interval

        Returns:
            bool: True if subscription is past last interval, else False
        """
        if not self.active:
            return False

        return self.interval > self._frequency

    @property
    def is_callback(self: Subscription) -> bool:
        """Returns whether a subscription is a callback subscription (i.e. period = 0)

        Returns:
            bool: True if subscription is a callback, else False
        """
        return self._period == 0

    @property
    def interval(self: Subscription) -> int:
        """Returns subscription interval based on active_at and period

        Raises:
            RuntimeError: Thrown if checking interval for inactive subscription

        Returns:
            int: current subscription interval
        """

        # Throw if checking interval for an inactive subscription
        if not self.active:
            raise RuntimeError("Checking interval for inactive subscription")

        # If period is 0, we're always at interval 1
        if self._period == 0:
            return 1

        # Else, interval = ((block.timestamp) - active_at) / period) + 1
        unix_ts = int(time.time())
        return ((unix_ts - self._active_at) // self._period) + 1

    @property
    def containers(self: Subscription) -> list[str]:
        """Returns subscription container IDs.
        Uses the ContainerIdDecoder to decode the container IDs.

        Returns:
            list[str]: container IDs
        """
        return self._container_lookup.get_containers(self.containers_hash)

    @property
    def containers_hash(self: Subscription) -> str:
        """Returns subscription container IDs hash

        Returns:
            bytes: container IDs hash
        """
        return add0x(self._containers_hash.hex())

    @property
    def payment_amount(self: Subscription) -> int:
        """Returns subscription payment amount

        Returns:
            int: payment amount
        """
        return self._payment_amount

    @property
    def payment_token(self: Subscription) -> ChecksumAddress:
        """Returns subscription payment token

        Returns:
            ChecksumAddress: payment token
        """
        return Web3.to_checksum_address(self._payment_token)

    @property
    def wallet(self: Subscription) -> ChecksumAddress:
        """Returns subscription wallet address

        Returns:
            ChecksumAddress: wallet address
        """
        return Web3.to_checksum_address(self._wallet)

    @property
    def last_interval(self: Subscription) -> bool:
        """Returns whether a subscription is on its last interval

        Returns:
            bool: True if subscription is on last interval, else False
        """

        # If subscription is inactive, cannot be on any interval
        if not self.active:
            return False

        return self.interval == self._frequency

    @property
    def completed(self: Subscription) -> bool:
        """Returns whether a subscription is completed (last interval, max responses
            received)

        Returns:
            bool: True if subscription is completed, else False
        """
        if (
            # If subscription is on its last interval
            (self.past_last_interval or self.last_interval)
            # And, subscription has received its max redundancy responses
            and self.get_response_count(self._frequency) == self._redundancy
        ):
            # Return completed
            return True

        # Else, return incomplete
        return False

    def get_response_count(self: Subscription, interval: int) -> int:
        """Returns response count by subscription interval

        Args:
            interval (int): subscription interval

        Returns:
            int: number of responses tracked during interval
        """

        # If interval is not tracked, return 0
        if interval not in self._responses:
            return 0

        # Else, return number of responses
        return self._responses[interval]

    def set_response_count(self: Subscription, interval: int, count: int) -> None:
        """Sets response count for a subscription interval

        Args:
            interval (int): subscription interval to set
            count (int): count of tracked subscription responses

        Raises:
            RuntimeError: Thrown if updating response count for inactive subscription
            RuntimeError: Thrown if updating response count for a future interval
        """

        # Throw if updating response count for inactive subscription
        if not self.active:
            raise RuntimeError("Cannot update response count for inactive subscription")

        # Throw if updating response count for a future interval
        if interval > self.interval:
            raise RuntimeError("Cannot update response count for future interval")

        # Update response count
        self._responses[interval] = count

    def get_node_replied(self: Subscription, interval: int) -> bool:
        """Returns whether local node has responded in interval

        Args:
            interval (int): subscription interval to get

        Returns:
            bool: True if node has replied in interval, else False
        """
        return self._node_replied.get(interval, False)

    def set_node_replied(self: Subscription, interval: int) -> None:
        """Sets local node as having responded in interval

        Args:
            interval (int): subscription interval to set as having been responded to
        """
        self._node_replied[interval] = True

    @cache
    def get_delegate_subscription_typed_data(
        self: Subscription,
        nonce: int,
        expiry: int,
        chain_id: int,
        verifying_contract: ChecksumAddress,
    ) -> SignableMessage:
        """Generates EIP-712 typed data to sign for DelegateeSubscription

        Args:
            nonce (int): delegatee signer nonce (relative to owner contract)
            expiry (int): signature expiry
            chain_id (int): contract chain ID (non-replayable across chains)
            verifying_contract (ChecksumAddress): EIP-712 signature verifying contract

        Returns:
            SignableMessage: typed, signable DelegateSubscription message
        """
        return encode_typed_data(
            full_message={
                "types": {
                    "EIP712Domain": [
                        {"name": "name", "type": "string"},
                        {"name": "version", "type": "string"},
                        {"name": "chainId", "type": "uint256"},
                        {"name": "verifyingContract", "type": "address"},
                    ],
                    "DelegateSubscription": [
                        {"name": "nonce", "type": "uint32"},
                        {"name": "expiry", "type": "uint32"},
                        {"name": "sub", "type": "Subscription"},
                    ],
                    "Subscription": [
                        {"name": "owner", "type": "address"},
                        {"name": "activeAt", "type": "uint32"},
                        {"name": "period", "type": "uint32"},
                        {"name": "frequency", "type": "uint32"},
                        {"name": "redundancy", "type": "uint16"},
                        {"name": "containerId", "type": "bytes32"},
                        {"name": "lazy", "type": "bool"},
                        {"name": "prover", "type": "address"},
                        {"name": "paymentAmount", "type": "uint256"},
                        {"name": "paymentToken", "type": "address"},
                        {"name": "wallet", "type": "address"},
                    ],
                },
                "primaryType": "DelegateSubscription",
                "domain": {
                    "name": "InfernetCoordinator",
                    "version": "1",
                    "chainId": chain_id,
                    "verifyingContract": verifying_contract,
                },
                "message": {
                    "nonce": nonce,
                    "expiry": expiry,
                    "sub": {
                        "owner": self.owner,
                        "activeAt": self._active_at,
                        "period": self._period,
                        "frequency": self._frequency,
                        "redundancy": self._redundancy,
                        "containerId": self._containers_hash,
                        "lazy": self._lazy,
                        "prover": self._prover,
                        "paymentAmount": self._payment_amount,
                        "paymentToken": self._payment_token,
                        "wallet": self._wallet,
                    },
                },
            }
        )

    @cache
    def get_tx_inputs(
        self: Subscription,
    ) -> tuple[str, int, int, int, int, bytes, bool, str, int, str, str]:
        """Returns subscription parameters as raw array input for generated txs

        Returns:
            tuple[str, int, int, int, int, bytes, bool, str, int, str, str]: raw tx
                input parameters
        """
        return (
            self.owner,
            self._active_at,
            self._period,
            self._frequency,
            self._redundancy,
            self._containers_hash,
            self._lazy,
            self._prover,
            self._payment_amount,
            self._payment_token,
            self._wallet,
        )


@dataclass(frozen=True)
class SerializedSubscription:
    """Serialized Infernet Coordinator subscription representation"""

    owner: str
    active_at: int
    period: int
    frequency: int
    redundancy: int
    containers: str
    lazy: bool
    prover: str
    payment_amount: int
    payment_token: str
    wallet: str

    def deserialize(
        self: SerializedSubscription,
        container_lookup: ContainerLookup,
    ) -> Subscription:
        """Deserializes input parameters to convert to class(Subscription)

        Returns:
            Subscription: deserialized class
        """
        return Subscription(
            -1,
            container_lookup,
            self.owner,
            self.active_at,
            self.period,
            self.frequency,
            self.redundancy,
            HexBytes(self.containers),
            self.lazy,
            self.prover,
            self.payment_amount,
            self.payment_token,
            self.wallet,
        )
