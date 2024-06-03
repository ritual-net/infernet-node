"""ChainProcessor

Handles processing of on-chain delivered subscriptions.
"""

from __future__ import annotations

import asyncio
import time
from asyncio import create_task, sleep
from copy import deepcopy
from typing import Any, Optional, Tuple, cast

from eth_abi import encode  # type: ignore
from eth_typing import HexStr
from web3.exceptions import ContractCustomError, ContractLogicError

from chain.container_lookup import ContainerLookup
from chain.coordinator import Coordinator, CoordinatorSignatureParams
from chain.errors import InfernetError
from chain.payment_wallet import PaymentWallet
from chain.registry import Registry
from chain.rpc import RPC
from chain.wallet import Wallet
from chain.wallet_checker import WalletChecker
from orchestration.orchestrator import Orchestrator
from shared.job import ContainerError, ContainerOutput, JobInput, JobLocation
from shared.message import (
    DelegatedSubscriptionMessage,
    MessageType,
    OnchainMessage,
    SubscriptionCreatedMessage,
)
from shared.service import AsyncTask
from shared.subscription import Subscription
from utils.constants import ZERO_ADDRESS
from utils.logging import log

# Blocked tx
BLOCKED: HexStr = cast(HexStr, "0xblocked")

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
DelegateSubscriptionID = Tuple[HexStr, int]  # in the format of f"{owner}-{nonce}"
UnionID = SubscriptionID | DelegateSubscriptionID
DelegateSubscriptionData = tuple[
    Subscription, CoordinatorSignatureParams, dict[Any, Any]
]


class ChainProcessor(AsyncTask):
    """Handles processing of on-chain delivered subscriptions.

    Process:
        1. Receives messages to track via `track()`
        2. Tracks messages (+ included subscriptions) according to type:
            2.1. SubscriptionCreatedMessage:
                Adds subscription to _subscriptions, indexed by ID
            2.4. DelegatedSubscriptionMessage:
                2.4.1. Checks if delegated subscription already exists on-chain
                  (by owner, nonce)
                2.4.2. Collects recover signer from signature
                2.4.3. Collects delegated signer from chain
                2.4.4. Verifies that recovered signer == delegated signer
                2.4.5. If verified, adds subscription to _delegate_subscriptions
                  indexed by str(owner-nonce)
        3. At each interval (default: every 100ms):
            3.1. Prune pending txs that have failed to allow for re-processing
                (successful txs pruned during event replay)
            3.2. Check for subscriptions
                3.2.1. If the node requires payment, check if the subscription has a
                    valid wallet and enough funds
                3.2.2. Check subscriptions that have been cancelled, and stop tracking
                3.2.3. Skip the inactive subscriptions
                3.2.4. Check if the subscription has already been completed, and stop
                    tracking
                3.2.5 Check if the subscription has passed the deadline, and stop
                    tracking
                3.2.6. Check if the subscription's transaction failure has exceeded the
                    maximum number of attempts, and if so, stop tracking
                3.2.7. Filter out ones where node has already submitted on-chain tx
                  for current interval, or has a pending tx submitted
                3.2.8. Queue for processing
            3.3. Check for delegated subscriptions that are tracked
                3.3.1. Skip the inactive subscriptions
                3.3.2. Check if the delegated subscription has already been completed,
                    and stop tracking
                3.3.3. Check if the delegated subscription's transaction failure has
                    exceeded the maximum number of attempts, and if so, stop tracking
                3.3.4. Filter out ones where node has a pending tx submitted
                3.3.5. Queue for processing

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
        _track_delegated_message: Handles event replayed DelegatedSubscriptionMessage(s)
        _has_responded_onchain_in_interval: Checks if local node wallet has responded
            on-chain for (subscription ID, interval)
        _prune_failed_txs: Prunes pending txs that have failed to allow for re-processing
        _stop_tracking: Stops tracking subscription (or delegated subscription)
        _has_subscription_tx_pending_in_interval: Checks if a tx is pending for
            (subscription ID, interval)
        _serialize_param: Serializes single container output param (consumed by
            _serialize_container_output)
        _serialize_container_output: Serializes orchestrator container output for
            on-chain consumption
        _stop_tracking_if_cancelled: Checks if subscription has been cancelled on-chain
        _stop_tracking_delegated_sub_if_completed: Checks if delegated subscription has
            already been completed, if so, stops tracking
        _stop_tracking_sub_if_completed: Checks if subscription has already been
            completed. If so, stops tracking
        _stop_tracking_if_maximum_retries_reached: Checks if subscription has exceeded
            the maximum number of attempts, if so, stops tracking.
        _stop_tracking_sub_if_missed_deadline: Checks if subscription has missed
            deadline, if so, stops tracking.
        _process_subscription: Handles subscription processing lifecycle

    Private attributes:
        _rpc (RPC): RPC instance
        _coordinator (Coordinator): Coordinator instance
        _wallet (Wallet): Wallet instance
        _wallet_checker (WalletChecker): WalletChecker instance
        _registry (Registry): Registry instance
        _subscriptions (dict[SubscriptionID, Subscription]): subscription ID => on-chain
            subscription
        _delegate_subscriptions (dict[DelegateSubscriptionID, DelegateSubscriptionData]):
            delegate subscription ID => delegate subscription data
        _pending (dict[tuple[UnionID, Interval], str]):
            (subscription ID, delivery interval) => tx hash
        _attempts (dict[tuple[UnionID, Interval], int]):
            (subscription ID, delivery interval) => number of failed tx attempts
        _attempts_lock (asyncio.Lock): Lock for _attempts dict
    """

    def __init__(
        self: ChainProcessor,
        rpc: RPC,
        coordinator: Coordinator,
        wallet: Wallet,
        payment_wallet: PaymentWallet,
        wallet_checker: WalletChecker,
        registry: Registry,
        orchestrator: Orchestrator,
        container_lookup: ContainerLookup,
    ):
        """Initializes new ChainProcessor

        Args:
            rpc (RPC): RPC instance
            coordinator (Coordinator): Coordinator instance
            wallet (Wallet): Wallet instance
            payment_wallet (PaymentWallet): PaymentWallet instance
            wallet_checker (WalletChecker): WalletChecker instance
            registry (Registry): Registry instance
            orchestrator (Orchestrator): Orchestrator instance
            container_lookup (ContainerLookup): ContainerLookup instance
        """

        # Initialize inherited AsyncTask
        super().__init__()

        self._rpc = rpc
        self._coordinator = coordinator
        self._wallet = wallet
        self._payment_wallet = payment_wallet
        self._wallet_checker = wallet_checker
        self._registry = registry
        self._orchestrator = orchestrator
        self._container_lookup = container_lookup

        # Subscription ID => subscription
        self._subscriptions: dict[SubscriptionID, Subscription] = {}

        # Delegate subscription ID => (subscription, signature, data)
        self._delegate_subscriptions: dict[
            DelegateSubscriptionID,
            DelegateSubscriptionData,
        ] = {}

        # (Union subscription ID, interval) => tx_hash
        self._pending: dict[tuple[UnionID, Interval], HexStr] = {}

        # (Union subscription ID, interval) => attempts
        self._attempts: dict[tuple[UnionID, Interval], int] = {}
        log.info("Initialized ChainProcessor")
        self._attempts_lock = asyncio.Lock()

    def _track_created_message(
        self: ChainProcessor, msg: SubscriptionCreatedMessage
    ) -> None:
        """Tracks SubscriptionCreatedMessage

        Process:
            1. Adds subscription to tracked _subscriptions

        Args:
            msg (SubscriptionCreatedMessage): subscription creation message
        """

        # Add subscription to tracked _subscriptions
        self._subscriptions[msg.subscription.id] = msg.subscription
        log.info(
            "Tracked new subscription!",
            id=msg.subscription.id,
            total=len(self._subscriptions.keys()),
        )

    async def _track_delegated_message(
        self: ChainProcessor, msg: DelegatedSubscriptionMessage
    ) -> None:
        """Tracks DelegatedSubscriptionMessage

        Process:
            1. Checks if delegated subscription already exists on-chain
                1.1. If so, evicts relevant run from pending and attempts to allow
                forced re-execution
            2. Collects recovered signer from signature
            3. Collects delegated signer from chain
            4. Verifies that recovered signer == delegated signer
            5. If verified, adds subscription to _delegate_subscriptions,
                indexed by (owner, nonce)

        Args:
            msg (DelegatedSubscriptionMessage): delegated subscription message
        """

        # Collect message inputs
        subscription: Subscription = msg.subscription.deserialize(
            self._container_lookup
        )
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

        # If delegate subscription already exists on-chain
        if exists:
            # Check if subscription is tracked locally, this can happen if the
            # user made a delegated subscription request again through the rest API,
            # or if another node had already created the same delegated subscription
            tracked = id in self._subscriptions
            log.info("Delegated subscription exists on-chain", id=id, tracked=tracked)

            # Evict current delegate runs from pending and attempts
            # Allows reprocessing failed delegate subscriptions, if they exist
            async with self._attempts_lock:
                key = (
                    (cast(HexStr, subscription.owner), signature.nonce),
                    subscription.interval,
                )
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
        sub_id: DelegateSubscriptionID = (
            cast(HexStr, subscription.owner),
            signature.nonce,
        )

        self._delegate_subscriptions[sub_id] = (
            subscription,
            signature,
            msg.data,
        )

        log.info(
            "Tracked new delegate subscription",
            sub_id=sub_id,
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
            log.info(
                "Node has already responded for this interval",
                id=sub.id,
                interval=sub.interval,
            )
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

        async with self._attempts_lock:
            # Make deep copy to avoid mutation during iteration
            pending_copy = deepcopy(self._pending)
            for (id, interval), tx_hash in pending_copy.items():
                # Check if tx_hash is not blocked
                if tx_hash != BLOCKED:
                    # Check if tx failed on-chain
                    (found, success) = await self._rpc.get_tx_success(tx_hash)
                    if not found:
                        continue
                    if success:
                        # clean attempts count
                        if (id, interval) in self._attempts:
                            self._attempts.pop((id, interval))
                    else:
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

                """
                If < 3 failed attempts, evict failed tx, the subscription will be
                reprocessed.

                If >= 3 failed attempts, the subscription will be deleted
                in the next cycle of the loop in: self.check_max_attempts
                """
                attempt_count = self._attempts[key]
                log.debug("attempt count", count=attempt_count, key=key)
                if attempt_count < 3:
                    self._pending.pop(key)
                    log.info(
                        "Evicted failed tx",
                        id=id,
                        interval=interval,
                        tx_hash=tx_hash,
                        retries=attempt_count,
                    )

    def _stop_tracking(
        self: ChainProcessor, subscription_id: UnionID, delegated: bool
    ) -> None:
        """Stops tracking subscription (or delegated subscription)
            1. Deletes subscription from _subscriptions or _delegate_subscriptions
            2. Deletes any pending transactions being checked

        Args:
            subscription_id (UnionID): subscription ID
            delegated (bool): True if tracking delegated subscription, else False.
                Defaults to False.
        """

        if delegated:
            if subscription_id in self._delegate_subscriptions:
                del self._delegate_subscriptions[
                    cast(DelegateSubscriptionID, subscription_id)
                ]

        else:
            if subscription_id in self._subscriptions:
                del self._subscriptions[cast(SubscriptionID, subscription_id)]

        for key in list(self._pending.copy().keys()):
            if key[0] == subscription_id:
                del self._pending[key]
                log.debug(
                    "Deleted pending transactions being checked",
                    id=subscription_id,
                    interval=key[1],
                )

        log.info(
            f"Stopped tracking subscription: {subscription_id}",
            id=subscription_id,
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

    async def _stop_tracking_if_sub_owner_cant_pay(
        self: ChainProcessor, sub_id: SubscriptionID
    ) -> bool:
        """
        Check if the subscription owner can pay for the subscription. If not, stop
        tracking the subscription. Checks for:
        1. Invalid wallet
        2. Insufficient balance

        Args:
            sub_id (SubscriptionID): subscription ID
        """
        sub = self._subscriptions.get(sub_id)
        # checking if sub is None is necessary because the subscription may have been
        # deleted in _process_subscription
        if sub is None:
            return True

        banner = f"Skipping subscription: {sub_id}"

        if not await self._wallet_checker.is_valid_wallet(sub.wallet):
            log.info(
                f"{banner}: Invalid subscription wallet, please use a wallet generated "
                f"by infernet's `WalletFactory`",
                sub_id=sub.id,
                wallet=sub.wallet,
            )
            self._stop_tracking(sub.id, delegated=False)
            return True

        has_balance, balance = await self._wallet_checker.has_enough_balance(
            sub.wallet, sub.payment_token, sub.payment_amount
        )

        if not has_balance:
            log.info(
                f"{banner}: Subscription wallet has insufficient balance",
                sub_id=sub.id,
                wallet=sub.wallet,
                sub_amount=sub.payment_amount,
                wallet_balance=balance,
            )
            self._stop_tracking(sub.id, delegated=False)
            return True

        return False

    async def _stop_tracking_if_cancelled(
        self: ChainProcessor, sub_id: SubscriptionID
    ) -> bool:
        """Check if the subscription has been cancelled on-chain, if so, stop tracking it

        Args:
            sub_id (SubscriptionID): subscription ID

        Returns:
            bool: True if subscription has been cancelled, else False
        """
        sub: Subscription = await self._coordinator.get_subscription_by_id(
            sub_id, await self._rpc.get_head_block_number()
        )
        if sub.cancelled:
            log.info("Subscription cancelled", id=sub_id)
            self._stop_tracking(sub.id, delegated=False)
            return True
        return False

    async def _stop_tracking_delegated_sub_if_completed(
        self: ChainProcessor, sub_id: DelegateSubscriptionID
    ) -> bool:
        """Check if the delegated subscription has already been completed. If so, stop
        tracking it.

        Note that delegated subscriptions may not have a subscription id yet generated,
        since we allow for delegated subscriptions to be created & fulfilled in the same
        transaction. In such cases, we use the owner-nonce pair as the subscription id.

        For delegated subscriptions, we only check if the transaction has already been
        submitted and was successful.
            1. For one-off delegated subscriptions (where redundancy=1 & frequency =1),
            this is sufficient.
            2. For recurring delegated subscriptions (redundancy>1 or frequency>1),
            the same subscription will get tracked again as it will show up on-chain
            & will get picked up by the listener. Past that point, the tracking of that
            subscription will be handled by the regular subscription tracking logic.

        Args:
            sub_id (DelegateSubscriptionID): delegated subscription ID

        Returns:
            bool: True if delegated subscription has already been completed, else False
        """
        sub: Subscription = self._delegate_subscriptions[sub_id][0]

        tx_hash: Optional[HexStr] = self._pending.get((sub_id, sub.interval), None)

        if tx_hash is None or tx_hash == BLOCKED:
            # We have not yet submitted the transaction for this delegated subscription
            return False

        (found, success) = await self._rpc.get_tx_success_with_retries(tx_hash)

        if found and success:
            # We have already submitted the transaction and it was successful
            log.info(
                "Delegated subscription completed for interval",
                id=sub_id,
                interval=sub.interval,
            )
            self._stop_tracking(sub_id, delegated=True)
            return True

        return False

    async def _stop_tracking_sub_if_completed(
        self: ChainProcessor, subscription: Subscription
    ) -> bool:
        """Check if the subscription has already been completed. If so, stop tracking it.

        This updates the response count for the subscription by reading it from on-chain
        storage. If the subscription has already been completed, it stops tracking it.

        Args:
            subscription (Subscription): subscription

        Returns:
            bool: True if subscription has already been completed, else False
        """

        _id, interval = subscription.id, subscription.interval
        response_count = await self._coordinator.get_subscription_response_count(
            _id, interval
        )
        subscription.set_response_count(interval, response_count)
        if subscription.completed:
            log.info(
                "Subscription already completed",
                id=subscription.id,
                interval=subscription.interval,
            )
            self._stop_tracking(subscription.id, delegated=False)
            return True
        return False

    async def _stop_tracking_if_maximum_retries_reached(
        self: ChainProcessor, sub_key: tuple[UnionID, Interval], delegated: bool
    ) -> bool:
        """Check if the subscription has exceeded the maximum number of attempts. If so,
            stop tracking it.

        Args:
            sub_key (tuple[UnionID, Interval]): subscription ID, interval
            delegated (bool): True if tracking delegated subscription, else False

        Returns:
            bool: True if the subscription has exceeded the maximum number of attempts,
            else False
        """
        if sub_key in self._attempts:
            attempt_count = self._attempts[sub_key]
            if attempt_count >= 3:
                log.error(
                    "Subscription has exceeded the maximum number of attempts",
                    id=sub_key[0],
                    interval=sub_key[1],
                    tx_hash=self._pending[sub_key],
                    attempts=attempt_count,
                )

                # clear attempts
                log.info("Clearing attempts", sub_key=sub_key)
                self._attempts.pop(sub_key)

                async with self._attempts_lock:
                    # delete subscription
                    self._stop_tracking(sub_key[0], delegated)

                return True
        return False

    def _stop_tracking_sub_if_missed_deadline(
        self: ChainProcessor, subscription_id: UnionID, delegated: bool
    ) -> bool:
        """Check if the subscription has missed the deadline. If so, stop tracking it.

        Args:
            subscription_id (UnionID): subscription ID
            delegated (bool): True if tracking delegated subscription, else False

        Returns:
            bool: True if the subscription has missed the deadline, else False
        """
        subscription = (
            self._subscriptions.get(cast(SubscriptionID, subscription_id))
            if not delegated
            else self._delegate_subscriptions.get(
                cast(DelegateSubscriptionID, subscription_id), [None]
            )[0]
        )
        # checking if subscription is None is necessary because the subscription may have
        # been deleted in _process_subscription
        if subscription is None:
            return True

        if subscription.past_last_interval:
            log.info(
                "Subscription expired",
                id=subscription.id,
                interval=subscription.interval,
            )
            # delete the subscription
            self._stop_tracking(subscription_id, delegated)
            return True

        return False

    async def _stop_tracking_if_infernet_errors_caught_in_simulation(
        self: ChainProcessor,
        subscription: Subscription,
        delegated: bool,
        signature: Optional[CoordinatorSignatureParams] = None,
    ) -> bool:
        """
        We first attempt a delivery with empty (input, output, proof) to check if there
        are any infernet-related errors caught during the transaction simulation. This
        allows us to catch a multitude of errors even if we had run the compute. This
        prevents the node from wasting resources on a compute that would have failed
        on-chain.

        Args:
            subscription (Subscription): subscription
            delegated (bool): True if processing delegated subscription, else False
            signature (Optional[CoordinatorSignatureParams]): delegated subscription
                signature, in case of normal subscription, it should be None

        Returns:
            bool: True if the subscription has any infernet-related errors, else False
        """
        if subscription.prover != ZERO_ADDRESS:
            return False
        try:
            await self._deliver(
                subscription=subscription,
                delegated=delegated,
                signature=signature,
                simulate_only=True,
            )
        except InfernetError:
            if subscription.is_callback:
                self._stop_tracking(subscription.id, delegated)
                return True
        except Exception:
            pass
        return False

    async def _deliver(
        self: ChainProcessor,
        subscription: Subscription,
        delegated: bool,
        signature: Optional[CoordinatorSignatureParams],
        simulate_only: bool = False,
        input: bytes = b"",
        output: bytes = b"",
        proof: bytes = b"",
    ) -> bytes:
        """
        Deliver the compute to the chain.

        Args:
            subscription (Subscription): subscription
            delegated (bool): True if processing delegated subscription, else False
            signature (Optional[CoordinatorSignatureParams]): delegated subscription
                signature, in case of normal subscription, it should be None
            simulate_only (bool): If set, the transaction is only simulated & not sent,
                used to pre-emptively check for subscriptions that would've failed even
                with correct compute delivered.
            input (bytes): input
            output (bytes): output
            proof (bytes): proof
        """
        if delegated:
            # Delegated subscriptions => deliver_compute_delegatee
            tx_hash = await self._wallet.deliver_compute_delegatee(
                subscription=subscription,
                signature=cast(CoordinatorSignatureParams, signature),
                input=input,
                output=output,
                proof=proof,
                simulate_only=simulate_only,
            )
        else:
            # Regular subscriptions => deliver_compute
            tx_hash = await self._wallet.deliver_compute(
                subscription=subscription,
                input=input,
                output=output,
                proof=proof,
                simulate_only=simulate_only,
            )
        return tx_hash

    async def _execute_on_containers(
        self: ChainProcessor,
        subscription: Subscription,
        delegated: bool,
        delegated_params: Optional[tuple[CoordinatorSignatureParams, dict[Any, Any]]],
    ) -> list[ContainerOutput | ContainerError]:
        # todo: tell the container if an on-chain sub request needs proof
        if delegated:
            # Setup off-chain inputs
            parsed_params = cast(
                tuple[CoordinatorSignatureParams, dict[Any, Any]],
                delegated_params,
            )
            container_input = JobInput(
                source=JobLocation.OFFCHAIN.value,
                destination=JobLocation.ONCHAIN.value,
                data=parsed_params[1],
            )
        else:
            # Setup on-chain inputs
            chain_input = await self._coordinator.get_container_inputs(
                subscription=subscription,
                interval=subscription.interval,
                timestamp=int(time.time()),
                caller=self._wallet.address,
            )
            container_input = JobInput(
                source=JobLocation.ONCHAIN.value,
                destination=JobLocation.ONCHAIN.value,
                data=chain_input.hex(),
            )

        log.debug(
            "Setup container input",
            id=id,
            interval=subscription.interval,
            input=container_input,
        )

        # Execute containers
        return await self._orchestrator.process_chain_processor_job(
            job_id=id,
            job_input=container_input,
            containers=subscription.containers,
            requires_proof=subscription.requires_proof,
        )

    async def _escrow_reward_in_wallet(
        self: ChainProcessor, subscription: Subscription
    ) -> None:
        # get escrow wallet instance
        log.info(
            "Escrowing reward in wallet",
            id=subscription.id,
            token=subscription.payment_token,
            amount=subscription.payment_amount,
            spender=self._registry.coordinator,
        )
        await self._payment_wallet.approve(
            self._rpc.account,
            subscription.payment_token,
            subscription.payment_amount,
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

        # # check if we missed the subscription deadline
        if self._stop_tracking_sub_if_missed_deadline(id, delegated):
            return

        # Block pending execution
        self._pending[(id, interval)] = BLOCKED

        if await self._stop_tracking_if_infernet_errors_caught_in_simulation(
            subscription, delegated, delegated_params and delegated_params[0]
        ):
            return

        # Execute containers
        container_results = await self._execute_on_containers(
            subscription=subscription,
            delegated=delegated,
            delegated_params=delegated_params,
        )

        if subscription.prover != ZERO_ADDRESS:
            # allow wallet to be escrowed
            await self._escrow_reward_in_wallet(subscription)

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
            if subscription.is_callback:
                self._stop_tracking(subscription.id, delegated)
            return
        elif (code := last_result.output.get("code")) is not None and code != "200":
            log.error(
                "Container execution errored",
                id=id,
                interval=interval,
                err=last_result,
            )
            del self._pending[(id, interval)]
            if subscription.is_callback:
                self._stop_tracking(subscription.id, delegated)
            return
        # Else, log successful execution
        else:
            log.info("Container execution succeeded", id=id, interval=interval)
            log.debug("Container output", last_result=last_result)

        # Serialize container output
        (input, output, proof) = self._serialize_container_output(last_result)

        try:
            tx_hash = await self._deliver(
                subscription=subscription,
                delegated=delegated,
                signature=delegated_params[0]
                if delegated and delegated_params
                else None,
                input=input,
                output=output,
                proof=proof,
            )
        except (InfernetError, ContractLogicError, ContractCustomError):
            # transaction simulation failed
            # if it's a callback subscription, we can stop tracking it
            # delegated subscriptions will expire instead
            if subscription.is_callback:
                self._stop_tracking(subscription.id, delegated)
            log.info(
                "Did not send tx",
                subscription=subscription,
                id=id,
                interval=interval,
                delegated=delegated,
            )
            return
        except Exception as e:
            log.error(
                f"Failed to send tx {e}",
                subscription=subscription,
                id=id,
                interval=interval,
                delegated=delegated,
            )
            if subscription.is_callback:
                self._stop_tracking(subscription.id, delegated)
            return

        # Update pending with accurate tx hash
        self._pending[(id, interval)] = cast(HexStr, tx_hash.hex())
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
            1. Every 100ms (note: not most efficient implementation, should just
              trigger as needed):
                For each subscription:
                    1.1. Prune pending txs that have failed
                    1.2 If the node requires payment, check if the subscription has a
                        valid wallet and enough funds
                    1.3 Check subscriptions that have been cancelled, and stop tracking
                    1.4 Skip the inactive subscriptions
                    1.5 Check if the subscription has already been completed, and stop
                        tracking
                    1.6 Check if the subscription has passed the deadline, and stop
                        tracking
                    1.7 Check if the subscription's transaction failure has exceeded the
                        maximum number of attempts, and if so, stop tracking
                    1.8 Filter out ones where node has already submitted on-chain tx
                        for current interval, or has a pending tx submitted
                    1.9 If all above checks pass, queue for processing
                For each delegated subscription:
                    1.1 Skip the inactive subscriptions
                    1.2 Check if the delegated subscription has already been completed,
                        and stop tracking
                    1.3 Check if the delegated subscription's transaction failure has
                        exceeded the maximum number of attempts, and if so, stop tracking
                    1.4 Filter out ones where node has a pending tx submitted
                    1.5 Queue for processing
        """
        while not self._shutdown:
            # Prune pending txs that have failed
            create_task(self._prune_failed_txs())

            # Make deep copy to avoid mutation during iteration
            subscriptions_copy = deepcopy(self._subscriptions)

            for sub_id, subscription in subscriptions_copy.items():
                # Checks if sub owner has a valid wallet & enough funds
                if await self._stop_tracking_if_sub_owner_cant_pay(sub_id):
                    continue

                # since cancellation means active_at == UINT32_MAX, we should
                # check if the subscription is cancelled before checking activation
                if await self._stop_tracking_if_cancelled(sub_id):
                    continue

                # Skips if subscription is not active
                if not subscription.active:
                    log.info(
                        "Ignored inactive subscription",
                        id=sub_id,
                        diff=subscription._active_at - time.time(),
                    )
                    continue

                if await self._stop_tracking_sub_if_completed(subscription):
                    continue

                if self._stop_tracking_sub_if_missed_deadline(
                    subscription.id, delegated=False
                ):
                    continue

                if await self._stop_tracking_if_maximum_retries_reached(
                    (sub_id, subscription.interval), delegated=False
                ):
                    continue

                # Check if subscription needs processing
                # 1. Response for current interval must not be in pending queue
                # 2. Response for current interval must not have already been confirmed
                #   on-chain
                if not self._has_subscription_tx_pending_in_interval(sub_id):
                    if not await self._has_responded_onchain_in_interval(sub_id):
                        create_task(
                            self._process_subscription(
                                id=sub_id,
                                subscription=subscription,
                                delegated=False,
                                delegated_params=None,
                            )
                        )

            # Make deep copy to avoid mutation during iteration
            delegate_subscriptions_copy = deepcopy(self._delegate_subscriptions)

            for delegate_sub_id, params in delegate_subscriptions_copy.items():
                # Skips if subscription is not active
                subscription = params[0]

                if not subscription.active:
                    log.debug(
                        "Ignored inactive subscription",
                        id=delegate_sub_id,
                        diff=subscription._active_at - time.time(),
                    )
                    continue

                if await self._stop_tracking_delegated_sub_if_completed(
                    delegate_sub_id
                ):
                    continue

                if await self._stop_tracking_if_maximum_retries_reached(
                    (delegate_sub_id, subscription.interval), delegated=True
                ):
                    continue

                # Check if subscription needs processing
                # 1. Response for current interval must not be in pending queue
                # Unlike subscriptions, delegate subscriptions cannot have already
                # confirmed on-chain txs, since those would be tracked by their
                # on-chain ID and not as a delegate subscription
                if not self._has_subscription_tx_pending_in_interval(delegate_sub_id):
                    # If not, process subscription
                    create_task(
                        self._process_subscription(
                            id=delegate_sub_id,
                            subscription=params[0],
                            delegated=True,
                            delegated_params=(params[1], params[2]),
                        )
                    )

            # Sleep loop for 100ms
            await sleep(0.1)

    async def cleanup(self: ChainProcessor) -> None:
        """Stateless task, no cleanup necessary"""
        pass
