from enum import Enum

from web3.exceptions import ContractCustomError

from shared import Subscription
from utils.logging import log


class ManagerError(Enum):
    """
    enums for mapping the 4-byte signature of the manager errors
    """

    NodeNotActive = "0x8741cbb8"
    NodeNotRegisterable = "0x5acfd518"
    CooldownActive = "0xc84b5bdd"
    NodeNotActivateable = "0x33daa7f9"


class CoordinatorError(Enum):
    """
    enums for mapping the 4-byte signature of the coordinator errors
    """

    GasPriceExceeded = "0x682bad5a"
    GasLimitExceeded = "0xbe9179a6"
    IntervalMismatch = "0x4db310c3"
    IntervalCompleted = "0x2f4ca85b"
    NodeRespondedAlready = "0x88a21e4f"
    SubscriptionNotFound = "0x1a00354f"
    NotSubscriptionOwner = "0xa7fba711"
    SubscriptionCompleted = "0xae6704a7"
    SubscriptionNotActive = "0xefb74efe"


node_not_active_error = "Node is not active"
node_not_registerable_error = "Node is not registerable"
cooldown_active_error = "Cooldown is active"
node_not_activateable_error = "Node is not activateable"
gas_price_exceeded_error = "Gas price exceeded the subscription's max gas price"
gas_limit_exceeded_error = "Gas limit exceeded the subscription's max gas limit"
interval_mismatch_error = "Interval mismatch. The interval is not the current one."
interval_completed_error = (
    "Interval completed. Redundancy has been already met for the current interval"
)
node_responded_already_error = "Node already responded for this interval"
subscription_not_found_error = "Subscription not found"
not_subscription_owner_error = "Caller is not the owner of the subscription"
subscription_completed_error = (
    "Subscription is already completed, another node "
    "has likely already delivered the response"
)
subscription_not_active_error = "Subscription is not active"


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
        ManagerError.NodeNotActive.value: node_not_active_error,
        ManagerError.NodeNotRegisterable.value: node_not_registerable_error,
        ManagerError.CooldownActive.value: cooldown_active_error,
        ManagerError.NodeNotActivateable.value: node_not_activateable_error,
        CoordinatorError.GasPriceExceeded.value: gas_price_exceeded_error,
        CoordinatorError.GasLimitExceeded.value: gas_limit_exceeded_error,
        CoordinatorError.IntervalMismatch.value: interval_mismatch_error,
        CoordinatorError.IntervalCompleted.value: interval_completed_error,
        CoordinatorError.NodeRespondedAlready.value: node_responded_already_error,
        CoordinatorError.SubscriptionNotFound.value: subscription_not_found_error,
        CoordinatorError.NotSubscriptionOwner.value: not_subscription_owner_error,
        CoordinatorError.SubscriptionCompleted.value: subscription_completed_error,
        CoordinatorError.SubscriptionNotActive.value: subscription_not_active_error,
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
