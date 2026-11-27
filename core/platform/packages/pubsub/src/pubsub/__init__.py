"""Universal Multi-Broker Pub/Sub platform capability package."""

from pubsub.adapters import (
    AmqpPublisherAdapter,
    AwsMessagePublisherAdapter,
    AwsSnsOutboxPublisher,
    AwsSqsConsumer,
    AwsSqsConsumerManager,
    AwsSqsOutboxPublisher,
    DefaultConsumerErrorHandler,
    InMemoryConsumerManager,
    InMemoryOutboxPublisher,
    InMemoryPublisherAdapter,
    KafkaConsumerManager,
    KafkaOutboxPublisher,
    KafkaPublisherAdapter,
)
from pubsub.config import PlatformPubSubSettings
from pubsub.domain import (
    AckableMessage,
    BrokerType,
    ConsumerError,
    ConsumerVerdict,
    NackCallbackPort,
    PublisherError,
    PublishResultDTO,
    PubSubError,
    UnsupportedBrokerSchemeError,
)
from pubsub.domain.exceptions import (
    BrokerTransportMismatchError,
    InvalidBrokerTransportError,
)
from pubsub.enums import (
    ConsumerAction,
    ConsumerDecision,
    ConsumerOutcome,
)
from pubsub.exceptions import (
    ConsumerTerminalError,
    ConsumerTransientError,
)
from pubsub.ports import (
    ConsumerErrorHandlerPort,
    ConsumerManagerPort,
    MessageConsumerPort,
    MessageHandler,
    MessagePublisherPort,
)
from pubsub.provider import PubSubProvider, create_default_broker_registry
from pubsub.registry import (
    BrokerPolicyGroup,
    BrokerTransportRegistry,
    BrokerTransportSpec,
    ConsumerBuildRequest,
    OutboxPublisherBuildRequest,
    PublisherBuildRequest,
    TransportPolicyViolation,
)

__all__ = [
    "AckableMessage",
    "AmqpPublisherAdapter",
    "AwsMessagePublisherAdapter",
    "AwsSnsOutboxPublisher",
    "AwsSqsConsumer",
    "AwsSqsConsumerManager",
    "AwsSqsOutboxPublisher",
    "BrokerPolicyGroup",
    "BrokerTransportMismatchError",
    "BrokerTransportRegistry",
    "BrokerTransportSpec",
    "BrokerType",
    "ConsumerAction",
    "ConsumerBuildRequest",
    "ConsumerDecision",
    "ConsumerError",
    "ConsumerErrorHandlerPort",
    "ConsumerManagerPort",
    "ConsumerOutcome",
    "ConsumerTerminalError",
    "ConsumerTransientError",
    "ConsumerVerdict",
    "DefaultConsumerErrorHandler",
    "InMemoryConsumerManager",
    "InMemoryOutboxPublisher",
    "InMemoryPublisherAdapter",
    "InvalidBrokerTransportError",
    "KafkaConsumerManager",
    "KafkaOutboxPublisher",
    "KafkaPublisherAdapter",
    "MessageConsumerPort",
    "MessageHandler",
    "MessagePublisherPort",
    "NackCallbackPort",
    "OutboxPublisherBuildRequest",
    "PlatformPubSubSettings",
    "PubSubError",
    "PubSubProvider",
    "PublishResultDTO",
    "PublisherBuildRequest",
    "PublisherError",
    "TransportPolicyViolation",
    "UnsupportedBrokerSchemeError",
    "create_default_broker_registry",
]
