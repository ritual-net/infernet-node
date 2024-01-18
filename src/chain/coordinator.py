"""Infernet Coordinator client

Off-chain interface to an Infernet Coordinator.

Examples:
    >>> rpc = RPC("https://my_rpc_url.com")
    >>> coordinator = Coordinator(rpc, "0x...")

    >>> coordinator.get_event_hashes()
    {CoordinatorEvent.SubscriptionCreated: "0x...", ...}

    >>> await coordinator.get_delegated_signer(subscription, 1000)
    0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045

    >>> await coordinator.get_existing_delegate_subscription(
            subscription, signature, 100
        )
    (True, 100)

    >>> await coordinator.recover_delegatee_signer(subscription, signature)
    0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045

    >>> await coordinator.get_deliver_compute_tx(data, tx)
    TxParams(...)

    >>> await coordiantor.get_deliver_compute_delegatee_tx(data, tx, signature)
    TxParams(...)

    >>> await coordinator.get_node_registration_tx(address)
    TxParams(...)

    >>> await coordinator.get_node_activation_tx()
    TxParams(...)

    >>> await coordinator.get_head_subscription_id(1000)
    100

    >>> await coordinator.get_subscription_by_id(1, 1000)
    Subscription(...)

    >>> await coordinator.get_node_status(0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045)
    (NodeStatus.Inactive, 0)

    >>> await coordinator.get_container_inputs(sub, interval, ts, caller)
    bytes("0xabc", "utf-8")

    >>> await coordinator.get_node_has_delivered_response(sub, interval, caller, 1000)
    True

    >>> await coordinator.get_subscription_response_count(1, 1, 1000)
    1

    >>> await coordinator.get_event_logs(1, 1000)
    [{...}]
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import cache
from typing import cast, Any, Iterable

from eth_abi import encode  # type: ignore
from eth_account import Account
from eth_typing import BlockNumber, ChecksumAddress, Hash32, HexStr
from hexbytes import HexBytes
from web3.constants import ADDRESS_ZERO
from web3.types import FilterParams, LogReceipt, TxParams, Nonce

from chain.rpc import RPC
from shared.subscription import Subscription
from utils.constants import (
    COORDINATOR_ABI,
    DELEGATED_SIGNER_ABI,
    SUBSCRIPTION_CONSUMER_ABI,
)
from utils.logging import log


class NodeStatus(Enum):
    """Coordinator (manager) node status"""

    Inactive = 0
    Registered = 1
    Active = 2


class CoordinatorEvent(Enum):
    """Coordinator emitted events (name -> human-readable ABI representation)"""

    SubscriptionCreated = "SubscriptionCreated(uint32)"
    SubscriptionCancelled = "SubscriptionCancelled(uint32)"
    SubscriptionFulfilled = "SubscriptionFulfilled(uint32,address)"


@dataclass(frozen=True)
class CoordinatorDeliveryParams:
    """Function input parameters for Coordinator deliverCompute* functions"""

    subscription: Subscription
    interval: int
    input: bytes
    output: bytes
    proof: bytes


@dataclass(frozen=True)
class CoordinatorSignatureParams:
    """Function input parameters for EIP-712 signed Coordinator functions"""

    nonce: int
    expiry: int
    v: int
    r: int
    s: int


@dataclass(frozen=True)
class CoordinatorTxParams:
    """Generic transaction parameters for Coordinator function calls"""

    nonce: int
    sender: ChecksumAddress
    gas_limit: int


"""
TopicType is a type alias for event topics
"""
TopicType = Iterable[Hash32 | HexBytes | HexStr]


class Coordinator:
    """Off-chain interface to an Infernet Coordinator.

    Public methods:
        get_event_hashes: Returns event => event hash dictionary
        get_delegated_signer: Returns subscription consumer's delegated signer
        get_existing_delegate_subscription: Checks if DelegateSubscription has already
            created on-chain subscription
        recover_delegatee_signer: Recovers delegatee signer from signature
        get_deliver_compute_tx: Returns deliverCompute() tx params
        get_deliver_compute_delegatee_tx: Returns deliverComputeDelegatee() tx params
        get_node_registration_tx: Returns registerNode() tx params
        get_node_activation_tx: Returns activateNode() tx params
        get_head_subscription_id: Returns latest coordinator subscription ID
        get_subscription_by_id: Returns subscription by subscription ID
        get_node_status: Returns node status from Manager
        get_container_inputs: Returns container inputs by subscription (local or via
            contract)
        get_node_has_delivered_response: Returns whether a node has delivered response
            for (sub, interval)
        get_subscription_response_count: Returns subscription count(responses) by
            interval
        get_event_logs: Returns Coordinator emitted logs in block range

    Private attributes:
        _rpc (RPC): RPC instance
        _checksum_address (str): Checksum-validated coordinator address
        _contract (AsyncContract): Coordinator AsyncContract instance
    """

    def __init__(self: Coordinator, rpc: RPC, coordinator_address: str) -> None:
        """Initializes new Infernet Coordinator client

        Args:
            rpc (RPC): RPC instance
            coordinator_address (str): Infernet Coordinator contract address

        Raises:
            ValueError: Coordinator address is incorrectly formatted
        """

        # Check if coordinator address is a valid address
        if not rpc.is_valid_address(coordinator_address):
            raise ValueError("Coordinator address is incorrectly formatted")

        self._rpc = rpc

        # Setup coordinator contract
        self._checksum_address = rpc.get_checksum_address(coordinator_address)
        self._contract = rpc.get_contract(
            address=self._checksum_address,
            abi=COORDINATOR_ABI,
        )
        log.info("Initialized Coordinator", address=self._checksum_address)

    @cache
    def get_event_hashes(self: Coordinator) -> dict[CoordinatorEvent, str]:
        """Gets event => event hash dictionary

        Returns:
            dict[CoordinatorEvent, str]: event => event hash
        """
        return dict(
            (event, self._rpc.get_event_hash(event.value)) for event in CoordinatorEvent
        )

    async def get_delegated_signer(
        self: Coordinator, subscription: Subscription, block_number: BlockNumber
    ) -> ChecksumAddress:
        """Collects delegated signer from subscription consumer inheriting Delegator.sol

        Args:
            subscription (Subscription): subscription
            block_number (BlockNumber): block number to collect at (TOCTTOU)

        Returns:
            ChecksumAddress: delegated signer (zero address in failure case)
        """

        # Set up subscription consumer contract
        # Presumably, this contract should have inherited Delegator.sol
        checksum_address = self._rpc.get_checksum_address(subscription.owner)
        delegator = self._rpc.get_contract(
            address=checksum_address, abi=DELEGATED_SIGNER_ABI
        )

        try:
            # Attempt to collect delegated signer
            return cast(
                ChecksumAddress,
                await delegator.functions.signer().call(block_identifier=block_number),
            )
        except Exception:
            # Else, return signer as zero address
            return cast(ChecksumAddress, ADDRESS_ZERO)

    async def get_existing_delegate_subscription(
        self: Coordinator,
        subscription: Subscription,
        signature: CoordinatorSignatureParams,
        block_number: BlockNumber,
    ) -> tuple[bool, int]:
        """Collects subscription ID created by DelegateSubscription, if exists

        Args:
            subscription (Subscription): subscription
            signature (CoordinatorSignatureParams): DelegateSubscription signature
            block_number (BlockNumber): block number to collect at (TOCTTOU)

        Returns:
            tuple[bool, int]: (delegatee subscription created on-chain subscription,
                ID of created subscription)
        """

        # Encode `delegateCreatedIds` mapping key
        checksum_address = self._rpc.get_checksum_address(subscription.owner)
        key = encode(["address", "uint32"], [checksum_address, signature.nonce])
        hashed = self._rpc.get_keccak(["bytes"], [key])

        # Collect delegate created subscription ID
        id = cast(
            int,
            await self._contract.functions.delegateCreatedIds(hashed).call(
                block_identifier=block_number
            ),
        )

        # If id == 0 (subscription not created)
        return (id != 0, id)

    async def recover_delegatee_signer(
        self: Coordinator,
        subscription: Subscription,
        signature: CoordinatorSignatureParams,
    ) -> ChecksumAddress:
        """Recovers delegatee signer from subscription + signature

        Args:
            subscription (Subscription): subscription
            signature (CoordinatorSignatureParams): DelegateSubscription signature

        Returns:
            ChecksumAddress: recovered delegatee signer address
        """

        # Re-generate EIP-712 typed DelegateSubscription message
        chain_id = await self._rpc.get_chain_id()
        typed_data = subscription.get_delegate_subscription_typed_data(
            nonce=signature.nonce,
            expiry=signature.expiry,
            chain_id=chain_id,
            verifying_contract=self._checksum_address,
        )

        # Recover address from signature
        return cast(
            ChecksumAddress,
            Account.recover_message(
                signable_message=typed_data,
                vrs=(signature.v, signature.r, signature.s),
            ),
        )

    async def get_deliver_compute_tx(
        self: Coordinator,
        data: CoordinatorDeliveryParams,
        tx: CoordinatorTxParams,
    ) -> TxParams:
        """Generates tx to call Coordinator.deliverCompute()

        Args:
            data (CoordinatorDeliveryParams): deliverCompute() params
            tx (CoordinatorTxParams): general tx params

        Returns:
            TxParams: built transaction params
        """
        return await self._contract.functions.deliverCompute(
            data.subscription.id,
            data.interval,
            data.input,
            data.output,
            data.proof,
        ).build_transaction(
            {
                "nonce": cast(Nonce, tx.nonce),
                "from": tx.sender,
                "gas": tx.gas_limit,
            }
        )

    async def get_deliver_compute_delegatee_tx(
        self: Coordinator,
        data: CoordinatorDeliveryParams,
        tx: CoordinatorTxParams,
        signature: CoordinatorSignatureParams,
    ) -> TxParams:
        """Generates tx to call Coordinator.deliverComputeDelegatee()

        Args:
            data (CoordinatorDeliveryParams): deliverCompute() params
            tx (CoordinatorTxParams): general tx params
            signature (CoordinatorSignatureParams): delegatee signature

        Returns:
            TxParams: built transaction params
        """
        return await self._contract.functions.deliverComputeDelegatee(
            signature.nonce,
            signature.expiry,
            data.subscription.get_tx_inputs(),
            signature.v,
            signature.r.to_bytes(32, "big"),
            signature.s.to_bytes(32, "big"),
            data.interval,
            data.input,
            data.output,
            data.proof,
        ).build_transaction(
            {
                "nonce": cast(Nonce, tx.nonce),
                "from": tx.sender,
                "gas": tx.gas_limit,
            }
        )

    async def get_node_registration_tx(
        self: Coordinator,
        node_address: ChecksumAddress,
        tx: CoordinatorTxParams,
    ) -> TxParams:
        """Generates tx to call Coordinator.registerNode()

        Args:
            node_address (ChecksumAddress): node adddess to register
            tx (CoordinatorTxParams): general tx params

        Returns:
            TxParams: built transaction params
        """
        return await self._contract.functions.registerNode(
            node_address
        ).build_transaction(
            {
                "nonce": cast(Nonce, tx.nonce),
                "from": tx.sender,
                "gas": tx.gas_limit,
            }
        )

    async def get_node_activation_tx(
        self: Coordinator, tx: CoordinatorTxParams
    ) -> TxParams:
        """Generates tx to call Coordinator.activateNode()

        Args:
            tx (CoordinatorTxParams): general tx params

        Returns:
            TxParams: built transaction params
        """
        return await self._contract.functions.activateNode().build_transaction(
            {
                "nonce": cast(Nonce, tx.nonce),
                "from": tx.sender,
                "gas": tx.gas_limit,
            }
        )

    async def get_head_subscription_id(
        self: Coordinator, block_number: BlockNumber
    ) -> int:
        """Collects highest subscription ID at block number

        Args:
            block_number (BlockNumber): block number to collect at (TOCTTOU)

        Returns:
            int: highest subscription ID
        """
        return cast(
            int,
            await self._contract.functions.id().call(block_identifier=block_number),
        )

    async def get_subscription_by_id(
        self: Coordinator, subscription_id: int, block_number: BlockNumber
    ) -> Subscription:
        """Collects subscription by ID at block number

        Args:
            subscription_id (int): subscription ID
            block_number (BlockNumber): block number to collect at (TOCTTOU)

        Returns:
            Subscription: collected subscription
        """

        # Collect raw subscription data
        subscription_data: list[Any] = await self._contract.functions.subscriptions(
            subscription_id
        ).call(block_identifier=block_number)
        return Subscription(subscription_id, *subscription_data)

    async def get_node_status(
        self: Coordinator, address: ChecksumAddress
    ) -> tuple[NodeStatus, int]:
        """Returns node status from Manager

        Args:
            address (ChecksumAddress): node address

        Returns:
            tuple[NodeStatus, int]: node status, action cooldown
        """
        # Collect NodeInfo struct via `nodeInfo()`
        [status, cooldown] = await self._contract.functions.nodeInfo(address).call()
        # Return node status, action cooldown
        return NodeStatus(status), cast(int, cooldown)

    async def get_container_inputs(
        self: Coordinator,
        subscription: Subscription,
        interval: int,
        timestamp: int,
        caller: ChecksumAddress,
    ) -> bytes:
        """Returns local or remotely-available container inputs by subscription

        If local subscription input is non-empty, returns inputs.
        If local subscription input is empty:
            1. Attempts to collect and return on-chain inputs
            2. Else, returns empty inptus

        Args:
            subscription (Subscription): subscription
            interval (int): delivery interval at point of checking
            timestamp (int): timestamp at time of checking
            caller (ChecksumAddress): checking address

        Returns:
            bytes: subscription inputs
        """

        # Immediately return if local inputs are non-empty
        if subscription.inputs != bytes("", "utf-8"):
            return subscription.inputs

        # Else, attempt to collect on-chain inputs
        # Set up subscription consumer contract
        checksum_address = self._rpc.get_checksum_address(subscription.owner)
        consumer = self._rpc.get_contract(
            address=checksum_address, abi=SUBSCRIPTION_CONSUMER_ABI
        )

        try:
            # Attempt to collect container inputs
            return cast(
                bytes,
                await consumer.functions.getContainerInputs(
                    subscription.id, interval, timestamp, caller
                ).call(),
            )
        except Exception:
            # Else, return default
            return bytes("", "utf-8")

    async def get_node_has_delivered_response(
        self: Coordinator,
        subscription_id: int,
        interval: int,
        node_address: ChecksumAddress,
        block_number: BlockNumber,
    ) -> bool:
        """Checks whether a node has delivered a response for a subscription ID at
            current interval

        Args:
            subscription_id (int): subscription ID
            interval (int): subscription interval
            node_address (ChecksumAddress): node address to check
            block_number (BlockNumber): block number to collect at (TOCTTOU)

        Returns:
            bool: True if node has delivered a response for current interval, else False
        """

        # Encode `nodeResponded` mapping key
        key = encode(
            ["uint32", "uint32", "address"],
            [subscription_id, interval, node_address],
        )
        hashed = self._rpc.get_keccak(["bytes"], [key])

        return cast(
            bool,
            await self._contract.functions.nodeResponded(hashed).call(
                block_identifier=block_number
            ),
        )

    async def get_subscription_response_count(
        self: Coordinator,
        subscription_id: int,
        interval: int,
        block_number: BlockNumber,
    ) -> int:
        """Collects count(subscription responses) by ID for interval at block number

        Args:
            subscription_id (int): subscription ID
            interval (int): subscription interval
            block_number (BlockNumber): block number to collect at (TOCTTOU)

        Returns:
            int: number of fulfilled responses in interval (redundancy)
        """

        # Encode `redundancyCount` mapping key
        key = encode(["uint32", "uint32"], [subscription_id, interval])
        hashed = self._rpc.get_keccak(["bytes"], [key])

        return cast(
            int,
            await self._contract.functions.redundancyCount(hashed).call(
                block_identifier=block_number
            ),
        )

    async def get_event_logs(
        self: Coordinator, start_block: BlockNumber, end_block: BlockNumber
    ) -> list[LogReceipt]:
        """Collects all Coordinator-emitted events in block range

        Args:
            start_block (BlockNumber): start block (inclusive, collection range)
            end_block (BlockNumber): end block (inclusive, collection range)

        Returns:
            list[LogReceipt]: collected logs
        """

        # Setup filter parameters
        params = FilterParams(
            address=self._checksum_address,
            fromBlock=start_block,
            toBlock=end_block,
            topics=[list(cast(TopicType, self.get_event_hashes().values()))],
        )

        # Return collected logs
        return await self._rpc.get_event_logs(params)
