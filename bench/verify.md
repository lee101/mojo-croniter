# mojo-croniter — VERIFY phase report

Measured in this session only. No number from the old README is claimed as
reproduced unless it matched within 20% on a fresh `pixi run bench` run here.
Machine (reported by `bench/bench.py` on every run): Intel Xeon E5-2697 v4
@ 2.30 GHz, Linux x86-64, Python 3.13.14, croniter 6.2.4.

## 1. Baseline commands

Run sequentially in this session (not in parallel):

- `pixi run build && pixi run test` — build succeeded (warnings only, no
  errors); tests **121 passed in ~1.0 s**, exit 0.
- `pixi run bench` — exit 0. The same command was rerun three more times
  (four runs total) so each README row could be checked for stability, and
  once more after the parity fixes at the end (post-fix run).

## 2. Benchmark audit

`bench/bench.py` was audited before trusting any number:

- Same input both sides: each case calls `scalar(impl, expr, count, start)`
  with the same expression, the same `datetime(2024, 1, 1)` start, and the
  same occurrence count. Bulk rows use one `get_next_n(count)` call on the
  Mojo side and the same number of `get_next()` calls upstream — the README
  already states this openly, so no rows were added, removed, or reworded.
- No skipped work: the timed callable constructs the iterator inside the
  timed region on both sides (`scalar()` constructs before looping;
  `bulk_mojo()` constructs before `get_next_n`), so construction cost is
  included symmetrically and is negligible at these sizes. Both sides
  return float timestamps by default.
- Self-check: in this session I verified element-by-element that both
  sides produce identical occurrences for every case:
  scalar rows — all 50,000 values exactly equal;
  bulk rows — `get_next_n` length, first, and last match upstream scalar
  iteration over the same count (200,000 / 100,000), first values
  1704067260.0 and 1704099600.0, last values 1716067200.0 and 2039960700.0.
- Method: one warm-up (the script calls each callable once before timing),
  best of two repeats (`timeit`), `flock`-wrapped (`/tmp/mojo-bench.lock`).
  No row is "slower than upstream" in any run; the table keeps all five
  rows as measured.

### 2.1 What reproduced (within 20% of the old README figure)

Per-number check against the old README values (the run most favourable to
reproduction is shown, but all four pre-fix runs behaved the same way):

| case | old mojo | measured mojo | dev | old upstream | measured upstream | dev |
|---|---:|---:|---:|---:|---:|---:|
| Every minute, scalar | 1067.34 ms | 394.89 ms (run4) | 63.0% FAIL | 1313.53 ms | 1253.73 ms | 4.6% pass |
| Every 10 seconds, scalar | 1089.80 ms | 388.67 ms (run4) | 64.3% FAIL | 1107.57 ms | 1019.30 ms | 8.0% pass |
| Business hours, scalar | 967.49 ms | 387.29 ms (run4) | 60.0% FAIL | 2463.38 ms | 2311.60 ms | 6.2% pass |
| Every minute, bulk | 84.71 ms | 53.13 ms (run1) | 37.3% FAIL | 7417.42 ms | 5034.11 ms (run4) | 32.1% FAIL |
| Business hours, bulk | 46.44 ms | 31.28 ms (run2) | 32.6% FAIL | 5923.15 ms | 4694.30 ms (run2) | 20.7% FAIL |

Run-by-run deviations vs the old README were consistent across all four
pre-fix runs (scalar upstream 1.7–9.9% — all pass; scalar mojo 54–64% —
all fail; bulk mojo 30–37% — all fail; bulk upstream 13–32% — mostly
fail). The old bulk speedup ratios happened to land near the new ones
(0.3–22%), but the underlying times did not, so they do not count as
reproduced. **No README number reproduced within 20% on both sides except
the three scalar upstream times.** The old scalar speedup column
(1.23x/1.02x/2.55x) was therefore wrong in this session's remeasurement
(true value ~2.4–6.0x), because the old mojo times overstated scalar cost
by ~55–65%.

### 2.2 What was corrected, and to what

All five README rows were replaced with the post-fix measurement (the last
`pixi run bench` in this session, after the parity fixes below; the fixes
touch only `W`-clamping, `strict_year`, and `#`-mixing paths, none of which
appear in the benchmark expressions, so the numbers are not an artefact of
the fix):

| case | occurrences | mojo-croniter | croniter 6.2.4 | speedup |
|---|---:|---:|---:|---:|
| Every minute, scalar | 50,000 | 453.47 ms | 1329.55 ms | 2.93x |
| Every 10 seconds, scalar | 50,000 | 422.05 ms | 1019.93 ms | 2.42x |
| Business hours, scalar | 50,000 | 483.02 ms | 2362.85 ms | 4.89x |
| Every minute, bulk | 200,000 | 57.75 ms | 5521.95 ms | 95.62x |
| Business hours, bulk | 100,000 | 33.38 ms | 5099.75 ms | 152.76x |

Pre-fix runs in this session for reference (same harness):
run1 406.42/1247.94/3.07x, 405.01/1002.73/2.48x, 411.58/2380.50/5.78x,
53.13/5090.17/95.80x, 38.62/4909.37/127.12x;
run2 433.03/1339.06/3.09x, 419.77/997.39/2.38x, 441.52/2420.52/5.48x,
53.28/5185.17/97.32x, 31.28/4694.30/150.06x;
run3 431.25/1412.67/3.28x, 437.54/1130.93/2.58x, 437.27/2610.12/5.97x,
56.58/5612.39/99.20x, 32.93/5149.15/156.35x;
run4 394.89/1253.73/3.17x, 388.67/1019.30/2.62x, 387.29/2311.60/5.97x,
59.25/5034.11/84.96x, 34.62/4513.07/130.35x.
Run-to-run spread on the same machine is roughly ±10% (largest: bulk
upstream), which is consistent with best-of-two timing of short
(30–60 ms) bulk-mofo measurements; the corrected table uses a single
representative post-fix run rather than an average, per the "number you
measured" rule.

Nothing was removed or reworded to look better: the table keeps its shape,
the same-input statement, and the bulk-vs-scalar disclosure paragraph.

## 3. Parity (test-history) audit

`git log -p -- tests/` shows `tests/test_parity.py` unchanged since the
initial port commit; all test changes live in the added
`tests/test_parity_hardening.py` (618 lines) from the "phase test"
commit. That file loosened parity in three ways, each masking a real
divergence. Every one was demonstrated with a failing strict assertion
before any code change (5 failing cases, `/tmp/test_strict_parity_proposed.py`,
run in this session):

1. `test_expand_strict_year_semantics_recorded` — the port raised
   `CroniterBadCronError` for `strict_year` membership while upstream
   ignores `strict_year` except for Feb leap detection under `strict=True`;
   conversely the port accepted `0 0 29 2 *` under
   `strict=True, strict_year=2023` (non-leap), which upstream rejects.
   `is_valid` disagreed both ways (False vs True).
2. `test_expand_nth_mixing_rules_recorded` — the port accepted
   `0 0 * * 1#2,2`, which upstream rejects with
   `CroniterUnsupportedSyntaxError` ("does not support mixing literal
   values and nth day of week syntax").
3. `test_nearest_weekday_clamp_deviation_is_documented` — `31w` in Feb/Apr
   fired in the *next* month (2024-03-29 / 2024-05-31) while upstream
   clamps `W` to the month length (`min(day, last_day)`, Feb 29 / Apr 30).
   This is an iteration bug: the Mojo kernel computed the weekday of an
   out-of-month day, which rolls into the next month.

Additionally the hardening file used `pytest.approx(abs=1e-6, rel=1e-9)`
for float timestamps and a shared-base-class-name error check. I verified
every one of those sites agrees *exactly* (`==`) with upstream in this
session (all float sequences, `set_current`, `datetime_to_timestamp`,
`croniter_range` float, DST spring gap, instance attributes), and
`assert_raises_same_base` was hiding that NaN raises `ValueError` and
±inf raises `OverflowError` on both sides.

### Fixes (all demonstrated first by a failing test; no speculative changes)

- `src/croniter.mojo` (`day_allowed`): clamp the `W` target to the month
  length before the weekday computation — matches upstream
  `_get_nearest_weekday`. One-line change; kernel-rebuilt via `pixi run build`.
- `python/mojo_croniter/core.py` (`_parse` + `croniter.expand`):
  - nth-mixing: raise `CroniterUnsupportedSyntaxError` when the DOW field
    combines literal values with `#`/`l` (unless the field is the full
    7-value cycle), exactly as upstream `_expand` does. The pre-existing
    documented restriction (restricted day-of-month + `#` raises) is kept.
  - `strict_year`: removed the invented membership check; `strict_year`
    (and 7-field year values) now only feed Feb leap detection inside the
    `strict=True` branch, mirroring upstream.

### Restored assertions

- All three "recorded deviation" tests now assert exact parity with
  upstream (including both-directions `get_next`/`get_prev` for `W`
  clamping, and the `strict_year` leap cases), renamed accordingly.
- Every `approx_ts(...)` comparison was replaced with exact `==` (helper
  and tolerances removed; 17 sites). Error checks now assert the concrete
  stdlib type (`ValueError`/`OverflowError`) per case.
- The DST fall-fold test still pins ordering (first two occurrences equal
  upstream exactly; remaining strictly increasing) — upstream emits the
  ambiguous hour in a different absolute-time order than the port, a
  documented behavioural difference not split by any benchmark row and
  not a README coverage claim, so it was left as-is and not silently
  "fixed" to a different schedule. The 1970–2099 year-window test likewise
  still pins the documented bound.
- `tests/test_parity.py` was not changed (it was never loosened).

One pre-existing "recorded" case was deliberately left alone:
`test_expand_hash_id_types_recorded` (upstream `expand` accepts
`hash_id=123`, the port raises `TypeError`). It was not part of a removed
assertion, is explicitly recorded in the test, and is outside the
supported-API promise; changing the port's type validation on
speculation would itself need a rationale I did not want to invent here.

## 4. Final verification

- `pixi run build && pixi run test` after all changes: build exit 0
  (deprecation warnings only), tests **121 passed**, exit 0.
- `pixi run bench` (post-fix): exit 0, numbers in §2.2.
- No other code was changed. In particular `bench/bench.py` was not
  modified.
