"""ChainProcessor

Handles processing of on-chain delivered subscriptions.
"""

from __future__ import annotations

import time
from asyncio import create_task, sleep
from typing import Optional, Any, cast

from eth_abi import encode  # type: ignore
from eth_typing import HexStr

from chain.rpc import RPC
from utils.logging import log
from chain.wallet import Wallet
from shared.service import AsyncTask
from shared.message import (
    MessageType,
    OnchainMessage,
    SubscriptionCreatedMessage,
    SubscriptionCancelledMessage,
    SubscriptionFulfilledMessage,
    DelegatedSubscriptionMessage,
)
from shared.subscription import Subscription
from shared.job import ContainerError, ContainerOutput
from chain.coordinator import Coordinator, CoordinatorSignatureParams
from orchestration.orchestrator import Orchestrator, OrchestratorInputSource

# Blocked tx
BLOCKED = "blocked"

# Container response keys
RESPONSE_KEYS = [
    "raw_input",
    "processed_input",
    "raw_output",
    "processed_output",
    "proof",
]

# Type aliases
Interval = int
SubscriptionID = int
DelegateSubscriptionID = tuple[str, int]  # (owner address, nonce)
UnionID = SubscriptionID | DelegateSubscriptionID
DelegateSubscriptionData = tuple[
    Subscription, CoordinatorSignatureParams, dict[Any, Any]
]


class ChainProcessor(AsyncTask):
    """Handles processing of on-chain delivered subscriptions.

    Process:
        1. Receives messages to track via `process()`
        2. Tracks messages (+ included subscriptions) according to type:
            2.1. SubscriptionCreatedMessage:
                2.1.1. Adds subscription to _subscriptions, indexed by ID
                2.1.2. If message originated in a tracked tx_hash (delegate subscription
                 being created), evict delegate subscription from
                 self._delegate_subscriptions
            2.2. SubscriptionCancelledMessage:
                2.2.1. Deletes ID key from _subscriptions, if exists
            2.3. SubscriptionFulfilledMessage:
                2.3.1. Checks if fufillment message is relevant (id tracked in
                  _subscriptions; note, runs after creation message so delegate
                  subscriptions will be tracked accordingly)
                2.3.2. If fulfillment was our own, removes from _pending
                    2.3.2.1. Updates our node as having responded to
                      (subscription, interval)
                2.3.3. Updates subscription fulfillment in _subscriptions
                    2.3.3.1. Checks subscription completion and removes from
                      _subscriptions if so
            2.4. DelegatedSubscriptionMessage:
                2.4.1. Checks if delegated subscription already exists on-chain
                  (by owner, nonce)
                2.4.2. Collects recover signer from signature
                2.4.3. Collects delegated signer from chain
                2.4.4. Verifies that recovered signer == delegated signer
                2.4.5. If verified, adds subscription to _delegate_subscriptions
                  indexed by str(owner-nonce)
        3. At each interval (default: every 500ms):
            3.1. Prune pending txs that have failed to allow for re-processing
                (successful txs pruned during event replay)
            3.2. Check for subscriptions + delegated subscriptions that are active
                3.2.1. Filter out ones with pending transactions emitted for current
                  interval
                3.2.2. Filter out ones where node has already submitted on-chain tx
                  for current interval
            3.3. Process:
                3.3.1. Toggle pending execution for interval by blocking self._pending
                3.3.2. Collect latest input parameters, if needed, from chain
                3.3.3. Execute relevant containers via orchestrator
                3.3.4. Serialize container response
                3.3.5. Send deliver_compute (or delivate_compute_delegatee if delegated
                  subscription) tx via wallet
                3.3.6. Update self._pending with accurate tx hash

    Public methods:
        setup: Inherited from AsyncTask. Unused
        cleanup: Inherited from AsyncTask: Unused
        track: Manages incoming OnchainMessage events; stores events
        run_forever: Core loop, 500ms cycle to run subscription execution process

    Private methods:
        _track_created_message: Handles event replayed SubscriptionCreatedMessage(s)
        _track_cancelled_message: Handles event replayed SubscriptionCancelledMessage(s)
        _track_fulfilled_message: Handles event replayed SubscriptionFulfilledMessage(s)
        _track_delegated_message: Handles event replayed DelegatedSubscriptionMessage(s)
        _has_responded_onchain_in_interval: Checks if local node wallet has responded
            on-chain for (subscription ID, interval)
        _has_subscription_tx_pending_in_interval: Checks if a tx is pending for
            (subscription ID, interval)
        _prune_failed_txs: Prunes pending txs that have failed to allow for re-processing
        _serialize_param: Serializes single container output param (consumed by
            _serialize_container_output)
        _serialize_container_output: Serializes orchestrator container output for
            on-chain consumption
        _process_subscription: Handles subscription processing lifecycle

    Private attributes:
        _rpc (RPC): RPC instance
        _coordinator (Coordinator): Coordinator instance
        _wallet (Wallet): Wallet instance
        _subscriptions (dict[SubscriptionID, Subscription]): subscription ID => on-chain
            subscription
        _delegate_subscriptions (dict[DelegateSubscriptionID, DelegateSubscriptionData]):
            delegate subscription ID => delegate subscription data
        _pending (dict[tuple[UnionID, Interval], str]):
            (subscription ID, delivery interval) => tx hash
        _attempts (dict[tuple[UnionID, Interval], int]):
            (subscription ID, delivery interval) => number of failed tx attempts
    """

    def __init__(
        self: ChainProcessor,
        rpc: RPC,
        coordinator: Coordinator,
        wallet: Wallet,
        orchestrator: Orchestrator,
    ):
        """Initializes new ChainProcessor

        Args:
            rpc (RPC): RPC instance
            coordinator (Coordinator): Coordinator instance
            wallet (Wallet): Wallet instance
            orchestrator (Orchestrator): Orchestrator instance
        """

        # Initialize inherited AsyncTask
        super().__init__()

        self._rpc = rpc
        self._coordinator = coordinator
        self._wallet = wallet
        self._orchestrator = orchestrator

        # Subscription ID => subscription
        self._subscriptions: dict[SubscriptionID, Subscription] = {}

        # Delegate subscription ID => (subscription, signature, data)
        self._delegate_subscriptions: dict[
            DelegateSubscriptionID,
            DelegateSubscriptionData,
        ] = {}

        # (Union subscription ID, interval) => tx_hash
        self._pending: dict[tuple[UnionID, Interval], str] = {}

        # (Union subscription ID, interval) => attempts
        self._attempts: dict[tuple[UnionID, Interval], int] = {}
        log.info("Initialized ChainProcessor")

    def _track_created_message(
        self: ChainProcessor, msg: SubscriptionCreatedMessage
    ) -> None:
        """Tracks SubscriptionCreatedMessage

        Process:
            1. Adds subscription to tracked _subscriptions
            2. Checks if subscription was created for a tracked tx
                2.1. If so, evicts delegate subscription

        Args:
            msg (SubscriptionCreatedMessage): subscription creation message
        """

        # Add subscription to tracked _subscriptions
        self._subscriptions[msg.subscription.id] = msg.subscription
        log.info(
            "Tracked new subscription",
            id=msg.subscription.id,
            total=len(self._subscriptions.keys()),
        )

        # If message has an associated tx_hash
        # We know this message came from event replay
        if msg.tx_hash:
            # Check if tx_hash exists in pending transactions
            for (id, _), tx_hash in self._pending.items():
                if tx_hash == msg.tx_hash:
                    # If tx_hash does exist, we know that this is the tx confirmation
                    # of an tx that we sent out. Because it is a creation event, we
                    # must have sent a corresponding delegate subscription that
                    # when confirmed on-chain, created a subscription. Now, because we
                    # track the actual subscription, we can remove the delegate.
                    del self._delegate_subscriptions[cast(DelegateSubscriptionID, id)]
                    log.info("Evicted created delegated subscription", id=id)

    def _track_cancelled_message(
        self: ChainProcessor, msg: SubscriptionCancelledMessage
    ) -> None:
        """Tracks SubscriptionCancelledMessage

        Process:
            1. Removes subscription by ID from tracked _subscriptions, if exists

        Args:
            msg (SubscriptionCancelledMessage): subscription cancellation message
        """
        if msg.subscription_id in self._subscriptions:
            del self._subscriptions[msg.subscription_id]
            log.info(
                "Tracked subscription cancellation",
                id=msg.subscription_id,
                total=len(self._subscriptions.keys()),
            )
        else:
            log.debug("Ignored irrelevant cancellation", id=msg.subscription_id)

    def _track_fulfilled_message(
        self: ChainProcessor, msg: SubscriptionFulfilledMessage
    ) -> None:
        """Tracks SubscriptionFulfilledMessage

        Process:
            1. Checks if fulfillment message is relevant (is for a tracked subscription)
            2. Calculates subscription interval from timestamp
            3. Checks if fulillment was our own
                3.1. If so, removes tx from _pending
                3.2. Updates our own node as having responded
            4. Updates subscription fulfillment in subscription in _subscriptions
            5. Checks subscription completion and removes from _subscriptions if so

        Args:
            msg (SubscriptionFulfilledMessage): subscription fulfillment message
        """

        # Return if fulfillment message is irrelevant
        if msg.subscription_id not in self._subscriptions:
            log.debug("Ignored irrelevant fulfillment", id=msg.subscription_id)
            return

        # Calculate subscription interval
        subscription = self._subscriptions[msg.subscription_id]
        interval = subscription.get_interval_by_timestamp(msg.timestamp)

        # If fulfillment is our own
        if msg.node == self._wallet.address:
            key = (subscription.id, interval)

            # Check if we tracked the pending tx
            if key in self._pending:
                # If so, remove pending tx and log removal
                tx_hash = self._pending.pop(key)
                log.info("Removed completed tx", tx_hash=tx_hash)
            else:
                # Else, log error if we did not track pending tx
                log.info(
                    "Tx not found in pending (potentially delegate)",
                    id=subscription.id,
                    interval=interval,
                )

            # Update node as having responded
            subscription.set_node_replied(interval)

        # Update subscription fulfillment
        existing_count = subscription.get_response_count(interval)
        subscription.set_response_count(interval, existing_count + 1)
        log.info(
            "Tracked subscription fulfillment",
            id=subscription.id,
            interval=interval,
            count=existing_count + 1,
        )

        # If subscription completed, remove from _subscriptions
        if subscription.completed:
            del self._subscriptions[subscription.id]
            log.info(
                "Evicted completed subscription",
                id=subscription.id,
                total=len(self._subscriptions.keys()),
            )

    async def _track_delegated_message(
        self: ChainProcessor, msg: DelegatedSubscriptionMessage
    ) -> None:
        """Tracks DelegatedSubscriptionMessage

        Process:
            1. Checks if delegated subscription already exists on-chain
                1.1. If so, evicts relevant run from pending and attempts
                    to allow forced re-execution
            2. Collects recovered signer from signature
            3. Collects delegated signer from chain
            4. Verifies that recovered signer == delegated signer
            5. If verified, adds subscription to _delegate_subscriptions,
                indexed by (owner, nonce)

        Args:
            msg (DelegatedSubscriptionMessage): delegated subscription message
        """

        # Collect message inputs
        subscription = msg.subscription.deserialize()
        signature = msg.signature

        # Check if delegated subscription already exists on-chain
        head_block = await self._rpc.get_head_block_number()
        (
            exists,
            id,
        ) = await self._coordinator.get_existing_delegate_subscription(
            subscription=subscription,
            signature=signature,
            block_number=head_block,
        )

        # If subscription exists
        if exists:
            # Check if subscription is tracked locally
            tracked = id in self._subscriptions
            log.info("Delegated subscription exists on-chain", id=id, tracked=tracked)

            # Evict current delegate runs from pending and attempts
            # Allows reprocessing failed delegate subscriptions, if they exist
            key = ((subscription.owner, signature.nonce), subscription.interval)
            if key in self._pending:
                self._pending.pop(key)
                log.info("Evicted past pending subscription tx", run=key)
            if key in self._attempts:
                self._attempts.pop(key)
                log.info("Evicted past pending subscription attempts", run=key)

        # Else, subscription does not exist on-chain
        try:
            # Recover signer from signature
            recovered_signer = await self._coordinator.recover_delegatee_signer(
                subscription=subscription, signature=signature
            )
            log.debug("Recovered delegatee signer", address=recovered_signer)
        except Exception:
            # In case of signature recovery failure, return
            log.error(
                "Could not recover delegatee signer",
                subscription=subscription,
                signature=signature,
            )
            return

        # Collect on-chain delegated signer
        delegated_signer = await self._coordinator.get_delegated_signer(
            subscription=subscription, block_number=head_block
        )
        log.debug("Collected delegated signer", address=delegated_signer)

        # If signers do not match, return
        if recovered_signer != delegated_signer:
            log.error(
                "Subscription signer mismatch",
                recovered=recovered_signer,
                delegated=delegated_signer,
            )
            return

        # Else, if signers match, track delegate subscription
        self._delegate_subscriptions[(subscription.owner, signature.nonce)] = (
            subscription,
            signature,
            msg.data,
        )
        log.info(
            "Tracked new delegate subscription",
            owner=subscription.owner,
            nonce=signature.nonce,
        )

    async def _has_responded_onchain_in_interval(
        self: ChainProcessor, subscription_id: SubscriptionID
    ) -> bool:
        """Checks whether node has responded on-chain in interval (non-pending)

        Args:
            subscription_id (SubscriptionID): on-chain subscription ID

        Returns:
            bool: True if node has responded on-chain in interval, else False
        """

        # Collect subscription
        sub = self._subscriptions[subscription_id]

        # Check if subscription response has already been submitted
        if sub.get_node_replied(sub.interval):
            # If so, return True
            return True

        # Else, check chain to see if response has already been submitted
        # This may trigger if restarting the node w/ incomplete subscriptions
        head_block = await self._rpc.get_head_block_number()
        node_responded = await self._coordinator.get_node_has_delivered_response(
            subscription_id=subscription_id,
            interval=sub.interval,
            node_address=self._wallet.address,
            block_number=head_block,
        )

        # Update node reply status and return
        if node_responded:
            sub.set_node_replied(sub.interval)
        return node_responded

    async def _prune_failed_txs(self: ChainProcessor) -> None:
        """Prunes pending txs that have failed to allow for re-processing

        Process:
            1. Checks for txs that are non-blocked, found on-chain, and failed
            2. Increments self._attempts dict
            3. If self._attempts[tx] < 3, evicts failed tx else keeps blocked
        """
        failed_txs: list[tuple[UnionID, Interval]] = []
        for (id, interval), tx_hash in self._pending.items():
            # Check if tx_hash is not blocked
            if tx_hash != BLOCKED:
                # Check if tx failed on-chain
                (found, success) = await self._rpc.get_tx_success(cast(HexStr, tx_hash))

                # If posted on-chain but failed, evict from pending txs
                if found and not success:
                    # Push to failed tx list
                    failed_txs.append((id, interval))

        # Evict failed txs
        for id, interval in failed_txs:
            key = (id, interval)

            # Check if key in attempts
            if key in self._attempts:
                # If so, increment attempts
                self._attempts[key] += 1
            else:
                # Else, initialize to 1 processed attempt
                self._attempts[key] = 1

            # If < 3 failed attempts, evict failed tx
            attempt_count = self._attempts[key]
            if attempt_count < 3:
                self._pending.pop(key)
                log.info(
                    "Evicted failed tx",
                    id=id,
                    interval=interval,
                    tx_hash=tx_hash,
                    retries=attempt_count,
                )

    def _has_subscription_tx_pending_in_interval(
        self: ChainProcessor,
        subscription_id: UnionID,
    ) -> bool:
        """Checks if a subscription (or delegated subscription) has a pending tx for
            current interval

        Args:
            subscription_id (UnionID): subscription ID

        Returns:
            bool: True if (subscription, interval) has a pending tx, else False
        """

        # Collect subscription
        if isinstance(subscription_id, SubscriptionID):
            sub = self._subscriptions[subscription_id]
        else:
            sub = self._delegate_subscriptions[subscription_id][0]

        return (
            False
            if self._pending.get((subscription_id, sub.interval), None) is None
            else True
        )

    def _serialize_param(self: ChainProcessor, input: Optional[str]) -> bytes:
        """Serializes container output param as bytes

        Args:
            input (Optional[str]): input parameter (utf-8-stringified bytes or None)

        Returns:
            bytes: parsed parameter
        """
        return bytes.fromhex(input) if input is not None else bytes("", "utf-8")

    def _serialize_container_output(
        self: ChainProcessor, output: ContainerOutput
    ) -> tuple[bytes, bytes, bytes]:
        """Serializes container output to conform to on-chain fn input

        Process:
            1. Check if all 5 keys are present in container output
                1.1. If so, parse returned output as raw bytes and generate returned data
            2. Else, serialize data into string and return as output

        Args:
            output (ContainerOutput): orchestrated container output

        Returns:
            tuple[bytes, bytes, bytes]: (input, output, proof)
        """

        # Check if all 5 keys are present in container output
        output_keys = output.output.keys()
        all_keys_exist = all(key in output_keys for key in RESPONSE_KEYS)

        # If all keys present, return parsed
        if all_keys_exist:
            return (
                # bytes(raw_input, processed_input)
                encode(
                    ["bytes", "bytes"],
                    [
                        self._serialize_param(output.output["raw_input"]),
                        self._serialize_param(output.output["processed_input"]),
                    ],
                ),
                # bytes(raw_output, processed_output)
                encode(
                    ["bytes", "bytes"],
                    [
                        self._serialize_param(output.output["raw_output"]),
                        self._serialize_param(output.output["processed_output"]),
                    ],
                ),
                # bytes(proof)
                self._serialize_param(output.output["proof"]),
            )

        # Else, return string-serialized data
        return (
            bytes("", "utf-8"),
            encode(["string"], [str(output.output)]),
            bytes("", "utf-8"),
        )

    async def _process_subscription(
        self: ChainProcessor,
        id: UnionID,
        subscription: Subscription,
        delegated: bool,
        delegated_params: Optional[tuple[CoordinatorSignatureParams, dict[Any, Any]]],
    ) -> None:
        """Processes subscription (collects inputs, runs containers, posts output
            on-chain)

        Process:
            1. Toggle pending execution for interval by blocking self._pending
            2. Collect latest input parameters, if needed, from chain
            3. Execute relevant containers via orchestrator
            4. Serialize container response
            5. Send deliver_compute (or delivate_compute_delegatee if delegated
                subscription) tx via wallet
            6. Update self._pending with accurate tx hash

        Args:
            id (UnionID): subscription ID
            subscription (Subscription): subscription
            delegated (bool): True if processing delegated subscription, else False
            delegated_params (
                Optional[tuple[CoordinatorSignatureParams, dict[Any, Any]]]
            ): delegated subscription signature, data
        """

        # Setup processing interval
        interval = subscription.interval
        log.info(
            "Processing subscription",
            id=id,
            interval=interval,
            delegated=delegated,
        )

        # Block pending execution
        self._pending[(id, interval)] = BLOCKED

        # Parse params if delegated subscription
        if delegated:
            parsed_params = cast(
                tuple[CoordinatorSignatureParams, dict[Any, Any]],
                delegated_params,
            )

        if delegated:
            # Setup off-chain inputs
            container_input = {
                "source": OrchestratorInputSource.OFFCHAIN.value,
                "data": parsed_params[1],
            }
        else:
            # Setup on-chain inputs
            chain_input = await self._coordinator.get_container_inputs(
                subscription=subscription,
                interval=interval,
                timestamp=int(time.time()),
                caller=self._wallet.address,
            )
            container_input = {
                "source": OrchestratorInputSource.ONCHAIN.value,
                "data": chain_input.hex(),
            }
        log.debug(
            "Setup container input",
            id=id,
            interval=interval,
            input=container_input,
        )

        # Execute containers
        container_results = await self._orchestrator.process_chain_processor_job(
            job_id=id,
            initial_input=container_input,
            containers=subscription.containers,
        )

        # Check if some container response received
        # If none, prevent blocking pending queue and return
        if len(container_results) == 0:
            log.error("Container results empty", id=id, interval=interval)
            del self._pending[(id, interval)]
            return

        # Check for container error
        # If error, prevent blocking pending queue and return
        last_result = container_results.pop()
        if isinstance(last_result, ContainerError):
            log.error(
                "Container execution errored",
                id=id,
                interval=interval,
                err=last_result,
            )
            del self._pending[(id, interval)]
            return
        # Else, log successful execution
        else:
            log.info("Container execution succeeded", id=id, interval=interval)
            log.debug("Container output", last_result=last_result)

        # Serialize container output
        (input, output, proof) = self._serialize_container_output(last_result)

        # Send on-chain submission tx
        if delegated:
            # Delegated subscriptions => deliver_compute_delegatee
            tx_hash = await self._wallet.deliver_compute_delegatee(
                subscription=subscription,
                signature=parsed_params[0],
                input=input,
                output=output,
                proof=proof,
            )
        else:
            # Regular subscriptions => deliver_compute
            tx_hash = await self._wallet.deliver_compute(
                subscription=subscription,
                input=input,
                output=output,
                proof=proof,
            )

        # Update pending with accurate tx hash
        self._pending[(id, interval)] = tx_hash.hex()
        log.info(
            "Sent tx",
            id=id,
            interval=interval,
            delegated=delegated,
            tx_hash=tx_hash.hex(),
        )

    async def track(self: ChainProcessor, msg: OnchainMessage) -> None:
        """Tracks incoming message by type

        Args:
            msg (OnchainMessage): incoming message
        """
        match msg.type:
            case MessageType.SubscriptionCreated:
                self._track_created_message(cast(SubscriptionCreatedMessage, msg))
            case MessageType.SubscriptionCancelled:
                self._track_cancelled_message(cast(SubscriptionCancelledMessage, msg))
            case MessageType.SubscriptionFulfilled:
                self._track_fulfilled_message(cast(SubscriptionFulfilledMessage, msg))
            case MessageType.DelegatedSubscription:
                await self._track_delegated_message(
                    cast(DelegatedSubscriptionMessage, msg)
                )
            case _:
                log.error("Unknown message type to track", message=msg)

    async def setup(self: ChainProcessor) -> None:
        """No async setup necessary"""
        pass

    async def run_forever(self: ChainProcessor) -> None:
        """Core ChainProcessor event loop

        Process:
            1. Every 500ms (note: not most efficient implementation, should just
              trigger as needed):
                1.1. Prune pending txs that have failed
                1.2. Check for subscriptions + delegated subscriptions that are active
                1.3. Filter for (subscription, interval)-pairs that do not have a
                  pending tx
                1.4. Filter for (subscription, interval)-pairs that do not have an
                  on-chain submitted tx
                1.5. Queue for processing
        """
        while not self._shutdown:
            # Prune pending txs that have failed
            create_task(self._prune_failed_txs())

            for subId, subscription in self._subscriptions.items():
                # Skips if subscription is not active
                if not subscription.active:
                    continue

                # Check if subscription needs processing
                # 1. Response for current interval must not be in pending queue
                # 2. Response for current interval must not have already been confirmed
                #   on-chain
                if not self._has_subscription_tx_pending_in_interval(subId):
                    if not await self._has_responded_onchain_in_interval(subId):
                        create_task(
                            self._process_subscription(
                                id=subId,
                                subscription=subscription,
                                delegated=False,
                                delegated_params=None,
                            )
                        )

            for delegateSubId, params in self._delegate_subscriptions.items():
                # Skips if subscription is not active
                if not params[0].active:
                    continue

                # Check if subscription needs processing
                # 1. Response for current interval must not be in pending queue
                # Unlike subscriptions, delegate subscriptions cannot have already
                # confirmed on-chain txs, since those would be tracked by their
                # on-chain ID and not as a delegate subscription
                if not self._has_subscription_tx_pending_in_interval(delegateSubId):
                    # If not, process subscription
                    create_task(
                        self._process_subscription(
                            id=delegateSubId,
                            subscription=params[0],
                            delegated=True,
                            delegated_params=(params[1], params[2]),
                        )
                    )

            # Sleep loop for 500ms
            await sleep(0.5)

    async def cleanup(self: ChainProcessor) -> None:
        """Stateless task, no cleanup necessary"""
        pass
