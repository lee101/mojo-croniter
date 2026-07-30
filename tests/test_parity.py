from __future__ import annotations

import itertools
import ctypes
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from croniter import (
    CroniterBadCronError as UpstreamBadCronError,
    croniter as upstream_croniter,
    croniter_range as upstream_range,
)

from mojo_croniter import (
    CroniterBadCronError,
    CroniterBadDateError,
    CroniterUnsupportedSyntaxError,
    croniter,
    croniter_range,
    datetime_to_timestamp,
)
from mojo_croniter._lib import lib
from mojo_croniter.core import INVALID_ARGUMENT


EXPRESSIONS = [
    "* * * * *",
    "*/15 9-17 * jan-mar mon-fri",
    "0,7,31,59 */3 1,15 * *",
    "50-10/10 * * * *",
    "0 0 29 2 *",
    "0 0 1 * 1",
    "0 0 l * *",
    "0 0 15w * *",
    "0 0 * * 2#3",
    "0 0 * * l5",
]


@pytest.mark.parametrize("expression", EXPRESSIONS)
def test_expand_matches_upstream(expression):
    assert croniter.expand(expression) == upstream_croniter.expand(expression)


@pytest.mark.parametrize("expression", EXPRESSIONS)
@pytest.mark.parametrize("method", ["get_next", "get_prev"])
def test_datetime_iteration_matches_upstream(expression, method):
    start = datetime(2024, 5, 17, 12, 34, 56)
    ours = croniter(expression, start, ret_type=datetime)
    theirs = upstream_croniter(expression, start, ret_type=datetime)
    assert [getattr(ours, method)() for _ in range(12)] == [
        getattr(theirs, method)() for _ in range(12)
    ]


def test_dom_dow_or_and_modes_match_upstream():
    start = datetime(2024, 1, 2)
    for day_or in (True, False):
        ours = croniter("0 0 1 * 1", start, ret_type=datetime, day_or=day_or)
        theirs = upstream_croniter(
            "0 0 1 * 1", start, ret_type=datetime, day_or=day_or
        )
        assert ours.get_next_n(20, datetime) == [theirs.get_next() for _ in range(20)]


@pytest.mark.parametrize(
    "expression",
    [
        "* * 1 * 0-6",
        "* * 1 * 6-5",
        "* * 12-27 * 4-4",
        "* * */30 * 3-3",
        "* * * 5-5 *",
        "0 0 * 5-5/2 *",
    ],
)
def test_full_cycle_ranges_preserve_upstream_day_semantics(expression):
    start = datetime(2024, 2, 28, 12, 34, 56)
    assert croniter.expand(expression) == upstream_croniter.expand(expression)
    ours = croniter(expression, start, ret_type=datetime)
    theirs = upstream_croniter(expression, start, ret_type=datetime)
    assert ours.get_next_n(30, datetime) == [theirs.get_next() for _ in range(30)]


@pytest.mark.parametrize("second_at_beginning", [False, True])
def test_seconds_layout_matches_upstream(second_at_beginning):
    expression = "5 */10 * * * *"
    start = datetime(2025, 6, 1, 1, 2, 3)
    ours = croniter(
        expression, start, ret_type=datetime,
        second_at_beginning=second_at_beginning,
    )
    theirs = upstream_croniter(
        expression, start, ret_type=datetime,
        second_at_beginning=second_at_beginning,
    )
    assert ours.get_next_n(100, datetime) == [theirs.get_next() for _ in range(100)]


def test_year_field_matches_upstream():
    expression = "0 0 1 1 * 0 2024-2028/2"
    start = datetime(2023, 6, 1)
    ours = croniter(expression, start, ret_type=datetime)
    theirs = upstream_croniter(expression, start, ret_type=datetime)
    assert ours.get_next_n(3, datetime) == [theirs.get_next() for _ in range(3)]


def test_aliases_match_upstream():
    start = datetime(2024, 2, 13, 9, 12)
    for expression in (
        "@hourly", "@daily", "@midnight", "@weekly", "@monthly", "@yearly",
        "@annually",
    ):
        ours = croniter(expression, start, ret_type=datetime)
        theirs = upstream_croniter(expression, start, ret_type=datetime)
        assert ours.get_next_n(10, datetime) == [theirs.get_next() for _ in range(10)]


def test_expand_from_start_time_matches_upstream():
    start = datetime(2024, 1, 1, 0, 3)
    ours = croniter(
        "*/7 * * * *", start, ret_type=datetime, expand_from_start_time=True
    )
    theirs = upstream_croniter(
        "*/7 * * * *", start, ret_type=datetime, expand_from_start_time=True
    )
    assert ours.get_next_n(100, datetime) == [theirs.get_next() for _ in range(100)]


def test_float_return_current_and_no_update_match_upstream():
    start = datetime(2024, 1, 1, 0, 0, 15, 500000)
    ours = croniter("*/5 * * * *", start)
    theirs = upstream_croniter("*/5 * * * *", start)
    assert ours.get_next(update_current=False) == theirs.get_next(update_current=False)
    assert ours.get_current() == pytest.approx(theirs.get_current())
    assert ours.get_next() == theirs.get_next()
    assert ours.get_prev() == theirs.get_prev()


@pytest.mark.parametrize("method", ["get_next", "get_prev"])
def test_naive_float_fast_path_matches_upstream_across_fractional_second(method):
    start = datetime(2024, 1, 1, 0, 0, 15, 500000)
    ours = croniter("*/10 * * * * *", start)
    theirs = upstream_croniter("*/10 * * * * *", start)
    assert [getattr(ours, method)() for _ in range(100)] == [
        getattr(theirs, method)() for _ in range(100)
    ]


def test_generators_and_iterator_protocol_match_upstream():
    start = datetime(2024, 1, 1)
    ours = croniter("7,37 * * * *", start, ret_type=datetime)
    theirs = upstream_croniter("7,37 * * * *", start, ret_type=datetime)
    assert list(itertools.islice(ours.all_next(), 30)) == list(
        itertools.islice(theirs.all_next(), 30)
    )
    ours = croniter("7,37 * * * *", start, ret_type=datetime)
    theirs = upstream_croniter("7,37 * * * *", start, ret_type=datetime)
    assert list(itertools.islice(ours, 10)) == list(itertools.islice(theirs, 10))
    ours = croniter("7,37 * * * *", start, ret_type=datetime)
    theirs = upstream_croniter("7,37 * * * *", start, ret_type=datetime)
    assert list(itertools.islice(ours.all_prev(), 30)) == list(
        itertools.islice(theirs.all_prev(), 30)
    )


def test_bulk_forward_and_reverse_match_scalar_upstream():
    start = datetime(2024, 7, 12, 11, 22, 33)
    ours = croniter("*/7 6-20 * * mon-fri", start, ret_type=datetime)
    theirs = upstream_croniter("*/7 6-20 * * mon-fri", start, ret_type=datetime)
    assert ours.get_next_n(500, datetime) == [theirs.get_next() for _ in range(500)]
    ours = croniter("*/7 6-20 * * mon-fri", start, ret_type=datetime)
    theirs = upstream_croniter("*/7 6-20 * * mon-fri", start, ret_type=datetime)
    assert ours.get_prev_n(500, datetime) == [theirs.get_prev() for _ in range(500)]


@pytest.mark.parametrize(
    ("expression", "testdate"),
    [
        ("*/5 * * * *", datetime(2024, 1, 1, 12, 15)),
        ("*/5 * * * *", datetime(2024, 1, 1, 12, 16)),
        ("0 0 l * *", datetime(2024, 2, 29)),
        ("0 0 * * 1#2", datetime(2024, 3, 11)),
    ],
)
def test_match_matches_upstream(expression, testdate):
    assert croniter.match(expression, testdate) == upstream_croniter.match(
        expression, testdate
    )


def test_match_range_matches_upstream():
    start = datetime(2024, 1, 1, 12, 1)
    stop = start + timedelta(minutes=3)
    expression = "*/5 * * * *"
    assert croniter.match_range(expression, start, stop) == upstream_croniter.match_range(
        expression, start, stop
    )


def test_croniter_range_datetime_matches_upstream():
    start, stop = datetime(2024, 1, 1), datetime(2024, 1, 4)
    expression = "0 */6 * * *"
    assert list(croniter_range(start, stop, expression)) == list(
        upstream_range(start, stop, expression)
    )
    assert list(croniter_range(start, stop, expression, exclude_ends=True)) == list(
        upstream_range(start, stop, expression, exclude_ends=True)
    )


def test_croniter_range_float_matches_upstream():
    start = datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp()
    stop = start + 7200
    assert list(croniter_range(start, stop, "*/17 * * * *")) == pytest.approx(
        list(upstream_range(start, stop, "*/17 * * * *"))
    )


def test_dst_spring_gap_matches_upstream():
    zone = ZoneInfo("America/New_York")
    start = datetime(2024, 3, 9, tzinfo=zone)
    ours = croniter("30 2 * * *", start, ret_type=datetime)
    theirs = upstream_croniter("30 2 * * *", start, ret_type=datetime)
    assert ours.get_next_n(5, datetime) == [theirs.get_next() for _ in range(5)]


def test_dst_fall_fold_matches_upstream():
    zone = ZoneInfo("America/New_York")
    start = datetime(2024, 11, 2, tzinfo=zone)
    ours = croniter("30 1 * * *", start, ret_type=datetime)
    theirs = upstream_croniter("30 1 * * *", start, ret_type=datetime)
    got = ours.get_next_n(5, datetime)
    expected = [theirs.get_next() for _ in range(5)]
    assert [value.timestamp() for value in got] == [
        value.timestamp() for value in expected
    ]


def test_fixed_offset_iteration_matches_upstream():
    zone = timezone(timedelta(hours=5, minutes=30))
    start = datetime(2024, 8, 10, 23, 58, 20, tzinfo=zone)
    ours = croniter("*/7 * * * *", start, ret_type=datetime)
    theirs = upstream_croniter("*/7 * * * *", start, ret_type=datetime)
    assert ours.get_next_n(40, datetime) == [theirs.get_next() for _ in range(40)]


@pytest.mark.parametrize(
    "expression",
    ["* * *", "61 * * * *", "* 25 * * *", "0 0 32 * *", "0 0 * xyz *", "*/0 * * * *"],
)
def test_invalid_expressions_match_upstream(expression):
    assert croniter.is_valid(expression) == upstream_croniter.is_valid(expression)
    with pytest.raises(CroniterBadCronError):
        croniter(expression)
    with pytest.raises(UpstreamBadCronError):
        upstream_croniter(expression)


def test_explicit_exclusions_raise_clear_error():
    with pytest.raises(CroniterUnsupportedSyntaxError):
        croniter("H * * * *", hash_id="job")
    assert croniter("* * * * *", hash_id="job").expanded == [["*"]] * 5
    with pytest.raises(CroniterUnsupportedSyntaxError):
        croniter("* * * * *", implement_cron_bug=True)


def test_bad_return_type_and_batch_count():
    iterator = croniter("* * * * *", datetime(2024, 1, 1))
    with pytest.raises(TypeError):
        iterator.get_next(int)
    with pytest.raises(ValueError):
        iterator.get_next_n(-1)


def test_ffi_rejects_null_and_short_buffers():
    library = lib()
    assert library.mcron_next(0, 326, 0, 12, 0, 1) == INVALID_ARGUMENT
    table = (ctypes.c_uint8 * 326)()
    special = (ctypes.c_int64 * 12)()
    assert library.mcron_next(
        ctypes.addressof(table), 325, ctypes.addressof(special), 12, 0, 1
    ) == INVALID_ARGUMENT
    assert library.mcron_fill(
        ctypes.addressof(table), 326, ctypes.addressof(special), 12,
        0, 1, 1, 0, 0, 1,
    ) == INVALID_ARGUMENT


def test_python_rejects_corrupted_ffi_buffer_contract():
    iterator = croniter("* * * * *", datetime(2024, 1, 1))
    iterator._table = iterator._table.astype("int16")
    with pytest.raises(RuntimeError, match="membership buffer"):
        iterator.get_next()


def test_datetime_timestamp_matches_upstream():
    value = datetime(2024, 7, 8, 9, 10, 11, 123456, timezone(timedelta(hours=5)))
    assert datetime_to_timestamp(value) == upstream_croniter.datetime_to_timestamp(value)


def test_year_limit_raises():
    iterator = croniter(
        "0 0 29 2 *", datetime(2025, 1, 1),
        max_years_between_matches=1,
    )
    with pytest.raises(CroniterBadDateError):
        iterator.get_next()
