from enum import Enum

from web3.exceptions import ContractCustomError

from shared import Subscription
from utils.logging import log


class CoordinatorError(Enum):
    """
    enums for mapping the 4-byte signature of the coordinator errors
    """

    InvalidWallet = "0x23455ba1"
    IntervalMismatch = "0x4db310c3"
    IntervalCompleted = "0x2f4ca85b"
    UnauthorizedProver = "0x8ebcfe1e"
    NodeRespondedAlready = "0x88a21e4f"
    SubscriptionNotFound = "0x1a00354f"
    ProofRequestNotFound = "0x1d68b37c"
    NotSubscriptionOwner = "0xa7fba711"
    SubscriptionCompleted = "0xae6704a7"
    SubscriptionNotActive = "0xefb74efe"
    UnsupportedProverToken = "0xa1e29b31"


class EIP712CoordinatorError(Enum):
    SignerMismatch = "0x10c74b03"
    SignatureExpired = "0x0819bdcd"


class WalletError(Enum):
    TransferFailed = "0x90b8ec18"
    InsufficientFunds = "0x356680b7"
    InsufficientAllowance = "0x13be252b"


class AllowlistError(Enum):
    NodeNotAllowed = "0x42764946"


class ERC20Error(Enum):
    InsufficientBalance = "0xf4d678b8"


invalid_wallet_error = (
    "Invalid wallet, please make sure you're using a wallet created "
    "from Infernet's `WalletFactory`."
)
interval_mismatch_error = "Interval mismatch. The interval is not the current one."
interval_completed_error = (
    "Interval completed. Redundancy has been already met for the current interval"
)
unauthorized_prover_error = "Prover is not authorized."
node_responded_already_error = "Node already responded for this interval"
subscription_not_found_error = "Subscription not found"
proof_request_not_found_error = "Proof request not found"
not_subscription_owner_error = "Caller is not the owner of the subscription"
subscription_completed_error = (
    "Subscription is already completed, another node "
    "has likely already delivered the response"
)
subscription_not_active_error = "Subscription is not active"
unsupported_prover_token_error = (
    "Unsupported prover token. Attempting to pay a `IProver`-contract in a token it "
    "does not support receiving payments in"
)
signer_mismatch_error = "Signer does not match."
signature_expired_error = "EIP-712 Signature has expired."
transfer_failed_error = "Token transfer failed."
insufficient_funds_error = (
    "Insufficient funds. You either are trying to withdraw `amount > "
    "unlockedBalance` or are trying to escrow `amount > unlockedBalance`"
    "or attempting to unlock `amount > lockedBalance`"
)
insufficient_allowance_error = "Insufficient allowance."
node_not_allowed_error = "Node is not allowed to deliver this subscription."
insufficient_balance_error = "Insufficient balance."


def is_infernet_error(e: ContractCustomError, sub: Subscription) -> bool:
    """
    Checks if the error belongs to the infernet contracts based on its 4-byte signature,
    and prints a helpful message and returns true if it does.

    Args:
        e (ContractCustomError): The error object
        sub (Subscription): The subscription object, used for logging

    Returns:
        bool: True if the error belongs to the coordinator, False otherwise
    """
    error_message = str(e)

    # List of errors and corresponding log messages
    errors = {
        CoordinatorError.InvalidWallet.value: invalid_wallet_error,
        CoordinatorError.IntervalMismatch.value: interval_mismatch_error,
        CoordinatorError.IntervalCompleted.value: interval_completed_error,
        CoordinatorError.UnauthorizedProver.value: unauthorized_prover_error,
        CoordinatorError.NodeRespondedAlready.value: node_responded_already_error,
        CoordinatorError.SubscriptionNotFound.value: subscription_not_found_error,
        CoordinatorError.ProofRequestNotFound.value: proof_request_not_found_error,
        CoordinatorError.NotSubscriptionOwner.value: not_subscription_owner_error,
        CoordinatorError.SubscriptionCompleted.value: subscription_completed_error,
        CoordinatorError.SubscriptionNotActive.value: subscription_not_active_error,
        CoordinatorError.UnsupportedProverToken.value: unsupported_prover_token_error,
        EIP712CoordinatorError.SignerMismatch.value: signer_mismatch_error,
        EIP712CoordinatorError.SignatureExpired.value: signature_expired_error,
        WalletError.TransferFailed.value: transfer_failed_error,
        WalletError.InsufficientFunds.value: insufficient_funds_error,
        WalletError.InsufficientAllowance.value: insufficient_allowance_error,
        AllowlistError.NodeNotAllowed.value: node_not_allowed_error,
        ERC20Error.InsufficientBalance.value: insufficient_balance_error,
    }

    for error_value, message in errors.items():
        if error_value in error_message:
            _log = (
                log.info
                if error_value
                in (
                    CoordinatorError.NodeRespondedAlready.value,
                    CoordinatorError.SubscriptionCompleted.value,
                    CoordinatorError.IntervalCompleted.value,
                )
                else log.error
            )
            _log(message, subscription_id=sub.id)
            return True

    return False
