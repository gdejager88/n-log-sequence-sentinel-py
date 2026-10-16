import unittest

from n_log_sequence_sentinel_py import Sentinel, SummaryRecord
from n_log_sequence_sentinel_py.core import EmittingSentinel, ListCollector


class FakeClock:
    """Deterministic clock for tests. Never touches wall-clock time."""

    def __init__(self, start: float = 0.0):
        self._t = start

    def __call__(self) -> float:
        return self._t

    def advance(self, dt: float) -> None:
        self._t += dt


class TestSentinelBasics(unittest.TestCase):
    def test_no_emission_before_threshold(self):
        clock = FakeClock()
        s = Sentinel(threshold=3, quiet_timeout=10.0, clock=clock)
        self.assertIsNone(s.observe("err"))
        self.assertIsNone(s.observe("err"))
        # The 3rd observation is the Nth and emits.
        self.assertIsNotNone(s.observe("err"))

    def test_emits_on_nth_occurrence(self):
        clock = FakeClock(start=100.0)
        s = Sentinel(threshold=3, quiet_timeout=10.0, clock=clock)
        s.observe("err")
        s.observe("err")
        record = s.observe("err")
        self.assertIsNotNone(record)
        self.assertEqual(record.count, 3)
        self.assertEqual(record.message, "err")
        self.assertEqual(record.first_timestamp, 100.0)
        self.assertEqual(record.summary_timestamp, 100.0)

    def test_threshold_of_one_emits_on_first_observation(self):
        clock = FakeClock()
        s = Sentinel(threshold=1, quiet_timeout=5.0, clock=clock)
        record = s.observe("boom")
        self.assertIsNotNone(record)
        self.assertEqual(record.count, 1)

    def test_invalid_threshold_raises(self):
        with self.assertRaises(ValueError):
            Sentinel(threshold=0, quiet_timeout=10.0, clock=FakeClock())
        with self.assertRaises(ValueError):
            Sentinel(threshold=-1, quiet_timeout=10.0, clock=FakeClock())

    def test_invalid_quiet_timeout_raises(self):
        with self.assertRaises(ValueError):
            Sentinel(threshold=3, quiet_timeout=0.0, clock=FakeClock())
        with self.assertRaises(ValueError):
            Sentinel(threshold=3, quiet_timeout=-5.0, clock=FakeClock())


class TestSuppression(unittest.TestCase):
    def test_suppression_after_emission(self):
        clock = FakeClock()
        s = Sentinel(threshold=2, quiet_timeout=10.0, clock=clock)
        self.assertIsNone(s.observe("x"))
        self.assertIsNotNone(s.observe("x"))  # emits
        # These occur during the quiet window -> suppressed.
        self.assertIsNone(s.observe("x"))
        clock.advance(5.0)
        self.assertIsNone(s.observe("x"))

    def test_resets_after_quiet_timeout(self):
        clock = FakeClock()
        s = Sentinel(threshold=2, quiet_timeout=10.0, clock=clock)
        s.observe("x")
        s.observe("x")  # emits, suppression until t=10
        clock.advance(9.0)
        # Still suppressed.
        self.assertIsNone(s.observe("x"))
        # Advance past the quiet window.
        clock.advance(2.0)  # total advance = 11, now t=11 > 10
        # Fresh sequence starts.
        self.assertIsNone(s.observe("x"))  # count 1
        record = s.observe("x")  # count 2 -> emits
        self.assertIsNotNone(record)
        self.assertEqual(record.count, 2)

    def test_exact_boundary_starts_fresh_sequence(self):
        # At the exact moment the quiet window ends, the sentinel resets and
        # starts a fresh sequence (now < suppressed_until is False at equality).
        clock = FakeClock()
        s = Sentinel(threshold=1, quiet_timeout=10.0, clock=clock)
        s.observe("x")  # emits, suppressed_until = 10
        clock.advance(10.0)  # now = 10, exactly at boundary
        # Fresh sequence starts; with threshold=1 this emits immediately.
        record = s.observe("x")
        self.assertIsNotNone(record)
        self.assertEqual(record.count, 1)


class TestSummaryRecord(unittest.TestCase):
    def test_record_is_frozen(self):
        record = SummaryRecord(
            message="m", count=2, first_timestamp=1.0, summary_timestamp=2.0
        )
        with self.assertRaises(Exception):
            record.count = 99  # type: ignore[misc]


class TestEmittingSentinel(unittest.TestCase):
    def test_callback_invoked_on_summary(self):
        clock = FakeClock()
        collector = ListCollector()
        es = EmittingSentinel(
            on_summary=collector, threshold=2, quiet_timeout=10.0, clock=clock
        )
        es.observe("msg")
        es.observe("msg")
        self.assertEqual(len(collector.records), 1)
        self.assertEqual(collector.records[0].message, "msg")
        self.assertEqual(collector.records[0].count, 2)

    def test_callback_not_invoked_for_suppressed(self):
        clock = FakeClock()
        collector = ListCollector()
        es = EmittingSentinel(
            on_summary=collector, threshold=1, quiet_timeout=10.0, clock=clock
        )
        es.observe("msg")
        self.assertEqual(len(collector.records), 1)
        es.observe("msg")
        es.observe("msg")
        self.assertEqual(len(collector.records), 1)

    def test_collector_clear(self):
        collector = ListCollector()
        record = SummaryRecord(
            message="m", count=1, first_timestamp=0.0, summary_timestamp=0.0
        )
        collector(record)
        self.assertEqual(len(collector.records), 1)
        collector.clear()
        self.assertEqual(len(collector.records), 0)


class TestProperties(unittest.TestCase):
    def test_threshold_property(self):
        s = Sentinel(threshold=7, quiet_timeout=30.0, clock=FakeClock())
        self.assertEqual(s.threshold, 7)

    def test_quiet_timeout_property(self):
        s = Sentinel(threshold=3, quiet_timeout=42.0, clock=FakeClock())
        self.assertEqual(s.quiet_timeout, 42.0)

    def test_emitting_sentinel_threshold_property(self):
        es = EmittingSentinel(
            on_summary=ListCollector(), threshold=4, quiet_timeout=10.0,
            clock=FakeClock(),
        )
        self.assertEqual(es.threshold, 4)


class TestDifferentMessages(unittest.TestCase):
    """Verify messages are not deduplicated; the sentinel treats every
    observation as part of the same single stream.

    This documents the chosen interpretation: we track one sequence counter,
    not per-message counters.
    """

    def test_messages_are_not_tracked_individually(self):
        clock = FakeClock()
        s = Sentinel(threshold=2, quiet_timeout=10.0, clock=clock)
        self.assertIsNone(s.observe("a"))
        record = s.observe("b")
        # The second observation triggers regardless of message content.
        self.assertIsNotNone(record)
        self.assertEqual(record.count, 2)
        # The summary record carries the message of the triggering (Nth) call.
        self.assertEqual(record.message, "b")


if __name__ == "__main__":
    unittest.main()
