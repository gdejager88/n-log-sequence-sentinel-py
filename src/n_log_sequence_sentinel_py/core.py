"""Core implementation of the N-log sequence sentinel."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, List, Optional


@dataclass(frozen=True)
class SummaryRecord:
    """Record emitted when the threshold is reached.

    The timestamp uses whatever clock the sentinel was constructed with,
    so tests can inject a deterministic fake clock. We use a frozen dataclass
    so the record is immutable and trivially comparable in assertions.
    """
    message: str
    count: int
    first_timestamp: float
    summary_timestamp: float


class Sentinel:
    """Emits a summary record after the Nth occurrence of a message.

    Further identical messages are suppressed until the quiet timeout passes.
    After suppression ends, the next occurrence starts a fresh sequence.

    Interpretation chosen for the brief's ambiguity around "after the Nth":
    the summary is emitted when the Nth occurrence is recorded (i.e. the
    summary accompanies the Nth, not the (N+1)th).

    Interpretation chosen for "quiet timeout": the quiet window starts at
    the Nth occurrence's timestamp (the moment of suppression), not after
    some additional delay. This keeps the behaviour deterministic for testing.
    """

    def __init__(
        self,
        threshold: int = 5,
        quiet_timeout: float = 300.0,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        if threshold < 1:
            raise ValueError("threshold must be >= 1")
        if quiet_timeout <= 0:
            raise ValueError("quiet_timeout must be > 0")
        # A clock callable lets tests advance time deterministically without
        # sleeping, and avoids coupling to wall-clock behaviour in the test suite.
        self._clock = clock if clock is not None else time.monotonic
        self._threshold = threshold
        self._quiet_timeout = quiet_timeout
        self._count = 0
        self._first_timestamp: Optional[float] = None
        self._suppressed_until: Optional[float] = None

    @property
    def threshold(self) -> int:
        return self._threshold

    @property
    def quiet_timeout(self) -> float:
        return self._quiet_timeout

    def observe(self, message: str) -> Optional[SummaryRecord]:
        """Record a message occurrence.

        Returns a SummaryRecord when the Nth occurrence triggers a summary.
        Returns None for suppressed messages or non-triggering occurrences.
        """
        now = self._clock()

        # If currently in suppression, check whether the quiet window has expired.
        if self._suppressed_until is not None:
            if now < self._suppressed_until:
                return None
            # Quiet window elapsed. Reset for a fresh sequence.
            self._reset()

        self._count += 1
        if self._first_timestamp is None:
            self._first_timestamp = now

        if self._count >= self._threshold:
            # Emit summary on the Nth occurrence and enter suppression.
            record = SummaryRecord(
                message=message,
                count=self._count,
                first_timestamp=self._first_timestamp,
                summary_timestamp=now,
            )
            self._suppressed_until = now + self._quiet_timeout
            # Reset the count so that the first observation after suppression
            # starts a brand-new sequence (not a continuation of the old one).
            self._count = 0
            self._first_timestamp = None
            return record

        return None

    def _reset(self) -> None:
        self._count = 0
        self._first_timestamp = None
        self._suppressed_until = None


class ListCollector:
    """Simple collector that stores emitted summary records in a list.

    Useful as a callback for real usage and as a test aid.
    """

    def __init__(self) -> None:
        self.records: List[SummaryRecord] = []

    def __call__(self, record: SummaryRecord) -> None:
        self.records.append(record)

    def clear(self) -> None:
        self.records.clear()


class EmittingSentinel:
    """Sentinel that invokes a callback when a summary is produced.

    This wraps Sentinel for the common case where callers want to pass a
    log function or collector rather than inspect the return value of each
    observe() call.
    """

    def __init__(
        self,
        on_summary: Callable[[SummaryRecord], None],
        threshold: int = 5,
        quiet_timeout: float = 300.0,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self._sentinel = Sentinel(
            threshold=threshold, quiet_timeout=quiet_timeout, clock=clock
        )
        self._on_summary = on_summary

    def observe(self, message: str) -> None:
        record = self._sentinel.observe(message)
        if record is not None:
            self._on_summary(record)

    @property
    def threshold(self) -> int:
        return self._sentinel.threshold

    @property
    def quiet_timeout(self) -> float:
        return self._sentinel.quiet_timeout
