from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any, AsyncIterator, Callable

from ..config import settings


class MemoryBus:
    """In-process pub/sub over asyncio.Queues. Zero-infra MVP mode.

    Implements the same interface as RedpandaBus so agents/ingest never
    care which is active.
    """

    def __init__(self) -> None:
        self._subs: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._log: dict[str, list[dict]] = defaultdict(list)

    async def publish(self, topic: str, value: dict[str, Any], key: str | None = None) -> None:
        self._log[topic].append(value)
        for q in self._subs.get(topic, []):
            await q.put(value)

    async def subscribe(self, topic: str) -> AsyncIterator[dict[str, Any]]:
        q: asyncio.Queue = asyncio.Queue()
        self._subs[topic].append(q)
        try:
            while True:
                yield await q.get()
        finally:
            self._subs[topic].remove(q)

    def history(self, topic: str) -> list[dict]:
        return list(self._log.get(topic, []))


class RedpandaBus:
    """Kafka-API bus via aiokafka. Swap in with BUS=redpanda."""

    def __init__(self) -> None:
        from aiokafka import AIOKafkaConsumer, AIOKafkaProducer  # type: ignore

        self._producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap,
            value_serializer=lambda v: json.dumps(v).encode(),
            key_serializer=lambda k: k.encode() if k else None,
        )
        self._consumer_cls = AIOKafkaConsumer

    async def start(self) -> None:
        await self._producer.start()

    async def stop(self) -> None:
        await self._producer.stop()

    async def publish(self, topic: str, value: dict[str, Any], key: str | None = None) -> None:
        await self._producer.send_and_wait(topic, value, key=key)

    async def subscribe(self, topic: str) -> AsyncIterator[dict[str, Any]]:
        consumer = self._consumer_cls(
            topic,
            bootstrap_servers=settings.kafka_bootstrap,
            value_deserializer=lambda b: json.loads(b.decode()),
            enable_auto_commit=True,
            group_id=f"chronotwin-{topic}",
        )
        await consumer.start()
        try:
            async for msg in consumer:
                yield msg.value
        finally:
            await consumer.stop()


_bus: Any = None


def get_bus() -> Any:
    global _bus
    if _bus is None:
        _bus = RedpandaBus() if settings.bus == "redpanda" else MemoryBus()
    return _bus


# canonical topic names
TOPIC_READINGS = "readings.raw"
TOPIC_VALIDATED = "reports.validated"
TOPIC_INCIDENTS = "incidents"
TOPIC_DLQ = "dlq"

__all__ = [
    "MemoryBus",
    "RedpandaBus",
    "get_bus",
    "TOPIC_READINGS",
    "TOPIC_VALIDATED",
    "TOPIC_INCIDENTS",
    "TOPIC_DLQ",
]
