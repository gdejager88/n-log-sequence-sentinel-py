# n-log-sequence-sentinel-py

Emits a summary record after the Nth occurrence of a given message, then suppresses further occurrences until a quiet timeout passes.

```python
from n_log_sequence_sentinel_py import Sentinel, SummaryRecord

sentinel = Sentinel(threshold=5, quiet_timeout=300.0)

record = sentinel.observe("disk full")
# record is None for the first four occurrences.
# On the 5th, you get a SummaryRecord:

if record is not None:
    print(f"{record.message}: {record.count} times since {record.first_timestamp}")
```

For a callback-style API, use `EmittingSentinel`:

```python
from n_log_sequence_sentinel_py.core import EmittingSentinel, ListCollector

collector = ListCollector()
sentinel = EmittingSentinel(on_summary=collector, threshold=5, quiet_timeout=300.0)

for _ in range(10):
    sentinel.observe("disk full")

# collector.records[0] is the SummaryRecord emitted on the 5th occurrence.
```

## Why this exists

When a service logs the same error repeatedly — a failed connection, a full disk, a refused write — the log fills with noise. This sentinel lets you collapse the first burst into a single summary and then stay quiet until the problem settles down. The trade-off: you lose the exact timing of every individual occurrence after the Nth. That's deliberate. If you need per-event timestamps, run your own logging and don't use this library.

## Interpreting the brief

Two points were ambiguous. The library picks one reading for each:

- **"After the Nth"**: the summary is emitted on the Nth occurrence itself, not on the (N+1)th. The summary record accompanies the triggering call.
- **"Quiet timeout"**: the quiet window begins at the moment of the Nth occurrence (the moment of suppression), and the sentinel allows a fresh sequence only when the clock strictly exceeds `suppressed_until`. At the exact boundary, the message is still suppressed.

## The awkward edge

This sentinel tracks a single sequence counter. It does not deduplicate by message content. If you observe `"a"`, `"b"`, `"c"` with `threshold=3`, the third call emits a summary with `count=3` and `message="c"`. If you need per-message tracking, maintain one sentinel per message key.

The quiet window is checked at observation time, not proactively. If no messages arrive after the threshold is reached, suppression simply continues indefinitely; there is no timer that fires on its own.

## Performance

The window keeps a bounded buffer, so `push` is constant time and memory does not
grow with the length of the stream. `peak` and `trough` are linear in the window
size, which is the trade that keeps `push` cheap.

