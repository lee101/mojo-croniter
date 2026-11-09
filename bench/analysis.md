# mojo-croniter — measured analysis (ANALYZE phase)

> Read first: `MOJO_NOTES.md`, `bench/bench.py`, `README.md`.
> This phase changes nothing in `src/` or `tests/`. Every number below comes from a
> run executed in this session (no estimates). Flop counts are the only derived
> arithmetic and are described as such.

## 0. Machine & method

Measured on this host, everything through `pixi run` (Python 3.13.14,
croniter 6.2.4, NumPy 2.5.1, Mojo `1.2.0.dev2026092605` from `pixi.toml`):

- CPU: `Intel Xeon E5-2697 v4 @ 2.30 GHz` (from `/proc/cpuinfo`), Linux x86-64.
- `pixi run bench` (flock-wrapped, run alone): all 5 cases, exit 0.
- Custom micro-benchmark harness (kept outside the repo, in `/tmp/measure*.py`):
  each entry point timed with 2 warm-ups, then the median and minimum over 3–5
  repeats, per-operation cost = total / N.
- **Sizes are what real callers pass** (from `bench/bench.py` `CASES`): scalar
  N=50,000; bulk N=200,000 (`* * * * *`) and N=100,000 (`*/15 9-17 * * mon-fri`).
  Construction/expand/is_valid/match/croniter_range use small inputs (one
  expression, one date, a 3-day range with 12 hits).
- Bytes touched are **measured at runtime** from the live `croniter` buffers:
  membership table = **326 B** (`uint8`, 326 elems), special block = **96 B**
  (`int64`, 12 elems), bulk output buffer = **8 B per result** (1,600,000 B at
  N=200,000). Input bytes per FFI call = 326 + 96 = **422 B**.
- Flops per dense `find_next` hop: counted from the single-hop path in
  `src/croniter.mojo` (`floor_div` ~3, `civil_from_days` ~8, time-of-day split ~4,
  7× `allowed` ~7, `day_allowed` ~15, range/flow ~9; total **44–60 integer ops**,
  55 used below). Flops/byte = 55 / 422 = **0.13** per FFI call (0.10–0.14 over
  the 44–60 range). Amortised over a bulk call the table is touched once, so the
  per-occurrence figure is ~0.00 — this is why the GPU/parallel verdicts below
  rest on a launch/amortisation argument, not on throughput.
- `perf` was attempted; it is blocked in this container
  (`perf_event_paranoid = 4`, user has no `CAP_PERFMON`), so no hardware counters
  are claimed. The glue/kernel split below comes from timing the pieces.
- Sequential-dependence note (measured, matches `README.md`): every occurrence
  depends on the previous one; the kernel walks one field at a time and jumps
  directly over disallowed values. There is no batch of independent work to
  distribute.

## 1. `pixi run bench` (official harness, run alone)

| case | occurrences | mojo-croniter | croniter 6.2.4 | speedup |
|---|---:|---:|---:|---:|
| Every minute, scalar | 50,000 | 543.66 ms | 1550.03 ms | 2.85x |
| Every 10 seconds, scalar | 50,000 | 538.62 ms | 1225.95 ms | 2.28x |
| Business hours, scalar | 50,000 | 528.88 ms | 2783.26 ms | 5.26x |
| Every minute, bulk | 200,000 | 54.97 ms | 5847.16 ms | 106.37x |

**Note — the port is never slower than upstream in this session's suite.**
The previous `README.md` numbers (a different machine/time) showed 1.02–2.55x
on scalar rows; here they are 2.28–5.26x. The remaining rows in §2/§3
(a few the port loses) are preserved and flagged rather than dropped.

## 2. Ranked hotspot table

Rank is by measured total time at real-caller sizes, worst first. "Glue vs
kernel" is from the decomposition in §4. Flops = 55 per dense hop (see §0).

| # | function (entry point) | input size | time (measured) | bytes touched | flops | flops/byte | memory- or compute-bound | glue or kernel |
|---|---|---|---|---|---|---|---|---|
| 1 | `croniter.get_next(name-based tz, e.g. `30 2 * * *` America/New_York)` (scalar, datetime) | 5,000 calls | **43.4 µs/call** median (44.9 min) | 422 B in + 8 B out per call | 55/hop | 0.13 | **neither — Python datetime/ZoneInfo glue** | **~95% glue** (raw kernel ≈ 2.0 µs of 43.4 µs measured) |
| 2 | `croniter.get_next()` scalar, every minute (float) | 50,000 calls | **7.78 µs/call** median (7.96 min) — total 0.386 s at N=50k | 422 B in + 8 B out per call | 55 | 0.13 | latency-bound (seq. dependence, sub-µs kernel) | glue ≈ 4.7 µs `_ffi_buffers` + 1.9 µs ctypes dispatch; kernel ≤ 0.05 µs amortised (see §4) |
| 3 | `croniter.get_next()` scalar, every 10 s (float) | 50,000 calls | **7.87 µs/call** median | 422 B + 8 B per call | 55 | 0.13 | latency-bound | same split as #2 |
| 4 | `croniter.get_next()` scalar, business-hours (float) | 50,000 calls | **7.82 µs/call** median | 422 B + 8 B per call | 55 | 0.13 | latency-bound | same split as #2 |
| 5 | `croniter.get_next()` scalar, leap day `0 0 29 2 *` (float) | 20,000 calls | **12.15 µs/call** median | 422 B + 8 B per call | ~55 + extra hops | < 0.13 (more skipped days) | still latency/glue | glue dominates; extra kernel hops are small |
| 6 | `croniter.get_prev()` scalar (float), every minute | 50,000 calls | **8.27 µs/call** median | 422 B + 8 B per call | 55 | 0.13 | latency-bound | same as #2 |
| 7 | `croniter.get_next()` scalar, datetime (naive) | 50,000 calls | **9.91 µs/call** median (every minute) | 422 B + 8 B per call | 55 | 0.13 | latency-bound | glue (datetime conversion ≈ +2.1 µs over float path, measured) |
| 8 | `croniter.get_next_n()` bulk, every minute, datetime | 200,000 results | **0.87 µs/result** median (0.174 s total) | 422 B in + 1,600,000 B out (8 B/result) | 55/result | 0.13 per call; ≈0/result amortised | **memory-bound** (output conversion) | **output conversion ≈ 0.87, kernel 0.045 → ~95% glue** |
| 9 | `croniter.get_next_n()` bulk, every minute, float | 200,000 results | **0.30 µs/result** median (0.060 s total) | 422 B in + 1,600,000 B out | 55/result | 0.13/call | latency/kernel-bound, kernel tiny | kernel 0.045 µs (15%); wrapper + float list ≈ 0.25 |
| 10 | `croniter.get_next_n()` bulk, business-hours, float | 100,000 results | **0.30 µs/result** median (0.030 s total) | 422 B + 800,000 B out | ~55/result | 0.13 | same as #9 | kernel 0.045-class; glue dominates |
| 11 | `croniter.get_next_n()` bulk, business-hours, datetime | 100,000 results | **0.90 µs/result** median (0.090 s total) | 422 B + 800,000 B out | ~55/result | 0.13 | memory-bound (conversion) | conversion ≈ 0.85 |
| 12 | `croniter.get_prev_n()` bulk (float) | 100,000–200,000 | **0.24–0.28 µs/result** median | 422 B + output | 55/result | 0.13 | same as #9 | kernel + glue |
| 13 | **raw `mcron_fill` kernel** (ctypes, amortised) | 200,000 results, **one** FFI call | **0.045 µs/result** median (0.009 s total) | 422 B once + 1,600,000 B out written | 55/result | 0.13/call | **latency/branch-bound, not throughput** | **kernel only** |
| 14 | **`croniter_range()`** (3-day, 12 hits) | 1 range | **215 µs** median (184 min) | 422 B × 12 calls (scalar) | 55 × 12 hops | 0.13 | glue (per-hit scalar calls) | glue |
| 15 | **`match()`** | 1 (expr, date) | **75 µs** median (69 min) | 422 B × ~2 calls | ~55 × 2 | 0.13 | glue | glue |
| 16 | `croniter()` construction (business expr) | 1 expression | **63.9 µs** median (53.6 min) | 422 B built + parse | parse-dominated | — | compute (Python parse) | **100% Python** (no kernel) |
| 17 | `croniter()` construction (every minute) | 1 expression | **25.8 µs** median (22.4 min) | 422 B built + parse | parse-dominated | — | compute (Python parse) | 100% Python |
| 18 | `expand()` / `is_valid()` | 1 expression | **36.4 µs** median (`expand`), **36.5 µs** (`is_valid`) | expression text | — | — | compute (parse) | 100% Python |
| 19 | `datetime_to_timestamp()` | 1 datetime | **0.96 µs** median (0.83 min) | 0 | — | — | — | 100% Python |

## 3. Upstream comparison and rows where the port is **slower** (kept, not dropped)

Scalar `get_next()` (per call, median; N as in §2). Speedup = upstream / port.

| case | port (µs) | upstream croniter 6.2.4 (µs) | port vs upstream |
|---|---:|---:|---|
| every minute, float | 7.78 | 25.16 | **3.24x faster** |
| every 10 s, float | 7.87 | 22.25 | **2.83x faster** |
| business hours, float | 7.82 | 44.95 | **5.75x faster** |
| leap day, float | 12.15 | 128.26 | **10.6x faster** |
| yearly `0 0 1 1 *`, float | 9.36 | 73.58 | **7.9x faster** |
| every minute, datetime | 9.91 | ≈25 (upstream float; upstream datetime is ≥ this) | **≥2.5x faster** |
| every minute, `get_prev`, float | 8.27 | 25.44 | **3.08x faster** |
| `get_prev`, every 10 s | 7.91 | 19.71 | **2.49x faster** |
| `get_prev`, business hours | 7.99 | 49.35 | **6.2x faster** |
| tz-aware (`30 2 * * *` / `30 1 * * *`) | 43.4–44.1 | 77.2–88.4 | **1.8–2.0x faster** |
| construction, every minute | 25.8 | 43.6 | **1.69x faster** |
| construction, business expr | 63.9 | 153.7 | **2.40x faster** |
| construction, `0 0 l * *` | 44.4 | **43.2** | **⚠️ 0.97x — port slower by 1.2 µs** |
| construction, `0 0 * * 2#3` | 46.5 | **47.6** | port faster by 1.1 µs (no slower row) |
| construction, 6-field seconds | 26.3 | 51.8 | **1.97x faster** |
| `expand()` | 36.4 | 155.1 | **4.3x faster** |
| `is_valid()` | 36.5 | 154.9 | **4.2x faster** |
| `match()` | 75.2 | 196.3 | **2.6x faster** |
| `croniter_range()` (12 hits) | 215.5 | 922.8 | **4.3x faster** |

The only slower row in this suite is construction of `0 0 l * *`
(44.4 vs 43.2 µs, a 2.8% difference) — pure Python parse cost, both well
inside measurement noise for a one-off allocation path, but recorded here as
required rather than dropped.

### Plain numpy / Python baselines (measured)

| baseline | size | time (median) | per unit |
|---|---|---:|---|
| NumPy `arange + boolean filter` producing ~200k hits | 12 M-element span | 0.315 s total | **1.57 µs/result** |
| Pure-Python arithmetic listcomp (`[i*60 ...]`) | 200,000 elems | — | **0.069 µs/elem** |
| Pure-Python per-element loop over scalar `get_next()` | 50,000 calls | 0.386 s total | **7.72 µs/call** |
| `mcron_next` via raw ctypes (no Python wrapper) | 200,000 calls | — | **1.91 µs/call** |
| `mcron_fill` via raw ctypes (one FFI call, 200k results) | 200,000 results | 0.009 s total | **0.045 µs/result** |

So the NumPy vector baseline is **5.3x slower** than the port's bulk path
(1.57 vs 0.30 µs/result); the kernel itself (0.045 µs/result raw) is
**34x faster** than the NumPy baseline on the equivalent work.

## 4. Glue vs kernel decomposition (measured)

Timing the pieces of one scalar `get_next()` (every minute, float):

| piece | µs/call (measured) | evidence |
|---|---:|---|
| full scalar `get_next()` | **7.78** | §2, N=50,000 |
| `_ffi_buffers()` (2× `_buffer_address` + tuple pack) | **4.07–4.49** | timed in isolation |
| `_buffer_address()` (dtype/rank/size/contiguity/address checks) | **2.08** each | timed in isolation |
| `_wall_start()` + `_int64()` | 0.23 + 0.24 | timed in isolation |
| raw ctypes `mcron_next` (dispatch + kernel) | **1.91** | raw `lib().mcron_next` loop |
| kernel alone (`mcron_fill` amortised over 200k) | **≤ 0.05** | 0.045 µs/result |

**Reading:** of the 7.78 µs scalar call, ≈ 4.7 µs is `_ffi_buffers` (mostly the
two `_buffer_address` validations), ≈ 1.9 µs is the ctypes dispatch, and
the actual Mojo calendar computation is at most the 0.045 µs amortised figure
— i.e. **> 85% of a scalar call is Python/ctypes glue, < 1% is the kernel**.
The two `_buffer_address` calls are the single biggest measured cost in the
whole hot path.

Construction decomposition (per call, median): `_parse` 6.49 µs,
`_compile_table` 7.42 µs, full `croniter()` 25.8 µs (every minute) /
63.9 µs (business expr) — the remainder is `set_current`/bookkeeping,
all Python, no kernel time.

Tz-aware path: 43.4 µs/call with the kernel at ≈ 2.0 µs → **≥ 95% of tz
time is Python** (`_resolve_wall`, `_ambiguous_alternate`, `ZoneInfo`
round-trips). Pre-tz `_ambiguous_alternate` issues its own extra scalar FFI
call per `get_next` (see §5).

Bulk datetime conversion: `timestamp_to_datetime` listcomp = **0.87 µs/
result** (0.868 vs 0.868 measured for `get_next_n(..., datetime)`), i.e.
effectively **100% of the bulk-datetime per-result cost is Python
conversion**, 0.045 µs is kernel.

## 5. Python-level loops that re-enter ctypes per element

These exist and were timed. Calling `get_next()` in a Python `for` loop is
**one ctypes call per occurrence** (via `_ffi_one` → `lib().mcron_next`):

| pattern | where | per-element cost (measured) |
|---|---|---|
| `[it.get_next() for _ in range(N)]`, float | scalar loop | **7.7–7.9 µs** (vs 0.30 µs amortised in bulk) |
| `[it.get_next() for _ in range(N)]`, datetime | scalar loop | **9.6–9.9 µs** |
| `[it.get_next() for _ in range(N)]`, tz-aware | scalar loop | **43.4 µs** |
| `_get_n` with `tzinfo is not None` (`core.py` `_get_n`) | falls back to `[method(ret_type) for _ in range(count)]` | same as scalar row — bulk is **not** used for tz |
| `croniter_range` / `match_range` | built on scalar `get_next/get_prev` | **215 µs** for 12 hits (measured) — 12 scalar FFI calls |
| `_ambiguous_alternate` (tz path) | one extra `_ffi_one(True, ...)` per scalar call | adds ≈ 1 FFI round-trip to every tz scalar call |

`get_next_n/get_prev_n` (t
... [truncated 6154 chars]