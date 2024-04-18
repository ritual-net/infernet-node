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

    match str(e):
        case ManagerError.NodeNotActive.value:
            log.error("Node is not active", subscription_id=sub.id)
            return True
        case ManagerError.NodeNotRegisterable.value:
            log.error("Node is not registerable", subscription_id=sub.id)
            return True
        case ManagerError.CooldownActive.value:
            log.error("Cooldown is active", subscription_id=sub.id)
            return True
        case ManagerError.NodeNotActivateable.value:
            log.error("Node is not activateable", subscription_id=sub.id)
            return True
        case CoordinatorError.GasPriceExceeded.value:
            log.error(
                "Gas price exceeded the subscription's max gas price",
                subscription_id=sub.id,
            )
            return True
        case CoordinatorError.GasLimitExceeded.value:
            log.error(
                "Gas limit exceeded the subscription's max gas limit",
                subscription_id=sub.id,
            )
            return True
        case CoordinatorError.IntervalMismatch.value:
            log.error(
                "Interval mismatch. The interval is not the current one.",
                subscription_id=sub.id,
            )
            return True
        case CoordinatorError.IntervalCompleted.value:
            log.error(
                "Interval completed. Redundancy has been already met for the "
                "current interval",
                subscription_id=sub.id,
            )
            return True
        case CoordinatorError.NodeRespondedAlready.value:
            log.error("Node already responded for this interval", subscription_id=sub.id)
            return True
        case CoordinatorError.SubscriptionNotFound.value:
            log.error("Subscription not found", subscription_id=sub.id)
            return True
        case CoordinatorError.NotSubscriptionOwner.value:
            log.error(
                "Caller is not the owner of the subscription", subscription_id=sub.id
            )
            return True
        case CoordinatorError.SubscriptionCompleted.value:
            log.info(
                "Subscription is already completed, another node has likely already "
                "delivered the response",
                subscription_id=sub.id,
            )
            return True
        case CoordinatorError.SubscriptionNotActive.value:
            log.error("Subscription is not active", subscription_id=sub.id)
            return True
        case _:
            return False
