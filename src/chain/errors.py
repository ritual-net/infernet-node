from enum import Enum, IntEnum

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
        ManagerError.NodeNotActive.value: "Node is not active",
        ManagerError.NodeNotRegisterable.value: "Node is not registerable",
        ManagerError.CooldownActive.value: "Cooldown is active",
        ManagerError.NodeNotActivateable.value: "Node is not activateable",
        CoordinatorError.GasPriceExceeded.value: "Gas price exceeded the subscription's max gas price",
        CoordinatorError.GasLimitExceeded.value: "Gas limit exceeded the subscription's max gas limit",
        CoordinatorError.IntervalMismatch.value: "Interval mismatch. The interval is not the current one.",
        CoordinatorError.IntervalCompleted.value: "Interval completed. Redundancy has been already met for the current interval",
        CoordinatorError.NodeRespondedAlready.value: "Node already responded for this interval",
        CoordinatorError.SubscriptionNotFound.value: "Subscription not found",
        CoordinatorError.NotSubscriptionOwner.value: "Caller is not the owner of the subscription",
        CoordinatorError.SubscriptionCompleted.value: "Subscription is already completed, another node has likely already delivered the response",
        CoordinatorError.SubscriptionNotActive.value: "Subscription is not active",
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
