from __future__ import annotations

import uuid

from app.repositories.notification_repository import ClientSendCounts
from app.services.metrics_service import MetricsService


class FakeNotificationRepository:
    def __init__(self) -> None:
        self.counts_by_client: dict[uuid.UUID, ClientSendCounts] = {}

    def count_sent_and_failed_for_client(self, client_id: uuid.UUID) -> ClientSendCounts:
        return self.counts_by_client.get(client_id, ClientSendCounts(sent=0, failed=0))


def test_get_client_metrics_returns_repo_counts() -> None:
    repo = FakeNotificationRepository()
    client_id = uuid.uuid4()
    repo.counts_by_client[client_id] = ClientSendCounts(sent=4, failed=2)
    service = MetricsService(repo)

    result = service.get_client_metrics(client_id)

    assert result.sent == 4
    assert result.failed == 2


def test_get_client_metrics_returns_zeros_when_repo_has_no_row() -> None:
    service = MetricsService(FakeNotificationRepository())
    result = service.get_client_metrics(uuid.uuid4())
    assert result.sent == 0
    assert result.failed == 0


def test_get_client_metrics_does_not_see_another_client() -> None:
    repo = FakeNotificationRepository()
    owner = uuid.uuid4()
    other = uuid.uuid4()
    repo.counts_by_client[owner] = ClientSendCounts(sent=1, failed=0)
    repo.counts_by_client[other] = ClientSendCounts(sent=9, failed=9)
    service = MetricsService(repo)

    result = service.get_client_metrics(owner)

    assert result.sent == 1
    assert result.failed == 0
