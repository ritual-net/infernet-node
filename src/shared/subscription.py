from __future__ import annotations

import time
from dataclasses import dataclass
from functools import cache

from eth_account.messages import SignableMessage, encode_structured_data
from eth_typing import ChecksumAddress


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
        max_gas_limit (int): Max gas limit in wei used by Infernet node
        inputs (bytes): Optional container input parameters

    Private attributes:
        _active_at (int): Timestamp when subscription is first active
        _period (int): Time, in seconds, between each subscription interval
        _frequency (int): Number of times a subscription is processed
        _redundancy (int): Number of unique nodes that can fulfill each interval
        _max_gas_price (int): Max gas price in wei paid by Infernet node
        _container_id (str): ","-concatenated container IDs (raw format)
        _responses (dict[int, int]): Subscription interval => response count
        _node_responded (dict[int, bool]): Subscription interval => has local node
            responded?
    """

    def __init__(
        self: Subscription,
        id: int,
        owner: str,
        active_at: int,
        period: int,
        frequency: int,
        redundancy: int,
        max_gas_price: int,
        max_gas_limit: int,
        container_id: str,
        inputs: bytes,
    ) -> None:
        """Initializes new Subscription

        Args:
            id (int): Subscription ID (-1 if delegated subscription)
            owner (str): Subscription owner + recipient
            active_at (int): Timestamp when subscription is first active
            period (int): Time, in seconds, between each subscription interval
            frequency (int): Number of times a subscription is processed
            redundancy (int): Number of unique nodes that can fulfill each interval
            max_gas_price (int): Max gas price in wei paid by Infernet node
            max_gas_limit (int): Max gas limit in wei used by Infernet node
            container_id (str): Comma-delimited container IDs
            inputs (bytes): Optional container input parameters
        """

        # Assign subscription parameters
        self.id = id
        self.owner = owner
        self._active_at = active_at
        self._period = period
        self._frequency = frequency
        self._redundancy = redundancy
        self._max_gas_price = max_gas_price
        self.max_gas_limit = max_gas_limit
        self._container_id = container_id
        self.containers = container_id.split(",")
        self.inputs = inputs

        self._responses: dict[int, int] = {}
        self._node_replied: dict[int, bool] = {}

    @property
    def active(self: Subscription) -> bool:
        """Returns whether a subscription is active (current time > active_at)

        Returns:
            bool: True if subscription is active, else False
        """
        return int(time.time()) > self._active_at

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
            self.last_interval
            # And, subscription has received its max redundancy responses
            and self.get_response_count(self.interval) == self._redundancy
        ):
            # Return completed
            return True

        # Else, return incomplete
        return False

    @cache
    def get_interval_by_timestamp(self: Subscription, timestamp: int) -> int:
        """Returns expected subscription interval given response timestamp

        Args:
            timestamp (int): response timestamp

        Returns:
            int: expected subscription interval
        """
        if timestamp < self._active_at:
            raise RuntimeError("Cannot get interval prior to activation")

        # If timestamp >= timestamp for last interval, return last interval
        last_interval_ts = self._active_at + (self._period * (self._frequency - 1))
        if timestamp >= last_interval_ts:
            return self._frequency

        # Else, return expected interval
        diff = timestamp - self._active_at
        return diff // self._period

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
        return encode_structured_data(
            {
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
                        {"name": "maxGasPrice", "type": "uint48"},
                        {"name": "maxGasLimit", "type": "uint32"},
                        {"name": "containerId", "type": "string"},
                        {"name": "inputs", "type": "bytes"},
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
                        "maxGasPrice": self._max_gas_price,
                        "maxGasLimit": self.max_gas_limit,
                        "containerId": ",".join(self.containers),
                        "inputs": self.inputs,
                    },
                },
            }
        )

    @cache
    def get_tx_inputs(
        self: Subscription,
    ) -> tuple[str, int, int, int, int, int, int, str, bytes]:
        """Returns subscription parameters as raw array input for generated txs

        Returns:
            tuple[str, int, int, int, int, int, int, str, bytes]: subscription parameters
        """
        return (
            self.owner,
            self._active_at,
            self._period,
            self._frequency,
            self._redundancy,
            self._max_gas_price,
            self.max_gas_limit,
            ",".join(self.containers),
            self.inputs,
        )


@dataclass(frozen=True)
class SerializedSubscription:
    """Serialized Infernet Coordinator subscription representation"""

    owner: str
    active_at: int
    period: int
    frequency: int
    redundancy: int
    max_gas_price: int
    max_gas_limit: int
    container_id: str
    inputs: str

    def deserialize(self: SerializedSubscription) -> Subscription:
        """Deserializes input parameters to convert to class(Subscription)

        Returns:
            Subscription: deserialized class
        """
        return Subscription(
            -1,
            self.owner,
            self.active_at,
            self.period,
            self.frequency,
            self.redundancy,
            self.max_gas_price,
            self.max_gas_limit,
            self.container_id,
            bytes(self.inputs, "utf-8"),
        )
