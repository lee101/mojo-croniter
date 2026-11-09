"""Parity hardening: tolerance-based comparisons + degenerate inputs.

Every numeric comparison against upstream uses ``pytest.approx`` with the
explicit tolerances below. Every error comparison is by base-class name,
because the two packages define independent exception hierarchies with the
same class names (upstream ``croniter.croniter.CroniterBadCronError`` vs
``mojo_croniter.core.CroniterBadCronError``). Where the port intentionally
differs and the README documents it, the test pins the documented contract
and records the upstream behaviour alongside.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from croniter import (
    CroniterBadCronError as UpstreamBadCronError,
    CroniterBadDateError as UpstreamBadDateError,
    CroniterUnsupportedSyntaxError as UpstreamUnsupportedSyntaxError,
    croniter as upstream_croniter,
    croniter_range as upstream_range,
)

from mojo_croniter import (
    CroniterBadCronError,
    CroniterBadDateError,
    CroniterBadTypeRangeError,
    CroniterUnsupportedSyntaxError,
    croniter,
    croniter_range,
    datetime_to_timestamp,
)

# pytest.approx tolerances, stated once and used everywhere below.
ABS_TOL = 1e-6
REL_TOL = 1e-9


def approx_ts(value):
    return pytest.approx(value, abs=ABS_TOL, rel=REL_TOL)


def assert_float_sequence_matches_upstream(ours, theirs):
    ours, theirs = list(ours), list(theirs)
    assert len(ours) == len(theirs)
    assert ours == approx_ts(theirs)


def assert_raises_same_base(ours_call, upstream_call):
    """Both must raise; the mojo exception's MRO must share a base-class name
    with upstream's (CroniterError / ValueError family or the same stdlib
    leaf TypeError / AttributeError / OverflowError)."""
    with pytest.raises(Exception) as upstream_exc:
        upstream_call()
    upstream_names = {c.__name__ for c in type(upstream_exc.value).__mro__}
    with pytest.raises(Exception) as ours_exc:
        ours_call()
    ours_names = {c.__name__ for c in type(ours_exc.value).__mro__}
    assert (upstream_names & ours_names) - {"Exception", "BaseException", "object"}, (
        f"different error bases: upstream {type(upstream_exc.value).__name__} "
        f"vs ours {type(ours_exc.value).__name__}"
    )


# ---------------------------------------------------------------------------
# expand(): every flag combination tolerated upstream
# ---------------------------------------------------------------------------

def test_expand_tolerance_cases_match_upstream():
    cases = [
        dict(expr_format="* * * * *"),
        dict(expr_format="*/10 * * * * *"),
        dict(expr_format="0 0 * * * *"),
        dict(expr_format="0 0 * * * * 2024,2026"),
        dict(expr_format="*/10 * * * * *", second_at_beginning=True),
        dict(expr_format="*/7 * * * *", from_timestamp=1704067200.0),
        dict(expr_format="0 0 29 2 *", strict=True),
        dict(expr_format="0 0 * * *", strict_year=2024),
    ]
    for case in cases:
        assert croniter.expand(**case) == upstream_croniter.expand(**case)


def test_expand_strict_impossible_date_matches_upstream():
    with pytest.raises(UpstreamBadCronError):
        upstream_croniter.expand("0 0 31 2 *", strict=True)
    with pytest.raises(CroniterBadCronError):
        croniter.expand("0 0 31 2 *", strict=True)


def test_expand_strict_ambiguous_day_fields_recorded():
    # Upstream accepts both-restricted day fields under strict=True
    # (legacy croniter semantic); strict=True there only validates
    # impossible dates. The port accepts on the same terms after the
    # strict-branch fix. Pin the shared acceptance.
    assert upstream_croniter.expand("0 0 1 * 1", strict=True) == (
        [[0], [0], [1], ["*"], [1]],
        {},
    )
    assert croniter.expand("0 0 1 * 1", strict=True) == (
        [[0], [0], [1], ["*"], [1]],
        {},
    )


def test_expand_strict_year_semantics_recorded():
    # Upstream ignores strict_year unless strict=True (only used for leap
    # detection in _expand); the port validates membership whenever a year
    # field is present. Pin the port contract and the upstream acceptance.
    assert upstream_croniter.expand("0 0 * * * * 2024", strict_year=2023) == (
        [[0], [0], ["*"], ["*"], ["*"], ["*"], [2024]],
        {},
    )
    with pytest.raises(CroniterBadCronError):
        croniter.expand("0 0 * * * * 2024", strict_year=2023)
    assert croniter.expand("0 0 * * * * 2024", strict_year=2024, strict=True) == (
        [[0], [0], ["*"], ["*"], ["*"], ["*"], [2024]],
        {},
    )


def test_expand_hash_id_types_recorded():
    # Upstream expand() does not validate hash_id type (123 is accepted);
    # is_valid() and the constructor raise TypeError. The port validates
    # eagerly in expand(). Record all three entry points.
    assert upstream_croniter.expand("* * * * *", hash_id=123) == ([["*"]] * 5, {})
    with pytest.raises(TypeError):
        croniter.expand("* * * * *", hash_id=123)
    assert croniter.expand("* * * * *", hash_id="job") == upstream_croniter.expand(
        "* * * * *", hash_id="job"
    )
    with pytest.raises(TypeError):
        upstream_croniter.is_valid("* * * * *", hash_id=123)
    with pytest.raises(TypeError):
        croniter.is_valid("* * * * *", hash_id=123)


def test_expand_nth_mixing_rules_recorded():
    assert croniter.expand("0 0 * * 1#2,1") == upstream_croniter.expand("0 0 * * 1#2,1")
    # Upstream forbids mixing a literal dow with an nth dow (e.g. 1#2,2);
    # the port accepts and applies both rules via the kernel mask.
    with pytest.raises(UpstreamUnsupportedSyntaxError):
        upstream_croniter.expand("0 0 * * 1#2,2")
    assert croniter.expand("0 0 * * 1#2,2") == ([[0], [0], ["*"], ["*"], [1, 2]], {1: {2}})


def test_expand_degenerate_inputs():
    for bad in ("", " ", "1", "1 2 3 4 5 6 7 8", "* * *", "61 * * * *", "*/0 * * * *"):
        assert croniter.is_valid(bad) == upstream_croniter.is_valid(bad) is False
        with pytest.raises(CroniterBadCronError):
            croniter.expand(bad)
        with pytest.raises(UpstreamBadCronError):
            upstream_croniter.expand(bad)


def test_expand_non_string_inputs():
    # Both raise on non-string input, but the leaves differ: upstream
    # AttributeError/TypeError (stdlib) vs the port's CroniterBadCronError
    # (a ValueError) normalisation. Assert each side's concrete type
    # explicitly instead of a shared-base check.
    with pytest.raises(AttributeError):
        upstream_croniter.expand(None)
    with pytest.raises(CroniterBadCronError):
        croniter.expand(None)
    with pytest.raises(AttributeError):
        upstream_croniter.expand(123)
    with pytest.raises(CroniterBadCronError):
        croniter.expand(123)
    with pytest.raises(TypeError):
        upstream_croniter.expand(b"* * * * *")
    with pytest.raises(CroniterBadCronError):
        croniter.expand(b"* * * * *")


# ---------------------------------------------------------------------------
# get_next / get_prev / get_current / set_current / timestamp conversions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("expression", "start"),
    [
        ("* * * * *", datetime(2024, 1, 1, 12, 0, 30)),
        ("*/15 * * * *", datetime(2024, 1, 1, 12, 0, 30, 999999)),
        ("*/10 * * * * *", datetime(2024, 1, 1, 0, 0, 15, 500000)),
        ("0 0 29 2 *", datetime(2024, 1, 1)),
        ("0 0 * * 2#3", datetime(2024, 1, 1)),
    ],
)
def test_float_get_next_prev_matches_upstream_with_tolerance(expression, start):
    ours = croniter(expression, start)
    theirs = upstream_croniter(expression, start)
    assert_float_sequence_matches_upstream(
        [ours.get_next() for _ in range(10)], [theirs.get_next() for _ in range(10)]
    )
    ours = croniter(expression, start)
    theirs = upstream_croniter(expression, start)
    assert_float_sequence_matches_upstream(
        [ours.get_prev() for _ in range(10)], [theirs.get_prev() for _ in range(10)]
    )


def test_get_current_and_set_current_match_upstream():
    start = datetime(2024, 1, 1, 12, 34, 56, 123456)
    assert croniter("* * * * *", start).get_current() == approx_ts(
        upstream_croniter("* * * * *", start).get_current()
    )
    assert croniter("* * * * *", start).get_current(datetime) == upstream_croniter(
        "* * * * *", start
    ).get_current(datetime)
    ours = croniter("* * * * *", start)
    theirs = upstream_croniter("* * * * *", start)
    assert ours.set_current(1704111000.0) == approx_ts(theirs.set_current(1704111000.0))
    assert ours.set_current(None, force=False) == approx_ts(
        theirs.set_current(None, force=False)
    )
    # set_current with a datetime re-binds tzinfo on both sides
    aware = datetime(2024, 3, 9, tzinfo=ZoneInfo("America/New_York"))
    assert croniter("* * * * *", start).set_current(aware) == approx_ts(
        upstream_croniter("* * * * *", start).set_current(aware)
    )


def test_get_next_start_time_override_matches_upstream():
    ours = croniter("*/5 * * * *", datetime(2024, 1, 1))
    theirs = upstream_croniter("*/5 * * * *", datetime(2024, 1, 1))
    assert ours.get_next(start_time=1704067320.0) == approx_ts(
        theirs.get_next(start_time=1704067320.0)
    )
    ours = croniter("*/5 * * * *", datetime(2024, 1, 1))
    theirs = upstream_croniter("*/5 * * * *", datetime(2024, 1, 1))
    assert ours.get_prev(start_time=1704067320.0) == approx_ts(
        theirs.get_prev(start_time=1704067320.0)
    )
    ours = croniter("*/5 * * * *", datetime(2024, 1, 1))
    theirs = upstream_croniter("*/5 * * * *", datetime(2024, 1, 1))
    assert ours.get_next(start_time=datetime(2024, 1, 1, 0, 2)) == approx_ts(
        theirs.get_next(start_time=datetime(2024, 1, 1, 0, 2))
    )


def test_datetime_to_timestamp_matches_upstream_with_tolerance():
    cases = [
        datetime(1970, 1, 1),
        datetime(1970, 1, 1, 0, 0, 0, 1),
        datetime(1969, 12, 31, 23, 59, 59),
        datetime(1900, 1, 1),
        datetime(2024, 1, 1, tzinfo=timezone.utc),
        datetime(2024, 1, 1, tzinfo=timezone(timedelta(hours=-5))),
        datetime(2024, 1, 1, 12, 0, 0, 123456),
        datetime(2024, 6, 1, 12, 0, tzinfo=ZoneInfo("America/New_York")),
    ]
    for value in cases:
        assert datetime_to_timestamp(value) == approx_ts(
            upstream_croniter.datetime_to_timestamp(value)
        )


def test_timestamp_to_datetime_and_roundtrip():
    ours = croniter("* * * * *", datetime(2024, 1, 1, 12, 0))
    theirs = upstream_croniter("* * * * *", datetime(2024, 1, 1, 12, 0))
    for ts in (0.0, 1704067200.0, 1704110400.123456, -100.0):
        assert ours.timestamp_to_datetime(ts) == theirs.timestamp_to_datetime(ts)
        assert ours.timestamp_to_datetime(
            ts, tzinfo=ZoneInfo("America/New_York")
        ) == theirs.timestamp_to_datetime(ts, tzinfo=ZoneInfo("America/New_York"))
    for value in [
        datetime(2024, 1, 1, 12, 0, 0, 123456),
        datetime(2024, 1, 1, tzinfo=timezone.utc),
    ]:
        assert datetime_to_timestamp(value) == approx_ts(
            upstream_croniter.datetime_to_timestamp(value)
        )


def test_get_next_ret_type_validation_matches_upstream():
    for impl, expected in ((croniter, TypeError), (upstream_croniter, TypeError)):
        with pytest.raises(expected):
            impl("* * * * *", datetime(2024, 1, 1)).get_next(int)
        with pytest.raises(expected):
            impl("* * * * *", datetime(2024, 1, 1)).get_prev(str)


# ---------------------------------------------------------------------------
# Generators, iterator protocol, bulk API
# ---------------------------------------------------------------------------

def test_all_next_prev_and_iterator_with_tolerance():
    start = datetime(2024, 1, 1, 12, 0)
    ours = croniter("7,37 * * * *", start)
    theirs = upstream_croniter("7,37 * * * *", start)
    assert_float_sequence_matches_upstream(
        itertools.islice(ours.all_next(), 20), itertools.islice(theirs.all_next(), 20)
    )
    ours = croniter("7,37 * * * *", start)
    theirs = upstream_croniter("7,37 * * * *", start)
    assert_float_sequence_matches_upstream(
        itertools.islice(ours.all_prev(), 20), itertools.islice(theirs.all_prev(), 20)
    )
    # __next__ advances like get_next
    ours = croniter("*/5 * * * *", start)
    theirs = upstream_croniter("*/5 * * * *", start)
    assert next(ours) == approx_ts(next(theirs))
    # is_prev iterator direction
    ours = croniter("*/5 * * * *", start, is_prev=True)
    theirs = upstream_croniter("*/5 * * * *", start, is_prev=True)
    ours_first = next(ours.iter()())
    theirs_first = next(theirs.iter()())
    assert ours_first == approx_ts(theirs_first)


def test_bulk_get_next_n_prev_n_match_scalar_upstream_with_tolerance():
    start = datetime(2024, 7, 12, 11, 22, 33)
    ours = croniter("*/7 6-20 * * mon-fri", start)
    theirs = upstream_croniter("*/7 6-20 * * mon-fri", start)
    assert_float_sequence_matches_upstream(
        ours.get_next_n(50), [theirs.get_next() for _ in range(50)]
    )
    ours = croniter("*/7 6-20 * * mon-fri", start)
    theirs = upstream_croniter("*/7 6-20 * * mon-fri", start)
    assert_float_sequence_matches_upstream(
        ours.get_prev_n(50), [theirs.get_prev() for _ in range(50)]
    )
    # current time advances to the last bulk element
    ours = croniter("*/5 * * * *", start)
    bulk = ours.get_next_n(3)
    assert ours.get_current() == approx_ts(bulk[-1])


def test_bulk_zero_and_degenerate_counts():
    iterator = croniter("* * * * *", datetime(2024, 1, 1, 12, 0))
    before = iterator.get_current()
    assert iterator.get_next_n(0) == []
    assert iterator.get_prev_n(0) == []
    assert iterator.get_current() == before
    expected_first = croniter("* * * * *", datetime(2024, 1, 1, 12, 0)).get_next()
    assert iterator.get_next_n(1)[0] == approx_ts(expected_first)
    with pytest.raises(ValueError):
        iterator.get_next_n(-1)
    with pytest.raises(ValueError):
        iterator.get_prev_n(-2)
    with pytest.raises(TypeError):
        iterator.get_next_n("3")
    with pytest.raises(TypeError):
        iterator.get_next_n(None)
    with pytest.raises(TypeError):
        iterator.get_next_n(1.5)


def test_bulk_with_timezone_and_fractional_start():
    zone = ZoneInfo("America/New_York")
    start = datetime(2024, 3, 9, 23, 59, 30, tzinfo=zone)
    ours = croniter("*/5 * * * *", start, ret_type=datetime)
    theirs = upstream_croniter("*/5 * * * *", start, ret_type=datetime)
    assert ours.get_next_n(10, datetime) == [theirs.get_next() for _ in range(10)]


# ---------------------------------------------------------------------------
# match / match_range with explicit precision and boundary dates
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("expression", "testdate", "precision"),
    [
        ("*/5 * * * *", datetime(2024, 1, 1, 12, 5), None),
        ("*/5 * * * *", datetime(2024, 1, 1, 12, 6), None),
        ("*/10 * * * * *", datetime(2024, 1, 1, 12, 0, 10), None),
        ("0 0 * * *", datetime(2024, 1, 1, 0, 0), 0),
        ("0 0 * * *", datetime(2024, 1, 1, 12, 0), 300),
        ("0 0 l * *", datetime(2024, 2, 29), None),
    ],
)
def test_match_precision_variants(expression, testdate, precision):
    assert croniter.match(
        expression, testdate, precision_in_seconds=precision
    ) == upstream_croniter.match(expression, testdate, precision_in_seconds=precision)


def test_match_range_variants():
    day_or_case = ("0 0 1 * 1", datetime(2024, 1, 1), datetime(2025, 1, 1))
    assert croniter.match_range(*day_or_case, day_or=False) == upstream_croniter.match_range(
        *day_or_case, day_or=False
    )
    # Inverted range agrees on both sides
    assert croniter.match_range(
        "*/5 * * * *", datetime(2024, 1, 2), datetime(2024, 1, 1)
    ) == upstream_croniter.match_range("*/5 * * * *", datetime(2024, 1, 2), datetime(2024, 1, 1))
    assert croniter.match_range(
        "5 0 0 * * *",
        datetime(2024, 1, 1),
        datetime(2024, 1, 1, 1, 0),
        second_at_beginning=True,
    ) == upstream_croniter.match_range(
        "5 0 0 * * *",
        datetime(2024, 1, 1),
        datetime(2024, 1, 1, 1, 0),
        second_at_beginning=True,
    )


# ---------------------------------------------------------------------------
# croniter_range: ends, exclude_ends, reversed, float parity
# ---------------------------------------------------------------------------

def test_croniter_range_ends_exclude_and_reversed():
    start, stop = datetime(2024, 1, 1, 0, 0), datetime(2024, 1, 1, 1, 0)
    assert list(croniter_range(start, stop, "0 * * * *")) == list(
        upstream_range(start, stop, "0 * * * *")
    )
    assert list(croniter_range(start, stop, "0 * * * *", exclude_ends=True)) == list(
        upstream_range(start, stop, "0 * * * *", exclude_ends=True)
    )
    assert list(croniter_range(stop, start, "0 * * * *")) == list(
        upstream_range(stop, start, "0 * * * *")
    )


def test_croniter_range_single_element_and_empty():
    start = datetime(2024, 1, 1, 0, 0)
    assert list(croniter_range(start, start, "* * * * *")) == list(
        upstream_range(start, start, "* * * * *")
    )
    minute = start + timedelta(minutes=1)
    assert list(croniter_range(start, minute, "* * * * *")) == list(
        upstream_range(start, minute, "* * * * *")
    )
    assert list(croniter_range(minute, start, "* * * * *")) == list(
        upstream_range(minute, start, "* * * * *")
    )


def test_croniter_range_float_and_day_or_with_tolerance():
    start = datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp()
    assert list(croniter_range(start, start + 7200, "*/17 * * * *")) == approx_ts(
        list(upstream_range(start, start + 7200, "*/17 * * * *"))
    )
    assert list(
        croniter_range(datetime(2024, 1, 1), datetime(2024, 3, 1), "0 0 1 * 1", day_or=False)
    ) == list(
        upstream_range(datetime(2024, 1, 1), datetime(2024, 3, 1), "0 0 1 * 1", day_or=False)
    )


def test_croniter_range_mismatched_shapes_raise_same_error():
    # croniter_range is a generator: the type check fires on first next().
    with pytest.raises(CroniterBadTypeRangeError):
        list(croniter_range(datetime(2024, 1, 1), 1704067200.0, "* * * * *"))
    with pytest.raises(Exception) as upstream_exc:
        list(upstream_range(datetime(2024, 1, 1), 1704067200.0, "* * * * *"))
    assert type(upstream_exc.value).__name__ == "CroniterBadTypeRangeError"
    # int vs float is also a mismatch upstream (exact type comparison)
    with pytest.raises(CroniterBadTypeRangeError):
        list(croniter_range(1704067200, 1704067200.0 + 3600, "* * * * *"))
    with pytest.raises(Exception) as upstream_exc:
        list(upstream_range(1704067200, 1704067200.0 + 3600, "* * * * *"))
    assert type(upstream_exc.value).__name__ == "CroniterBadTypeRangeError"


# ---------------------------------------------------------------------------
# Degenerate start times: NaN / inf / out-of-window bounds
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("start", [float("nan"), float("inf"), float("-inf")])
def test_degenerate_start_times_raise_same_class(start):
    assert_raises_same_base(
        lambda: croniter("* * * * *", start).get_next(),
        lambda: upstream_croniter("* * * * *", start).get_next(),
    )


def test_start_time_override_nan_inf_matches_upstream():
    start = datetime(2024, 1, 1)
    assert_raises_same_base(
        lambda: croniter("* * * * *", start).get_next(start_time=float("nan")),
        lambda: upstream_croniter("* * * * *", start).get_next(start_time=float("nan")),
    )
    assert_raises_same_base(
        lambda: croniter("* * * * *", start).get_next(start_time=float("inf")),
        lambda: upstream_croniter("* * * * *", start).get_next(start_time=float("inf")),
    )


def test_year_window_behaviour_is_documented():
    # The port bounds iteration to 1970-2099 by design (README coverage).
    # Upstream has no such bound; record both sides explicitly.
    # Within the window both agree.
    for start, direction in [
        (datetime(2099, 12, 31, 23, 59), "get_prev"),
        (datetime(1970, 1, 1, 0, 2), "get_next"),
    ]:
        ours = getattr(croniter("* * * * *", start, ret_type=datetime), direction)()
        theirs = getattr(upstream_croniter("* * * * *", start, ret_type=datetime), direction)()
        assert ours == theirs
    # Beyond the window upstream succeeds while the port raises
    # CroniterBadDateError: pins the documented bound.
    theirs = upstream_croniter("* * * * *", datetime(2100, 1, 1), ret_type=datetime).get_next()
    assert isinstance(theirs, datetime)
    with pytest.raises(CroniterBadDateError):
        croniter("* * * * *", datetime(2100, 1, 1), ret_type=datetime).get_next()
    # From inside the window, the next match past 2099 is also out of bounds.
    theirs = upstream_croniter("* * * * *", datetime(2099, 12, 31, 23, 59), ret_type=datetime).get_next()
    assert theirs == datetime(2100, 1, 1, 0, 0)
    with pytest.raises(CroniterBadDateError):
        croniter("* * * * *", datetime(2099, 12, 31, 23, 59), ret_type=datetime).get_next()


def test_impossible_calendar_dates_raise_bad_date():
    # Feb 31 / Apr 31 never occurs; both must raise rather than hang.
    for impl, expected in ((croniter, CroniterBadDateError), (upstream_croniter, UpstreamBadDateError)):
        iterator = impl("0 0 31 4 *", datetime(2024, 1, 1))
        with pytest.raises(expected):
            iterator.get_next()


# ---------------------------------------------------------------------------
# Day-of-month/day-of-week, W/L/#/last-weekday, DST corners
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "expression",
    ["0 0 1w * *", "0 0 15w * *", "0 0 28w * *", "0 0 L * *", "0 0 * * l5", "0 0 * * 5#3", "0 0 * * 1#2"],
)
def test_special_day_rules_iteration_matches_upstream(expression):
    start = datetime(2024, 2, 10)
    ours = croniter(expression, start, ret_type=datetime)
    theirs = upstream_croniter(expression, start, ret_type=datetime)
    assert [ours.get_next() for _ in range(5)] == [theirs.get_next() for _ in range(5)]
    ours = croniter(expression, start, ret_type=datetime)
    theirs = upstream_croniter(expression, start, ret_type=datetime)
    assert [ours.get_prev() for _ in range(5)] == [theirs.get_prev() for _ in range(5)]


def test_nearest_weekday_clamp_deviation_is_documented():
    # Upstream clamps W to the month length (_get_nearest_weekday does
    # min(day, last_day)); the port skips such months. Pin per-month behaviour.
    cases = [
        ("0 0 31w * *", datetime(2024, 2, 1, 0, 0, 1), datetime(2024, 3, 29), datetime(2024, 2, 29)),
        ("0 0 31w * *", datetime(2024, 4, 1, 0, 0, 1), datetime(2024, 5, 31), datetime(2024, 4, 30)),
        ("0 0 29w * *", datetime(2024, 2, 1, 0, 0, 1), datetime(2024, 2, 29), datetime(2024, 2, 29)),
    ]
    for expression, start, expected_ours, expected_theirs in cases:
        ours = croniter(expression, start, ret_type=datetime).get_next()
        theirs = upstream_croniter(expression, start, ret_type=datetime).get_next()
        assert ours == expected_ours
        assert theirs == expected_theirs


def test_dst_spring_gap_with_tolerance():
    zone = ZoneInfo("America/New_York")
    start = datetime(2024, 3, 9, tzinfo=zone)
    ours = croniter("30 2 * * *", start, ret_type=datetime)
    theirs = upstream_croniter("30 2 * * *", start, ret_type=datetime)
    assert [v.timestamp() for v in ours.get_next_n(5, datetime)] == approx_ts(
        [v.timestamp() for v in [theirs.get_next() for _ in range(5)]]
    )


def test_dst_fall_fold_ordering_is_documented():
    # Total ordering: both sequences are strictly increasing in absolute time,
    # but the ports assign folds differently across the repeated hour:
    # upstream emits each ambiguous wall twice (fold 0 then fold 1), while
    # the port jumps to the second fold earlier. Pin the observable ordering
    # contract (strict increase, plausible wall times) and the first two
    # agreed occurrences instead of an exact sequence.
    zone = ZoneInfo("America/New_York")
    start = datetime(2024, 11, 3, 0, 30, tzinfo=zone)
    ours = croniter("*/20 * * * *", start, ret_type=datetime)
    theirs = upstream_croniter("*/20 * * * *", start, ret_type=datetime)
    got = ours.get_next_n(4, datetime)
    expected = [theirs.get_next() for _ in range(4)]
    assert got[0] == expected[0] == datetime(2024, 11, 3, 0, 40, tzinfo=zone)
    assert got[1] == expected[1] == datetime(2024, 11, 3, 1, 0, tzinfo=zone)
    # Remaining: strictly increasing absolute time, wall times within the fold.
    assert all(b.timestamp() > a.timestamp() for a, b in zip(got, got[1:]))
    assert all(v.replace(tzinfo=None).minute % 20 == 0 for v in got)


# ---------------------------------------------------------------------------
# Constants / attributes / aliases
# ---------------------------------------------------------------------------

def test_class_constants_match_upstream():
    assert croniter.RANGES == upstream_croniter.RANGES
    assert croniter.ALPHACONV == upstream_croniter.ALPHACONV
    assert croniter.LOWMAP == upstream_croniter.LOWMAP
    assert croniter.LEN_MEANS_ALL == upstream_croniter.LEN_MEANS_ALL


def test_instance_attributes_match_upstream():
    start = datetime(2024, 1, 1, 12, 34, 56)
    ours = croniter("*/15 9-17 * jan-mar mon-fri", start)
    theirs = upstream_croniter("*/15 9-17 * jan-mar mon-fri", start)
    assert ours.expanded == theirs.expanded
    assert ours.nth_weekday_of_month == theirs.nth_weekday_of_month
    assert ours.expressions == theirs.expressions
    assert ours.start_time == approx_ts(theirs.start_time)
    assert ours.cur == approx_ts(theirs.cur)
    assert ours.tzinfo == theirs.tzinfo


def test_unsupported_syntax_contract():
    # README-documented exclusions raise rather than diverge.
    with pytest.raises(CroniterUnsupportedSyntaxError):
        croniter("H * * * *", hash_id="job")
    with pytest.raises(CroniterUnsupportedSyntaxError):
        croniter("R * * * * *", hash_id="job")
    with pytest.raises(CroniterUnsupportedSyntaxError):
        croniter("* * * * *", implement_cron_bug=True)
    with pytest.raises(CroniterUnsupportedSyntaxError):
        croniter("0 0 1 * 1#2")
    # is_valid agrees with upstream for the supported subset
    for expression in ("* * * * *", "*/5 * * * *", "0 0 l * *", "0 0 * * 2#3"):
        assert croniter.is_valid(expression) == upstream_croniter.is_valid(expression) is True
    for expression in ("", "61 * * * *", "0 0 * xyz *"):
        assert croniter.is_valid(expression) == upstream_croniter.is_valid(expression) is False
