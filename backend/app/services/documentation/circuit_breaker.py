"""In-memory, bounded circuit breaker for documentation retrieval providers.

States:
- closed: Normal operation. Requests pass through to upstream.
- open: Tripped by repeated transient failures. Fast-fails immediately without network calls.
- half_open: Recovery cooldown elapsed. Permits a single probe request to check upstream health.

Scope:
- In-memory, per-provider-instance (not distributed, not persisted across process restarts).
- Thread-safe and concurrency-safe via instance-level lock (no global lock).
"""

import threading
import time
from typing import Callable, Literal, Optional

CircuitState = Literal["closed", "open", "half_open"]


class CircuitBreaker:
    """Bounded, thread-safe, in-memory circuit breaker scoped per provider instance."""

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout_seconds: float = 30.0,
        time_fn: Optional[Callable[[], float]] = None,
    ) -> None:
        self.failure_threshold = max(1, failure_threshold)
        self.recovery_timeout_seconds = max(0.001, recovery_timeout_seconds)
        self._time_fn = time_fn or time.monotonic
        self._lock = threading.Lock()

        self._state: CircuitState = "closed"
        self._consecutive_failures: int = 0
        self._last_failure_time: float = 0.0
        self._probe_in_flight: bool = False

    @property
    def state(self) -> CircuitState:
        """Current state of the circuit breaker with automatic half-open evaluation."""
        with self._lock:
            if self._state == "open":
                now = self._time_fn()
                if (now - self._last_failure_time) >= self.recovery_timeout_seconds:
                    self._state = "half_open"
                    self._probe_in_flight = False
            return self._state

    @property
    def consecutive_failures(self) -> int:
        """Number of consecutive failures recorded."""
        with self._lock:
            return self._consecutive_failures

    @property
    def is_probe_in_flight(self) -> bool:
        """Whether a recovery probe is currently executing."""
        with self._lock:
            return self._probe_in_flight

    def can_execute(self) -> bool:
        """Return True if a request is permitted to proceed, False if circuit is open.

        Guarantees:
        - When in 'half_open', only the first caller is admitted as a probe.
        - Concurrent callers are rejected while the probe is in flight.
        """
        with self._lock:
            # Re-evaluate transition from open to half_open atomically under lock
            if self._state == "open":
                now = self._time_fn()
                if (now - self._last_failure_time) >= self.recovery_timeout_seconds:
                    self._state = "half_open"
                    self._probe_in_flight = False

            if self._state == "closed":
                return True
            elif self._state == "half_open":
                if not self._probe_in_flight:
                    self._probe_in_flight = True
                    return True
                return False
            else:  # open
                return False

    def record_success(self) -> None:
        """Record a successful response: resets failures and closes the circuit."""
        with self._lock:
            self._state = "closed"
            self._consecutive_failures = 0
            self._probe_in_flight = False

    def record_failure(self) -> None:
        """Record a transient failure: increments count and trips to open if threshold reached or in half_open."""
        with self._lock:
            self._consecutive_failures += 1
            self._last_failure_time = self._time_fn()
            self._probe_in_flight = False

            # Any failure in half_open immediately trips back to open;
            # in closed, threshold consecutive failures trips to open.
            if self._state == "half_open" or self._consecutive_failures >= self.failure_threshold:
                self._state = "open"

    def record_probe_abandoned(self) -> None:
        """If a half-open probe is cancelled or aborted before completion,
        release probe_in_flight so subsequent calls can re-probe rather than getting stuck.
        """
        with self._lock:
            if self._state == "half_open":
                self._probe_in_flight = False

    def reset(self) -> None:
        """Manually reset the circuit breaker to closed state."""
        with self._lock:
            self._state = "closed"
            self._consecutive_failures = 0
            self._probe_in_flight = False
            self._last_failure_time = 0.0

