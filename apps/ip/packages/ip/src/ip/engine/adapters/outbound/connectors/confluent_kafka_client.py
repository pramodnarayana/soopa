"""Enterprise confluent-kafka (librdkafka) adapter implementing KafkaProducerClientPort."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping, Sequence
from typing import Final

import structlog
from confluent_kafka import KafkaError, KafkaException, Message, Producer
from confluent_kafka.admin import AdminClient
from ip.engine.domain.dispatch.enums import FailureDisposition
from ip.engine.domain.exceptions import ConnectionCheckError, KafkaConnectionError, Result
from ip.engine.ports.outbound.kafka_client_port import (
    KafkaProducerClientFactoryPort,
    KafkaProducerClientPort,
    KafkaProduceResultDTO,
)
from seedwork.domain.types import JsonDict

logger = structlog.get_logger(__name__)

_DEFAULT_SOCKET_TIMEOUT_MS: Final[int] = 10000
_DEFAULT_RETRY_BACKOFF_MS: Final[int] = 250
_DEFAULT_RETRIES: Final[int] = 5


def build_confluent_kafka_config(
    public_config: JsonDict,
    credentials: JsonDict,
) -> dict[str, str | int | float | bool]:
    """Translates generic public configuration and credentials into librdkafka configuration properties."""
    bootstrap_servers = str(public_config.get("bootstrap_servers", "")).strip()
    client_id = str(public_config.get("client_id", "soopa-ip-producer")).strip()
    security_protocol = str(public_config.get("security_protocol", "PLAINTEXT")).strip().upper()
    acks = str(public_config.get("acks", "all")).strip().lower()
    compression = str(public_config.get("compression_type", "snappy")).strip().lower()

    raw_retries = public_config.get("retries", _DEFAULT_RETRIES)
    retries = int(raw_retries) if isinstance(raw_retries, (int, str)) else _DEFAULT_RETRIES
    raw_backoff = public_config.get("retry_backoff_ms", _DEFAULT_RETRY_BACKOFF_MS)
    retry_backoff_ms = (
        int(raw_backoff) if isinstance(raw_backoff, (int, str)) else _DEFAULT_RETRY_BACKOFF_MS
    )
    raw_timeout = public_config.get("socket_timeout_ms", _DEFAULT_SOCKET_TIMEOUT_MS)
    socket_timeout_ms = (
        int(raw_timeout) if isinstance(raw_timeout, (int, str)) else _DEFAULT_SOCKET_TIMEOUT_MS
    )

    conf: dict[str, str | int | float | bool] = {
        "bootstrap.servers": bootstrap_servers,
        "client.id": client_id,
        "security.protocol": security_protocol,
        "acks": acks,
        "retries": retries,
        "retry.backoff.ms": retry_backoff_ms,
        "socket.timeout.ms": socket_timeout_ms,
        "enable.idempotence": acks in ("all", "-1"),
    }

    if compression and compression != "none":
        conf["compression.type"] = compression

    # SASL Authentication
    if security_protocol in ("SASL_PLAINTEXT", "SASL_SSL"):
        mechanism = (
            str(public_config.get("sasl_mechanism") or credentials.get("sasl_mechanism") or "PLAIN")
            .strip()
            .upper()
        )
        conf["sasl.mechanism"] = mechanism

        username = str(credentials.get("username") or public_config.get("username") or "").strip()
        password = str(credentials.get("password") or public_config.get("password") or "").strip()
        if username:
            conf["sasl.username"] = username
        if password:
            conf["sasl.password"] = password

    # SSL / TLS Trust & Client Certificates
    ca_location = str(
        public_config.get("ssl_ca_location") or credentials.get("ssl_ca_cert") or ""
    ).strip()
    if ca_location:
        conf["ssl.ca.location"] = ca_location

    cert_location = str(
        public_config.get("ssl_certificate_location") or credentials.get("ssl_client_cert") or ""
    ).strip()
    if cert_location:
        conf["ssl.certificate.location"] = cert_location

    key_location = str(
        public_config.get("ssl_key_location") or credentials.get("ssl_client_key") or ""
    ).strip()
    if key_location:
        conf["ssl.key.location"] = key_location

    return conf


class ConfluentKafkaProducerClient(KafkaProducerClientPort):
    """Enterprise-grade Kafka producer and cluster inspector backed by librdkafka."""

    def __init__(self, config: Mapping[str, str | int | float | bool]) -> None:
        self._config: dict[str, str | int | float | bool] = dict(config)
        self._producer: Producer | None = None
        self._admin: AdminClient | None = None
        self._lock = asyncio.Lock()

    def _get_admin(self) -> AdminClient:
        if self._admin is None:
            self._admin = AdminClient(self._config)
        return self._admin

    def _get_producer(self) -> Producer:
        if self._producer is None:
            self._producer = Producer(self._config)
        return self._producer

    async def test_connection(self) -> Result[None, ConnectionCheckError]:
        """Preflight metadata verification: validates broker connectivity, credentials, and cluster readiness."""
        servers = str(self._config.get("bootstrap.servers", ""))
        timeout_sec = (
            float(self._config.get("socket.timeout.ms", _DEFAULT_SOCKET_TIMEOUT_MS)) / 1000.0
        )

        def _fetch_cluster_metadata() -> tuple[str | None, int]:
            admin = self._get_admin()
            metadata = admin.list_topics(timeout=timeout_sec)
            cluster_id = metadata.cluster_id
            broker_count = len(metadata.brokers)
            return cluster_id, broker_count

        try:
            cluster_id, broker_count = await asyncio.to_thread(_fetch_cluster_metadata)
            if broker_count == 0:
                return Result.fail(
                    ConnectionCheckError(
                        message=f"Cluster at '{servers}' returned 0 active brokers.",
                    )
                )
            logger.info(
                "kafka_connection_check_verified",
                servers=servers,
                cluster_id=cluster_id,
                broker_count=broker_count,
            )
            return Result.ok(None)
        except KafkaException as exc:
            err = exc.args[0] if exc.args else None
            reason = err.str() if (err is not None and hasattr(err, "str")) else str(exc)
            logger.error("kafka_connection_check_failed", servers=servers, error=reason)
            return Result.fail(
                ConnectionCheckError(
                    message=f"Failed to connect to Kafka brokers at '{servers}': {reason}",
                )
            )
        except (RuntimeError, ValueError, OSError) as exc:
            logger.error("kafka_connection_check_os_error", servers=servers, error=str(exc))
            return Result.fail(
                ConnectionCheckError(
                    message=f"Network or system failure while connecting to Kafka brokers at '{servers}': {exc}",
                )
            )

    async def list_topics(self) -> Result[Sequence[str], KafkaConnectionError]:
        """Retrieves user-accessible topics, filtering out internal management topics."""
        servers = str(self._config.get("bootstrap.servers", ""))
        timeout_sec = (
            float(self._config.get("socket.timeout.ms", _DEFAULT_SOCKET_TIMEOUT_MS)) / 1000.0
        )

        def _fetch_topics() -> list[str]:
            admin = self._get_admin()
            metadata = admin.list_topics(timeout=timeout_sec)
            return sorted(
                [
                    str(t)
                    for t in metadata.topics
                    if not str(t).startswith("__") and not str(t).startswith("_confluent")
                ]
            )

        try:
            topics = await asyncio.to_thread(_fetch_topics)
            return Result.ok(topics)
        except KafkaException as exc:
            err = exc.args[0] if exc.args else None
            reason = err.str() if (err is not None and hasattr(err, "str")) else str(exc)
            logger.error("kafka_list_topics_failed", servers=servers, error=reason)
            return Result.fail(
                KafkaConnectionError(
                    bootstrap_servers=servers,
                    message=f"Failed to query topics from Kafka cluster at '{servers}': {reason}",
                    disposition=FailureDisposition.RETRY,
                )
            )
        except (RuntimeError, ValueError, OSError) as exc:
            logger.error("kafka_list_topics_os_error", servers=servers, error=str(exc))
            return Result.fail(
                KafkaConnectionError(
                    bootstrap_servers=servers,
                    message=f"Network or system failure while querying topics at '{servers}': {exc}",
                    disposition=FailureDisposition.RETRY,
                )
            )

    async def produce(
        self,
        topic: str,
        value: bytes,
        key: bytes | None = None,
        headers: Mapping[str, bytes] | None = None,
        partition: int | None = None,
    ) -> Result[KafkaProduceResultDTO, KafkaConnectionError]:
        """Asynchronously writes a message to Kafka, serving delivery callbacks via the running event loop."""
        servers = str(self._config.get("bootstrap.servers", ""))
        producer = self._get_producer()
        loop = asyncio.get_running_loop()
        delivery_future: asyncio.Future[Result[Message, KafkaConnectionError]] = (
            loop.create_future()
        )

        def _on_delivery(err: KafkaError | None, msg: Message) -> None:
            if err is not None:
                loop.call_soon_threadsafe(
                    delivery_future.set_result,
                    Result.fail(
                        KafkaConnectionError(
                            bootstrap_servers=servers,
                            message=f"Kafka produce delivery failed: {err.str()}",
                            disposition=FailureDisposition.RETRY,
                        )
                    ),
                )
            else:
                loop.call_soon_threadsafe(delivery_future.set_result, Result.ok(msg))

        headers_list: list[tuple[str, str | bytes | None]] | None = (
            [(str(k), bytes(v)) for k, v in headers.items()] if headers is not None else None
        )
        target_partition = partition if partition is not None else -1
        timeout_sec = (
            float(self._config.get("socket.timeout.ms", _DEFAULT_SOCKET_TIMEOUT_MS)) / 1000.0
        )

        def _produce_and_poll() -> None:
            try:
                producer.produce(
                    topic=topic,
                    value=value,
                    key=key,
                    partition=target_partition,
                    headers=headers_list,
                    on_delivery=_on_delivery,
                )
            except BufferError:
                producer.flush(1.0)
                producer.produce(
                    topic=topic,
                    value=value,
                    key=key,
                    partition=target_partition,
                    headers=headers_list,
                    on_delivery=_on_delivery,
                )

            deadline = time.monotonic() + timeout_sec
            while not delivery_future.done():
                if time.monotonic() > deadline:
                    loop.call_soon_threadsafe(
                        delivery_future.set_result,
                        Result.fail(
                            KafkaConnectionError(
                                bootstrap_servers=servers,
                                message=f"Produce delivery acknowledgement timed out after {timeout_sec:.1f}s",
                                disposition=FailureDisposition.RETRY,
                            )
                        ),
                    )
                    break
                producer.poll(0.05)

        await asyncio.to_thread(_produce_and_poll)
        delivery_res = await delivery_future
        if delivery_res.is_err or delivery_res.value is None:
            err_val = delivery_res.error or KafkaConnectionError(
                bootstrap_servers=servers,
                message=f"Failed to produce record to topic '{topic}'.",
                disposition=FailureDisposition.RETRY,
            )
            return Result.fail(err_val)

        confirmed_msg = delivery_res.value
        raw_ts = confirmed_msg.timestamp()
        ts_ms = (
            raw_ts[1]
            if isinstance(raw_ts, tuple) and len(raw_ts) > 1 and raw_ts[1] > 0
            else int(time.time() * 1000)
        )
        raw_part = confirmed_msg.partition()
        assigned_partition = int(raw_part) if raw_part is not None else 0
        raw_offset = confirmed_msg.offset()
        assigned_offset = int(raw_offset) if raw_offset is not None else 0

        return Result.ok(
            KafkaProduceResultDTO(
                topic=str(confirmed_msg.topic()),
                partition=assigned_partition,
                offset=assigned_offset,
                timestamp_ms=ts_ms,
            )
        )

    async def close(self) -> None:
        """Flushes in-flight messages and releases producer resources."""
        if self._producer is not None:
            producer = self._producer
            self._producer = None
            await asyncio.to_thread(producer.flush, 5.0)


class ConfluentKafkaProducerClientFactory(KafkaProducerClientFactoryPort):
    """Factory translating IP connection configuration into ConfluentKafkaProducerClient instances."""

    def create_producer(
        self,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> KafkaProducerClientPort:
        config = build_confluent_kafka_config(public_config, credentials)
        return ConfluentKafkaProducerClient(config)


__all__ = [
    "ConfluentKafkaProducerClient",
    "ConfluentKafkaProducerClientFactory",
    "build_confluent_kafka_config",
]
