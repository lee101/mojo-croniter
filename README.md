# mojo-croniter

`mojo-croniter` is a Mojo implementation of the hot path in
[croniter](https://pypi.org/project/croniter/): finding the next or previous
datetime matching an expanded cron expression. It keeps parsing, Python
datetime objects, and time-zone edge handling in a small Python layer, then
runs calendar traversal and field matching in a compiled Mojo shared library.

The Python API is compatible with the covered subset after changing the import:

```python
from mojo_croniter import croniter, croniter_range
```

Tests compare `croniter`, `get_next`, `get_prev`, `get_current`, `all_next`,
`all_prev`, `expand`, `is_valid`, `match`, `match_range`, and `croniter_range`
against upstream behavior. `get_next_n` and `get_prev_n` are additional bulk
methods which expand many occurrences through one FFI call.

## Coverage

Supported:

- 5-field minute, 6-field second, and 7-field year expressions
- seconds at the end or at the beginning
- wildcards, lists, steps, ordinary and wraparound ranges
- English month and weekday names
- `@hourly`, `@daily`, `@midnight`, `@weekly`, `@monthly`, `@yearly`, and
  `@annually`
- day-of-month/day-of-week OR and AND modes
- last day (`L`), nearest weekday (`W`), nth weekday (`#`), and last weekday
- forward and reverse iteration, timestamps and datetimes, fixed offsets, and
  IANA time zones including DST gaps and folds
- `expand_from_start_time`

This is not a complete port of croniter's public API. Iteration is
intentionally bounded to 1970 through 2099. Hashed and random fields (`H` and
`R`), `implement_cron_bug`, and combinations of a restricted day-of-month with
`#` or last-weekday syntax are not implemented. These cases raise
`CroniterUnsupportedSyntaxError` rather than silently producing a different
schedule. Unlisted croniter classes, constants, internal helpers, and
implementation-specific extension points are not compatibility targets.

## Install

This repository is currently installed from source with Pixi; it does not yet
publish a wheel. Install the pinned Mojo toolchain, Python, NumPy, pytest, and
croniter 6.2.4, then build the shared library:

```bash
pixi install
pixi run build
```

The upstream package is an environment dependency for parity tests and
benchmarks; `mojo_croniter` does not import it at runtime.

Run the complete checks with:

```bash
pixi run build
pixi run test
pixi run bench
```

## Usage

```python
from datetime import datetime
from mojo_croniter import croniter

schedule = croniter(
    "*/15 9-17 * * mon-fri",
    datetime(2026, 7, 30, 12, 7),
    ret_type=datetime,
)

print(schedule.get_next())
# 2026-07-30 12:15:00

print(schedule.get_next_n(3, datetime))
# [datetime.datetime(2026, 7, 30, 12, 30),
#  datetime.datetime(2026, 7, 30, 12, 45),
#  datetime.datetime(2026, 7, 30, 13, 0)]
```

## Benchmarks

Measured with `pixi run bench` on an Intel Xeon E5-2697 v4 at 2.30 GHz,
Linux x86-64, Python 3.13.14. Times are the best of two measured runs after
one warm-up. Both implementations produce the same number of occurrences from
the same start datetime.

| case | occurrences | mojo-croniter | croniter 6.2.4 | speedup |
|---|---:|---:|---:|---:|
| Every minute, scalar | 50,000 | 1067.34 ms | 1313.53 ms | 1.23x |
| Every 10 seconds, scalar | 50,000 | 1089.80 ms | 1107.57 ms | 1.02x |
| Business hours, scalar | 50,000 | 967.49 ms | 2463.38 ms | 2.55x |
| Every minute, bulk | 200,000 | 84.71 ms | 7417.42 ms | 87.56x |
| Business hours, bulk | 100,000 | 46.44 ms | 5923.15 ms | 127.54x |

Scalar rows call the same `get_next()` API as upstream for every occurrence.
Bulk rows use `get_next_n()` on the Mojo side and repeated `get_next()` calls
upstream because croniter has no bulk equivalent. This isolates the benefit of
amortizing the Python/FFI boundary; it is not presented as a scalar API
comparison.

## How it works

The Python parser normalizes an expression into a 326-byte membership table:
60 minutes, 24 hours, 32 day slots, 13 month slots, 7 weekdays, 60 seconds,
and 130 years. A separate twelve-element `int64` block carries dynamic
day rules. Both arrays are contiguous and caller-owned.

ctypes passes their addresses and lengths as signed 64-bit integers. Python
checks each buffer's dtype, rank, length, contiguity, and non-null address and
keeps the NumPy owners alive for the call. The exported C-ABI Mojo functions
validate lengths and addresses before reconstructing mutable pointers using
`AnyOrigin[mut=True]`; no parametric type crosses the ABI and the Mojo code
performs no allocation.
The kernel converts epoch days with integer Gregorian calendar arithmetic and
jumps directly over disallowed years, months, days, hours, minutes, or
seconds. Python converts between that wall-clock representation and timezone-
aware datetimes, including nonexistent and repeated local times.

`get_next_n` and `get_prev_n` pass an additional contiguous `int64` output
buffer, so an entire sequence is generated inside Mojo without a Python or
ctypes round trip per occurrence.

The traversal is branch-heavy, each occurrence depends on the previous one,
and the membership scans cover at most 130 bytes. Profiling found no
vectorizable or independent hot loop, and the arithmetic intensity is well
below the threshold where GPU transfer and launch overhead could pay off.
Consequently this library intentionally has no parallel or GPU path.
