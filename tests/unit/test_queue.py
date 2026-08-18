import uuid

from app.services.queue import InMemoryNotificationQueue


def test_in_memory_queue_records_ids_in_order() -> None:
    queue = InMemoryNotificationQueue()
    first = uuid.uuid4()
    second = uuid.uuid4()
    queue.enqueue(first)
    queue.enqueue(second)
    assert queue.enqueued == [first, second]


def test_in_memory_queue_starts_empty() -> None:
    assert InMemoryNotificationQueue().enqueued == []
