from dataclasses import dataclass
from enum import Enum
from typing import Any, Union

from chain.coordinator import CoordinatorSignatureParams
from shared.subscription import SerializedSubscription, Subscription


class MessageType(Enum):
    """Message types"""

    OffchainJob = 0
    DelegatedSubscription = 1
    SubscriptionCreated = 2


@dataclass(frozen=True)
class BaseMessage:
    """Base off-chain message"""

    id: str
    ip: str


@dataclass(frozen=True)
class OffchainJobMessage(BaseMessage):
    """Off-chain orginating, off-chain delivery job message"""

    containers: list[str]
    data: dict[Any, Any]
    type: MessageType = MessageType.OffchainJob


@dataclass(frozen=True)
class DelegatedSubscriptionMessage(BaseMessage):
    """Off-chain originating, on-chain delivery message"""

    subscription: SerializedSubscription
    signature: CoordinatorSignatureParams
    data: dict[Any, Any]
    type: MessageType = MessageType.DelegatedSubscription


@dataclass(frozen=True)
class SubscriptionCreatedMessage:
    """On-chain subscription creation event"""

    subscription: Subscription
    type: MessageType = MessageType.SubscriptionCreated


# Type alias for off-chain originating message
OffchainMessage = Union[OffchainJobMessage, DelegatedSubscriptionMessage]

# Type alias for coordinator event messages
CoordinatorMessage = Union[SubscriptionCreatedMessage,]

# Type alias for filtered event message
FilteredMessage = Union[OffchainMessage, CoordinatorMessage]

# Type alias for pre-filtered event messages
PrefilterMessage = Union[OffchainMessage, CoordinatorMessage]

# Type alias for on-chain processed messages
OnchainMessage = Union[CoordinatorMessage, DelegatedSubscriptionMessage]


@dataclass(frozen=True)
class GuardianError:
    """Guardian error"""

    message: PrefilterMessage
    error: str
    params: dict[str, Any]
