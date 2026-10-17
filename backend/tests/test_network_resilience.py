"""Bounded Network Resilience and Circuit Breaker Tests.

Verifies:
1. Immediate success requires exactly one attempt.
2. Transient server failure (HTTP 503) followed by success.
3. Transient connection failure (ConnectError) followed by success.
4. Exhausted retry budget (3 total attempts: 1 initial + 2 retries).
5. Non-retryable errors (401/403 auth, 429 rate limit, 404, malformed JSON, empty content, SSRF) abort on attempt 1.
6. Safe Retry-After header parsing within 2.0s ceiling.
7. Unsafe / excessive Retry-After header (> 2.0s) aborts retries immediately.
8. Request deadline exhaustion aborts retries and returns TIMEOUT.
9. Cancellation during a retry delay raises asyncio.CancelledError without suppression.
10. Unapproved or rejected URLs never trigger retries or network requests.
11. Circuit breaker transitions:
    - Closed on start.
    - Trips to OPEN after failure threshold (3 consecutive transient failures).
    - Fast-fails requests while OPEN with error_code='CIRCUIT_OPEN' (zero network calls).
    - Transitions to HALF_OPEN after recovery timeout.
    - Successful probe in HALF_OPEN recovers and resets to CLOSED.
    - Failed probe in HALF_OPEN trips immediately back to OPEN.
    - Separate retriever instances maintain isolated circuit breaker states.
12. Failures cause safe Evidence Court abstention (verdict='unable_to_verify') and zero secret leakage.
"""

import asyncio
import json
import logging
import threading
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest
from httpx import AsyncClient

from app.config import settings
from app.schemas.documentation import NormalizedEvidence
from app.schemas.evidence import AnalysisRequest
from app.services.documentation.circuit_breaker import CircuitBreaker
from app.services.documentation.retrieval_service import retrieval_service
from app.services.documentation.tinyfish_adapter import TinyFishLiveRetriever
from app.services.evidence.adjudicator import adjudicator
from app.services.providers.status import get_tinyfish_lifecycle_state


CANARY_SECRET_TOKEN = "sk-live-resilience-canary-secret-998877665544332211"


# ==============================================================================
# 1. Bounded Retry Policy Tests
# ==============================================================================

class TestBoundedRetryPolicy:
    """Verifies that transient errors trigger bounded retries while permanent errors fail fast."""

    @pytest.mark.asyncio
    async def test_immediate_success_requires_exactly_one_attempt(self) -> None:
        """Contract: When upstream succeeds on the first attempt, exactly 1 HTTP call is made."""
        mock_sleep = AsyncMock()
        retriever = TinyFishLiveRetriever(
            api_key="tf-test-key",
            max_retries=2,
            sleep_fn=mock_sleep,
        )
        mock_resp = httpx.Response(
            200,
            json={"results": [{"url": "https://docs.stripe.com/api/charges/create", "title": "Charge", "text": "Valid doc text"}]},
            request=httpx.Request("POST", retriever.fetch_base_url),
        )

        with patch.object(httpx.AsyncClient, "post", return_value=mock_resp) as mock_post:
            evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges/create")

            assert evidence.status == "success"
            assert mock_post.call_count == 1
            mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_transient_503_followed_by_success(self) -> None:
        """Contract: Transient 503 on attempt 1, followed by 200 on attempt 2 succeeds with 1 retry."""
        mock_sleep = AsyncMock()
        retriever = TinyFishLiveRetriever(
            api_key="tf-test-key",
            max_retries=2,
            base_backoff_seconds=0.1,
            sleep_fn=mock_sleep,
            jitter_fn=lambda a: 0.0,
        )

        resp_503 = httpx.Response(503, text="Service Unavailable", request=httpx.Request("POST", retriever.fetch_base_url))
        resp_200 = httpx.Response(
            200,
            json={"results": [{"url": "https://docs.stripe.com/api/charges/create", "title": "Charge", "text": "Recovered doc"}]},
            request=httpx.Request("POST", retriever.fetch_base_url),
        )

        with patch.object(httpx.AsyncClient, "post", side_effect=[resp_503, resp_200]) as mock_post:
            evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges/create")

            assert evidence.status == "success"
            assert mock_post.call_count == 2
            mock_sleep.assert_called_once_with(0.1)

    @pytest.mark.asyncio
    async def test_transient_connection_error_followed_by_success(self) -> None:
        """Contract: ConnectError on attempt 1, followed by 200 on attempt 2 succeeds with 1 retry."""
        mock_sleep = AsyncMock()
        retriever = TinyFishLiveRetriever(
            api_key="tf-test-key",
            max_retries=2,
            base_backoff_seconds=0.2,
            sleep_fn=mock_sleep,
            jitter_fn=lambda a: 0.0,
        )

        resp_200 = httpx.Response(
            200,
            json={"results": [{"url": "https://docs.stripe.com/api/charges/create", "title": "Charge", "text": "Recovered doc"}]},
            request=httpx.Request("POST", retriever.fetch_base_url),
        )

        with patch.object(
            httpx.AsyncClient,
            "post",
            side_effect=[httpx.ConnectError("Connection refused by peer"), resp_200],
        ) as mock_post:
            evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges/create")

            assert evidence.status == "success"
            assert mock_post.call_count == 2
            mock_sleep.assert_called_once_with(0.2)

    @pytest.mark.asyncio
    async def test_exhausted_retry_budget(self) -> None:
        """Contract: Repeated 503 failures exhaust the retry budget (3 attempts total: 1 initial + 2 retries)."""
        mock_sleep = AsyncMock()
        retriever = TinyFishLiveRetriever(
            api_key="tf-test-key",
            max_retries=2,
            base_backoff_seconds=0.05,
            sleep_fn=mock_sleep,
        )

        resp_503 = httpx.Response(503, text="Service Unavailable", request=httpx.Request("POST", retriever.fetch_base_url))

        with patch.object(httpx.AsyncClient, "post", return_value=resp_503) as mock_post:
            evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges/create")

            assert evidence.status == "unavailable"
            assert evidence.error_code == "PROVIDER_ERROR"
            assert "503" in (evidence.error_message or "")
            assert mock_post.call_count == 3  # 1 initial + 2 retries
            assert mock_sleep.call_count == 2  # 2 backoff sleeps

    @pytest.mark.asyncio
    async def test_non_retryable_auth_failures_abort_immediately(self) -> None:
        """Contract: HTTP 401 and 403 must NEVER be retried; abort on attempt 1."""
        mock_sleep = AsyncMock()
        retriever = TinyFishLiveRetriever(
            api_key="tf-test-key",
            max_retries=2,
            sleep_fn=mock_sleep,
        )

        for code in [401, 403]:
            mock_resp = httpx.Response(code, text="Unauthorized", request=httpx.Request("POST", retriever.fetch_base_url))
            with patch.object(httpx.AsyncClient, "post", return_value=mock_resp) as mock_post:
                evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges/create")
                assert evidence.status == "unavailable"
                assert evidence.error_code == "AUTHENTICATION_FAILED"
                assert mock_post.call_count == 1
                mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_rate_limiting_429_does_not_retry_or_storm(self) -> None:
        """Contract: HTTP 429 rate limit is non-retryable to avoid worsening upstream load."""
        mock_sleep = AsyncMock()
        retriever = TinyFishLiveRetriever(
            api_key="tf-test-key",
            max_retries=2,
            sleep_fn=mock_sleep,
        )

        mock_resp = httpx.Response(429, text="Rate Limited", request=httpx.Request("POST", retriever.fetch_base_url))
        with patch.object(httpx.AsyncClient, "post", return_value=mock_resp) as mock_post:
            evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges/create")
            assert evidence.status == "unavailable"
            assert evidence.error_code == "RATE_LIMITED"
            assert mock_post.call_count == 1
            mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_malformed_json_response_does_not_retry(self) -> None:
        """Contract: Malformed or unparseable JSON response is non-retryable."""
        mock_sleep = AsyncMock()
        retriever = TinyFishLiveRetriever(
            api_key="tf-test-key",
            max_retries=2,
            sleep_fn=mock_sleep,
        )

        mock_resp = httpx.Response(200, text="<html>Corrupted response", request=httpx.Request("POST", retriever.fetch_base_url))
        with patch.object(httpx.AsyncClient, "post", return_value=mock_resp) as mock_post:
            evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges/create")
            assert evidence.status == "unavailable"
            assert evidence.error_code == "INVALID_RESPONSE_JSON"
            assert mock_post.call_count == 1
            mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_retry_after_header_respected_within_safe_ceiling(self) -> None:
        """Contract: Upstream Retry-After header is used if within the 2.0s ceiling."""
        mock_sleep = AsyncMock()
        retriever = TinyFishLiveRetriever(
            api_key="tf-test-key",
            max_retries=2,
            sleep_fn=mock_sleep,
        )

        resp_503 = httpx.Response(
            503,
            headers={"Retry-After": "1.5"},
            text="Service Unavailable",
            request=httpx.Request("POST", retriever.fetch_base_url),
        )
        resp_200 = httpx.Response(
            200,
            json={"results": [{"url": "https://docs.stripe.com/api/charges/create", "title": "Charge", "text": "Valid doc"}]},
            request=httpx.Request("POST", retriever.fetch_base_url),
        )

        with patch.object(httpx.AsyncClient, "post", side_effect=[resp_503, resp_200]) as mock_post:
            evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges/create")
            assert evidence.status == "success"
            assert mock_post.call_count == 2
            mock_sleep.assert_called_once_with(1.5)

    @pytest.mark.asyncio
    async def test_retry_after_header_exceeding_ceiling_aborts_retries(self) -> None:
        """Contract: Upstream Retry-After header > 2.0s aborts retries immediately to avoid blocking."""
        mock_sleep = AsyncMock()
        retriever = TinyFishLiveRetriever(
            api_key="tf-test-key",
            max_retries=2,
            sleep_fn=mock_sleep,
        )

        resp_503 = httpx.Response(
            503,
            headers={"Retry-After": "60"},  # 60s is beyond safe ceiling
            text="Service Unavailable",
            request=httpx.Request("POST", retriever.fetch_base_url),
        )

        with patch.object(httpx.AsyncClient, "post", return_value=resp_503) as mock_post:
            evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges/create")
            assert evidence.status == "unavailable"
            assert evidence.error_code == "PROVIDER_ERROR"
            assert mock_post.call_count == 1
            mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_deadline_exhaustion_aborts_retries(self) -> None:
        """Contract: When overall request deadline budget is reached, retries abort and return TIMEOUT."""
        # Simulated time generator: starts at 0, jumps past timeout on first retry check
        time_points = [0.0, 1.0, 16.0, 16.0]  # Jump to 16s (past 15s budget)
        time_iter = iter(time_points)

        def mock_time() -> float:
            return next(time_iter, 20.0)

        mock_sleep = AsyncMock()
        retriever = TinyFishLiveRetriever(
            api_key="tf-test-key",
            timeout_seconds=15.0,
            max_retries=2,
            time_fn=mock_time,
            sleep_fn=mock_sleep,
        )

        resp_503 = httpx.Response(503, text="Service Unavailable", request=httpx.Request("POST", retriever.fetch_base_url))

        with patch.object(httpx.AsyncClient, "post", return_value=resp_503) as mock_post:
            evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges/create")
            assert evidence.status == "unavailable"
            assert evidence.error_code in ("PROVIDER_ERROR", "TIMEOUT")
            # Should not perform all retries because budget expired
            assert mock_post.call_count == 1
            mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_cancellation_during_retry_delay_propagates(self) -> None:
        """Contract: Task cancellation during retry backoff sleep propagates immediately without suppression."""
        async def cancel_sleep(delay: float) -> None:
            raise asyncio.CancelledError()

        retriever = TinyFishLiveRetriever(
            api_key="tf-test-key",
            max_retries=2,
            sleep_fn=cancel_sleep,
        )

        resp_503 = httpx.Response(503, text="Service Unavailable", request=httpx.Request("POST", retriever.fetch_base_url))

        with patch.object(httpx.AsyncClient, "post", return_value=resp_503):
            with pytest.raises(asyncio.CancelledError):
                await retriever.fetch_url("https://docs.stripe.com/api/charges/create")

    @pytest.mark.asyncio
    async def test_unapproved_urls_never_retry(self) -> None:
        """Contract: Pre-flight security rejects unapproved URLs before initiating any network calls."""
        mock_sleep = AsyncMock()
        retriever = TinyFishLiveRetriever(api_key="tf-test-key", max_retries=2, sleep_fn=mock_sleep)

        with patch.object(httpx.AsyncClient, "post") as mock_post:
            evidence = await retriever.fetch_url("https://unapproved-hacker-site.com/docs")
            assert evidence.status == "rejected"
            assert evidence.error_code == "SSRF_POLICY_VIOLATION"
            mock_post.assert_not_called()
            mock_sleep.assert_not_called()

    def test_deterministic_jitter_applied_to_backoff(self) -> None:
        """Contract: Bounded jitter is added to exponential backoff and is deterministically testable."""
        # Custom deterministic jitter
        retriever = TinyFishLiveRetriever(
            api_key="tf-test-key",
            base_backoff_seconds=0.1,
            jitter_fn=lambda attempt: 0.015,
        )
        backoff_0, abort_0 = retriever._calculate_backoff(attempt=0)
        assert abort_0 is False
        assert pytest.approx(backoff_0, 0.0001) == 0.115  # 0.1 * 1 + 0.015

        backoff_1, abort_1 = retriever._calculate_backoff(attempt=1)
        assert abort_1 is False
        assert pytest.approx(backoff_1, 0.0001) == 0.215  # 0.1 * 2 + 0.015

        # Default bounded jitter is within [0.0, 0.02]
        default_retriever = TinyFishLiveRetriever(api_key="tf-test-key", base_backoff_seconds=0.1)
        for attempt in range(3):
            delay, abort = default_retriever._calculate_backoff(attempt)
            assert abort is False
            expected_base = 0.1 * (2 ** attempt)
            assert expected_base <= delay <= expected_base + 0.02

    def test_retry_after_negative_and_malformed_fall_back_to_exponential(self) -> None:
        """Contract: Malformed, non-numeric, or negative Retry-After headers fall back safely to backoff."""
        retriever = TinyFishLiveRetriever(
            api_key="tf-test-key",
            base_backoff_seconds=0.05,
            jitter_fn=lambda attempt: 0.0,
        )

        for invalid_val in ["-10", "-0.5", "invalid-str", "tomorrow", ""]:
            delay, should_abort = retriever._calculate_backoff(attempt=0, retry_after_header=invalid_val)
            assert should_abort is False
            assert delay == 0.05

        # Safe positive Retry-After <= 2.0s is honored
        delay, should_abort = retriever._calculate_backoff(attempt=0, retry_after_header="1.25")
        assert should_abort is False
        assert delay == 1.25

        # Excessive Retry-After > 2.0s triggers immediate abort
        delay, should_abort = retriever._calculate_backoff(attempt=0, retry_after_header="2.01")
        assert should_abort is True

    @pytest.mark.asyncio
    async def test_retryable_read_timeout_and_transport_errors(self) -> None:
        """Contract: ReadTimeout and RemoteProtocolError are transient and trigger bounded retry."""
        mock_sleep = AsyncMock()
        retriever = TinyFishLiveRetriever(
            api_key="tf-test-key",
            max_retries=2,
            base_backoff_seconds=0.05,
            sleep_fn=mock_sleep,
            jitter_fn=lambda a: 0.0,
        )

        resp_200 = httpx.Response(
            200,
            json={"results": [{"url": "https://docs.stripe.com/api/charges/create", "title": "Charge", "text": "Recovered doc"}]},
            request=httpx.Request("POST", retriever.fetch_base_url),
        )

        # Attempt 1: ReadTimeout, Attempt 2: 200 OK -> exactly 2 attempts
        with patch.object(
            httpx.AsyncClient,
            "post",
            side_effect=[httpx.ReadTimeout("Read timed out"), resp_200],
        ) as mock_post:
            evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges/create")
            assert evidence.status == "success"
            assert mock_post.call_count == 2
            mock_sleep.assert_called_once_with(0.05)

    @pytest.mark.asyncio
    async def test_non_retryable_400_404_500_abort_on_attempt_1(self) -> None:
        """Contract: Permanent client errors (400, 404) and non-transient server error (500) abort on attempt 1."""
        mock_sleep = AsyncMock()
        retriever = TinyFishLiveRetriever(api_key="tf-test-key", max_retries=2, sleep_fn=mock_sleep)

        for code in [400, 404, 500]:
            mock_sleep.reset_mock()
            resp = httpx.Response(code, text=f"HTTP {code}", request=httpx.Request("POST", retriever.fetch_base_url))
            with patch.object(httpx.AsyncClient, "post", return_value=resp) as mock_post:
                evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges/create")
                assert evidence.status == "unavailable"
                assert evidence.error_code == "PROVIDER_ERROR"
                assert mock_post.call_count == 1
                mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_each_attempt_uses_exact_canonical_url_and_headers(self) -> None:
        """Contract: Every attempt in the retry loop uses the validated canonical URL and auth headers."""
        mock_sleep = AsyncMock()
        retriever = TinyFishLiveRetriever(
            api_key="tf-test-key-exact",
            max_retries=2,
            base_backoff_seconds=0.01,
            sleep_fn=mock_sleep,
            jitter_fn=lambda a: 0.0,
        )

        resp_503 = httpx.Response(503, text="Unavailable", request=httpx.Request("POST", retriever.fetch_base_url))
        resp_200 = httpx.Response(
            200,
            json={"results": [{"url": "https://docs.stripe.com/api/charges/create", "title": "C", "text": "T"}]},
            request=httpx.Request("POST", retriever.fetch_base_url),
        )

        target_url = "https://docs.stripe.com/api/charges/create?utm_source=tracker"
        with patch.object(httpx.AsyncClient, "post", side_effect=[resp_503, resp_200]) as mock_post:
            evidence = await retriever.fetch_url(target_url)
            assert evidence.status == "success"
            assert mock_post.call_count == 2
            for call in mock_post.call_args_list:
                # Target URL is canonicalized without tracking params
                assert call.kwargs["json"]["urls"] == ["https://docs.stripe.com/api/charges/create"]
                assert call.kwargs["headers"]["X-API-Key"] == "tf-test-key-exact"

    @pytest.mark.asyncio
    async def test_retry_sleep_will_not_exceed_remaining_budget(self) -> None:
        """Contract: When backoff delay exceeds remaining deadline budget, retry sleep is aborted immediately."""
        # Simulated time generator: starts at 0, attempt 1 takes 14.9s (budget 15.0s), remaining = 0.1s
        # Planned backoff is 0.5s > 0.1s remaining budget
        time_points = [0.0, 0.0, 14.9, 14.9, 14.9]
        time_iter = iter(time_points)

        def mock_time() -> float:
            return next(time_iter, 14.9)

        mock_sleep = AsyncMock()
        retriever = TinyFishLiveRetriever(
            api_key="tf-test-key",
            timeout_seconds=15.0,
            max_retries=2,
            base_backoff_seconds=0.5,
            time_fn=mock_time,
            sleep_fn=mock_sleep,
            jitter_fn=lambda a: 0.0,
        )

        resp_503 = httpx.Response(503, text="Service Unavailable", request=httpx.Request("POST", retriever.fetch_base_url))

        with patch.object(httpx.AsyncClient, "post", return_value=resp_503) as mock_post:
            evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges/create")
            assert evidence.status == "unavailable"
            assert evidence.error_code == "TIMEOUT"
            # Aborts without sleeping because backoff would exceed budget
            assert mock_post.call_count == 1
            mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_hard_wallclock_deadline_enforced_by_asyncio_timeout(self) -> None:
        """Contract: A slow HTTP request is hard-cancelled by asyncio.timeout when attempt budget expires."""
        async def slow_post(*args, **kwargs):
            # Hangs longer than configured timeout budget
            await asyncio.sleep(0.5)
            return httpx.Response(200, json={"results": []})

        retriever = TinyFishLiveRetriever(
            api_key="tf-test-key",
            timeout_seconds=0.05,  # 50ms total budget
            max_retries=0,
        )

        with patch.object(httpx.AsyncClient, "post", side_effect=slow_post):
            evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges/create")
            assert evidence.status == "unavailable"
            assert evidence.error_code == "TIMEOUT"
            assert "timed out" in (evidence.error_message or "").lower()

    @pytest.mark.asyncio
    async def test_cancellation_during_http_request_propagates(self) -> None:
        """Contract: Task cancellation during in-flight HTTP post propagates immediately without suppression."""
        async def cancelled_post(*args, **kwargs):
            raise asyncio.CancelledError()

        retriever = TinyFishLiveRetriever(api_key="tf-test-key", max_retries=1)

        with patch.object(httpx.AsyncClient, "post", side_effect=cancelled_post):
            with pytest.raises(asyncio.CancelledError):
                await retriever.fetch_url("https://docs.stripe.com/api/charges/create")


# ==============================================================================
# 2. Circuit Breaker Lifecycle & State Transition Tests
# ==============================================================================

class TestCircuitBreakerLifecycle:
    """Verifies in-memory circuit breaker state machine transitions and recovery probing."""

    def test_circuit_starts_in_closed_state(self) -> None:
        """Circuit breaker is initialized in CLOSED state."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout_seconds=30.0)
        assert cb.state == "closed"
        assert cb.can_execute() is True
        assert cb.consecutive_failures == 0

    def test_circuit_trips_to_open_after_failure_threshold(self) -> None:
        """Circuit trips to OPEN on the 3rd consecutive transient failure."""
        virtual_now = 100.0
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout_seconds=30.0, time_fn=lambda: virtual_now)

        cb.record_failure()
        assert cb.state == "closed"
        assert cb.can_execute() is True
        assert cb.consecutive_failures == 1

        cb.record_failure()
        assert cb.state == "closed"
        assert cb.can_execute() is True
        assert cb.consecutive_failures == 2

        cb.record_failure()
        assert cb.state == "open"
        assert cb.can_execute() is False
        assert cb.consecutive_failures == 3

    def test_circuit_resets_failures_on_success(self) -> None:
        """Success resets consecutive failure counter back to 0."""
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.consecutive_failures == 2

        cb.record_success()
        assert cb.state == "closed"
        assert cb.consecutive_failures == 0

    def test_circuit_transitions_to_half_open_after_recovery_timeout(self) -> None:
        """After recovery timeout elapses, circuit transitions from OPEN to HALF_OPEN."""
        virtual_now = 1000.0

        def current_time() -> float:
            return virtual_now

        cb = CircuitBreaker(failure_threshold=2, recovery_timeout_seconds=30.0, time_fn=current_time)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"
        assert cb.can_execute() is False

        # Advance virtual time by 29 seconds (still within recovery cooldown)
        virtual_now += 29.0
        assert cb.state == "open"
        assert cb.can_execute() is False

        # Advance virtual time by 2 more seconds (31s elapsed > 30s timeout)
        virtual_now += 2.0
        assert cb.state == "half_open"
        # First call permits exactly 1 recovery probe
        assert cb.can_execute() is True
        # Subsequent call while probe in flight is rejected
        assert cb.can_execute() is False

    def test_successful_probe_recovers_to_closed(self) -> None:
        """A successful probe in HALF_OPEN resets consecutive failures and restores CLOSED state."""
        virtual_now = 1000.0
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout_seconds=10.0, time_fn=lambda: virtual_now)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"

        # Advance past cooldown to enter half_open
        virtual_now += 15.0
        assert cb.state == "half_open"
        assert cb.can_execute() is True

        # Probe succeeds
        cb.record_success()
        assert cb.state == "closed"
        assert cb.consecutive_failures == 0
        assert cb.can_execute() is True

    def test_failed_probe_trips_immediately_back_to_open(self) -> None:
        """A failed probe in HALF_OPEN trips immediately back to OPEN and resets cooldown timer."""
        virtual_now = 1000.0
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout_seconds=10.0, time_fn=lambda: virtual_now)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"

        # Advance past cooldown
        virtual_now += 15.0
        assert cb.state == "half_open"
        assert cb.can_execute() is True

        # Probe fails
        cb.record_failure()
        assert cb.state == "open"
        assert cb.can_execute() is False

    @pytest.mark.asyncio
    async def test_retriever_fast_fails_when_circuit_is_open(self) -> None:
        """TinyFishLiveRetriever fast-fails with error_code='CIRCUIT_OPEN' without invoking network."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout_seconds=30.0)
        # Pre-trip the circuit
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"

        retriever = TinyFishLiveRetriever(api_key="tf-test-key", circuit_breaker=cb)

        with patch.object(httpx.AsyncClient, "post") as mock_post:
            evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges/create")

            assert evidence.status == "unavailable"
            assert evidence.error_code == "CIRCUIT_OPEN"
            assert "circuit breaker is OPEN" in (evidence.error_message or "")
            mock_post.assert_not_called()

    def test_retriever_instances_do_not_share_circuit_state(self) -> None:
        """Separate TinyFishLiveRetriever instances have isolated circuit breaker instances."""
        retriever_a = TinyFishLiveRetriever(api_key="key-a")
        retriever_b = TinyFishLiveRetriever(api_key="key-b")

        # Trip retriever A's circuit
        for _ in range(3):
            retriever_a.circuit_breaker.record_failure()

        assert retriever_a.circuit_breaker.state == "open"
        assert retriever_b.circuit_breaker.state == "closed"
        assert retriever_b.circuit_breaker.can_execute() is True

    @pytest.mark.asyncio
    async def test_concurrent_calls_permit_only_one_half_open_probe(self) -> None:
        """Contract: When circuit is HALF_OPEN, concurrent tasks cannot all become probes; exactly 1 is permitted."""
        virtual_now = 1000.0
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout_seconds=10.0, time_fn=lambda: virtual_now)
        cb.record_failure()
        assert cb.state == "open"

        # Advance past cooldown
        virtual_now += 15.0
        assert cb.state == "half_open"

        # Launch 20 concurrent tasks calling can_execute()
        async def call_breaker() -> bool:
            return cb.can_execute()

        results = await asyncio.gather(*(call_breaker() for _ in range(20)))
        assert results.count(True) == 1
        assert results.count(False) == 19

    def test_cancellation_during_probe_releases_in_flight_flag(self) -> None:
        """Contract: Cancellation during probe clears probe_in_flight and never falsely reports recovery."""
        virtual_now = 1000.0
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout_seconds=10.0, time_fn=lambda: virtual_now)
        cb.record_failure()
        assert cb.state == "open"

        virtual_now += 15.0
        assert cb.state == "half_open"
        assert cb.can_execute() is True
        assert cb.is_probe_in_flight is True
        assert cb.can_execute() is False

        # Probe cancelled -> record_probe_abandoned() called
        cb.record_probe_abandoned()

        # Breaker must NOT claim recovery (state is still half_open, not closed)
        assert cb.state == "half_open"
        assert cb.is_probe_in_flight is False
        # Subsequent probe is permitted
        assert cb.can_execute() is True

    def test_failed_probe_trips_immediately_to_open_regardless_of_prior_counter(self) -> None:
        """Contract: In HALF_OPEN, a single failure immediately trips back to OPEN."""
        virtual_now = 1000.0
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout_seconds=10.0, time_fn=lambda: virtual_now)
        # Manually set to half_open with consecutive failures < threshold
        cb._state = "half_open"
        cb._consecutive_failures = 1

        cb.record_failure()
        assert cb.state == "open"
        assert cb.can_execute() is False

    def test_concurrent_success_and_failure_thread_safety(self) -> None:
        """Contract: Concurrent execution across multiple threads is completely thread-safe without data race."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout_seconds=1.0)
        errors = []

        def worker(thread_id: int) -> None:
            try:
                for i in range(50):
                    if i % 2 == 0:
                        cb.record_failure()
                    else:
                        cb.record_success()
                    _ = cb.can_execute()
                    _ = cb.state
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert cb.state in ("closed", "open", "half_open")


# ==============================================================================
# 3. Evidence Invariants Under Network Resilience
# ==============================================================================

class TestEvidenceInvariantsUnderNetworkResilience:
    """Verifies that network retries and circuit breaker states preserve Evidence Court invariants."""

    @pytest.mark.asyncio
    async def test_circuit_open_causes_safe_abstention(self) -> None:
        """When circuit breaker trips open, analysis reports verdict='unable_to_verify' (never 'clean')."""
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure()
        assert cb.state == "open"

        retriever = TinyFishLiveRetriever(api_key="tf-test-key", circuit_breaker=cb)
        evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges/create")
        assert evidence.status == "unavailable"
        assert evidence.error_code == "CIRCUIT_OPEN"

        req = AnalysisRequest(source="import stripe\nstripe.Charge.create(amount=2000, currency='usd')\n")
        report = await adjudicator.adjudicate(req, _internal_evidence=[evidence])

        assert report.verdict == "unable_to_verify"
        assert len(report.verified_issues) == 0
        assert report.candidate_assessments[0].status == "unresolved"

    @pytest.mark.asyncio
    async def test_canary_secret_not_leaked_in_retry_logs(self, caplog: pytest.LogCaptureFixture) -> None:
        """Canary secret token is never leaked in retry logging or provider error messages."""
        retriever = TinyFishLiveRetriever(
            api_key=CANARY_SECRET_TOKEN,
            max_retries=1,
            base_backoff_seconds=0.01,
        )

        resp_503 = httpx.Response(
            503,
            text=f"Gateway timeout with token {CANARY_SECRET_TOKEN}",
            request=httpx.Request("POST", retriever.fetch_base_url),
        )

        with patch.object(httpx.AsyncClient, "post", return_value=resp_503), caplog.at_level(logging.DEBUG):
            evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges/create")

            assert evidence.status == "unavailable"
            assert CANARY_SECRET_TOKEN not in (evidence.error_message or "")
            for record in caplog.records:
                assert CANARY_SECRET_TOKEN not in record.message

    @pytest.mark.asyncio
    async def test_health_endpoint_reports_tinyfish_unavailable_when_circuit_open(self, client: AsyncClient) -> None:
        """Contract: GET /api/v1/health dynamically reports TinyFish as 'unavailable' when circuit breaker is OPEN."""
        retriever = retrieval_service.live_retriever
        if isinstance(retriever, TinyFishLiveRetriever):
            retriever.circuit_breaker.reset()
            # Trip circuit breaker
            for _ in range(settings.DOC_CIRCUIT_BREAKER_FAILURES):
                retriever.circuit_breaker.record_failure()
            assert retriever.circuit_breaker.state == "open"

            with patch.object(settings, "MOCK_MODE", False), patch.object(settings, "TINYFISH_API_KEY", "tf-test-key"):
                # Check health with open breaker
                resp = await client.get("/api/v1/health")
                assert resp.status_code == 200
                data = resp.json()
                assert data["provider_status"]["tinyfish"] == "unavailable"

                # Reset circuit breaker
                retriever.circuit_breaker.reset()
                resp2 = await client.get("/api/v1/health")
                assert resp2.status_code == 200
                data2 = resp2.json()
                assert data2["provider_status"]["tinyfish"] == "configured"

    @pytest.mark.asyncio
    async def test_health_endpoint_makes_zero_network_calls_during_check(self, client: AsyncClient) -> None:
        """Contract: GET /api/v1/health inspects local state without making external HTTP requests."""
        with patch.object(TinyFishLiveRetriever, "fetch_url") as mock_fetch:
            resp = await client.get("/api/v1/health")
            assert resp.status_code == 200
            mock_fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_redirect_escape_violation_is_non_retryable(self) -> None:
        """Contract: When upstream returns a redirected URL that escapes allowlist or targets private IP, abort immediately."""
        mock_sleep = AsyncMock()
        retriever = TinyFishLiveRetriever(api_key="tf-test-key", max_retries=2, sleep_fn=mock_sleep)

        # Redirect escapes to private IP address
        malicious_escape_resp = httpx.Response(
            200,
            json={"results": [{"url": "https://10.0.0.1/admin", "title": "Evil", "text": "Hacked"}]},
            request=httpx.Request("POST", retriever.fetch_base_url),
        )

        with patch.object(httpx.AsyncClient, "post", return_value=malicious_escape_resp) as mock_post:
            evidence = await retriever.fetch_url("https://docs.stripe.com/api/charges/create")
            assert evidence.status == "rejected"
            assert evidence.error_code == "REDIRECT_ESCAPE_VIOLATION"
            assert mock_post.call_count == 1
            mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_provider_failure_cannot_produce_clean_or_issues_found_verdict(self) -> None:
        """Contract: Upstream documentation failure must never produce 'clean' or 'issues_found' verdicts."""
        failed_evidence = NormalizedEvidence(
            evidence_id="ev_failed_503",
            ecosystem="stripe",
            package="stripe",
            source_url="https://docs.stripe.com/api/charges/create",
            canonical_url="https://docs.stripe.com/api/charges/create",
            title=None,
            content_excerpt="",
            retrieved_at="2026-10-17T00:00:00Z",
            provider="tinyfish_live",
            status="unavailable",
            is_mock=False,
            source_trust="official",
            error_code="PROVIDER_ERROR",
            error_message="TinyFish 503 Service Unavailable",
        )

        req = AnalysisRequest(source="import stripe\nstripe.Charge.create(amount=100)\n")
        report = await adjudicator.adjudicate(req, _internal_evidence=[failed_evidence])

        assert report.verdict == "unable_to_verify"
        assert len(report.verified_issues) == 0
