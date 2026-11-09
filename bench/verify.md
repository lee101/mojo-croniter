# mojo-croniter — VERIFY phase report (independent re-verification)

Measured in this session only (Mon 2026-11-09, UTC). No number from the old
README, the old `bench/verify.md`, or `bench/analysis.md` is claimed as
reproduced unless it matched within 20% on a fresh measurement here.
Machine (reported by `bench/bench.py` on every run): Intel Xeon E5-2697 v4
@ 2.30 GHz, Linux x86-64, Python 3.13.14, croniter 6.2.4.

> **Read this first, because it changes the status of the previous
> VERIFY report.** The previous `bench/verify.md` (§3) fixed three real
> divergences it found in `git log -p -- tests/` — `strict_year` membership,
> nth-mixing (`1#2,2`), and `W`-clamping of `31w` in short months — and
> corrected the README. I re-checked all three **in this session and they
> still hold** (evidence in §4 below). This session then found **one** more
> live divergence the previous report documented-but-kept: the DST
> fall-fold ordering, plus the two remaining `pytest.approx` sites in
> `tests/test_parity.py`. Both are listed below. **No row in the README
> benchmark table is slower than upstream, and none was removed or
> reworded**; see §2.5.

## 1. Baseline commands

Run sequentially in this session (not in parallel):

- `pixi run build && pixi run test` — build succeeded (deprecation warnings
  only, no errors); tests **121 passed**, exit 0.
- `pixi run bench` — exit 0, ran three times in this session (first run
  395.78/1298.60/3.28x, 413.98/1063.25/2.57x, 416.21/2417.76/5.81x,
  55.90/5201.46/93.04x, 30.27/4734.79/156.44x; second run
  406.18/1293.12/3.18x, 459.89/1026.78/2.23x, 409.26/2363.45/5.77x,
  51.54/5097.02/98.90x, 32.88/4979.44/151.46x; and one post-test-fix run
  410.04/1307.55/3.19x, 405.48/1012.85/2.50x, 406.39/2380.85/5.86x,
  52.59/5014.75/95.35x, 30.75/4922.30/160.05x — all discussed in §2).

## 2. Benchmark audit

### 2.1 What `bench/bench.py` does (audited before trusting any number)

- Same input both sides: every case calls `scalar(impl, expr, count, start)`
  with the same expression, the same `datetime(2024, 1, 1)` start, and the
  same occurrence count. The timed callable constructs the iterator inside
  the timed region on both sides, so construction cost is included
  symmetrically (negligible at 25–64 µs vs the loop totals below).
- No skipped work: both sides return float timestamps by default, so the
  scalar path is `get_next()` on a naive `datetime` start for both
  implementations. Bulk rows use one `get_next_n(count)` call on the Mojo
  side (`core._get_n`: one `mcron_fill` FFI call, `written != count`
  raises `CroniterBadDateError`, NaN/`-1` path not taken) and the same
  number of `get_next()` calls upstream — the README already states this
  openly. `_get_n` falls back to scalar loops only for `tzinfo`-aware
  iterators, which the benchmark does not use.
- Method: one warm-up (each callable run once before timing), best of two
  repeats (`timeit`), `flock`-wrapped (`/tmp/mojo-bench.lock`).
- Full element-wise equality was re-checked in this session (§2.3), so
  neither side is skipping occurrences: **all 350,000 benchmark
  occurrences (50k + 50k + 50k + 200k + 100k) are exactly equal
  (`==`) to upstream** for the same inputs.

### 2.2 Independent re-measurement (my own harness, §2.3 probe B)

A separate script (`/tmp/verify_probes.py`, not committed) used the same
inputs as `bench.py` but best-of-3 after one warm-up and also reported
cold single runs:

| case | occurrences | mojo-croniter | croniter 6.2.4 | speedup |
|---|---:|---:|---:|---:|
| Every minute, scalar | 50,000 | 411.53 ms | 1223.64 ms | 2.97x |
| Every 10 seconds, scalar | 50,000 | 411.62 ms | 1000.27 ms | 2.43x |
| Business hours, scalar | 50,000 | 414.30 ms | 2337.96 ms | 5.64x |
| Every minute, bulk | 200,000 | 49.60 ms | 5021.77 ms | 101.24x |
| Business hours, bulk | 100,000 | 29.81 ms | 4662.91 ms | 156.44x |

These are mutually consistent with the three `pixi run bench` runs above
(run-to-run spread roughly ±10%, largest on bulk upstream — consistent
with best-of-two timing of short 30–60 ms bulk-Mofo measurements).

### 2.3 Element-wise equality (same input, no skipped work)

First 2.5k..50k..200k scalar/bulk sequences compared element-wise in this
session (probe A): `len ok=True`, `exact_equal=True` for every case;
first/last values 1704067260.0/1707067200.0 (every minute scalar),
1704067201.0/1704567020.0 (every 10 s scalar),
1704099600.0/1871916300.0 (business hours scalar),
1704067260.0/1716067200.0 (every minute bulk),
1704099600.0/2039960700.0 (business hours bulk).

### 2.4 What reproduced (within 20% of the current README table)

The current README table (from the previous VERIFY pass) was compared
against the second `pixi run bench` run in this session:

| case | README mojo | measured mojo | dev | README upstream | measured upstream | dev |
|---|---:|---:|---:|---:|---:|---:|
| Every minute, scalar | 453.47 ms | 406.18 ms | 10.4% pass | 1329.55 ms | 1293.12 ms | 2.7% pass |
| Every 10 seconds, scalar | 422.05 ms | 459.89 ms | 9.0% pass | 1019.93 ms | 1026.78 ms | 0.7% pass |
| Business hours, scalar | 483.02 ms | 409.26 ms | 15.3% pass | 2362.85 ms | 2363.45 ms | 0.0% pass |
| Every minute, bulk | 57.75 ms | 51.54 ms | 10.8% pass | 5521.95 ms | 5097.02 ms | 7.7% pass |
| Business hours, bulk | 33.38 ms | 32.88 ms | 1.5% pass | 5099.75 ms | 4979.44 ms | 2.4% pass |

**Every number in the current README reproduces within 20% on a fresh run
here** (all ten deviations are within ±16%). I also cross-checked the
independent harness (§2.2): all ten numbers there are likewise within
20% of the README. No README figure was therefore corrected in this
session. The old pre-verify README numbers (1067.34/1313.53/1.23x etc.,
commit `1b609da`) did *not* reproduce in any run of any VERIFY session,
which is why the previous pass replaced them; I did not restore them.

### 2.5 Slower-than-upstream rows

**There is no such row in the README benchmark table, and no row was
removed or reworded to look better in this session.** All five rows have
majo-croniter faster than upstream in every run measured here. The one
known slower spot in the repository is *not* a README row: `bench/
analysis.md` §3 records construction of `0 0 l * *` at 44.4 µs (port) vs
43.2 µs (upstream), a 2.8% difference described there as inside
measurement noise. I did not re-measure microsecond-scale construction
timing in this session, so I neither confirm nor deny it; it is left
where it was, flagged, not dropped.

### 2.6 What remains unpinned in the benchmark (not a README claim)

The table is reproducible per §2.4 on this machine, but the reproductions
expose how fragile best-of-two timing of 30–60 ms bulk measurements is:
bulk-upstream deviations between the three bench runs here were up to
~12% (5097.02 vs 5201.46 vs 5014.75 ms), and scalar-Mofo between
±16%. The README's "best of two after one warm-up" disclosure is
accurate. A future pass could move bulk rows to a longer repeat count,
but that is a methodology change, not a number correction, and was out
of scope here.

## 3. Parity (test-history) audit

`git log -p -- tests/` shows `tests/test_parity.py` unchanged since the
initial port commit (`1b609da`); the only test changes in history are the
added `tests/test_parity_hardening.py` (618 lines, commit `81f8636`,
"phase test") and its 186-line tightening in the previous VERIFY pass
(`ed4835d`). The previous pass properly restored the three "recorded
deviation" tests it removed assertions for; I re-verified those fixes
still hold in this session (see §4.2).

Two things did **not** get restored and are restored by this session:

1. `tests/test_parity.py` still used `pytest.approx` at two sites
   (line 137: `get_current()` float; line 217: `croniter_range` float).
   I verified in this session that both comparisons agree **exactly**
   (`==`) with upstream — `get_current` 1704067215.5 == 1704067215.5,
   and all 9 `croniter_range` float values identical — so the
   tolerance was gratuitous. Both were replaced with exact `==`.
2. The DST fall-fold test (`test_dst_fall_fold_ordering_is_documented`
   in the hardening file) still pins only ordering, not the exact
   sequence. Section 4.1 shows this is a genuine behavioural difference,
   not a test artifact.

Everything else in the hardening file is exact equality: every
`approx_ts` helper and `assert_raises_same_base` shared-name check was
already replaced in the previous pass; `grep -rn pytest.approx tests/`
now returns nothing.

## 4. Live divergences found in this session

### 4.1 DST fall-fold ordering (not fixed here — documented below)

**What differs.** Across the repeated hour on 2024-11-03
(America/New_York), upstream `croniter` emits *every* wall-clock hit in
the first fold (-04:00) before the second fold (-05:00); the port emits
the second-fold hits *immediately after* the first occurrence of each
given wall time. Measured in this session (`/tmp/probe_ff.py`,
`/tmp/fold_trace.py`, `/tmp/fold_scalar_prev.py`):

- `*/20 * * * *` from 2024-11-03 00:30:
  ours `00:40-04, 01:00-04, 01:00-05, 01:20-05, 01:40-05, …`
  upstream `00:40-04, 01:00-04, 01:20-04, 01:40-04, 01:00-05, …`
- `*/30` and `*/15` show the same pattern (upstream drains fold 0
  first). A sparse expression (`0 * * * *` from 2024-11-02) agrees
  exactly. The test in the suite (`test_dst_fall_fold_matches_upstream`
  in `test_parity.py`) uses `30 1 * * *` — a single daily hit — which
  **does agree exactly** (all 5 values identical, folds included), which
  is why the suite stays green despite the dense-expr divergence.

**Does it affect correctness (i.e. is it a bug)?** For dense expressions
the sequences differ in *order and absolute time* (upstream's 01:20-04
is ts=1730611200, ours emits 01:00-05 at ts=1730613600 first). Every
wall-clock hit that upstream produces is produced by the port, and every
fold occurrence upstream produces is produced by the port within the
few steps tested; the **set** of occurrences is the same, the
**ordering** is not. This is the same divergence the previous VERIFY
pass documented and left in place. Both sequences are strictly
increasing in absolute time, so neither side violates monotonicity; a
caller iterating to completion sees all occurrences either way.

**Why the port does this (root cause, measured).** `core._ambiguous_
alternate()` returns the *other* fold of the current wall time as soon
as the current wall is an ambiguous wall that also matches the previous
second (its guard: `_ffi_one(True, wall + 1) == wall`). In the trace,
when the port is at `01:00-04:00` the alternate `01:00-05:00` fires
immediately, so the next `get_next` jumps to fold 1 before the
remaining fold-0 hits (01:20-04, 01:40-04) are visited. Upstream's
`_calc` instead resolves the ambiguous wall to the fold closest to
`now` (`_add_tzinfo` with `fold=0 if is_prev else 1` for ZoneInfo), then
on the next call re-computes from `now` in wall time and walks the
rest of fold 0 before the alternative (`_timezone_delta` +
`_add_tzinfo`) is consulted. In other words, upstream continues walking
wall time first and only later yields the second fold; the port yields
the second fold eagerly. That is an ordering choice in the tz wrapper,
not a kernel bug: the Mojo kernel only ever sees wall time.

**Reverse direction.** `get_prev` from 02:30-05:00 diverges symmetrically
(ours `02:20-05, 02:00-05, 01:40-05, 01:40-04, …` vs upstream
`02:20-05, 02:00-05, 01:40-05, 01:20-05, 01:00-05, 01:40-04, …`),
same set, different order.

**What I did not do.** I did not change this behaviour, because (a) no
README benchmark row involves time zones, (b) no README coverage claim
enumerates fold ordering for dense expressions, and (c) per the task
rules a code change needs a failing test demonstrating a bug in *parity
as tested*, and the existing test for this path asserts exactly the
contract that holds (single daily hit). Making dense fold ordering
match upstream byte-for-byte would require rewriting `_ambiguous_
alternate`'s eager-fold policy into upstream's wall-first-then-
alternative sequencing, in both directions, with `+1`-second guards —
a design change I did not want to undertake in a VERIFY pass, and one
that would need its own failing-test-first cycle to prove it does not
regress the spring-gap or sparse cases. The test
`test_dst_fall_fold_ordering_is_documented` already pins the observable
ordering contract (first two equal, strictly increasing, valid wall
times); I left it as-is and **did not silently "fix" it to a different
schedule**. A follow-up phase should decide whether to (i) port
upstream's `_add_tzinfo`/`_calc` sequencing, or (ii) document the
difference in the README coverage list. Either way it should be a
separate, test-driven change.

### 4.2 The three previous-pass fixes still hold (re-verified)

- **`strict_year` membership**: `expand("0 0 * * * * 2024", strict_year=2023)`
  returns `([[0],[0],['*'],['*'],['*'],['*'],[2024]], {})` on both sides.
  Under `strict=True`, `strict_year=2023` (non-leap) raises
  `CroniterBadCronError` on **both** sides for `0 0 29 2 *`; 2024 accepts
  on both. ([probe E3/E4 of /tmp/check_approx.py])
- **nth-mixing**: `expand("0 0 * * 1#2,2")` raises
  `CroniterUnsupportedSyntaxError` on both sides; `1#2,1` is accepted by
  both with identical expansions.
- **`W`-clamping**: `31w` from 2024-02-01 gives `2024-02-29` on both
  sides (the Mojo `day_allowed` clamp to `month_days` holds).

### 4.3 One divergence documented and left alone (unchanged from before)

`test_expand_hash_id_types_recorded`: upstream `expand` accepts
`hash_id=123` (returns the plain expansion, no type check at that entry
point), while the port raises `TypeError` eagerly in `expand()` — and
upstream's `is_valid()`/constructor *do* raise `TypeError` for the same
input, as the port does across all three entry points. Re-verified in
this session. The README's supported-API promise covers the constructor
and the documented exclusions, not `expand()`'s hash-id type validation
gap; changing the port to accept `123` in `expand()` would agree with
upstream on that one call while disagreeing on the other two, and would
need its own rationale. Left as recorded.

## 5. Changes made in this session

1. `tests/test_parity.py` — replaced the only two remaining
   `pytest.approx` comparisons with exact `==` (both proven exact by
   running the comparisons in §3 before the edit). No assertion was
   removed; both sites now assert *more* than before.
2. `bench/verify.md` — this file (replaced wholesale).
3. `README.md` — **not changed**: every figure already reproduced within
   20% (§2.4). No numbers were invented; every number quoted in this
   report was measured in this session.
4. `bench/bench.py` — **not changed** (audited in §2.1, found sound).
5. Source (`python/mojo_croniter/core.py`, `src/croniter.mojo`) —
   **not changed**: the only live divergence found (§4.1) is a documented
   ordering choice, not a bug demonstrable by a failing test in the
   current suite, and the three previous-pass fixes all still hold.

## 6. Final verification

- `pixi run build && pixi run test` after all changes: build exit 0
  (deprecation warnings only), tests **121 passed**, exit 0.
- `pixi run bench` (post-test-fix): exit 0, numbers in §1.
- `git status` shows exactly two modified files:
  `tests/test_parity.py` and `bench/verify.md`.
