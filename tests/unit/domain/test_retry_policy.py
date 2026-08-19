import pytest

from app.domain.retry_policy import DeliveryRetryPolicy

_POLICY = DeliveryRetryPolicy(max_attempts=5, countdown_seconds=(5, 15, 45))


def test_first_three_failures_use_schedule_then_cap() -> None:
    assert _POLICY.countdown_for(1) == 5
    assert _POLICY.countdown_for(2) == 15
    assert _POLICY.countdown_for(3) == 45
    assert _POLICY.countdown_for(4) == 45


def test_retry_while_budget_remains() -> None:
    assert _POLICY.should_retry(1, retryable=True) is True
    assert _POLICY.should_retry(4, retryable=True) is True
    assert _POLICY.should_retry(5, retryable=True) is False


def test_permanent_failure_never_retries() -> None:
    assert _POLICY.should_retry(1, retryable=False) is False


def test_single_attempt_budget_fails_fast() -> None:
    policy = DeliveryRetryPolicy(max_attempts=1, countdown_seconds=(5, 15, 45))
    assert policy.should_retry(1, retryable=True) is False


def test_invalid_policy_rejected() -> None:
    with pytest.raises(ValueError):
        DeliveryRetryPolicy(max_attempts=0, countdown_seconds=(5,))
    with pytest.raises(ValueError):
        DeliveryRetryPolicy(max_attempts=5, countdown_seconds=())
    with pytest.raises(ValueError):
        DeliveryRetryPolicy(max_attempts=5, countdown_seconds=(5, 0))
